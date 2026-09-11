import re

from .detector import normalize_text

RESOLUTION_PATTERNS = (
    "ya esta resuelto",
    "caso resuelto",
    "situacion regularizada",
    "situacion se encuentra regularizada",
    "deuda saldada",
    "deuda pagada",
    "deuda fue pagada",
    "pago realizado",
    "pago efectuado",
    "ya fue pagado",
    "ya fueron pagadas",
    "fueron pagadas",
    "fue pagada",
    "fue pagado",
    "se regularizo el pago",
    "se concreto el pago",
    "no mantiene deuda",
)

UNRESOLVED_PATTERNS = (
    "sigue pendiente",
    "continua pendiente",
    "aun pendiente",
    "todavia pendiente",
    "factura pendiente",
    "facturas pendientes",
    "pago pendiente",
    "pagos pendientes",
    "saldo pendiente",
    "deuda pendiente",
    "adeuda",
    "no se ha pagado",
    "no han pagado",
    "no hemos recibido el pago",
    "sin fecha de pago",
    "plan de pago",
    "compromiso de pago",
)


def _matched_patterns(text, patterns):
    normalized = normalize_text(text or "")
    return [pattern for pattern in patterns if normalize_text(pattern) in normalized]


def analyze_public_outcome(text):
    normalized = normalize_text(text or "")
    resolved_matches = _matched_patterns(normalized, RESOLUTION_PATTERNS)
    if not resolved_matches:
        return {"state": "OPEN_OR_UNKNOWN", "resolved_signals": [], "pending_signals": []}

    remainder = normalized
    for pattern in resolved_matches:
        remainder = remainder.replace(normalize_text(pattern), " ")
    remainder = re.sub(r"\s+", " ", remainder)
    pending_matches = _matched_patterns(remainder, UNRESOLVED_PATTERNS)

    state = "PARTIAL" if pending_matches else "RESOLVED"
    return {
        "state": state,
        "resolved_signals": resolved_matches,
        "pending_signals": pending_matches,
    }
