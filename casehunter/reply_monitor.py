import hashlib
import os
from datetime import date

from .config import STORE_REPLY_CONTENT
from .database import row_to_dict, transaction, utc_now
from .delivery_health import mark_delivery_failure
from .delivery_monitor import fetch_delivery_failures
from .engines.reply_intelligence import REPLY_CLASSES, analyze_reply, classify_reply
from .gmail_service import fetch_replies, fetch_sent_messages, imap_configured
from .pilot_metrics import start_pilot
from .portfolio_discovery import refresh_due_pilot_portfolios
from .resolution_learning import refresh_active_pilot_recommendations
from .repository import add_timeline_event, create_action, update_case_status
from .watch_batch import run_bounded_active_watches

WATCH_SOURCES_PER_CASE = max(
    1,
    min(100, int(os.getenv("CASE_HUNTER_WATCH_SOURCES_PER_CASE", "25"))),
)
MAX_WATCH_SOURCES_PER_CASE = max(
    1,
    min(2000, int(os.getenv("CASE_HUNTER_MAX_WATCH_SOURCES_PER_CASE", "250"))),
)


def list_replies(case_id=None, classification=None, limit=100, db_path=None):
    query = "SELECT * FROM outreach_replies"
    clauses = []
    params = []
    if case_id is not None:
        clauses.append("case_id=?")
        params.append(int(case_id))
    if classification:
        clauses.append("classification=?")
        params.append(classification)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(500, int(limit))))
    with transaction(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(row) for row in rows]


def _ensure_action(case_id, action_type, title, due_date=None, note=None, db_path=None):
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM actions WHERE case_id=? AND action_type=? AND status='TODO' ORDER BY id DESC LIMIT 1",
            (int(case_id), action_type),
        ).fetchone()
    if row:
        return None
    return create_action(
        case_id,
        title,
        action_type=action_type,
        due_date=due_date,
        responsible="Nicolás / Case Hunter",
        note=note,
        db_path=db_path,
    )


def _manual_outreach_targets(db_path=None):
    """Return only recipient addresses that map unambiguously to one case."""
    with transaction(db_path) as conn:
        contact_rows = conn.execute(
            "SELECT id AS contact_id,case_id,email FROM contacts WHERE status<>'REJECTED' AND email IS NOT NULL"
        ).fetchall()
        outreach_rows = conn.execute(
            "SELECT contact_id,case_id,recipient_email AS email FROM outreach_messages WHERE recipient_email IS NOT NULL"
        ).fetchall()

    grouped = {}
    for raw in list(contact_rows) + list(outreach_rows):
        row = row_to_dict(raw)
        email = (row.get("email") or "").strip().lower()
        if not email:
            continue
        entry = grouped.setdefault(email, {"case_ids": set(), "contact_ids": []})
        entry["case_ids"].add(int(row["case_id"]))
        if row.get("contact_id") is not None:
            entry["contact_ids"].append(int(row["contact_id"]))

    targets = []
    ambiguous = 0
    for email, entry in grouped.items():
        if len(entry["case_ids"]) != 1:
            ambiguous += 1
            continue
        targets.append({
            "email": email,
            "case_id": next(iter(entry["case_ids"])),
            "contact_id": entry["contact_ids"][0] if entry["contact_ids"] else None,
        })
    return targets, ambiguous


def sync_manual_outreach(db_path=None):
    """Import manually sent Gmail messages when recipient-to-case identity is exact.

    The bridge deliberately skips ambiguous recipient addresses. It never guesses a
    case from message text or a company domain.
    """
    if not imap_configured():
        return {"configured": False, "targets": 0, "ambiguous": 0, "checked": 0, "imported": 0}

    targets, ambiguous = _manual_outreach_targets(db_path)
    sent_messages = fetch_sent_messages(targets)
    imported = 0
    now = utc_now()
    for message in sent_messages:
        provider_id = (message.get("provider_message_id") or "").strip()
        if not provider_id:
            continue
        dedupe_key = hashlib.sha256(
            f"MANUAL_GMAIL|{int(message['case_id'])}|{provider_id}".encode("utf-8")
        ).hexdigest()
        with transaction(db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM outreach_messages WHERE provider_message_id=? OR dedupe_key=? LIMIT 1",
                (provider_id, dedupe_key),
            ).fetchone()
            if existing:
                continue
            conn.execute(
                """INSERT INTO outreach_messages(
                       case_id,contact_id,recipient_email,subject,body,status,dedupe_key,
                       sent_at,provider_message_id,created_at,updated_at
                   ) VALUES(?,?,?,?,?,'SENT',?,?,?,?,?)""",
                (
                    int(message["case_id"]), message.get("contact_id"), message["recipient_email"],
                    message.get("subject") or "Correo Gmail importado", message.get("body") or "",
                    dedupe_key, message.get("sent_at") or now, provider_id, now, now,
                ),
            )
            imported += 1
    return {
        "configured": True,
        "targets": len(targets),
        "ambiguous": ambiguous,
        "checked": len(sent_messages),
        "imported": imported,
    }


