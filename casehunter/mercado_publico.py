from datetime import date, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import os
import time

BASE = "https://api.mercadopublico.cl/servicios/v1/publico"
PROVIDER_LOOKUP = "https://api.mercadopublico.cl/servicios/v1/Publico/Empresas/BuscarProveedor"
PENDING_ORDER_STATES = {
    5: "PURCHASE_ORDER_IN_PROCESS",
    13: "RECEPTION_PENDING",
    14: "RECEPTION_PARTIAL",
    15: "RECEPTION_INCOMPLETE",
}


def configured():
    return bool(os.getenv("MERCADO_PUBLICO_TICKET", "").strip())


def _ticket(value=None):
    ticket = (value or os.getenv("MERCADO_PUBLICO_TICKET", "")).strip()
    if not ticket:
        raise ValueError("Falta MERCADO_PUBLICO_TICKET. Solicita tu ticket oficial y configúralo fuera del código.")
    return ticket


def _get_json(url, timeout=20, retries=2):
    last_error = None
    for attempt in range(retries + 1):
        request = Request(url, headers={"User-Agent": "CaseHunterResolve/2.0", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(10_000_000)
            return json.loads(raw.decode("utf-8-sig"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt >= retries:
                raise OSError(f"No se pudo consultar Mercado Público: {exc}") from exc
            time.sleep(0.25 * (attempt + 1))
    raise OSError(f"No se pudo consultar Mercado Público: {last_error}")


def _walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def lookup_provider(rut, ticket=None):
    clean = (rut or "").strip()
    if not clean:
        raise ValueError("El RUT es obligatorio")
    params = urlencode({"rutempresaproveedor": clean, "ticket": _ticket(ticket)})
    data = _get_json(f"{PROVIDER_LOOKUP}?{params}")
    for item in _walk_dicts(data):
        code = item.get("CodigoEmpresa") or item.get("CódigoEmpresa") or item.get("Codigo")
        name = item.get("NombreEmpresa") or item.get("Nombre")
        if code and name:
            return {"provider_code": str(code), "name": str(name), "raw": data}
    raise ValueError("Mercado Público no devolvió un proveedor reconocible para ese RUT")


def purchase_orders_by_provider_date(provider_code, when, ticket=None):
    if isinstance(when, str):
        when = date.fromisoformat(when)
    params = urlencode({
        "fecha": when.strftime("%d%m%Y"),
        "CodigoProveedor": str(provider_code),
        "ticket": _ticket(ticket),
    })
    data = _get_json(f"{BASE}/ordenesdecompra.json?{params}")
    listing = data.get("Listado", []) if isinstance(data, dict) else []
    return listing if isinstance(listing, list) else []


def purchase_order_by_code(code, ticket=None):
    clean = " ".join(str(code or "").split()).strip()
    if not clean:
        raise ValueError("El código de orden de compra es obligatorio")
    params = urlencode({"codigo": clean, "ticket": _ticket(ticket)})
    data = _get_json(f"{BASE}/ordenesdecompra.json?{params}")
    listing = data.get("Listado", []) if isinstance(data, dict) else []
    if isinstance(listing, list) and listing:
        return listing[0]
    raise ValueError(f"Mercado Público no devolvió la orden de compra {clean}")


def _problem_for_order(order):
    try:
        code = int(order.get("CodigoEstado"))
    except (TypeError, ValueError):
        return None
    problem_type = PENDING_ORDER_STATES.get(code)
    if not problem_type:
        return None
    return {"type": problem_type, "matched_patterns": [str(order.get("Estado") or code)]}


def _order_date(order, fallback):
    fechas = order.get("Fechas") if isinstance(order.get("Fechas"), dict) else {}
    raw = fechas.get("FechaUltimaModificacion") or fechas.get("FechaCreacion")
    if raw:
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
    return fallback.isoformat()


def order_to_candidate(order, provider_name, query_date):
    problem = _problem_for_order(order)
    if not problem:
        return None
    code = str(order.get("Codigo") or "").strip()
    if not code:
        return None
    buyer = order.get("Comprador") if isinstance(order.get("Comprador"), dict) else {}
    total = order.get("Total")
    amounts = []
    try:
        if total is not None and float(total) > 0 and str(order.get("TipoMoneda", "CLP")).upper() == "CLP":
            amounts.append(int(round(float(total))))
    except (TypeError, ValueError):
        pass
    status = str(order.get("Estado") or "")
    name = str(order.get("Nombre") or order.get("Descripcion") or code)
    raw_text = "\n".join(filter(None, [
        f"Orden de compra {code}",
        name,
        f"Estado {status}",
        f"Organismo {buyer.get('NombreOrganismo','')}",
        f"Proveedor {provider_name}",
        f"Total CLP {amounts[0]}" if amounts else None,
    ]))
    return {
        "audience_id": code,
        "date": _order_date(order, query_date),
        "detail_url": None,
        "source_url": "https://www.mercadopublico.cl/",
        "safis": [],
        "amounts_clp": amounts,
        "problems": [problem],
        "confidence": {"score": 0.75 if amounts else 0.5, "label": "MEDIUM"},
        "represented_entities": [provider_name] if provider_name else [],
        "works_for": [],
        "agency": buyer.get("NombreOrganismo") or buyer.get("NombreUnidad"),
        "contract_ref": f"OC {code}",
        "raw_text": raw_text,
        "detail_text": json.dumps(order, ensure_ascii=False, indent=2),
    }


def scan_purchase_orders_for_rut(rut, start_date, end_date, ticket=None, max_days=62):
    start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    if end < start:
        raise ValueError("La fecha final no puede ser anterior a la inicial")
    days = (end - start).days + 1
    if days > max_days:
        raise ValueError(f"El rango máximo por sincronización es de {max_days} días")

    provider = lookup_provider(rut, ticket)
    candidates = []
    requests = 0
    current = start
    while current <= end:
        orders = purchase_orders_by_provider_date(provider["provider_code"], current, ticket)
        requests += 1
        for order in orders:
            candidate = order_to_candidate(order, provider["name"], current)
            if candidate:
                candidates.append(candidate)
        current += timedelta(days=1)

    unique = {}
    for item in candidates:
        unique[item["audience_id"]] = item
    candidates = list(unique.values())
    candidates.sort(key=lambda item: (item["confidence"]["score"], max(item["amounts_clp"], default=0), item["date"]), reverse=True)
    return {
        "source": "MERCADO_PUBLICO",
        "source_url": "https://api.mercadopublico.cl/",
        "provider": {"rut": rut, "provider_code": provider["provider_code"], "name": provider["name"]},
        "pages_scanned": requests,
        "candidate_count": len(candidates),
        "enrichment_errors": [],
        "candidates": candidates,
    }
