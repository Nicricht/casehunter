from dataclasses import dataclass

from .contact_trust import assess_contact


@dataclass(frozen=True)
class OutreachDecision:
    action: str
    allowed: bool
    priority: int
    contact_score: int
    reasons: tuple[str, ...]


def evaluate_first_contact(
    *,
    email,
    source_url,
    confidence_label,
    company_name,
    financial_priority,
    contact_status="DISCOVERED",
    min_priority=70,
    sent_today=0,
    daily_limit=10,
    independent_sources=1,
):
    priority = max(0, min(100, int(financial_priority or 0)))
    reasons = []

    if contact_status == "REJECTED":
        return OutreachDecision("REJECT", False, priority, 0, ("contact_rejected",))
    if priority < int(min_priority):
        reasons.append("priority_below_threshold")
    if int(sent_today) >= int(daily_limit):
        reasons.append("daily_limit_reached")

    assessment = assess_contact(
        email,
        source_url,
        confidence_label,
        company_name,
        independent_sources=independent_sources,
    )
    reasons.extend(assessment.reasons)

    if reasons and ("priority_below_threshold" in reasons or "daily_limit_reached" in reasons):
        return OutreachDecision("HOLD", False, priority, assessment.score, tuple(reasons))
    if assessment.auto_send_allowed:
        return OutreachDecision("AUTO_SEND", True, priority, assessment.score, tuple(reasons))
    if assessment.decision == "REVIEW":
        return OutreachDecision("REVIEW", False, priority, assessment.score, tuple(reasons))
    return OutreachDecision("REJECT", False, priority, assessment.score, tuple(reasons))
