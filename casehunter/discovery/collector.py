from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import time


class VisibleTextParser(HTMLParser):
    HIDDEN_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self):
        super().__init__()
        self._hidden_depth = 0
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.HIDDEN_TAGS:
            self._hidden_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.HIDDEN_TAGS and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data):
        if self._hidden_depth == 0:
            value = " ".join(data.split())
            if value:
                self._parts.append(value)

    def get_text(self):
        return "\n".join(self._parts)


class TableRowParser(HTMLParser):
    """Extract visible table rows and links from server-rendered HTML."""

    HIDDEN_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self._hidden_depth = 0
        self._in_row = False
        self._row_depth = 0
        self._parts = []
        self._links = []
        self._cells = []
        self._in_cell = False
        self._cell_parts = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.HIDDEN_TAGS:
            self._hidden_depth += 1
            return

        if tag == "tr":
            if not self._in_row:
                self._in_row = True
                self._row_depth = 1
                self._parts = []
                self._links = []
                self._cells = []
                self._in_cell = False
                self._cell_parts = []
            else:
                self._row_depth += 1

        if self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []

        if self._in_row and tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._links.append(urljoin(self.base_url, href))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.HIDDEN_TAGS:
            if self._hidden_depth:
                self._hidden_depth -= 1
            return

        if tag in {"td", "th"} and self._in_row and self._in_cell:
            self._cells.append(" ".join(self._cell_parts).strip())
            self._in_cell = False
            self._cell_parts = []

        if tag == "tr" and self._in_row:
            self._row_depth -= 1
            if self._row_depth == 0:
                text = "\n".join(self._parts).strip()
                if text:
                    self.rows.append({"text": text, "links": list(dict.fromkeys(self._links)), "cells": list(self._cells)})
                self._in_row = False
                self._parts = []
                self._links = []
                self._cells = []
                self._in_cell = False
                self._cell_parts = []

    def handle_data(self, data):
        if self._in_row and self._hidden_depth == 0:
            value = " ".join(data.split())
            if value:
                self._parts.append(value)
                if self._in_cell:
                    self._cell_parts.append(value)


class LinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(urljoin(self.base_url, href))


def html_to_text(html: str) -> str:
    parser = VisibleTextParser()
    parser.feed(html)
    parser.close()
    return parser.get_text().strip()


def html_table_rows(html: str, base_url: str):
    parser = TableRowParser(base_url)
    parser.feed(html)
    parser.close()
    return parser.rows


def html_links(html: str, base_url: str):
    parser = LinkParser(base_url)
    parser.feed(html)
    parser.close()
    return list(dict.fromkeys(parser.links))


def fetch_public_document(url: str, timeout: int = 20, retries: int = 2, max_bytes: int = 5_000_000):
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("La fuente debe comenzar con http:// o https://")

    last_error = None
    for attempt in range(retries + 1):
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; CaseHunter/1.0; public-source-research)",
                "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                content_type = response.headers.get_content_type()
                charset = response.headers.get_content_charset() or "utf-8"
                raw = response.read(max_bytes + 1)
                final_url = response.geturl() if hasattr(response, "geturl") else url
            if len(raw) > max_bytes:
                raise ValueError(f"La respuesta supera el límite de {max_bytes} bytes")
            break
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt >= retries:
                raise OSError(f"No se pudo descargar {url}: {exc}") from exc
            time.sleep(0.25 * (attempt + 1))
    else:
        raise OSError(f"No se pudo descargar {url}: {last_error}")

    if content_type not in {"text/html", "text/plain"}:
        raise ValueError(
            f"Tipo de contenido no soportado: {content_type}. "
            "Use una página HTML o texto público."
        )

    decoded = raw.decode(charset, errors="replace")
    text = html_to_text(decoded) if content_type == "text/html" else decoded.strip()
    if not text:
        raise ValueError("La fuente respondió, pero no produjo texto utilizable.")

    return {
        "source_url": final_url,
        "content_type": content_type,
        "text": text,
        "raw_html": decoded if content_type == "text/html" else None,
    }


def fetch_public_text(url: str, timeout: int = 20):
    document = fetch_public_document(url, timeout=timeout)
    return {
        "source_url": document["source_url"],
        "content_type": document["content_type"],
        "text": document["text"],
    }
