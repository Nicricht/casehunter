import hashlib
import re
from email.message import EmailMessage
from email.utils import make_msgid
import smtplib

from .config import SMTP_FROM_NAME, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USERNAME
from .database import row_to_dict, transaction, utc_now
from .delivery_health import is_unusable_email
from .repository import get_case

EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)
VALID_OUTREACH_STATUSES = {
    "NEEDS_CONTACT", "READY_FOR_APPROVAL", "APPROVED", "SENT", "REPLIED",
    "FAILED", "REJECTED", "SKIPPED_DUPLICATE", "BOUNCED", "DELIVERY_BLOCKED",
}


def _problem_summary(case):
    types = {p.get("type") for p in case.get("problems", [])}
    parts = []
    if any("RETENTION" in str(v) for v in types):
        parts.append("retenciones contractuales")
    if any("PAYMENT" in str(v) or "PURCHASE_ORDER" in str(v) for v in types):
        parts.append("pagos o estados de pago")
    if any("LIQUIDATION" in str(v) or "CLOSURE" in str(v) for v in types):
        parts.append("liquidación o cierre administrativo")
    if any("GUARANTEE" in str(v) for v in types):
        parts.append("garantías")
    if not parts:
        blocker = (case.get("current_blocker") or "").replace("_", " ").lower()
        parts.append(blocker or "tramitación contractual")
    return ", ".join(parts[:3])


def build_outreach_email(case):
    company = case.get("company_name") or case.get("detected_company_name") or "su empresa"
    contract = case.get("contract_ref")
    signal = _problem_summary(case)
    if "retencion" in signal.lower() or "retención" in signal.lower():
        subject = "Antecedentes públicos sobre retenciones contractuales"
    elif "pago" in signal.lower():
        subject = "Antecedentes públicos sobre estado de pago"
    elif "liquidación" in signal.lower() or "cierre" in signal.lower():
        subject = "Antecedentes públicos sobre liquidación de contratos"
    else:
        subject = "Antecedentes públicos sobre contrato"
    contract_phrase = f" y {contract}" if contract else ""
    body = f"""Hola, buenos días.

Revisando antecedentes públicos encontré gestiones relacionadas con {company}{contract_phrase}, donde aparecen materias asociadas a {signal}.

Estoy desarrollando Case Hunter, una herramienta independiente que detecta y ordena antecedentes públicos sobre contratos, pagos y cierres administrativos con organismos públicos. No represento al organismo ni a una empresa de cobranza.

La utilidad concreta es preparar una ficha breve con cronología, fuentes públicas, señales del posible bloqueo y las siguientes gestiones que conviene validar, separando claramente lo confirmado de lo que todavía requiere información de la empresa.

En su caso encontré suficientes antecedentes públicos para preparar esa síntesis de una página.

¿Se las envío?

Saludos,
Nicolás Vega
"""
    return {"subject": subject, "body": body}


def _dedupe_key(case_id, recipient_email):
    raw = f"{int(case_id)}|{(recipient_email or 'pending').strip().lower()}|FIRST_CONTACT_V1"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _assert_recipient_usable(email, db_path=None):
    address = (email or "").strip().lower()
    if address and is_unusable_email(address, db_path):
        raise ValueError("El correo está suprimido por un fallo de entrega anterior; busca un contacto alternativo")


def list_outreach(status=None, db_path=None):
    query = """SELECT o.*, k.detected_company_name, k.contract_ref, k.financial_priority,
                      c.company_name contact_company, c.source_url contact_source_url
               FROM outreach_messages o
               JOIN cases k ON k.id=o.case_id
               LEFT JOIN contacts c ON c.id=o.contact_id"""
    params = []
    if status:
        query += " WHERE o.status=?"
        params.append(status)
    query += " ORDER BY CASE o.status WHEN 'APPROVED' THEN 0 WHEN 'READY_FOR_APPROVAL' THEN 1 WHEN 'NEEDS_CONTACT' THEN 2 ELSE 3 END, k.financial_priority DESC, o.id DESC"
    with transaction(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(row) for row in rows]


def get_outreach(message_id, db_path=None):
    with transaction(db_path) as conn:
        row = conn.execute("SELECT * FROM outreach_messages WHERE id=?", (int(message_id),)).fetchone()
    if row is None:
        raise KeyError("Mensaje de prospección no encontrado")
    return row_to_dict(row)


