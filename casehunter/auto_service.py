import json
import time

from .config import (
    AUTO_CASES_PER_CYCLE, AUTO_CONTACT_DISCOVERY, AUTO_ENRICH_LIMIT, AUTO_INDEX_PAGES,
    AUTO_INTERVAL_MINUTES, AUTO_MAX_FIRST_CONTACTS_PER_DAY, AUTO_MAX_PAGES, AUTO_MIN_PRIORITY,
    AUTO_MONITOR_REPLIES, AUTO_POLICY_SEND, AUTO_SEND_APPROVED, AUTO_SEND_FOLLOWUPS,
    AUTO_SEND_MIN_PRIORITY, AUTO_SOURCE_URLS, AUTO_SUBJECTS_PER_CYCLE,
)
from .contact_discovery import (
    discover_contacts_for_case,
    is_verified_corporate_contact,
    quarantine_unsafe_contacts,
)
from .discovery.source_index import expand_year_index, is_year_index
from .database import row_to_dict, transaction, utc_now
from .followup import process_due_followups
from .gmail_service import imap_configured
from .outreach import approve_outreach, ensure_outreach_draft, list_outreach, send_outreach, smtp_configured
from .reply_monitor import sync_replies
from .repository import get_case
from .scanner_service import run_ley_lobby_scan


def _rotate_source_batch(source_url, subjects, batch_size, db_path=None):
    if not subjects:
        return []
    size = max(1, min(int(batch_size), len(subjects)))
    with transaction(db_path) as conn:
        row = conn.execute("SELECT cursor_index FROM automation_source_state WHERE source_url=?", (source_url,)).fetchone()
        cursor = int(row["cursor_index"]) if row else 0
        cursor %= len(subjects)
        selected = [subjects[(cursor + offset) % len(subjects)] for offset in range(size)]
        next_cursor = (cursor + size) % len(subjects)
        conn.execute(
            """INSERT INTO automation_source_state(source_url,cursor_index,last_total,updated_at) VALUES(?,?,?,?)
               ON CONFLICT(source_url) DO UPDATE SET cursor_index=excluded.cursor_index,last_total=excluded.last_total,updated_at=excluded.updated_at""",
            (source_url, next_cursor, len(subjects), utc_now()),
        )
    return selected


def _expand_auto_source(source_url, db_path=None):
    if not is_year_index(source_url):
        return [source_url]
    subjects = expand_year_index(source_url, max_index_pages=AUTO_INDEX_PAGES, max_subjects=500)
    return _rotate_source_batch(source_url, subjects, AUTO_SUBJECTS_PER_CYCLE, db_path)


def _start_run(source_urls, db_path=None):
    now = utc_now()
    with transaction(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO automation_runs(started_at,status,source_urls) VALUES(?,'RUNNING',?)",
            (now, json.dumps(source_urls, ensure_ascii=False)),
        )
        return cur.lastrowid


def _finish_run(run_id, metrics, error=None, db_path=None):
    now = utc_now()
    with transaction(db_path) as conn:
        conn.execute(
            """UPDATE automation_runs SET finished_at=?,status=?,scans_started=?,cases_created=?,cases_updated=?,contacts_found=?,drafts_created=?,messages_sent=?,error=? WHERE id=?""",
            (
                now, "FAILED" if error else "COMPLETED", metrics["scans_started"], metrics["cases_created"],
                metrics["cases_updated"], metrics["contacts_found"], metrics["drafts_created"], metrics["messages_sent"], error, int(run_id),
            ),
        )


def _sent_today_count(db_path=None):
    today = utc_now()[:10]
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) n FROM outreach_messages WHERE sent_at IS NOT NULL AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()
    return int(row["n"])


