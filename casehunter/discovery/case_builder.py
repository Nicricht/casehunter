from .detector import detect_problems
from .extractor import extract_safis, extract_amounts_clp

def calculate_confidence(safis, amounts, problems):
    score = 0.0
    if safis:
        score += 0.25
    if problems:
        score += 0.50
    if amounts:
        score += 0.25
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
    problems = detect_problems(text)
    return {
        "safis": safis,
        "amounts_clp": amounts,
        "problems": problems,
        "confidence": calculate_confidence(safis, amounts, problems),
        "raw_text": text.strip(),
    }
