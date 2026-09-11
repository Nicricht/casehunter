import email
import imaplib
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime

from .config import IMAP_HOST, IMAP_PASSWORD, IMAP_PORT, IMAP_USERNAME


def imap_configured():
    return bool(IMAP_HOST and IMAP_PORT and IMAP_USERNAME and IMAP_PASSWORD)


def _decode_header(value):
    if not value:
        return ""
    parts = []
    for chunk, encoding in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts)


def _plain_text(message):
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")).lower():
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    payload = message.get_payload(decode=True)
    if payload is None:
        return str(message.get_payload() or "")
    return payload.decode(message.get_content_charset() or "utf-8", errors="replace")


def _normalize_subject(subject):
    text = _decode_header(subject).strip().lower()
    while True:
        cleaned = re.sub(r"^(re|rv|fw|fwd)\s*:\s*", "", text, flags=re.I).strip()
        if cleaned == text:
            return cleaned
        text = cleaned


def _date_iso(value):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _connect():
    if not imap_configured():
        raise RuntimeError("Gmail/IMAP no configurado")
    client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    client.login(IMAP_USERNAME, IMAP_PASSWORD)
    return client


def _mailbox_with_flag(client, flag, fallback):
    status, rows = client.list()
    if status == "OK":
        for raw in rows or []:
            line = raw.decode("utf-8", errors="replace")
            if flag.lower() not in line.lower():
                continue
            match = re.search(r'"([^"]+)"\s*$', line)
            if match:
                return match.group(1)
            tail = line.rsplit(" ", 1)[-1].strip('"')
            if tail:
                return tail
    return fallback


def was_recipient_contacted(recipient_email):
    address = (recipient_email or "").strip().lower()
    if not address or not imap_configured():
        return False
    client = _connect()
    try:
        mailbox = _mailbox_with_flag(client, "\\Sent", "[Gmail]/Sent Mail")
        status, _ = client.select(f'"{mailbox}"', readonly=True)
        if status != "OK":
            return False
        status, data = client.search(None, "TO", f'"{address}"')
        return bool(status == "OK" and data and data[0].split())
    finally:
        try:
            client.logout()
        except Exception:
            pass


def fetch_sent_messages(targets, since_days=45, max_messages_per_contact=20):
    """Read manually-sent Gmail messages only for unambiguous known case contacts.

    Targets must already be resolved to one case by the caller. This function does
    not guess company identity from domains or message text.
    """
    if not imap_configured() or not targets:
        return []
    client = _connect()
    results = []
    seen_ids = set()
    try:
        mailbox = _mailbox_with_flag(client, "\\Sent", "[Gmail]/Sent Mail")
        status, _ = client.select(f'"{mailbox}"', readonly=True)
        if status != "OK":
            return []
        since = (datetime.now(timezone.utc) - timedelta(days=max(1, int(since_days)))).strftime("%d-%b-%Y")
        for target in targets:
            recipient = (target.get("email") or "").strip().lower()
            if not recipient:
                continue
            status, data = client.search(None, "SINCE", since, "TO", f'"{recipient}"')
            if status != "OK" or not data:
                continue
            ids = data[0].split()[-max(1, int(max_messages_per_contact)):]
            for msg_num in ids:
                status, payload = client.fetch(msg_num, "(RFC822)")
                if status != "OK" or not payload:
                    continue
                raw = next((item[1] for item in payload if isinstance(item, tuple) and len(item) > 1), None)
                if not raw:
                    continue
                message = email.message_from_bytes(raw)
                message_id = (message.get("Message-ID") or f"imap-sent:{msg_num.decode(errors='ignore')}").strip()
                if message_id in seen_ids:
                    continue
                seen_ids.add(message_id)
                results.append({
                    "case_id": int(target["case_id"]),
                    "contact_id": target.get("contact_id"),
                    "recipient_email": recipient,
                    "provider_message_id": message_id,
                    "subject": _decode_header(message.get("Subject")) or "Correo Gmail importado",
                    "body": _plain_text(message).strip(),
                    "sent_at": _date_iso(message.get("Date")),
                })
        return results
    finally:
        try:
            client.logout()
        except Exception:
            pass


def fetch_replies(messages, since_days=45, max_messages_per_contact=20):
    if not imap_configured() or not messages:
        return []
    client = _connect()
    results = []
    seen_ids = set()
    try:
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            return []
        since = (datetime.now(timezone.utc) - timedelta(days=max(1, int(since_days)))).strftime("%d-%b-%Y")
        for outbound in messages:
            recipient = (outbound.get("recipient_email") or "").strip().lower()
            if not recipient:
                continue
            status, data = client.search(None, "SINCE", since, "FROM", f'"{recipient}"')
            if status != "OK" or not data:
                continue
            ids = data[0].split()[-max(1, int(max_messages_per_contact)):]
            for msg_num in ids:
                status, payload = client.fetch(msg_num, "(RFC822)")
                if status != "OK" or not payload:
                    continue
                raw = next((item[1] for item in payload if isinstance(item, tuple) and len(item) > 1), None)
                if not raw:
                    continue
                message = email.message_from_bytes(raw)
                message_id = (message.get("Message-ID") or f"imap:{msg_num.decode(errors='ignore')}").strip()
                if message_id in seen_ids:
                    continue
                in_reply_to = (message.get("In-Reply-To") or "").strip()
                references = (message.get("References") or "").strip()
                outbound_id = (outbound.get("provider_message_id") or "").strip()
                subject_matches = _normalize_subject(message.get("Subject")) == _normalize_subject(outbound.get("subject"))
                reference_matches = bool(outbound_id and (outbound_id in in_reply_to or outbound_id in references))
                if not (reference_matches or subject_matches):
                    continue
                seen_ids.add(message_id)
                results.append({
                    "outreach_id": int(outbound["id"]),
                    "case_id": int(outbound["case_id"]),
                    "provider_message_id": message_id,
                    "in_reply_to": in_reply_to or None,
                    "sender_email": parseaddr(message.get("From") or "")[1].lower() or recipient,
                    "subject": _decode_header(message.get("Subject")),
                    "body": _plain_text(message).strip(),
                    "received_at": _date_iso(message.get("Date")) or message.get("Date") or None,
                })
        return results
    finally:
        try:
            client.logout()
        except Exception:
            pass
