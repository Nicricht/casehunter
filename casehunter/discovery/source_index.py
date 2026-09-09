import re
from urllib.parse import urlparse

from .collector import fetch_public_document, html_links

YEAR_INDEX_RE = re.compile(r"^/instituciones/([^/]+)/audiencias/(\d{4})/?$")
SUBJECT_RE = re.compile(r"^/instituciones/([^/]+)/audiencias/(\d{4})/(\d+)/?$")


def is_year_index(url):
    return bool(YEAR_INDEX_RE.match(urlparse(url).path))


def _pagination_links(html, base_url):
    parsed = urlparse(base_url)
    base_path = parsed.path.rstrip("/")
    found = []
    for link in html_links(html or "", base_url):
        p = urlparse(link)
        if p.netloc != parsed.netloc or p.path.rstrip("/") != base_path:
            continue
        if "page=" in p.query and link not in found:
            found.append(link)
    return found


def expand_year_index(url, timeout=20, max_index_pages=10, max_subjects=500):
    if not is_year_index(url):
        return [url]
    parsed = urlparse(url)
    match = YEAR_INDEX_RE.match(parsed.path)
    institution, year = match.groups()
    queue = [url]
    seen_pages = set()
    subjects = []
    while queue and len(seen_pages) < max_index_pages and len(subjects) < max_subjects:
        page = queue.pop(0)
        if page in seen_pages:
            continue
        doc = fetch_public_document(page, timeout=timeout)
        seen_pages.add(doc["source_url"])
        for link in html_links(doc.get("raw_html") or "", doc["source_url"]):
            p = urlparse(link)
            m = SUBJECT_RE.match(p.path)
            if not m:
                continue
            inst, link_year, _ = m.groups()
            if inst != institution or link_year != year:
                continue
            canonical = f"{p.scheme}://{p.netloc}{p.path.rstrip('/')}"
            if canonical not in subjects:
                subjects.append(canonical)
                if len(subjects) >= max_subjects:
                    break
        for link in _pagination_links(doc.get("raw_html"), doc["source_url"]):
            if link not in seen_pages and link not in queue:
                queue.append(link)
    return subjects
