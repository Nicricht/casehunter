from dataclasses import dataclass
import re
import unicodedata
from urllib.parse import urlparse

FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "yahoo.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
}

GENERIC_COMPANY_TOKENS = {
    "sa", "spa", "ltda", "eirl", "chile", "empresa", "grupo", "sociedad", "limitada", "compania",
    "corporacion", "constructora", "construccion", "ingenieria", "ingenieros", "servicios", "proyectos",
    "obras", "consultora", "consultores", "inversiones", "soluciones", "tecnologia", "tecnologias",
}


@dataclass(frozen=True)
class ContactAssessment:
    score: int
    decision: str
    reasons: tuple[str, ...]
    source_host: str
    email_domain: str

    @property
    def auto_send_allowed(self):
        return self.decision == "AUTO_SEND"


def _tokens(value):
    normalized = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii").lower()
    return [
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) >= 3 and token not in GENERIC_COMPANY_TOKENS
    ]


def _host_matches(host, domain):
    host = (host or "").lower().split(":")[0].strip(".")
    domain = (domain or "").lower().strip(".")
    return bool(host and domain and (host == domain or host.endswith("." + domain)))


def company_host_match(company_name, host):
    normalized_host = re.sub(r"[^a-z0-9]", "", (host or "").lower())
    return any(token in normalized_host for token in _tokens(company_name))


def assess_contact(email, source_url, confidence_label, company_name, *, independent_sources=1):
    """Score identity evidence for an unattended first contact.

    Domain equality is useful evidence, but it is not mandatory. A Gmail or
    external-domain address can pass when it is published by a website whose
    host is strongly related to the target company. This avoids rejecting
    legitimate SMEs that use free-mail providers while still blocking random
    addresses discovered on unrelated pages.
    """
    email = (email or "").strip().lower()
    email_domain = email.partition("@")[2]
    parsed = urlparse(source_url or "")
    source_host = parsed.netloc.lower().split(":")[0]
    confidence = (confidence_label or "LOW").upper()
    path = (parsed.path or "").lower()

    score = 0
    reasons = []

    if confidence == "HIGH":
        score += 25
        reasons.append("confidence_high")
    elif confidence == "MEDIUM":
        score += 15
        reasons.append("confidence_medium")

    source_matches_company = company_host_match(company_name, source_host)
    if source_matches_company:
        score += 35
        reasons.append("company_matches_source_host")

    if _host_matches(source_host, email_domain):
        score += 25
        reasons.append("email_domain_matches_source")
    elif email_domain in FREE_EMAIL_DOMAINS and source_matches_company:
        score += 15
        reasons.append("free_email_published_by_company_site")
    elif source_matches_company:
        score += 10
        reasons.append("external_email_published_by_company_site")
    else:
        score -= 30
        reasons.append("no_company_source_relationship")

    if any(part in path for part in ("contact", "contacto", "nosotros", "empresa", "quienes")):
        score += 10
        reasons.append("contact_or_company_page")

    if independent_sources >= 2:
        score += 15
        reasons.append("multiple_independent_sources")

    score = max(0, min(100, score))

    if score >= 70 and source_matches_company:
        decision = "AUTO_SEND"
    elif score >= 45:
        decision = "REVIEW"
    else:
        decision = "REJECT"

    return ContactAssessment(
        score=score,
        decision=decision,
        reasons=tuple(reasons),
        source_host=source_host,
        email_domain=email_domain,
    )
