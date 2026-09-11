from dataclasses import dataclass


REPLY_CLASSES = {
    "POSITIVE",
    "REQUESTS_INFO",
    "STILL_PENDING",
    "NO_AGENCY_RESPONSE",
    "RESOLVED",
    "NOT_INTERESTED",
    "NEGATIVE",
    "OTHER",
}


@dataclass(frozen=True)
class ReplyDecision:
    classification: str
    confidence: float
    next_case_status: str | None
    action_type: str | None
    action_title: str | None
    stop_outreach: bool = False


PHRASES = {
    "RESOLVED": [
        "ya está resuelto", "ya esta resuelto", "se resolvió", "se resolvio", "ya fue pagado",
        "ya se pagó", "ya se pago", "ya fue liquidado", "ya se liquidó", "ya se liquido",
        "ya está cerrado", "ya esta cerrado", "no está pendiente", "no esta pendiente",
    ],
    "NO_AGENCY_RESPONSE": [
        "no hemos recibido más información", "no hemos recibido mas informacion",
        "no hemos recibido respuesta", "no recibimos respuesta", "sin respuesta",
        "sin respuesta de correo", "no hubo respuesta", "no hubo respuesta posterior",
        "no respondió", "no respondio", "no han respondido", "no nos han respondido",
        "no hubo comunicación posterior", "no hubo comunicacion posterior",
    ],
    "STILL_PENDING": [
        "sigue pendiente", "aún está pendiente", "aun esta pendiente", "continúa pendiente",
        "continua pendiente", "todavía está pendiente", "todavia esta pendiente", "no hemos recibido el pago",
        "no nos han pagado", "no se ha pagado", "no se ha liquidado", "no se ha liberado",
    ],
    "NOT_INTERESTED": [
        "no nos interesa", "no me interesa", "no estamos interesados", "no gracias", "no enviar",
        "no nos contacte", "no me contacte", "favor no contactar",
    ],
    "REQUESTS_INFO": [
        "envíamela", "enviamela", "envíemela", "enviemela", "envíenosla", "envienosla",
        "puede enviar", "puedes enviar", "mándamela", "mandamela", "comparta la información",
        "comparta la informacion", "envíe la información", "envie la informacion", "sí, por favor", "si, por favor",
        "envíame", "enviame", "envíenos", "envienos",
    ],
    "NEGATIVE": [
        "no corresponde", "está equivocado", "esta equivocado", "empresa incorrecta", "contrato incorrecto",
    ],
    "POSITIVE": ["me interesa", "nos interesa", "interesados", "de acuerdo", "perfecto", "adelante"],
}


def _classification(text):
    value = (text or "").strip().lower()
    if not value:
        return "OTHER", 0.2

    for label in (
        "RESOLVED",
        "NO_AGENCY_RESPONSE",
        "STILL_PENDING",
        "NOT_INTERESTED",
        "REQUESTS_INFO",
        "NEGATIVE",
        "POSITIVE",
    ):
        if any(token in value for token in PHRASES[label]):
            return label, 0.95
    if value in {"sí", "si", "ok", "okay"}:
        return "POSITIVE", 0.8
    return "OTHER", 0.35


def analyze_reply(text):
    classification, confidence = _classification(text)
    if classification in {"POSITIVE", "REQUESTS_INFO"}:
        return ReplyDecision(
            classification,
            confidence,
            "VALIDATING",
            "SEND_PUBLIC_SUMMARY",
            "Enviar síntesis pública de una página solicitada por la empresa",
        )
    if classification == "STILL_PENDING":
        return ReplyDecision(
            classification,
            confidence,
            "VALIDATING",
            "CONFIRM_CURRENT_BLOCKER",
            "Confirmar con la empresa cuál es el bloqueo administrativo actual",
        )
    if classification == "NO_AGENCY_RESPONSE":
        return ReplyDecision(
            classification,
            confidence,
            "BLOCKER_IDENTIFIED",
            "ESCALATE_RESPONSIBLE_UNIT",
            "Identificar la unidad responsable y escalar el seguimiento solicitando folio, estado y fecha de respuesta",
        )
    if classification == "RESOLVED":
        return ReplyDecision(classification, confidence, "RESOLVED", None, None, True)
    if classification in {"NOT_INTERESTED", "NEGATIVE"}:
        return ReplyDecision(
            classification,
            confidence,
            None,
            "NO_FURTHER_OUTREACH",
            "No realizar nuevos contactos comerciales sobre este caso",
            True,
        )
    return ReplyDecision(
        "OTHER",
        confidence,
        None,
        "REVIEW_REPLY",
        "Revisar manualmente la respuesta recibida",
    )


def classify_reply(text):
    return analyze_reply(text).classification
