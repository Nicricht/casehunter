from datetime import datetime, timedelta, timezone

from .config import AUTO_FOLLOWUP_DAYS, AUTO_SEND_FOLLOWUPS
from .database import row_to_dict, transaction, utc_now


def _followup_body(company_name=None):
    company = company_name or ""
    greeting = f"Hola, {company}." if company else "Hola, buenos días."
    return f"""{greeting}

Quería retomar el correo anterior sobre los antecedentes públicos que encontré asociados a uno de sus contratos con un organismo público.

Si la situación sigue vigente, puedo enviarles la síntesis breve con las fechas, antecedentes y fuentes públicas para que la revisen.

¿Se las envío?

Saludos,
Nicolás Vega
"""


def schedule_followup(outreach_id, db_path=None, due_days=None):
    days = AUTO_FOLLOWUP_DAYS if due_days is None else max(1, int(due_days))
    due_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    now = utc_now()
    with transaction(db_path) as conn:
        outreach = conn.execute(
            """SELECT o.id,o.case_id,o.recipient_email,o.subject,o.status,k.detected_company_name
               FROM outreach_messages o JOIN cases k ON k.id=o.case_id WHERE o.id=?""",
            (int(outreach_id),),
        ).fetchone()
        if outreach is None:
            raise KeyError("Mensaje de prospección no encontrado")
        if outreach["status"] not in {"SENT", "REPLIED"}:
            return None
        existing = conn.execute("SELECT id FROM followups WHERE outreach_id=? AND sequence=1", (int(outreach_id),)).fetchone()
        if existing:
            return row_to_dict(conn.execute("SELECT * FROM followups WHERE id=?", (existing["id"],)).fetchone())
        cur = conn.execute(
            """INSERT INTO followups(outreach_id,case_id,sequence,status,due_at,subject,body,created_at,updated_at)
               VALUES(?,?,1,'PENDING',?,?,?,?,?)""",
            (
                int(outreach_id), int(outreach["case_id"]), due_at,
                f"Re: {outreach['subject']}", _followup_body(outreach["detected_company_name"]), now, now,
            ),
        )
        return row_to_dict(conn.execute("SELECT * FROM followups WHERE id=?", (cur.lastrowid,)).fetchone())


def list_followups(status=None, limit=100, db_path=None):
    query = """SELECT f.*,o.recipient_email,k.detected_company_name,k.contract_ref,k.financial_priority
               FROM followups f JOIN outreach_messages o ON o.id=f.outreach_id JOIN cases k ON k.id=f.case_id"""
    params = []
    if status:
        query += " WHERE f.status=?"
        params.append(status)
    query += " ORDER BY f.due_at ASC LIMIT ?"
    params.append(max(1, min(500, int(limit))))
    with transaction(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(row) for row in rows]


def process_due_followups(db_path=None, send=None, sender=None):
    do_send = AUTO_SEND_FOLLOWUPS if send is None else bool(send)
    if do_send and sender is None:
        from .outreach import smtp_configured
        if not smtp_configured():
            do_send = False
    now = utc_now()
    with transaction(db_path) as conn:
        conn.execute(
            """UPDATE followups SET status='DUE',updated_at=?
               WHERE status='PENDING' AND due_at<=? AND outreach_id IN
               (SELECT id FROM outreach_messages WHERE status='SENT')""",
            (now, now),
        )
        rows = conn.execute(
            """SELECT f.*,o.recipient_email,o.approved_at,o.status outreach_status
               FROM followups f JOIN outreach_messages o ON o.id=f.outreach_id
               WHERE f.status='DUE' ORDER BY f.due_at ASC"""
        ).fetchall()
    due = [row_to_dict(row) for row in rows]
    sent = 0
    failed = 0
    if do_send:
        from .outreach import _send_smtp
        send_fn = sender or _send_smtp
        for item in due:
            if not item.get("approved_at") or item.get("outreach_status") != "SENT":
                continue
            try:
                provider_id = send_fn(item["recipient_email"], item["subject"], item["body"])
            except Exception as exc:
                failed += 1
                with transaction(db_path) as conn:
                    conn.execute(
                        "UPDATE followups SET status='FAILED',last_error=?,updated_at=? WHERE id=?",
                        (str(exc), utc_now(), int(item["id"])),
                    )
                continue
            sent += 1
            now_sent = utc_now()
            with transaction(db_path) as conn:
                conn.execute(
                    "UPDATE followups SET status='SENT',sent_at=?,provider_message_id=?,last_error=NULL,updated_at=? WHERE id=?",
                    (now_sent, str(provider_id or "sent"), now_sent, int(item["id"])),
                )
    return {"due": len(due), "sent": sent, "failed": failed, "automatic_send": do_send}
