import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from .case_builder import build_case
from .collector import fetch_public_document, html_links, html_table_rows

DATE_PATTERN = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
AUDIENCE_ID_PATTERN = re.compile(r"\b([A-Z]{2}\d{3}AW\d{7})\b", re.IGNORECASE)
SIGNAL_TYPES = {
    "RETENTION_PENDING",
    "LIQUIDATION_PENDING",
    "PAYMENT_PENDING",
    "GUARANTEE_PENDING",
    "DOCUMENT_MISSING",
    "INTERNAL_APPROVAL_PENDING",
    "ADMINISTRATIVE_DISPUTE",
    "CONTRACT_MODIFICATION_PENDING",
    "FINAL_ADJUSTMENT_PENDING",
}


def is_ley_lobby_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host in {"www.leylobby.gob.cl", "leylobby.gob.cl"}


def _candidate_from_text(text: str, source_url: str, detail_url=None):
    audience_match = AUDIENCE_ID_PATTERN.search(text)
    date_match = DATE_PATTERN.search(text)
    case = build_case(text)
    signal_types = [p["type"] for p in case["problems"] if p["type"] in SIGNAL_TYPES]
    if not signal_types:
        return None

    return {
        "audience_id": audience_match.group(1).upper() if audience_match else None,
        "date": date_match.group(1) if date_match else None,
        "detail_url": detail_url,
        "source_url": source_url,
        "safis": case["safis"],
        "amounts_clp": case["amounts_clp"],
        "problems": case["problems"],
        "confidence": case["confidence"],
        "represented_entities": [],
        "works_for": [],
        "raw_text": text.strip(),
    }


def _rows_to_candidates(rows, source_url: str):
    candidates = []
    for row in rows:
        text = row["text"]
        if not DATE_PATTERN.search(text) and not AUDIENCE_ID_PATTERN.search(text):
            continue
        detail_url = next((link for link in row.get("links", []) if "/audiencias/" in link), None)
        candidate = _candidate_from_text(text, source_url, detail_url)
        if candidate:
            candidates.append(candidate)
    return candidates


def _text_blocks_to_candidates(text: str, source_url: str):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    starts = [i for i, line in enumerate(lines) if DATE_PATTERN.search(line)]
    candidates = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        block = "\n".join(lines[start:end])
        candidate = _candidate_from_text(block, source_url)
        if candidate:
            candidates.append(candidate)
    return candidates


def _candidate_key(item):
    return item.get("audience_id") or item.get("detail_url") or (
        item.get("date"),
        tuple(item.get("safis", [])),
        tuple(p["type"] for p in item.get("problems", [])),
    )


def _dedupe_candidates(candidates):
    seen = set()
    output = []
    for item in candidates:
        key = _candidate_key(item)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _pagination_urls(html: str, base_url: str):
    if not html:
        return []
    base = urlparse(base_url)
    found = []
    for link in html_links(html, base_url):
        parsed = urlparse(link)
        if parsed.netloc.lower() != base.netloc.lower() or parsed.path != base.path:
            continue
        page = parse_qs(parsed.query).get("page")
        if page and page[0].isdigit():
            if int(page[0]) == 1:
                continue
            found.append(link)
    return list(dict.fromkeys(found))


def _page_number(url: str):
    page = parse_qs(urlparse(url).query).get("page", ["1"])[0]
    return int(page) if str(page).isdigit() else 1


def _normalize_first_page(url: str):
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    qs.pop("page", None)
    query = urlencode(qs, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))


def _detail_metadata(document):
    represented = []
    works_for = []
    audience_id = None
    date = None

    if document.get("raw_html"):
        rows = html_table_rows(document["raw_html"], document["source_url"])
        for row in rows:
            cells = [cell.strip() for cell in row.get("cells", [])]
            parts = cells if cells else [p.strip() for p in row["text"].splitlines() if p.strip()]
            if len(parts) >= 2 and parts[0].lower() == "identificador":
                audience_id = parts[1].upper()
            if len(parts) >= 2 and parts[0].lower() == "fecha":
                match = DATE_PATTERN.search(parts[1])
                date = match.group(1) if match else date
            if len(parts) >= 4 and parts[1].lower() in {"gestor de intereses", "lobista"}:
                if parts[2] and parts[2] not in works_for:
                    works_for.append(parts[2])
                if parts[3] and parts[3] not in represented:
                    represented.append(parts[3])

    if not audience_id:
        match = AUDIENCE_ID_PATTERN.search(document["text"])
        audience_id = match.group(1).upper() if match else None
    if not date:
        match = DATE_PATTERN.search(document["text"])
        date = match.group(1) if match else None

    return {
        "audience_id": audience_id,
        "date": date,
        "represented_entities": represented,
        "works_for": works_for,
    }


