import html
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from .config import CONTACT_DISCOVERY_MAX_SITES, CONTACT_DISCOVERY_TIMEOUT
from .database import row_to_dict, transaction, utc_now
from .repository import get_case

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
BLOCKED_DOMAINS = {
    "leylobby.gob.cl", "mercadopublico.cl", "www.mercadopublico.cl", "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com", "linkedin.com", "www.linkedin.com", "x.com", "twitter.com",
}
BAD_LOCALPARTS = {"noreply", "no-reply", "donotreply", "example", "test"}
BLOCKED_EMAIL_DOMAINS = {"minsegpres.gob.cl", "leylobby.gob.cl", "mop.gov.cl", "mercadopublico.cl"}


def _fetch_text(url, timeout=None, limit=2_000_000):
    timeout = CONTACT_DISCOVERY_TIMEOUT if timeout is None else max(2, int(timeout))
    req = Request(url, headers={"User-Agent": "CaseHunterResolve/2.2 (+public-contact-discovery)", "Accept": "text/html,text/plain;q=0.9,*/*;q=0.5"})
    try:
        with urlopen(req, timeout=timeout) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "text" not in content_type and "html" not in content_type:
                return ""
            raw = response.read(limit)
        return raw.decode("utf-8", errors="ignore")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return ""


def extract_emails(text):
    found = []
    for candidate in EMAIL_RE.findall(html.unescape(text or "")):
        email = candidate.strip(".,;:()[]{}<>\"\'").lower()
        local, _, domain = email.partition("@")
        if not domain or local in BAD_LOCALPARTS:
            continue
        if domain in BLOCKED_EMAIL_DOMAINS or domain.endswith(".gob.cl") or domain.endswith(".gov.cl"):
            continue
        if email not in found:
            found.append(email)
    return found


def _unwrap_ddg_url(value):
    value = html.unescape(value)
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target) if target else ""
    return value


def search_company_websites(company_name, max_results=None):
    clean = (company_name or "").strip()
    if not clean:
        return []
    max_results = CONTACT_DISCOVERY_MAX_SITES if max_results is None else max(1, int(max_results))
    query = quote_plus(f'"{clean}" contacto Chile')
    text = _fetch_text(f"https://html.duckduckgo.com/html/?q={query}")
    urls = []
    for href in HREF_RE.findall(text):
        url = _unwrap_ddg_url(href)
        if not url.startswith("http"):
            continue
        host = urlparse(url).netloc.lower().split(":")[0]
        if not host or host in BLOCKED_DOMAINS or host.endswith(".gob.cl"):
            continue
        root = f"{urlparse(url).scheme}://{urlparse(url).netloc}/"
        if root not in urls:
            urls.append(root)
        if len(urls) >= max_results:
            break
    return urls


def discover_public_contacts(company_name, seed_urls=None, search_web=True, max_sites=None):
    max_sites = CONTACT_DISCOVERY_MAX_SITES if max_sites is None else max(1, int(max_sites))
    candidates = []
    seen = set()
    urls = [u for u in (seed_urls or []) if u]
    if search_web:
        urls.extend(search_company_websites(company_name, max_results=max_sites))
    for base in urls:
        parsed = urlparse(base)
        if not parsed.scheme or not parsed.netloc:
            continue
        host = parsed.netloc.lower().split(":")[0]
        if host in BLOCKED_DOMAINS or host.endswith(".gob.cl") or host.endswith(".gov.cl"):
            continue
        pages = [base]
        root = f"{parsed.scheme}://{parsed.netloc}/"
        for path in ("contacto", "contact", "nosotros", "empresa"):
            pages.append(urljoin(root, path))
        for page in pages:
            text = _fetch_text(page)
            for email in extract_emails(text):
                domain = email.split("@", 1)[1]
                site_host = urlparse(page).netloc.lower()
                confidence = "HIGH" if domain in site_host or site_host.endswith(domain) else "MEDIUM"
                key = (email, page)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({"email": email, "source_url": page, "confidence_label": confidence})
        if len({c["email"] for c in candidates}) >= 5:
            break
    unique = {}
    rank = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}
    for item in candidates:
        current = unique.get(item["email"])
        if current is None or rank[item["confidence_label"]] > rank[current["confidence_label"]]:
            unique[item["email"]] = item
    return sorted(unique.values(), key=lambda x: (-rank[x["confidence_label"]], x["email"]))


def save_contacts(case_id, contacts, db_path=None):
    case = get_case(case_id, db_path)
    now = utc_now()
    created = 0
    with transaction(db_path) as conn:
        for item in contacts:
            email = item["email"].strip().lower()
            existing = conn.execute("SELECT id FROM contacts WHERE case_id=? AND email=?", (int(case_id), email)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE contacts SET source_url=?,confidence_label=?,updated_at=? WHERE id=?",
                    (item.get("source_url"), item.get("confidence_label", "LOW"), now, existing["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO contacts(case_id,company_name,email,source_url,confidence_label,status,created_at,updated_at)
                       VALUES(?,?,?,?,?,'DISCOVERED',?,?)""",
                    (int(case_id), case.get("company_name") or case.get("detected_company_name"), email, item.get("source_url"), item.get("confidence_label", "LOW"), now, now),
                )
                created += 1
    return {"created": created, "contacts": list_contacts(case_id=case_id, db_path=db_path)}


def list_contacts(case_id=None, db_path=None):
    query = "SELECT * FROM contacts"
    params = []
    if case_id is not None:
        query += " WHERE case_id=?"
        params.append(int(case_id))
    query += " ORDER BY CASE confidence_label WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, id"
    with transaction(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(row) for row in rows]


def discover_contacts_for_case(case_id, db_path=None, search_web=True):
    case = get_case(case_id, db_path)
    company = case.get("company_name") or case.get("detected_company_name")
    direct = []
    for text, source in ((case.get("raw_text"), case.get("detail_url") or case.get("source_url")), (case.get("detail_text"), case.get("detail_url") or case.get("source_url"))):
        for email in extract_emails(text or ""):
            direct.append({"email": email, "source_url": source, "confidence_label": "MEDIUM"})
    seed_urls = [case.get("detail_url"), case.get("source_url")]
    found = direct + discover_public_contacts(company, seed_urls=seed_urls, search_web=search_web)
    return save_contacts(case_id, found, db_path)
