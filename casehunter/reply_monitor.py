from datetime import date

from .config import STORE_REPLY_CONTENT
from .database import row_to_dict, transaction, utc_now
from .engines.reply_intelligence import REPLY_CLASSES, analyze_reply, classify_reply
from .gmail_service import fetch_replies, imap_configured
from .repository import add_timeline_event, create_action, update_case_status


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


def _apply_reply_to_case(reply, decision, db_path=None):
    case_id = int(reply["case_id"])
    today = date.today().isoformat()

    if decision.next_case_status:
        update_case_status(case_id, decision.next_case_status, db_path)

    if decision.action_type and decision.action_title:
        notes = {
            "SEND_PUBLIC_SUMMARY": "La empresa respondió positivamente o pidió antecedentes. Mantener separados hechos confirmados e hipótesis.",
            "CONFIRM_CURRENT_BLOCKER": "La empresa indicó que la situación continúa pendiente.",
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


def sync_replies(db_path=None):
    if not imap_configured():
        return {"configured": False, "checked": 0, "created": 0, "classifications": {}}
    with transaction(db_path) as conn:
        rows = conn.execute(
            """SELECT id,case_id,recipient_email,subject,provider_message_id,status
               FROM outreach_messages
               WHERE status IN ('SENT','REPLIED') AND recipient_email IS NOT NULL
               ORDER BY id DESC LIMIT 300"""
        ).fetchall()
    messages = [row_to_dict(row) for row in rows]
    incoming = fetch_replies(messages)
    created = 0
    classes = {}
    for reply in incoming:
        result = ingest_reply(reply, db_path)
        if result["created"]:
            created += 1
            label = result["reply"]["classification"]
            classes[label] = classes.get(label, 0) + 1
    return {"configured": True, "checked": len(incoming), "created": created, "classifications": classes}
