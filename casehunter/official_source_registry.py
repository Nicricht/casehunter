import unicodedata


def _norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


REGISTRY = (
    {
        "match_all": ("rio claro",),
        "sources": (
            "https://rioclaro.cl/",
            "https://rioclaro.cl/2026/",
            "https://www.portaltransparencia.cl/PortalPdT/pdtta?codOrganismo=MU271",
        ),
    },
)


def sources_for_case(case):
    haystack = " ".join(
        _norm(case.get(key))
        for key in ("agency", "detected_company_name", "company_name", "contract_ref", "raw_text", "detail_text")
    )
    result = []
    for rule in REGISTRY:
        if all(token in haystack for token in rule.get("match_all", ())):
            result.extend(rule.get("sources", ()))
    return list(dict.fromkeys(result))