def _apply_reply_to_case(reply, decision, db_path=None):
    case_id = int(reply["case_id"])
    today = date.today().isoformat()

    if decision.next_case_status:
        update_case_status(case_id, decision.next_case_status, db_path)

    if decision.classification == "PILOT_REQUESTED":
        start_pilot(
            case_id,
            note="La empresa solicitó o confirmó que Case Hunter continúe realizando seguimiento activo del caso.",
            db_path=db_path,
        )

    if decision.action_type and decision.action_title:
        notes = {
            "SEND_PUBLIC_SUMMARY": "La empresa respondió positivamente o pidió antecedentes. Mantener separados hechos confirmados e hipótesis.",
            "CONFIRM_CURRENT_BLOCKER": "La empresa indicó que la situación continúa pendiente.",
            "ESCALATE_RESPONSIBLE_UNIT": "El organismo no respondió. Identificar responsable actual y pedir folio, estado y fecha concreta.",
            "WATCH_PUBLIC_CASE": "Piloto activo. Revisar cambios públicos y respuestas del organismo; avisar solo cuando exista una novedad accionable.",
            "NO_FURTHER_OUTREACH": f"Clasificación automática de respuesta: {decision.classification}.",
            "REVIEW_REPLY": "La respuesta no pudo clasificarse con suficiente precisión.",
        }
        _ensure_action(
            case_id,
            decision.action_type,
            decision.action_title,
            due_date=today,
            note=notes.get(decision.action_type),
            db_path=db_path,
        )

    details = (reply.get("body") or "")[:4000] if STORE_REPLY_CONTENT else "Contenido no persistido por privacidad; solo se guardó la clasificación automática."
    add_timeline_event(
        case_id,
        title=f"Respuesta de empresa: {decision.classification}",
        details=details,
        event_type="COMPANY_REPLY",
        event_date=today,
        source_url=None,
        db_path=db_path,
    )


