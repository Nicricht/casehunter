from collections import Counter, defaultdict

from .company_identity import normalize_company_name
from .repository import get_case, list_cases


ACTIVE_STATUSES = {
    "VALIDATING",
    "BLOCKER_IDENTIFIED",
    "ACTION_REQUIRED",
    "DOCUMENT_SENT",
    "WAITING_AGENCY",
    "FOLLOW_UP",
}


def _next_action(case):
    for action in case.get("actions", []):
        if action.get("status") == "TODO":
            return {
                "action_type": action.get("action_type"),
                "title": action.get("title"),
                "due_date": action.get("due_date"),
                "responsible": action.get("responsible"),
            }
    return None


def list_portfolios(min_cases=2, active_only=True, search=None, db_path=None):
    grouped = defaultdict(list)
    names = defaultdict(list)
    for item in list_cases(search=search, db_path=db_path):
        if active_only and item.get("status") not in ACTIVE_STATUSES:
            continue
        name = (item.get("company_name") or item.get("detected_company_name") or "").strip()
        key = normalize_company_name(name)
        if not key:
            continue
        grouped[key].append(item)
        names[key].append(name)

    portfolios = []
    for identity_key, items in grouped.items():
        if len(items) < int(min_cases):
            continue

        details = [get_case(item["id"], db_path) for item in items]
        open_cases = [case for case in details if case.get("status") != "RESOLVED"]
        resolved_cases = [case for case in details if case.get("status") == "RESOLVED"]
        confirmed_amount = 0
        agencies = Counter()
        blockers = Counter()
        for case in details:
            confirmed_amount += sum(int(value or 0) for value in case.get("amounts_clp", []))
            if case.get("agency"):
                agencies[str(case["agency"])] += 1
            if case.get("current_blocker"):
                blockers[str(case["current_blocker"])] += 1

        ranked = sorted(
            details,
            key=lambda case: (
                int(case.get("financial_priority") or 0),
                case.get("event_date") or "",
                int(case.get("id") or 0),
            ),
            reverse=True,
        )
        priority_case = ranked[0] if ranked else None
        display_name = Counter(names[identity_key]).most_common(1)[0][0]

        portfolios.append({
            "company_name": display_name,
            "identity_key": identity_key,
            "name_variants": sorted(set(names[identity_key])),
            "case_count": len(details),
            "open_case_count": len(open_cases),
            "resolved_case_count": len(resolved_cases),
            "confirmed_public_amount_clp": confirmed_amount,
            "highest_priority": max((int(case.get("financial_priority") or 0) for case in details), default=0),
            "agencies": [{"name": name, "case_count": count} for name, count in agencies.most_common()],
            "blockers": [{"type": name, "case_count": count} for name, count in blockers.most_common()],
            "priority_case": {
                "case_id": priority_case.get("id"),
                "status": priority_case.get("status"),
                "agency": priority_case.get("agency"),
                "contract_ref": priority_case.get("contract_ref"),
                "current_blocker": priority_case.get("current_blocker"),
                "next_action": _next_action(priority_case),
            } if priority_case else None,
            "case_ids": [case.get("id") for case in details],
        })

    portfolios.sort(
        key=lambda item: (item["open_case_count"], item["highest_priority"], item["case_count"]),
        reverse=True,
    )
    return portfolios
