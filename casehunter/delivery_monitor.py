import email

from .gmail_service import _connect, _date_iso, _decode_header, _plain_text, imap_configured


INVALID_MARKERS = (
    "no such user",
    "address not found",
    "no se encontró la dirección",
    "no se encontro la direccion",
    "the email account that you tried to reach does not exist",
    "domain not found",
    "no encontramos el dominio",
    "5.1.1",
)
BLOCKED_MARKERS = (
    "message blocked",
    "mensaje se bloqueó",
    "mensaje se bloqueo",
    "se bloqueó tu mensaje",
    "se bloqueo tu mensaje",
    "blocked your message",
)


def classify_delivery_failure(subject, body):
    text = f"{subject or ''}\n{body or ''}".lower()
    if any(marker in text for marker in BLOCKED_MARKERS):
        return "BLOCKED"
    if any(marker in text for marker in INVALID_MARKERS):
        return "INVALID"
    return "BOUNCED"


def _failure_reason(subject, body, limit=800):
    text = " ".join((body or subject or "Delivery failure").split())
    return text[: max(80, int(limit))]


def fetch_delivery_failures(messages, since_days=45, max_messages=300):
    """Return Gmail DSNs that can be tied to a known outbound recipient.

    Delivery notifications are deliberately handled separately from commercial
    replies because Gmail sends them from mailer-daemon, not from the prospect.
    The newest outbound message for a recipient wins when more than one exists.
    """
    if not imap_configured() or not messages:
        return []

    by_recipient = {}
    for outbound in messages:
        recipient = (outbound.get("recipient_email") or "").strip().lower()
        if recipient and recipient not in by_recipient:
            by_recipient[recipient] = outbound
    if not by_recipient:
        return []

    client = _connect()
    results = []
    seen_ids = set()
    try:
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            return []

        from datetime import datetime, timedelta, timezone

        since = (datetime.now(timezone.utc) - timedelta(days=max(1, int(since_days)))).strftime("%d-%b-%Y")
        status, data = client.search(None, "SINCE", since, "FROM", '"mailer-daemon@googlemail.com"')
        if status != "OK" or not data:
            return []

        ids = data[0].split()[-max(1, int(max_messages)):]
        for msg_num in ids:
            status, payload = client.fetch(msg_num, "(RFC822)")
            if status != "OK" or not payload:
                continue
            raw = next((item[1] for item in payload if isinstance(item, tuple) and len(item) > 1), None)
            if not raw:
                continue
            message = email.message_from_bytes(raw)
            provider_id = (message.get("Message-ID") or f"imap-dsn:{msg_num.decode(errors='ignore')}").strip()
            if provider_id in seen_ids:
                continue

            subject = _decode_header(message.get("Subject"))
            body = _plain_text(message).strip()
            haystack = f"{subject}\n{body}".lower()
            matches = [address for address in by_recipient if address in haystack]
            if len(matches) != 1:
                continue

            recipient = matches[0]
            outbound = by_recipient[recipient]
            seen_ids.add(provider_id)
            results.append({
                "outreach_id": int(outbound["id"]),
                "case_id": int(outbound["case_id"]),
                "contact_id": outbound.get("contact_id"),
                "recipient_email": recipient,
                "provider_message_id": provider_id,
                "failure_kind": classify_delivery_failure(subject, body),
                "reason": _failure_reason(subject, body),
                "received_at": _date_iso(message.get("Date")) or message.get("Date") or None,
            })
        return results
    finally:
        try:
            client.logout()
        except Exception:
            pass
