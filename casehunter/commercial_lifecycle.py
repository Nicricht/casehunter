from datetime import datetime, timezone

from .commercial_pipeline import QUALIFYING_REPLY_CLASSES
from .commercial_store import (
    VALID_COMMERCIAL_STATUSES,
    ensure_commercial_schema,
    get_commercial_row,
    save_commercial_row,
)
from .database import transaction, utc_now
from .pilot_metrics import start_pilot
from .repository import add_timeline_event, get_case


POSITIVE_REPLY_CLASSES = {
    "REQUESTS_INFO",
    "STILL_PENDING",
    "PILOT_REQUESTED",
    "NO_AGENCY_RESPONSE",
}


def _money(value):
    if value is None:
        return None
    number = int(value)
    if number < 0:
        raise ValueError("Los valores comerciales no pueden ser negativos")
    return number


def _parse_dt(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _avg_hours(pairs):
    values = []
    for first, second in pairs:
        start = _parse_dt(first)
        end = _parse_dt(second)
        if start is None or end is None or end < start:
            continue
        values.append((end - start).total_seconds() / 3600.0)
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def get_commercial_opportunity(case_id, db_path=None):
    case = get_case(int(case_id), db_path)
    row = get_commercial_row(case_id, db_path) or {
        "case_id": int(case_id),
        "status": "OPEN",
        "pilot_price_clp": None,
        "monthly_price_clp": None,
        "expected_value_clp": None,
        "lost_reason": None,
        "note": None,
        "pilot_started_at": None,
        "closed_at": None,
        "created_at": None,
        "updated_at": None,
    }
    result = dict(row)
    result["company_name"] = case.get("company_name") or case.get("detected_company_name")
    result["agency"] = case.get("agency")
    result["contract_ref"] = case.get("contract_ref")
    result["case_status"] = case.get("status")
    return result


def set_commercial_status(
    case_id,
    status,
    lost_reason=None,
    pilot_price_clp=None,
    monthly_price_clp=None,
    expected_value_clp=None,
    note=None,
    db_path=None,
):
    case_id = int(case_id)
    status = str(status or "").strip().upper()
    if status not in VALID_COMMERCIAL_STATUSES:
        raise ValueError("Estado comercial no válido")
    if status == "LOST" and not str(lost_reason or "").strip():
        raise ValueError("LOST requiere indicar lost_reason")

    get_case(case_id, db_path)
    current = get_commercial_row(case_id, db_path) or {}
    now = utc_now()
    pilot_price = _money(pilot_price_clp) if pilot_price_clp is not None else current.get("pilot_price_clp")
    monthly_price = _money(monthly_price_clp) if monthly_price_clp is not None else current.get("monthly_price_clp")
    expected_value = _money(expected_value_clp) if expected_value_clp is not None else current.get("expected_value_clp")
    pilot_started_at = current.get("pilot_started_at")
    if status == "PILOT_ACTIVE" and not pilot_started_at:
        pilot_started_at = now
    closed_at = now if status in {"WON", "LOST"} else None
    clean_lost_reason = str(lost_reason or "").strip() if status == "LOST" else None
    clean_note = str(note or "").strip() or current.get("note")

    if status == "PILOT_ACTIVE":
        start_pilot(case_id, note=clean_note, db_path=db_path)

    saved = save_commercial_row(
        case_id,
        status,
        pilot_price_clp=pilot_price,
        monthly_price_clp=monthly_price,
        expected_value_clp=expected_value,
        lost_reason=clean_lost_reason,
        note=clean_note,
        pilot_started_at=pilot_started_at,
        closed_at=closed_at,
        db_path=db_path,
    )
    add_timeline_event(
        case_id,
        title=f"Estado comercial: {status}",
        details=clean_lost_reason or clean_note or "Actualización del ciclo comercial.",
        event_type="COMMERCIAL_STATUS",
        db_path=db_path,
    )
    return saved


def commercial_metrics(db_path=None):
    ensure_commercial_schema(db_path)
    qualifying = tuple(sorted(QUALIFYING_REPLY_CLASSES))
    positive = tuple(sorted(POSITIVE_REPLY_CLASSES))
    qualifying_marks = ",".join("?" for _ in qualifying)
    positive_marks = ",".join("?" for _ in positive)

    with transaction(db_path) as conn:
        sent_attempts = int(conn.execute(
            "SELECT COUNT(*) n FROM outreach_messages WHERE status IN ('SENT','REPLIED','BOUNCED','DELIVERY_BLOCKED')"
        ).fetchone()["n"])
        delivery_failures = int(conn.execute(
            "SELECT COUNT(*) n FROM outreach_messages WHERE status IN ('BOUNCED','DELIVERY_BLOCKED')"
        ).fetchone()["n"])
        replies = int(conn.execute("SELECT COUNT(*) n FROM outreach_replies").fetchone()["n"])
        positive_replies = int(conn.execute(
            f"SELECT COUNT(*) n FROM outreach_replies WHERE classification IN ({positive_marks})",
            positive,
        ).fetchone()["n"])
        qualified = int(conn.execute(
            f"""SELECT COUNT(*) n FROM (
                    SELECT latest.case_id
                    FROM (
                        SELECT case_id, MAX(id) reply_id
                        FROM outreach_replies GROUP BY case_id
                    ) latest
                    JOIN outreach_replies r ON r.id=latest.reply_id
                    WHERE r.classification IN ({qualifying_marks})
                ) q""",
            qualifying,
        ).fetchone()["n"])
        commercial_rows = conn.execute(
            "SELECT status,COUNT(*) n FROM commercial_opportunities GROUP BY status"
        ).fetchall()
        commercial_counts = {row["status"]: int(row["n"]) for row in commercial_rows}
        pipeline_value = int(conn.execute(
            "SELECT COALESCE(SUM(expected_value_clp),0) n FROM commercial_opportunities WHERE status NOT IN ('WON','LOST')"
        ).fetchone()["n"])
        won_monthly = int(conn.execute(
            "SELECT COALESCE(SUM(monthly_price_clp),0) n FROM commercial_opportunities WHERE status='WON'"
        ).fetchone()["n"])
        response_rows = conn.execute(
            """SELECT om.sent_at,r.received_at
               FROM outreach_replies r JOIN outreach_messages om ON om.id=r.outreach_id
               WHERE om.sent_at IS NOT NULL AND r.received_at IS NOT NULL"""
        ).fetchall()
        legacy_active = int(conn.execute(
            "SELECT COUNT(DISTINCT case_id) n FROM timeline_events WHERE event_type='PILOT_STARTED'"
        ).fetchone()["n"])

    delivered_or_pending = max(0, sent_attempts - delivery_failures)
    won = commercial_counts.get("WON", 0)
    lost = commercial_counts.get("LOST", 0)
    decisions = won + lost
    return {
        "sent_attempts": sent_attempts,
        "delivery_failures": delivery_failures,
        "delivered_or_pending": delivered_or_pending,
        "delivery_rate": round(delivered_or_pending / sent_attempts, 4) if sent_attempts else 0.0,
        "replies_received": replies,
        "reply_rate": round(replies / delivered_or_pending, 4) if delivered_or_pending else 0.0,
        "positive_replies": positive_replies,
        "qualified_opportunities": qualified,
        "pilots_proposed": commercial_counts.get("PILOT_PROPOSED", 0),
        "pilots_active": max(commercial_counts.get("PILOT_ACTIVE", 0), legacy_active),
        "won": won,
        "lost": lost,
        "win_rate": round(won / decisions, 4) if decisions else 0.0,
        "avg_response_hours": _avg_hours([(row["sent_at"], row["received_at"]) for row in response_rows]),
        "pipeline_expected_value_clp": pipeline_value,
        "won_monthly_revenue_clp": won_monthly,
        "commercial_statuses": commercial_counts,
    }
