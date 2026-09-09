import re

SAFI_NUMBER = r"\d{1,3}(?:[.\s]\d{3}){1,2}|\d{5,7}"
SAFI_BLOCK_PATTERN = re.compile(
    rf"\bSAFIS?\b\s*(?:N[°ºo]\s*)?[:#-]?\s*"
    rf"((?:{SAFI_NUMBER})(?:(?:\s*(?:-|/|,|;|y|e)\s*)(?:{SAFI_NUMBER}))*)",
    re.IGNORECASE,
)
SINGLE_SAFI_PATTERN = re.compile(
    rf"\b(?:N[°ºo]\s*)?SAFI\b\s*(?:N[°ºo]\s*)?[:#-]?\s*({SAFI_NUMBER})\b",
    re.IGNORECASE,
)
NUMBER_IN_SAFI_BLOCK = re.compile(SAFI_NUMBER)

NORMAL_MONEY_PATTERNS = [
    re.compile(r"\$\s*([0-9]{1,3}(?:[.\s,][0-9]{3})+|[0-9]+)", re.IGNORECASE),
    re.compile(r"\bCLP\s*\$?\s*([0-9]{1,3}(?:[.\s,][0-9]{3})+|[0-9]+)", re.IGNORECASE),
]
MONEY_THOUSANDS_PATTERN = re.compile(r"\bM\$\s*([0-9]{1,3}(?:[.\s,][0-9]{3})*|[0-9]+)", re.IGNORECASE)
MILLIONS_PATTERN = re.compile(
    r"(?:\$\s*)?([0-9]{1,3}(?:[.,][0-9]{1,3})?)\s*(?:millones|mm)\b",
    re.IGNORECASE,
)


def _digits_only(value: str) -> int:
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else 0


def _normalize_safi(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def extract_safis(text: str):
    safis = []

    for block in SAFI_BLOCK_PATTERN.findall(text):
        for raw in NUMBER_IN_SAFI_BLOCK.findall(block):
            safi = _normalize_safi(raw)
            if safi and safi not in safis:
                safis.append(safi)

    for raw in SINGLE_SAFI_PATTERN.findall(text):
        safi = _normalize_safi(raw)
        if safi and safi not in safis:
            safis.append(safi)

    return safis


def extract_amounts_clp(text: str):
    amounts = []

    for raw in MONEY_THOUSANDS_PATTERN.findall(text):
        amount = _digits_only(raw) * 1000
        if amount and amount not in amounts:
            amounts.append(amount)

    text_without_m = MONEY_THOUSANDS_PATTERN.sub("", text)

    for pattern in NORMAL_MONEY_PATTERNS:
        for raw in pattern.findall(text_without_m):
            amount = _digits_only(raw)
            if amount and amount not in amounts:
                amounts.append(amount)

    for raw in MILLIONS_PATTERN.findall(text):
        normalized = raw.replace(".", "").replace(",", ".")
        try:
            amount = int(float(normalized) * 1_000_000)
        except ValueError:
            continue
        if amount and amount not in amounts:
            amounts.append(amount)

    return amounts
