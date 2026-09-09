def calculate_priority(amounts_clp, problem_types, confidence_label):
    amounts = [int(v) for v in amounts_clp if int(v) > 0]
    maximum = max(amounts, default=0)

    if maximum >= 1_000_000_000:
        amount_score = 50
    elif maximum >= 100_000_000:
        amount_score = 40
    elif maximum >= 10_000_000:
        amount_score = 30
    elif maximum > 0:
        amount_score = 20
    else:
        amount_score = 0

    problem_score = min(30, len(set(problem_types)) * 8)
    confidence_score = {"HIGH": 20, "MEDIUM": 12, "LOW": 5}.get(confidence_label, 0)
    return min(100, amount_score + problem_score + confidence_score)


def summarize_amounts(amounts_clp):
    amounts = sorted({int(v) for v in amounts_clp if int(v) > 0}, reverse=True)
    return {
        "observed_amounts_clp": amounts,
        "largest_observed_amount_clp": amounts[0] if amounts else 0,
        "sum_observed_amounts_clp": sum(amounts),
        "warning": (
            "Los montos provienen de antecedentes públicos y no deben interpretarse automáticamente "
            "como dinero recuperable o actualmente adeudado."
        ),
    }
