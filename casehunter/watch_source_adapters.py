import json
import re
from urllib.parse import urlparse

from .discovery.collector import fetch_public_document, html_links
from .mercado_publico import purchase_order_by_code

KNOWN_OFFICIAL_HOSTS = {
    "www.leylobby.gob.cl",
    "leylobby.gob.cl",
    "www.mercadopublico.cl",
    "mercadopublico.cl",
    "api.mercadopublico.cl",
    "www.portaltransparencia.cl",
    "portaltransparencia.cl",
    "www.infotransparencia.cl",
    "infotransparencia.cl",
}

OFFICIAL_PATH_TERMS = (
    "transpar",
    "decreto",
    "resoluc",
    "acta",
    "proveedor",
    "pago",
    "factura",
    "finanza",
    "tesorer",
    "presupuesto",
    "compra",
    "contrato",
)


def source_kind(source_url):
    value = str(source_url or "").strip()
    if value.lower().startswith("mercadopublico:oc:"):
        return "MERCADO_PUBLICO_OC"
    parsed = urlparse(value)
    host = parsed.netloc.lower().split(":", 1)[0]
    if host in {"leylobby.gob.cl", "www.leylobby.gob.cl"}:
        return "LEY_LOBBY"
    if host in {"portaltransparencia.cl", "www.portaltransparencia.cl", "infotransparencia.cl", "www.infotransparencia.cl"}:
        return "TRANSPARENCIA"
    if host in {"mercadopublico.cl", "www.mercadopublico.cl", "api.mercadopublico.cl"}:
        return "MERCADO_PUBLICO_WEB"
    if host.endswith(".gob.cl"):
        return "GOVERNMENT_WEB"
    return "PUBLIC_WEB"


def mercado_publico_order_ref(code):
    clean = " ".join(str(code or "").split()).strip()
    if not clean:
        raise ValueError("El código de orden de compra es obligatorio")
    return f"mercadopublico:oc:{clean}"


def _order_code_from_ref(source_url):
    prefix = "mercadopublico:oc:"
    value = str(source_url or "").strip()
    if not value.lower().startswith(prefix):
        return None
    return value[len(prefix):].strip()


def _canonical_order_text(order):
    if not isinstance(order, dict):
        return json.dumps(order, ensure_ascii=False, sort_keys=True)

    buyer = order.get("Comprador") if isinstance(order.get("Comprador"), dict) else {}
    supplier = order.get("Proveedor") if isinstance(order.get("Proveedor"), dict) else {}
    fechas = order.get("Fechas") if isinstance(order.get("Fechas"), dict) else {}
    fields = {
        "codigo": order.get("Codigo"),
        "estado": order.get("Estado"),
        "codigo_estado": order.get("CodigoEstado"),
        "nombre": order.get("Nombre") or order.get("Descripcion"),
        "total": order.get("Total"),
        "moneda": order.get("TipoMoneda"),
        "organismo": buyer.get("NombreOrganismo") or buyer.get("NombreUnidad"),
        "proveedor": supplier.get("Nombre") or supplier.get("NombreProveedor"),
        "fecha_creacion": fechas.get("FechaCreacion"),
        "fecha_ultima_modificacion": fechas.get("FechaUltimaModificacion"),
        "fecha_aceptacion": fechas.get("FechaAceptacion"),
        "fecha_cancelacion": fechas.get("FechaCancelacion"),
    }
    lines = [f"{key}: {value}" for key, value in fields.items() if value not in (None, "")]
    return "\n".join(lines)


def _same_host_or_official(candidate_url, parent_url):
    parsed = urlparse(str(candidate_url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = parsed.netloc.lower().split(":", 1)[0]
    parent_host = urlparse(str(parent_url or "")).netloc.lower().split(":", 1)[0]
    if host in KNOWN_OFFICIAL_HOSTS or host.endswith(".gob.cl"):
        return True
    if host == parent_host:
        searchable = f"{parsed.path}?{parsed.query}".lower()
        return any(term in searchable for term in OFFICIAL_PATH_TERMS)
    return False


def discover_official_links(raw_html, source_url, limit=12):
    if not raw_html:
        return []
    candidates = []
    for url in html_links(raw_html, source_url):
        if _same_host_or_official(url, source_url):
            candidates.append(url)
        if len(candidates) >= max(1, int(limit)):
            break
    return list(dict.fromkeys(candidates))


def fetch_watch_source(source_url, http_fetcher=None, mercado_fetcher=None):
    kind = source_kind(source_url)
    code = _order_code_from_ref(source_url)
    if code:
        fetch_order = mercado_fetcher or purchase_order_by_code
        order = fetch_order(code)
        return {
            "source_url": source_url,
            "kind": kind,
            "text": _canonical_order_text(order),
            "discovered_urls": [],
        }

    fetch = http_fetcher or fetch_public_document
    document = fetch(source_url)
    raw_html = document.get("raw_html") if isinstance(document, dict) else None
    return {
        "source_url": document.get("source_url", source_url),
        "kind": kind,
        "text": document.get("text", ""),
        "discovered_urls": discover_official_links(raw_html, document.get("source_url", source_url)),
    }


def extract_order_code(contract_ref):
    text = " ".join(str(contract_ref or "").split()).strip()
    if not text:
        return None
    match = re.search(r"\bOC\s+([A-Z0-9][A-Z0-9-]{3,})\b", text, flags=re.I)
    return match.group(1) if match else None
