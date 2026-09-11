import re
import unicodedata


LEGAL_SUFFIXES = {
    "spa", "sa", "s a", "ltda", "limitada", "eirl", "e i r l", "sociedad", "anonima",
    "compania", "cia", "company", "chile",
}


def normalize_company_name(value):
    text = " ".join(str(value or "").split()).strip().lower()
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [token for token in text.split() if token]
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def company_matches(value, aliases):
    target = normalize_company_name(value)
    if not target:
        return False
    normalized_aliases = {normalize_company_name(alias) for alias in aliases if normalize_company_name(alias)}
    return target in normalized_aliases
