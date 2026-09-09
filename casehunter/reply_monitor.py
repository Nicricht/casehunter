from datetime import date

from .config import STORE_REPLY_CONTENT
from .database import row_to_dict, transaction, utc_now
from .gmail_service import fetch_replies, imap_configured
from .repository import add_timeline_event, create_action, update_case_status

REPLY_CLASSES = {
    "POSITIVE",
    "REQUESTS_INFO",
    "STILL_PENDING",
    "RESOLVED",
    "NOT_INTERESTED",
    "NEGATIVE",
    "OTHER",
}


def classify_reply(text):
    value = (text or "").strip().lower()
    if not value:
        return "OTHER"

    resolved = [
        "ya está resuelto", "ya esta resuelto", "se resolvió", "se resolvio", "ya fue pagado",
        "ya se pagó", "ya se pago", "ya fue liquidado", "ya se liquidó", "ya se liquido",
        "ya está cerrado", "ya esta cerrado", "no está pendiente", "no esta pendiente",
    ]
    pending = [
        "sigue pendiente", "aún está pendiente", "aun esta pendiente", "continúa pendiente",
        "continua pendiente", "todavía está pendiente", "todavia esta pendiente", "no hemos recibido el pago",
        "no nos han pagado", "no se ha pagado", "no se ha liquidado", "no se ha liberado",
    ]
    not_interested = [
        "no nos interesa", "no me interesa", "no estamos interesados", "no gracias", "no enviar",
        "no nos contacte", "no me contacte", "favor no contactar",
    ]
    asks_info = [
        "envíamela", "enviamela", "envíemela", "enviemela", "envíenosla", "envienosla",
        "puede enviar", "puedes enviar", "mándamela", "mandamela", "comparta la información",
        "comparta la informacion", "envíe la información", "envie la informacion", "sí, por favor", "si, por favor",
        "envíame", "enviame", "envíenos", "envienos",
    ]
    positive = ["me interesa", "nos interesa", "interesados", "de acuerdo", "perfecto", "adelante"]
    negative = ["no corresponde", "está equivocado", "esta equivocado", "empresa incorrecta", "contrato incorrecto"]

    if any(token in value for token in resolved):
        return "RESOLVED"
    if any(token in value for token in pending):
        return "STILL_PENDING"
    if any(token in value for token in not_interested):
        return "NOT_INTERESTED"
    if any(token in value for token in asks_info):
        return "REQUESTS_INFO"
    if any(token in value for token in negative):
        return "NEGATIVE"
    if any(token in value for token in positive) or value in {"sí", "si", "ok", "okay"}:
        return "POSITIVE"
    return "OTHER"


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


def _apply_reply_to_case(reply, classification, db_path=None):
    case_id = int(reply["case_id"])
    today = date.today().isoformat()
    if classification in {"POSITIVE", "REQUESTS_INFO"}:
        update_case_status(case_id, "VALIDATING", db_path)
        _ensure_action(
            case_id,
            "SEND_PUBLIC_SUMMARY",
            "Enviar síntesis pública de una página solicitada por la empresa",
            due_date=today,
            note="La empresa respondió positivamente o pidió antecedentes. Mantener separados hechos confirmados e hipótesis.",
            db_path=db_path,
        )
    elif classification == "STILL_PENDING":
        update_case_status(case_id, "VALIDATING", db_path)
        _ensure_action(
            case_id,
            "CONFIRM_CURRENT_BLOCKER",
            "Confirmar con la empresa cuál es el bloqueo administrativo actual",
            due_date=today,
            note="La empresa indicó que la situación continúa pendiente.",
            db_path=db_path,
        )
    elif classification == "RESOLVED":
        update_case_status(case_id, "RESOLVED", db_path)
    elif classification in {"NOT_INTERESTED", "NEGATIVE"}:
        _ensure_action(
            case_id,
            "NO_FURTHER_OUTREACH",
            "No realizar nuevos contactos comerciales sobre este caso",
            due_date=today,
            note=f"Clasificación automática de respuesta: {classification}.",
            db_path=db_path,
        )
    else:
        _ensure_action(
            case_id,
            "REVIEW_REPLY",
            "Revisar manualmente la respuesta recibida",
            due_date=today,
            note="La respuesta no pudo clasificarse con suficiente precisión.",
            db_path=db_path,
        )

    details = (reply.get("body") or "")[:4000] if STORE_REPLY_CONTENT else "Contenido no persistido por privacidad; solo se guardó la clasificación automática."
    add_timeline_event(
        case_id,
        title=f"Respuesta de empresa: {classification}",
        details=details,
        event_type="COMPANY_REPLY",
        event_date=today,
        source_url=None,
        db_path=db_path,
    )


def ingest_reply(reply, db_path=None):
    classification = classify_reply(reply.get("body"))
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
    _apply_reply_to_case(reply, classification, db_path)
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
