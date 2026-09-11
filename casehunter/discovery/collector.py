from html.parser import HTMLParser
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import os
import time

from pypdf import PdfReader


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


def _ocr_pdf_text(raw: bytes, max_pages: int = 30, max_chars: int = 300_000, dpi: int = 160) -> str:
    """OCR only the first bounded set of pages of a scanned public PDF.

    Tesseract is intentionally used as a fallback, never as the first parser. This
    keeps ordinary text PDFs fast and prevents a large scanned file from exhausting
    the automatic cycle.
    """
    try:
        import fitz
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise ValueError("El PDF requiere OCR, pero el motor OCR no está instalado.") from exc

    lang = (os.getenv("CASE_HUNTER_OCR_LANG") or "spa+eng").strip()
    try:
        document = fitz.open(stream=raw, filetype="pdf")
    except Exception as exc:
        raise ValueError("No se pudo abrir el PDF para OCR.") from exc

    parts = []
    total = 0
    page_limit = min(len(document), max(1, int(max_pages)))
    scale = max(1.0, float(dpi) / 72.0)
    matrix = fitz.Matrix(scale, scale)

    try:
        for index in range(page_limit):
            page = document[index]
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.open(BytesIO(pixmap.tobytes("png")))
            try:
                text = (pytesseract.image_to_string(image, lang=lang, config="--psm 6") or "").strip()
            except Exception as exc:
                raise ValueError(f"El motor OCR falló al procesar la página {index + 1}: {exc}") from exc
            finally:
                image.close()

            if not text:
                continue
            remaining = max_chars - total
            if remaining <= 0:
                break
            chunk = text[:remaining]
            parts.append(chunk)
            total += len(chunk)
    finally:
        document.close()

    result = "\n".join(parts).strip()
    if not result:
        raise ValueError("El PDF no produjo texto utilizable ni mediante OCR.")
    return result


def extract_pdf_text(
    raw: bytes,
    max_pages: int = 200,
    max_chars: int = 1_000_000,
    allow_ocr: bool = True,
    min_native_chars: int = 80,
    ocr_engine=None,
) -> str:
    if not raw:
        raise ValueError("El PDF está vacío.")
    reader = PdfReader(BytesIO(raw), strict=False)
    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception as exc:
            raise ValueError("El PDF está cifrado y no puede procesarse automáticamente.") from exc
        if not unlocked:
            raise ValueError("El PDF está cifrado y requiere contraseña.")
    if len(reader.pages) > max_pages:
        raise ValueError(f"El PDF supera el límite de {max_pages} páginas")

    parts = []
    total = 0
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        remaining = max_chars - total
        if remaining <= 0:
            break
        chunk = text[:remaining]
        parts.append(chunk)
        total += len(chunk)
    native = "\n".join(parts).strip()
    if len(native) >= max(1, int(min_native_chars)):
        return native

    if not allow_ocr:
        if native:
            return native
        raise ValueError("El PDF no contiene texto nativo extraíble. Puede requerir OCR.")

    engine = ocr_engine or _ocr_pdf_text
    try:
        ocr_text = (engine(raw) or "").strip()
    except ValueError:
        if native:
            return native
        raise
    except Exception as exc:
        if native:
            return native
        raise ValueError(f"No se pudo ejecutar OCR sobre el PDF: {exc}") from exc

    # Some PDFs contain a tiny text layer plus scanned pages. Prefer whichever
    # extraction provides materially more information instead of concatenating
    # duplicated text.
    return ocr_text if len(ocr_text) > len(native) else native


def fetch_public_document(url: str, timeout: int = 20, retries: int = 2, max_bytes: int = 10_000_000):
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("La fuente debe comenzar con http:// o https://")

    last_error = None
    for attempt in range(retries + 1):
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; CaseHunter/1.0; public-source-research)",
                "Accept": "text/html,application/pdf,text/plain;q=0.9,*/*;q=0.1",
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

    if content_type == "application/pdf":
        text = extract_pdf_text(raw)
        return {
            "source_url": final_url,
            "content_type": content_type,
            "text": text,
            "raw_html": None,
        }

    if content_type not in {"text/html", "text/plain"}:
        raise ValueError(
            f"Tipo de contenido no soportado: {content_type}. "
            "Use una página HTML, texto público o PDF."
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
