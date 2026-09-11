import unicodedata

RULES = {
    "RETENTION_PENDING": [
        "devolucion de retenciones",
        "retenciones pendientes",
        "retencion pendiente",
        "demora en devolucion de retenciones",
        "retenciones por devolver",
        "canje de retenciones",
        "cobro de retenciones",
        "cobro de las retenciones",
        "retenciones correspondientes",
        "devolver retenciones",
        "devolucion de garantia y retenciones",
        "retenciones contractuales adeudadas",
        "restitucion de las retenciones",
        "fondos retenidos",
        "montos retenidos",
    ],
    "LIQUIDATION_PENDING": [
        "liquidacion pendiente",
        "contrato no liquidado",
        "liquidar contrato",
        "pendiente de liquidacion",
        "liquidacion del contrato",
        "liquidacion de contrato",
        "liquidacion final de contratos",
        "demora en liquidacion de contratos",
        "seguimiento liquidacion",
        "cierre administrativo",
        "cierre administrativo de las obras",
    ],
    "PAYMENT_PENDING": [
        "pago pendiente",
        "estado de pago",
        "factura pendiente",
        "facturas pendientes",
        "facturas vencidas",
        "deuda vencida",
        "pendiente de pago",
        "pendientes de pago",
        "pagos pendientes",
        "saldos pendientes de pagos",
        "no se ha efectuado pago alguno",
        "paguese",
        "saldo pendiente",
        "no ha salido ningun pago",
    ],
    "GUARANTEE_PENDING": [
        "boleta de garantia",
        "renovacion de garantia",
        "garantia pendiente",
        "devolucion de garantia",
        "garantias pendientes",
        "demora en devolucion de garantias",
    ],
    "DOCUMENT_MISSING": [
        "falta informe",
        "falta oficio",
        "falta carta",
        "antecedentes pendientes",
        "documentacion pendiente",
        "documentos faltantes",
        "falta documentacion",
    ],
    "INTERNAL_APPROVAL_PENDING": [
        "en revision",
        "pendiente de aprobacion",
        "pendiente de firma",
        "para revision",
        "en tramitacion",
    ],
    "CONTRACT_MODIFICATION_PENDING": [
        "modificacion pendiente",
        "modificaciones pendientes",
        "pendiente tramitacion modificacion",
        "pendiente de tramitacion modificacion",
        "modificacion en revision",
        "modificacion reingresada",
    ],
    "FINAL_ADJUSTMENT_PENDING": [
        "ajuste final pendiente",
        "pendiente tramitacion ajuste final",
        "pendiente de tramitacion ajuste final",
        "tramitacion ajuste final",
    ],
    "ADMINISTRATIVE_DISPUTE": [
        "recurso de invalidacion",
        "controversia",
        "consulta juridica",
        "recurso administrativo",
    ],
}


def normalize_text(text: str) -> str:
    text = text.lower()
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def detect_problems(text: str):
    normalized = normalize_text(text)
    results = []
    for problem_type, patterns in RULES.items():
        matched = []
        for pattern in patterns:
            if normalize_text(pattern) in normalized:
                matched.append(pattern)
        if matched:
            results.append({"type": problem_type, "matched_patterns": matched})
    return results