def _policy_candidates(db_path=None):
    with transaction(db_path) as conn:
        rows = conn.execute(
            """SELECT o.id message_id,o.recipient_email,o.contact_id,
                      c.company_name,c.source_url,c.confidence_label,c.status contact_status,
                      k.financial_priority,k.detected_company_name
               FROM outreach_messages o
               JOIN cases k ON k.id=o.case_id
               JOIN contacts c ON c.id=o.contact_id
               WHERE o.status='READY_FOR_APPROVAL'
               ORDER BY k.financial_priority DESC,o.id ASC"""
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def list_auto_runs(limit=20, db_path=None):
    with transaction(db_path) as conn:
        rows = conn.execute("SELECT * FROM automation_runs ORDER BY id DESC LIMIT ?", (max(1, min(100, int(limit))),)).fetchall()
    result = []
    for row in rows:
        item = row_to_dict(row)
        try:
            item["source_urls"] = json.loads(item["source_urls"])
        except Exception:
            pass
        result.append(item)
    return result


def auto_status(db_path=None):
    runs = list_auto_runs(1, db_path)
    queue = list_outreach(db_path=db_path)
    counts = {}
    for item in queue:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    with transaction(db_path) as conn:
        reply_count = conn.execute("SELECT COUNT(*) n FROM outreach_replies").fetchone()["n"]
        followup_due = conn.execute("SELECT COUNT(*) n FROM followups WHERE status IN ('DUE','READY')").fetchone()["n"]
    return {
        "last_run": runs[0] if runs else None,
        "queue_counts": counts,
        "configured_sources": AUTO_SOURCE_URLS,
        "min_priority": AUTO_MIN_PRIORITY,
        "interval_minutes": AUTO_INTERVAL_MINUTES,
        "contact_discovery": AUTO_CONTACT_DISCOVERY,
        "send_approved_automatically": AUTO_SEND_APPROVED,
        "policy_auto_send": AUTO_POLICY_SEND,
        "policy_send_min_priority": AUTO_SEND_MIN_PRIORITY,
        "max_first_contacts_per_day": AUTO_MAX_FIRST_CONTACTS_PER_DAY,
        "sent_today": _sent_today_count(db_path),
        "smtp_configured": smtp_configured(),
        "gmail_monitoring_configured": imap_configured(),
        "monitor_replies": AUTO_MONITOR_REPLIES,
        "send_followups_automatically": AUTO_SEND_FOLLOWUPS,
        "reply_count": reply_count,
        "followups_due": followup_due,
    }


def run_auto_cycle(source_urls=None, min_priority=None, max_pages=None, enrich_limit=None, discover_contacts=None, send_approved=None, db_path=None):
    urls = list(source_urls or AUTO_SOURCE_URLS)
    if not urls:
        raise ValueError("No hay fuentes configuradas para Case Hunter Auto")
    threshold = AUTO_MIN_PRIORITY if min_priority is None else max(0, min(100, int(min_priority)))
    pages = AUTO_MAX_PAGES if max_pages is None else max(1, min(50, int(max_pages)))
    enrich = AUTO_ENRICH_LIMIT if enrich_limit is None else max(0, min(100, int(enrich_limit)))
    do_contacts = AUTO_CONTACT_DISCOVERY if discover_contacts is None else bool(discover_contacts)
    requested_send = AUTO_SEND_APPROVED if send_approved is None else bool(send_approved)
    do_send = bool(requested_send and smtp_configured())
    metrics = {"scans_started": 0, "cases_created": 0, "cases_updated": 0, "contacts_found": 0, "drafts_created": 0, "messages_sent": 0}
    run_id = _start_run(urls, db_path)
    touched = []
    reply_sync = {"configured": False, "checked": 0, "created": 0, "classifications": {}}
    followups = {"due": 0, "sent": 0, "failed": 0, "automatic_send": False}
    sent_before = _sent_today_count(db_path)
    policy = {
        "enabled": bool(AUTO_POLICY_SEND and do_send),
        "min_priority": AUTO_SEND_MIN_PRIORITY,
        "daily_limit": AUTO_MAX_FIRST_CONTACTS_PER_DAY,
        "sent_today_before": sent_before,
        "auto_approved": 0,
        "auto_sent": 0,
        "skipped_policy": 0,
        "limit_reached": sent_before >= AUTO_MAX_FIRST_CONTACTS_PER_DAY,
    }
    try:
        quarantine_unsafe_contacts(db_path)

        if AUTO_MONITOR_REPLIES:
            reply_sync = sync_replies(db_path)

        for source_url in urls:
            scan_urls = _expand_auto_source(source_url, db_path)
            for url in scan_urls:
                result = run_ley_lobby_scan(url, pages, True, enrich, db_path)
                metrics["scans_started"] += 1
                metrics["cases_created"] += result["import"]["created"]
                metrics["cases_updated"] += result["import"]["updated"]
                touched.extend(result["import"]["case_ids"])

        eligible = []
        for case_id in dict.fromkeys(touched):
            case = get_case(case_id, db_path)
            if int(case.get("financial_priority") or 0) >= threshold:
                eligible.append(case)
        eligible.sort(key=lambda case: int(case.get("financial_priority") or 0), reverse=True)

        for case in eligible[:AUTO_CASES_PER_CYCLE]:
            case_id = int(case["id"])
            contacts = []
            if do_contacts:
                contact_result = discover_contacts_for_case(case_id, db_path, search_web=True)
                contacts = [item for item in contact_result["contacts"] if item.get("status") != "REJECTED"]
                metrics["contacts_found"] += contact_result["created"]
            high_confidence = [item for item in contacts if item.get("confidence_label") == "HIGH"]
            best = high_confidence[0] if high_confidence else None
            draft = ensure_outreach_draft(case_id, best["email"] if best else None, best["id"] if best else None, db_path)
            if draft["created"]:
                metrics["drafts_created"] += 1

        if do_send:
            remaining = max(0, AUTO_MAX_FIRST_CONTACTS_PER_DAY - _sent_today_count(db_path))

            for message in list_outreach(status="APPROVED", db_path=db_path):
                if remaining <= 0:
                    policy["limit_reached"] = True
                    break
                sent = send_outreach(message["id"], db_path)
                if sent.get("status") == "SENT":
                    metrics["messages_sent"] += 1
                    remaining -= 1

            if AUTO_POLICY_SEND and remaining > 0:
                for candidate in _policy_candidates(db_path):
                    if remaining <= 0:
                        policy["limit_reached"] = True
                        break
                    priority = int(candidate.get("financial_priority") or 0)
                    company_name = candidate.get("company_name") or candidate.get("detected_company_name") or ""
                    verified = is_verified_corporate_contact(
                        candidate.get("recipient_email"),
                        candidate.get("source_url"),
                        candidate.get("confidence_label"),
                        company_name,
                    )
                    if candidate.get("contact_status") == "REJECTED" or priority < AUTO_SEND_MIN_PRIORITY or not verified:
                        policy["skipped_policy"] += 1
                        continue
                    approve_outreach(candidate["message_id"], db_path=db_path)
                    policy["auto_approved"] += 1
                    sent = send_outreach(candidate["message_id"], db_path)
                    if sent.get("status") == "SENT":
                        metrics["messages_sent"] += 1
                        policy["auto_sent"] += 1
                        remaining -= 1

        followups = process_due_followups(db_path=db_path)
        policy["sent_today_after"] = _sent_today_count(db_path)
        _finish_run(run_id, metrics, db_path=db_path)
        return {
            "run_id": run_id,
            **metrics,
            "email_send_requested": requested_send,
            "email_send_active": do_send,
            "policy_auto_send": policy,
            "reply_sync": reply_sync,
            "followups": followups,
            "queue": list_outreach(db_path=db_path),
        }
    except Exception as exc:
        _finish_run(run_id, metrics, error=str(exc), db_path=db_path)
        raise


def run_daemon(interval_minutes=None, db_path=None):
    interval = max(60, int(interval_minutes or AUTO_INTERVAL_MINUTES))
    while True:
        try:
            run_auto_cycle(db_path=db_path)
        except Exception as exc:
            print(f"Case Hunter Auto: ciclo falló: {exc}")
        time.sleep(interval * 60)
