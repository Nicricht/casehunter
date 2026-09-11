from .detector import detect_problems
from .extractor import extract_safis, extract_amounts_clp
from .outcome import analyze_public_outcome


def calculate_confidence(safis, amounts, problems, outcome=None):
    score = 0.0
    if safis:
        score += 0.25
    if problems:
        score += 0.50
    if amounts:
        score += 0.25
    if outcome and outcome.get("state") in {"PARTIAL", "RESOLVED"}:
        score = max(score, 0.5)
    if score >= 0.80:
        label = "HIGH"
    elif score >= 0.50:
        label = "MEDIUM"
    else:
        label = "LOW"
    return {"score": round(score, 2), "label": label}


def build_case(text: str):
    safis = extract_safis(text)
    amounts = extract_amounts_clp(text)
    detected_problems = detect_problems(text)
    outcome = analyze_public_outcome(text)
    historical_problems = []
    problems = detected_problems
    if outcome["state"] == "RESOLVED":
        historical_problems = detected_problems
        problems = []
    return {
        "safis": safis,
        "amounts_clp": amounts,
        "problems": problems,
        "historical_problems": historical_problems,
        "outcome": outcome,
        "confidence": calculate_confidence(safis, amounts, problems or historical_problems, outcome),
        "raw_text": text.strip(),
    }