def enrich_candidate(candidate, timeout=20):
    detail_url = candidate.get("detail_url")
    if not detail_url:
        return candidate
    document = fetch_public_document(detail_url, timeout=timeout)
    detail_case = build_case(document["text"])
    metadata = _detail_metadata(document)

    merged = dict(candidate)
    merged["audience_id"] = metadata["audience_id"] or merged.get("audience_id")
    merged["date"] = metadata["date"] or merged.get("date")
    merged["represented_entities"] = metadata["represented_entities"]
    merged["works_for"] = metadata["works_for"]
    merged["safis"] = list(dict.fromkeys(merged.get("safis", []) + detail_case["safis"]))
    merged["amounts_clp"] = list(dict.fromkeys(merged.get("amounts_clp", []) + detail_case["amounts_clp"]))

    problems_by_type = {p["type"]: p for p in merged.get("problems", [])}
    for problem in detail_case["problems"]:
        current = problems_by_type.get(problem["type"])
        if not current:
            problems_by_type[problem["type"]] = problem
        else:
            current["matched_patterns"] = list(dict.fromkeys(current["matched_patterns"] + problem["matched_patterns"]))
    merged["problems"] = list(problems_by_type.values())
    merged["confidence"] = build_case("\n".join([merged.get("raw_text", ""), document["text"]]))["confidence"]
    merged["detail_text"] = document["text"].strip()
    return merged


def scan_ley_lobby_listing(url: str, timeout: int = 20, max_pages: int = 10, enrich: bool = True, enrich_limit: int = 25):
    if not is_ley_lobby_url(url):
        raise ValueError("El scanner Ley del Lobby solo acepta URLs de leylobby.gob.cl")

    first_url = _normalize_first_page(url)
    queue = [first_url]
    seen_pages = set()
    all_candidates = []

    while queue and len(seen_pages) < max_pages:
        page_url = queue.pop(0)
        if page_url in seen_pages:
            continue
        document = fetch_public_document(page_url, timeout=timeout)
        seen_pages.add(document["source_url"])

        page_candidates = []
        if document["raw_html"]:
            rows = html_table_rows(document["raw_html"], document["source_url"])
            page_candidates.extend(_rows_to_candidates(rows, document["source_url"]))
        if not page_candidates:
            page_candidates.extend(_text_blocks_to_candidates(document["text"], document["source_url"]))
        all_candidates.extend(page_candidates)

        for link in _pagination_urls(document.get("raw_html"), document["source_url"]):
            if link not in seen_pages and link not in queue:
                queue.append(link)
        queue.sort(key=_page_number)

    candidates = _dedupe_candidates(all_candidates)
    candidates.sort(
        key=lambda item: (
            item["confidence"]["score"],
            bool(item["amounts_clp"]),
            bool(item["safis"]),
            item["date"] or "",
        ),
        reverse=True,
    )

    enrichment_errors = []
    if enrich:
        enriched = []
        for index, item in enumerate(candidates):
            if index >= enrich_limit or not item.get("detail_url"):
                enriched.append(item)
                continue
            try:
                enriched.append(enrich_candidate(item, timeout=timeout))
            except (OSError, ValueError) as exc:
                item = dict(item)
                item["enrichment_error"] = str(exc)
                enriched.append(item)
                enrichment_errors.append({"audience_id": item.get("audience_id"), "error": str(exc)})
        candidates = enriched

    return {
        "source": "LEY_DEL_LOBBY",
        "source_url": first_url,
        "pages_scanned": len(seen_pages),
        "candidate_count": len(candidates),
        "enrichment_errors": enrichment_errors,
        "candidates": candidates,
    }