def ensure_outreach_draft(case_id, recipient_email=None, contact_id=None, db_path=None):
    case = get_case(case_id, db_path)
    email = (recipient_email or "").strip().lower() or None
    if email and not EMAIL_RE.match(email):
        raise ValueError("El correo de contacto no es válido")
    if email:
        _assert_recipient_usable(email, db_path)
    payload = build_outreach_email(case)
    key = _dedupe_key(case_id, email)
    now = utc_now()
    status = "READY_FOR_APPROVAL" if email else "NEEDS_CONTACT"
    with transaction(db_path) as conn:
        existing = conn.execute("SELECT id FROM outreach_messages WHERE dedupe_key=?", (key,)).fetchone()
        if existing:
            message_id = existing["id"]
            created = False
        elif email:
            pending = conn.execute(
                "SELECT id FROM outreach_messages WHERE case_id=? AND status='NEEDS_CONTACT' ORDER BY id LIMIT 1",
                (int(case_id),),
            ).fetchone()
            if pending:
                message_id = pending["id"]
                conn.execute(
                    """UPDATE outreach_messages SET contact_id=?,recipient_email=?,status='READY_FOR_APPROVAL',
                       dedupe_key=?,subject=?,body=?,updated_at=? WHERE id=?""",
                    (contact_id, email, key, payload["subject"], payload["body"], now, message_id),
                )
                created = False
            else:
                cur = conn.execute(
                    """INSERT INTO outreach_messages(case_id,contact_id,recipient_email,subject,body,status,dedupe_key,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (int(case_id), contact_id, email, payload["subject"], payload["body"], status, key, now, now),
                )
                message_id = cur.lastrowid
                created = True
        else:
            cur = conn.execute(
                """INSERT INTO outreach_messages(case_id,contact_id,recipient_email,subject,body,status,dedupe_key,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (int(case_id), contact_id, None, payload["subject"], payload["body"], status, key, now, now),
            )
            message_id = cur.lastrowid
            created = True
    return {"message": get_outreach(message_id, db_path), "created": created}


def attach_recipient(message_id, recipient_email, contact_id=None, db_path=None):
    email = (recipient_email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("El correo de contacto no es válido")
    _assert_recipient_usable(email, db_path)
    message = get_outreach(message_id, db_path)
    key = _dedupe_key(message["case_id"], email)
    now = utc_now()
    with transaction(db_path) as conn:
        duplicate = conn.execute("SELECT id FROM outreach_messages WHERE dedupe_key=? AND id<>?", (key, int(message_id))).fetchone()
        if duplicate:
            raise ValueError("Ya existe un primer contacto preparado para este caso y destinatario")
        conn.execute(
            """UPDATE outreach_messages SET recipient_email=?,contact_id=?,status='READY_FOR_APPROVAL',dedupe_key=?,updated_at=?,last_error=NULL WHERE id=?""",
            (email, contact_id, key, now, int(message_id)),
        )
    return get_outreach(message_id, db_path)


def approve_outreach(message_id, recipient_email=None, db_path=None):
    if recipient_email:
        attach_recipient(message_id, recipient_email, db_path=db_path)
    message = get_outreach(message_id, db_path)
    if message["status"] in {"SENT", "REPLIED"}:
        raise ValueError("El mensaje ya fue enviado")
    if not message.get("recipient_email"):
        raise ValueError("Falta un correo de destinatario confirmado")
    _assert_recipient_usable(message["recipient_email"], db_path)
    now = utc_now()
    with transaction(db_path) as conn:
        conn.execute("UPDATE outreach_messages SET status='APPROVED',approved_at=?,updated_at=?,last_error=NULL WHERE id=?", (now, now, int(message_id)))
    return get_outreach(message_id, db_path)


def reject_outreach(message_id, db_path=None):
    get_outreach(message_id, db_path)
    now = utc_now()
    with transaction(db_path) as conn:
        conn.execute("UPDATE outreach_messages SET status='REJECTED',updated_at=? WHERE id=?", (now, int(message_id)))
    return get_outreach(message_id, db_path)


def smtp_configured():
    return bool(SMTP_USERNAME and SMTP_PASSWORD and SMTP_HOST and SMTP_PORT)


def _send_smtp(recipient, subject, body):
    if not smtp_configured():
        raise RuntimeError("SMTP no configurado. Define las credenciales de Gmail fuera del código.")
    msg = EmailMessage()
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USERNAME}>" if SMTP_FROM_NAME else SMTP_USERNAME
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()
    msg.set_content(body)
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
    return msg["Message-ID"]


def send_outreach(message_id, db_path=None, sender=None):
    message = get_outreach(message_id, db_path)
    if message["status"] not in {"APPROVED", "FAILED"}:
        raise ValueError("El mensaje debe estar aprobado antes de enviarse")
    if message["status"] == "FAILED" and not message.get("approved_at"):
        raise ValueError("El mensaje fallido no tiene aprobación previa")
    _assert_recipient_usable(message.get("recipient_email"), db_path)

    if sender is None:
        from .gmail_service import imap_configured, was_recipient_contacted
        if imap_configured() and was_recipient_contacted(message["recipient_email"]):
            now = utc_now()
            with transaction(db_path) as conn:
                conn.execute(
                    "UPDATE outreach_messages SET status='SKIPPED_DUPLICATE',last_error=?,updated_at=? WHERE id=?",
                    ("Gmail indica que este destinatario ya fue contactado anteriormente", now, int(message_id)),
                )
            return get_outreach(message_id, db_path)

    send_fn = sender or _send_smtp
    now = utc_now()
    try:
        provider_id = send_fn(message["recipient_email"], message["subject"], message["body"])
    except Exception as exc:
        with transaction(db_path) as conn:
            conn.execute("UPDATE outreach_messages SET status='FAILED',last_error=?,updated_at=? WHERE id=?", (str(exc), now, int(message_id)))
        raise
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE outreach_messages SET status='SENT',sent_at=?,provider_message_id=?,last_error=NULL,updated_at=? WHERE id=?",
            (now, str(provider_id or "sent"), now, int(message_id)),
        )
    from .followup import schedule_followup
    schedule_followup(message_id, db_path=db_path)
    return get_outreach(message_id, db_path)
