from collections import Counter

from .repository import get_case, get_company, list_cases
from .resolution_learning import resolution_recommendation


VISIBLE_TIMELINE_TYPES = {
    "PUBLIC_WATCH_CHANGE",
    "STATUS_CHANGED",
    "PILOT_STARTED",
    "RESOLUTION_RECOMMENDATION",
    "BLOCKER_CONFIRMED",
}


def _public_source(case):
    return case.get("detail_url") or case.get("source_url")


def _latest_signal(case):
    visible = [event for event in case.get("timeline", []) if event.get("event_type") in VISIBLE_TIMELINE_TYPES]
    event = visible[0] if visible else None
    if not event:
        return None
    return {
        "event_type": event.get("event_type"),
        "event_date": event.get("event_date"),
        "title": event.get("title"),
        "details": event.get("details"),
        "source_url": event.get("source_url"),
    }


def _open_actions(case):
    result = []
    for action in case.get("actions", []):
        if action.get("status") != "TODO":
            continue
        result.append({
            "title": action.get("title"),
            "action_type": action.get("action_type"),
            "due_date": action.get("due_date"),
            "responsible": action.get("responsible"),
        })
    return result


def _safe_recommendation(case_id, db_path=None):
    try:
        result = resolution_recommendation(case_id, db_path=db_path)
    except Exception:
        return None
    if result.get("status") != "READY" or not result.get("recommendation"):
        return {
            "status": result.get("status"),
            "recommendation": None,
            "causality_notice": result.get("causality_notice"),
        }
    rec = result["recommendation"]
    evidence = []
    for item in rec.get("evidence") or []:
        evidence.append({
            "basis": item.get("basis"),
            "evidence": item.get("evidence"),
            "source_url": item.get("source_url"),
        })
    return {
        "status": "READY",
        "recommendation": {
            "action_type": rec.get("action_type"),
            "title": rec.get("title"),
            "confidence": rec.get("confidence"),
            "precedent_count": rec.get("precedent_count"),
            "rationale": rec.get("rationale"),
            "evidence": evidence,
        },
        "causality_notice": result.get("causality_notice"),
    }


def build_client_portfolio(company_id, db_path=None):
    company_id = int(company_id)
    company = get_company(company_id, db_path)
    summaries = list_cases(company_id=company_id, db_path=db_path)
    details = [get_case(int(item["id"]), db_path) for item in summaries]

    cases = []
    agencies = Counter()
    blockers = Counter()
    total_amount = 0
    open_cases = 0
    resolved_cases = 0
    open_actions = 0
    public_changes = 0

    for case in details:
        amounts = [int(value or 0) for value in case.get("amounts_clp", [])]
        amount = sum(amounts)
        total_amount += amount
        if case.get("agency"):
            agencies[str(case["agency"])] += 1
        if case.get("current_blocker"):
            blockers[str(case["current_blocker"])] += 1
        if case.get("status") == "RESOLVED":
            resolved_cases += 1
        elif case.get("status") != "DISMISSED":
            open_cases += 1
        actions = _open_actions(case)
        open_actions += len(actions)
        public_changes += sum(1 for event in case.get("timeline", []) if event.get("event_type") == "PUBLIC_WATCH_CHANGE")

        cases.append({
            "case_id": int(case["id"]),
            "agency": case.get("agency"),
            "contract_ref": case.get("contract_ref") or case.get("external_id"),
            "status": case.get("status"),
            "current_blocker": case.get("current_blocker"),
            "event_date": case.get("event_date"),
            "amount_clp": amount,
            "source_url": _public_source(case),
            "latest_signal": _latest_signal(case),
            "open_actions": actions,
            "recommendation": _safe_recommendation(int(case["id"]), db_path=db_path),
        })

    cases.sort(
        key=lambda item: (
            item.get("status") == "RESOLVED",
            -(int(item.get("amount_clp") or 0)),
            item.get("event_date") or "",
        )
    )

    return {
        "company": {
            "id": company_id,
            "name": company.get("name"),
            "rut": company.get("rut"),
        },
        "metrics": {
            "case_count": len(cases),
            "open_case_count": open_cases,
            "resolved_case_count": resolved_cases,
            "observed_amount_clp": total_amount,
            "open_actions": open_actions,
            "public_changes": public_changes,
        },
        "agencies": [{"name": name, "case_count": count} for name, count in agencies.most_common()],
        "blockers": [{"type": name, "case_count": count} for name, count in blockers.most_common()],
        "cases": cases,
    }
