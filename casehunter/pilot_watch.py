ACTIVE_STATUS_WEIGHTS = {
    "ACTION_REQUIRED": 100,
    "BLOCKER_IDENTIFIED": 95,
    "FOLLOW_UP": 90,
    "WAITING_AGENCY": 85,
    "VALIDATING": 80,
    "DOCUMENT_SENT": 75,
    "DETECTED": 40,
}


def _next_action(case):
    todo = [action for action in case.get("actions", []) if action.get("status") == "TODO"]
    if not todo:
        return None
    todo.sort(key=lambda action: (action.get("due_date") is None, action.get("due_date") or "9999-12-31", action.get("id", 0)))
    action = todo[0]
    return {
        "action_type": action.get("action_type"),
        "title": action.get("title"),
        "due_date": action.get("due_date"),
        "responsible": action.get("responsible"),
    }


def build_watchlist(search=None, limit=20, db_path=None):
    from .repository import get_case, list_cases

    if limit < 1:
        return []

    rows = list_cases(search=search, db_path=db_path)
    watch = []
    for row in rows:
        status = row.get("status")
        if status not in ACTIVE_STATUS_WEIGHTS:
            continue

        case = get_case(row["id"], db_path)
        next_action = _next_action(case)
        status_weight = ACTIVE_STATUS_WEIGHTS[status]
        financial_priority = int(row.get("financial_priority") or 0)
        overdue_bonus = 0
        if next_action and next_action.get("due_date"):
            from datetime import date
            try:
                if date.fromisoformat(next_action["due_date"]) < date.today():
                    overdue_bonus = 15
            except ValueError:
                pass

        watch_score = status_weight + min(financial_priority, 100) + overdue_bonus
        watch.append({
            "case_id": row["id"],
            "company": row.get("company_name") or row.get("detected_company_name"),
            "status": status,
            "current_blocker": row.get("current_blocker"),
            "event_date": row.get("event_date"),
            "financial_priority": financial_priority,
            "watch_score": watch_score,
            "next_action": next_action,
            "detail_url": row.get("detail_url"),
        })

    watch.sort(key=lambda item: (item["watch_score"], item.get("event_date") or ""), reverse=True)
    return watch[:limit]
