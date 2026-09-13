from .commercial_lifecycle import commercial_metrics
from .commercial_pipeline import commercialize_case
from .commercial_store import ensure_commercial_schema
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
    """Return business-facing KPIs and ranked commercial opportunities."""
    top_limit = max(1, min(50, int(top_limit)))
    ensure_commercial_schema(db_path)
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

        candidate_limit = max(200, top_limit * 10)
        rows = conn.execute(
            """SELECT k.id,k.detected_company_name,k.contract_ref,k.agency,k.status,
                      k.financial_priority,k.confidence_score,k.confidence_label,k.current_blocker,
                      COALESCE(co.status,'OPEN') commercial_status,
                      co.pilot_price_clp,co.monthly_price_clp,co.expected_value_clp,co.lost_reason,
                      COALESCE((
                          SELECT MAX(COALESCE(a.trust_score,0))
                          FROM contacts c LEFT JOIN contact_assessments a ON a.contact_id=c.id
                          WHERE c.case_id=k.id AND c.status<>'REJECTED'
                      ),0) contact_trust_score,
                      CASE WHEN (
                          SELECT COUNT(*) FROM contacts c
                          WHERE c.case_id=k.id AND c.status<>'REJECTED'
                      )>0 THEN 1 ELSE 0 END has_contact,
                      CASE WHEN (
                          SELECT COUNT(*) FROM contacts c JOIN contact_assessments a ON a.contact_id=c.id
                          WHERE c.case_id=k.id AND c.status<>'REJECTED' AND a.decision='AUTO_SEND'
                      )>0 THEN 1 ELSE 0 END has_auto_send_contact,
                      CASE WHEN (
                          SELECT COUNT(*) FROM outreach_messages o
                          WHERE o.case_id=k.id AND o.status IN ('SENT','REPLIED')
                      )>0 THEN 1 ELSE 0 END has_contacted,
                      CASE WHEN (
                          SELECT COUNT(*) FROM outreach_replies r WHERE r.case_id=k.id
                      )>0 THEN 1 ELSE 0 END has_reply,
                      COALESCE((
                          SELECT r.classification FROM outreach_replies r
                          WHERE r.case_id=k.id ORDER BY r.id DESC LIMIT 1
                      ),'') latest_reply_classification,
                      CASE WHEN (
                          SELECT COUNT(*) FROM actions ac
                          WHERE ac.case_id=k.id AND ac.action_type='WATCH_PUBLIC_CASE' AND ac.status='TODO'
                      )>0 THEN 1 ELSE 0 END has_watch_action,
                      CASE WHEN (
                          SELECT COUNT(*) FROM timeline_events te
                          WHERE te.case_id=k.id AND te.event_type='PILOT_STARTED'
                      )>0 THEN 1 ELSE 0 END has_pilot_started
               FROM cases k
               LEFT JOIN commercial_opportunities co ON co.case_id=k.id
               WHERE k.status NOT IN ('RESOLVED','DISMISSED')
                 AND COALESCE(co.status,'OPEN') NOT IN ('WON','LOST')
               ORDER BY k.financial_priority DESC,k.id DESC
               LIMIT ?""",
            (candidate_limit,),
        ).fetchall()

    pilots = pilot_funnel(limit=500, db_path=db_path)
    commercial = commercial_metrics(db_path=db_path)
    pilot_counts = pilots["counts"]
    opportunities = [commercialize_case(row_to_dict(row)) for row in rows]
    opportunities.sort(
        key=lambda item: (
            int(item.get("opportunity_score") or 0),
            int(item.get("financial_priority") or 0),
            int(item.get("contact_trust_score") or 0),
            int(item.get("id") or 0),
        ),
        reverse=True,
    )
    opportunities = opportunities[:top_limit]

    stage_counts = {}
    for item in opportunities:
        stage = item["commercial_stage"]
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

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
            "pilots_active": max(pilots["active_pilots"], commercial["pilots_active"]),
            "pilot_engaged": pilot_counts["ENGAGED"],
            "pilot_problem_confirmed": pilot_counts["PROBLEM_CONFIRMED"],
            "pilot_resolved": pilots["resolved"],
            "delivery_failures": commercial["delivery_failures"],
            "delivery_rate": commercial["delivery_rate"],
            "positive_replies": commercial["positive_replies"],
            "qualified_opportunities": commercial["qualified_opportunities"],
            "pilots_proposed": commercial["pilots_proposed"],
            "won": commercial["won"],
            "lost": commercial["lost"],
            "win_rate": commercial["win_rate"],
            "avg_response_hours": commercial["avg_response_hours"],
            "pipeline_expected_value_clp": commercial["pipeline_expected_value_clp"],
            "won_monthly_revenue_clp": commercial["won_monthly_revenue_clp"],
        },
        "case_statuses": status_counts,
        "commercial_stages_top": stage_counts,
        "commercial_metrics": commercial,
        "pilot_funnel": pilots,
        "top_opportunities": opportunities,
    }