def ingest_reply(reply, db_path=None):
    decision = analyze_reply(reply.get("body"))
    classification = decision.classification
    now = utc_now()
    provider_id = (reply.get("provider_message_id") or "").strip()
    if not provider_id:
        raise ValueError("La respuesta no tiene Message-ID")
    stored_subject = reply.get("subject") if STORE_REPLY_CONTENT else None
    stored_body = reply.get("body") if STORE_REPLY_CONTENT else None
    with transaction(db_path) as conn:
        existing = conn.execute("SELECT id FROM outreach_replies WHERE provider_message_id=?", (provider_id,)).fetchone()
        if existing:
            return {"created": False, "reply": row_to_dict(conn.execute("SELECT * FROM outreach_replies WHERE id=?", (existing["id"],)).fetchone())}
        cur = conn.execute(
            """INSERT INTO outreach_replies(outreach_id,case_id,provider_message_id,in_reply_to,sender_email,subject,body,classification,received_at,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                int(reply["outreach_id"]), int(reply["case_id"]), provider_id, reply.get("in_reply_to"),
                reply.get("sender_email"), stored_subject, stored_body, classification,
                reply.get("received_at") or now, now,
            ),
        )
        reply_id = cur.lastrowid
        conn.execute(
            "UPDATE outreach_messages SET status='REPLIED',updated_at=?,last_error=NULL WHERE id=?",
            (now, int(reply["outreach_id"])),
        )
        conn.execute(
            "UPDATE followups SET status='CANCELLED',updated_at=? WHERE outreach_id=? AND status IN ('PENDING','DUE','READY')",
            (now, int(reply["outreach_id"])),
        )
    _apply_reply_to_case(reply, decision, db_path)
    with transaction(db_path) as conn:
        row = conn.execute("SELECT * FROM outreach_replies WHERE id=?", (reply_id,)).fetchone()
    return {"created": True, "reply": row_to_dict(row)}


def ingest_delivery_failure(failure, db_path=None):
    """Record a delivery failure without treating it as a prospect reply."""
    outreach_id = int(failure["outreach_id"])
    case_id = int(failure["case_id"])
    recipient = (failure.get("recipient_email") or "").strip().lower()
    provider_id = (failure.get("provider_message_id") or "").strip()
    kind = (failure.get("failure_kind") or "BOUNCED").strip().upper()
    if kind not in {"INVALID", "BLOCKED", "BOUNCED"}:
        kind = "BOUNCED"
    reason = (failure.get("reason") or "Delivery failure")[:2000]
    now = utc_now()

    with transaction(db_path) as conn:
        current = conn.execute(
            "SELECT id,status,recipient_email FROM outreach_messages WHERE id=? AND case_id=?",
            (outreach_id, case_id),
        ).fetchone()
        if current is None:
            raise KeyError("Mensaje de prospección no encontrado para el rebote")
        if current["status"] in {"BOUNCED", "DELIVERY_BLOCKED"}:
            return {"created": False, "failure_kind": kind, "outreach_id": outreach_id}

    mark_delivery_failure(
        recipient or current["recipient_email"],
        kind,
        reason=reason,
        provider_message_id=provider_id or None,
        db_path=db_path,
    )

    outbound_status = "DELIVERY_BLOCKED" if kind == "BLOCKED" else "BOUNCED"
    rejected_email = recipient or (current["recipient_email"] or "").strip().lower()
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE outreach_messages SET status=?,last_error=?,updated_at=? WHERE id=?",
            (outbound_status, f"{kind}: {reason}", now, outreach_id),
        )
        conn.execute(
            "UPDATE followups SET status='CANCELLED',updated_at=? WHERE outreach_id=? AND status IN ('PENDING','DUE','READY')",
            (now, outreach_id),
        )
        if rejected_email:
            conn.execute(
                "UPDATE contacts SET status='REJECTED',updated_at=? WHERE lower(email)=?",
                (now, rejected_email),
            )

    _ensure_action(
        case_id,
        "FIND_ALTERNATE_CONTACT",
        "Buscar contacto corporativo alternativo verificado",
        due_date=date.today().isoformat(),
        note=f"El envío a {rejected_email or 'el contacto anterior'} falló ({kind}). No reutilizar esa dirección; validar un canal alternativo antes de preparar otro correo.",
        db_path=db_path,
    )
    add_timeline_event(
        case_id,
        title=f"Fallo de entrega: {kind}",
        details=f"Destinatario: {rejected_email or 'desconocido'}. {reason}"[:3000],
        event_type="DELIVERY_FAILURE",
        event_date=date.today().isoformat(),
        source_url=None,
        db_path=db_path,
    )
    return {"created": True, "failure_kind": kind, "outreach_id": outreach_id, "status": outbound_status}


def _run_background_case_intelligence(db_path=None):
    # Use the same bounded watcher as the production worker. This prevents reply
    # synchronization from bypassing the per-case source budget.
    public_watch = run_bounded_active_watches(
        db_path=db_path,
        source_limit_per_case=WATCH_SOURCES_PER_CASE,
        max_sources_per_case=MAX_WATCH_SOURCES_PER_CASE,
    )
    # Portfolios run before precedent learning so newly discovered resolved cases
    # are immediately available as evidence in the same cycle.
    pilot_portfolios = refresh_due_pilot_portfolios(db_path=db_path)
    resolution_learning = refresh_active_pilot_recommendations(db_path=db_path)
    return {
        "public_watch": public_watch,
        "pilot_portfolios": pilot_portfolios,
        "resolution_learning": resolution_learning,
    }


def sync_replies(db_path=None):
    if not imap_configured():
        intelligence = _run_background_case_intelligence(db_path)
        return {
            "configured": False, "checked": 0, "created": 0, "classifications": {},
            "manual_outreach_imported": 0,
            "delivery_failures_checked": 0,
            "delivery_failures_created": 0,
            "delivery_failure_kinds": {},
            **intelligence,
        }

    manual = sync_manual_outreach(db_path)
    with transaction(db_path) as conn:
        rows = conn.execute(
            """SELECT id,case_id,contact_id,recipient_email,subject,provider_message_id,status
               FROM outreach_messages
               WHERE status IN ('SENT','REPLIED') AND recipient_email IS NOT NULL
               ORDER BY id DESC LIMIT 300"""
        ).fetchall()
    messages = [row_to_dict(row) for row in rows]

    failures = fetch_delivery_failures(messages)
    failures_created = 0
    failure_kinds = {}
    for failure in failures:
        result = ingest_delivery_failure(failure, db_path)
        if result["created"]:
            failures_created += 1
            kind = result["failure_kind"]
            failure_kinds[kind] = failure_kinds.get(kind, 0) + 1

    incoming = fetch_replies(messages)
    created = 0
    classes = {}
    for reply in incoming:
        result = ingest_reply(reply, db_path)
        if result["created"]:
            created += 1
            label = result["reply"]["classification"]
            classes[label] = classes.get(label, 0) + 1

    intelligence = _run_background_case_intelligence(db_path)
    return {
        "configured": True,
        "checked": len(incoming),
        "created": created,
        "classifications": classes,
        "manual_outreach_checked": manual["checked"],
        "manual_outreach_imported": manual["imported"],
        "manual_targets_ambiguous": manual["ambiguous"],
        "delivery_failures_checked": len(failures),
        "delivery_failures_created": failures_created,
        "delivery_failure_kinds": failure_kinds,
        **intelligence,
    }
