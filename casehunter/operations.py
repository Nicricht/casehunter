from .database import row_to_dict, transaction
from .pilot_metrics import pilot_funnel


ACTIVE_CASE_STATUSES = {
    "DETECTED",
    "VALIDATING",
    "BLOCKER_IDENTIFIED",
    "ACTION_REQUIRED",
    "DOCUMENT_SENT",
    "WAITING_AGENCY",
    "FOLLOW_UP",
}


def _ratio(numerator, denominator):
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def operations_snapshot(db_path=None, top_limit=10):
    """Return business-facing KPIs instead of infrastructure-only metrics.

    The product should optimize for confirmed cases, replies, active pilots and
    resolutions, not merely for scans or email volume.
    """
    top_limit = max(1, min(50, int(top_limit)))
    with transaction(db_path) as conn:
        case_rows = conn.execute("SELECT status,COUNT(*) n FROM cases GROUP BY status").fetchall()
        status_counts = {row["status"]: int(row["n"]) for row in case_rows}
        total_cases = sum(status_counts.values())
        active_cases = sum(status_counts.get(status, 0) for status in ACTIVE_CASE_STATUSES)
        resolved_cases = status_counts.get("RESOLVED", 0)

        contacts = int(conn.execute("SELECT COUNT(*) n FROM contacts WHERE status<>'REJECTED'").fetchone()["n"])
        trusted_contacts = int(conn.execute(
            """SELECT COUNT(*) n
               FROM contact_assessments a
               JOIN contacts c ON c.id=a.contact_id
               WHERE a.decision='AUTO_SEND' AND c.status<>'REJECTED'"""
        ).fetchone()["n"])
        sent = int(conn.execute("SELECT COUNT(*) n FROM outreach_messages WHERE status IN ('SENT','REPLIED')").fetchone()["n"])
        replies = int(conn.execute("SELECT COUNT(*) n FROM outreach_replies").fetchone()["n"])
        open_actions = int(conn.execute("SELECT COUNT(*) n FROM actions WHERE status NOT IN ('DONE','CANCELLED')").fetchone()["n"])
        due_followups = int(conn.execute("SELECT COUNT(*) n FROM followups WHERE status IN ('DUE','READY')").fetchone()["n"])

        top = conn.execute(
            """SELECT k.id,k.detected_company_name,k.contract_ref,k.agency,k.status,k.financial_priority,
                      MAX(COALESCE(a.trust_score,0)) contact_trust_score,
                      MAX(CASE WHEN a.decision='AUTO_SEND' THEN 1 ELSE 0 END) has_auto_send_contact
               FROM cases k
               LEFT JOIN contacts c ON c.case_id=k.id AND c.status<>'REJECTED'
               LEFT JOIN contact_assessments a ON a.contact_id=c.id
               WHERE k.status NOT IN ('RESOLVED','DISMISSED')
               GROUP BY k.id
               ORDER BY k.financial_priority DESC,contact_trust_score DESC,k.id DESC
               LIMIT ?""",
            (top_limit,),
        ).fetchall()

    pilots = pilot_funnel(limit=500, db_path=db_path)
    pilot_counts = pilots["counts"]

    return {
        "kpis": {
            "cases_total": total_cases,
            "cases_active": active_cases,
            "cases_resolved": resolved_cases,
            "contacts_found": contacts,
            "contacts_auto_send_ready": trusted_contacts,
            "first_contacts_sent": sent,
            "replies_received": replies,
            "open_actions": open_actions,
            "followups_due": due_followups,
            "reply_rate": _ratio(replies, sent),
            "resolution_rate": _ratio(resolved_cases, total_cases),
            "pilots_active": pilots["active_pilots"],
            "pilot_engaged": pilot_counts["ENGAGED"],
            "pilot_problem_confirmed": pilot_counts["PROBLEM_CONFIRMED"],
            "pilot_resolved": pilots["resolved"],
        },
        "case_statuses": status_counts,
        "pilot_funnel": pilots,
        "top_opportunities": [row_to_dict(row) for row in top],
    }
