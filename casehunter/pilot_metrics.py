from datetime import date

from .database import row_to_dict, transaction
from .repository import add_timeline_event


PILOT_STAGES = (
    "DETECTED",
    "CONTACTED",
    "ENGAGED",
    "PROBLEM_CONFIRMED",
    "ACTIVE_PILOT",
    "RESOLVED",
)


def _stage_for(row):
    if row.get("case_status") == "RESOLVED":
        return "RESOLVED"
    if row.get("pilot_started", 0):
        return "ACTIVE_PILOT"
    if row.get("problem_confirmed", 0):
        return "PROBLEM_CONFIRMED"
    if row.get("reply_count", 0) > 0:
        return "ENGAGED"
    if row.get("sent_count", 0) > 0:
        return "CONTACTED"
    return "DETECTED"


def _score_for(row):
    score = 0
    if row.get("sent_count", 0) > 0:
        score += 10
    if row.get("reply_count", 0) > 0:
        score += 20
    if row.get("positive_reply_count", 0) > 0:
        score += 10
    if row.get("problem_confirmed", 0):
        score += 20
    if row.get("pilot_started", 0):
        score += 25
    if row.get("done_actions", 0) > 0:
        score += 5
    if row.get("case_status") == "RESOLVED":
        score += 10
    return min(score, 100)


def list_pilot_metrics(limit=100, db_path=None):
    limit = max(1, min(500, int(limit)))
    with transaction(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                k.id AS case_id,
                COALESCE(c.name, k.detected_company_name) AS company_name,
                k.status AS case_status,
                k.current_blocker,
                k.financial_priority,
                COUNT(DISTINCT CASE WHEN om.status IN ('SENT','REPLIED') THEN om.id END) AS sent_count,
                COUNT(DISTINCT r.id) AS reply_count,
                COUNT(DISTINCT CASE WHEN r.classification IN ('POSITIVE','REQUESTS_INFO') THEN r.id END) AS positive_reply_count,
                MAX(CASE WHEN r.classification='STILL_PENDING' THEN 1 ELSE 0 END) AS still_pending_reply,
                MAX(CASE WHEN k.status='BLOCKER_IDENTIFIED' OR r.classification='STILL_PENDING' THEN 1 ELSE 0 END) AS problem_confirmed,
                MAX(CASE WHEN te.event_type='PILOT_STARTED' THEN 1 ELSE 0 END) AS pilot_started,
                COUNT(DISTINCT CASE WHEN a.status='DONE' THEN a.id END) AS done_actions,
                COUNT(DISTINCT CASE WHEN a.status='TODO' THEN a.id END) AS open_actions,
                MAX(r.received_at) AS last_reply_at,
                MAX(om.sent_at) AS last_sent_at
            FROM cases k
            LEFT JOIN companies c ON c.id=k.company_id
            LEFT JOIN outreach_messages om ON om.case_id=k.id
            LEFT JOIN outreach_replies r ON r.case_id=k.id
            LEFT JOIN actions a ON a.case_id=k.id
            LEFT JOIN timeline_events te ON te.case_id=k.id
            GROUP BY k.id
            ORDER BY k.financial_priority DESC, k.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    result = []
    for raw in rows:
        row = row_to_dict(raw)
        row["stage"] = _stage_for(row)
        row["pilot_score"] = _score_for(row)
        result.append(row)
    result.sort(key=lambda row: (row["pilot_score"], row.get("financial_priority") or 0), reverse=True)
    return result


def get_pilot_metric(case_id, db_path=None):
    case_id = int(case_id)
    rows = list_pilot_metrics(limit=500, db_path=db_path)
    for row in rows:
        if int(row["case_id"]) == case_id:
            return row
    raise KeyError("Caso no encontrado")


def start_pilot(case_id, note=None, db_path=None):
    case_id = int(case_id)
    with transaction(db_path) as conn:
        exists = conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
        if exists is None:
            raise KeyError("Caso no encontrado")
        already = conn.execute(
            "SELECT id FROM timeline_events WHERE case_id=? AND event_type='PILOT_STARTED' ORDER BY id DESC LIMIT 1",
            (case_id,),
        ).fetchone()
    if not already:
        add_timeline_event(
            case_id,
            title="Piloto de seguimiento iniciado",
            details=(note or "").strip() or "La empresa aceptó seguimiento activo del caso.",
            event_type="PILOT_STARTED",
            event_date=date.today().isoformat(),
            db_path=db_path,
        )
    return get_pilot_metric(case_id, db_path=db_path)


def pilot_funnel(limit=500, db_path=None):
    rows = list_pilot_metrics(limit=limit, db_path=db_path)
    counts = {stage: 0 for stage in PILOT_STAGES}
    for row in rows:
        counts[row["stage"]] += 1
    return {
        "counts": counts,
        "total_cases": len(rows),
        "active_pilots": counts["ACTIVE_PILOT"],
        "resolved": counts["RESOLVED"],
        "rows": rows,
    }
