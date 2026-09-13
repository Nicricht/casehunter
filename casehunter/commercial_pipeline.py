QUALIFYING_REPLY_CLASSES = {
    "REQUESTS_INFO",
    "STILL_PENDING",
    "PILOT_REQUESTED",
    "NO_AGENCY_RESPONSE",
}

EXPLICIT_COMMERCIAL_STAGES = {
    "PILOT_PROPOSED",
    "PILOT_ACTIVE",
    "WON",
    "LOST",
}

STATUS_URGENCY = {
    "ACTION_REQUIRED": 10,
    "BLOCKER_IDENTIFIED": 9,
    "FOLLOW_UP": 8,
    "WAITING_AGENCY": 7,
    "VALIDATING": 5,
    "DOCUMENT_SENT": 4,
    "DETECTED": 2,
}


def commercial_stage(case):
    """Derive a commercial stage from facts already stored by Case Hunter."""
    explicit = str(case.get("commercial_status") or "").strip().upper()
    if explicit in EXPLICIT_COMMERCIAL_STAGES:
        return explicit
    if bool(case.get("has_pilot_started")):
        return "PILOT_ACTIVE"

    status = str(case.get("status") or "")
    if status == "RESOLVED":
        return "CASE_RESOLVED"
    if status == "DISMISSED":
        return "CLOSED"
    if bool(case.get("has_watch_action")) and status == "FOLLOW_UP":
        return "WATCHING"
    latest_reply = str(case.get("latest_reply_classification") or "")
    if bool(case.get("has_reply")) and latest_reply in QUALIFYING_REPLY_CLASSES:
        return "QUALIFIED"
    if bool(case.get("has_reply")):
        return "REPLIED"
    if bool(case.get("has_contacted")):
        return "CONTACTED"
    if bool(case.get("has_auto_send_contact")) or int(case.get("contact_trust_score") or 0) >= 60:
        return "CONTACT_READY"
    if float(case.get("confidence_score") or 0) >= 0.75 or int(case.get("financial_priority") or 0) >= 50:
        return "RESEARCHED"
    return "NEW"


def opportunity_score(case):
    """Return a transparent 0-100 commercial priority score.

    This score never sends email or mutates state. It only ranks where human or
    automated research effort has the highest expected value based on evidence,
    contactability and engagement already present in the database.
    """
    financial = min(100, max(0, int(case.get("financial_priority") or 0))) * 0.40
    evidence = min(1.0, max(0.0, float(case.get("confidence_score") or 0))) * 20.0

    trust = min(100, max(0, int(case.get("contact_trust_score") or 0)))
    if bool(case.get("has_auto_send_contact")):
        contact = 15.0
    elif trust:
        contact = min(12.0, trust * 0.12)
    elif bool(case.get("has_contact")):
        contact = 5.0
    else:
        contact = 0.0

    stage = commercial_stage(case)
    engagement = {
        "PILOT_ACTIVE": 25.0,
        "PILOT_PROPOSED": 22.0,
        "WATCHING": 20.0,
        "QUALIFIED": 20.0,
        "REPLIED": 15.0,
        "CONTACTED": 9.0,
        "CONTACT_READY": 6.0,
        "RESEARCHED": 3.0,
        "NEW": 0.0,
        "WON": 0.0,
        "LOST": 0.0,
        "CASE_RESOLVED": 0.0,
        "CLOSED": 0.0,
    }.get(stage, 0.0)
    urgency = float(STATUS_URGENCY.get(str(case.get("status") or ""), 0))
    return max(0, min(100, int(round(financial + evidence + contact + engagement + urgency))))


def next_commercial_move(case):
    stage = commercial_stage(case)
    moves = {
        "NEW": "Enriquecer evidencia pública y confirmar empresa antes de contactar.",
        "RESEARCHED": "Buscar y validar un contacto corporativo confiable.",
        "CONTACT_READY": "Revisar el borrador y decidir si se aprueba el primer contacto.",
        "CONTACTED": "Esperar respuesta y ejecutar seguimiento solo cuando corresponda.",
        "REPLIED": "Clasificar la respuesta y definir si existe una oportunidad real.",
        "QUALIFIED": "Preparar una propuesta de piloto concreta y registrar si fue enviada.",
        "PILOT_PROPOSED": "Conseguir aceptación explícita del piloto y fijar alcance, duración y precio.",
        "PILOT_ACTIVE": "Demostrar valor medible: cambio detectado, evidencia ordenada o tiempo manual evitado.",
        "WON": "Registrar ingreso real, mantener la cuenta y buscar renovación o expansión.",
        "LOST": "Registrar el motivo de pérdida y usarlo para mejorar segmentación, oferta o timing.",
        "WATCHING": "Vigilar cambios públicos materiales y actuar solo cuando cambie el caso.",
        "CASE_RESOLVED": "Documentar el resultado y reutilizarlo como precedente para futuros casos.",
        "CLOSED": "No dedicar más esfuerzo comercial salvo nueva evidencia.",
    }
    return moves.get(stage, moves["NEW"])


def commercialize_case(case):
    """Return the original row enriched with explainable commercial intelligence."""
    result = dict(case)
    stage = commercial_stage(result)
    result["commercial_stage"] = stage
    result["opportunity_score"] = opportunity_score(result)
    result["next_commercial_move"] = next_commercial_move(result)

    reasons = []
    priority = int(result.get("financial_priority") or 0)
    confidence = float(result.get("confidence_score") or 0)
    trust = int(result.get("contact_trust_score") or 0)
    if priority:
        reasons.append(f"prioridad financiera {priority}/100")
    if confidence:
        reasons.append(f"confianza de evidencia {round(confidence * 100)}%")
    if trust:
        reasons.append(f"confianza de contacto {trust}/100")
    if result.get("latest_reply_classification"):
        reasons.append(f"respuesta {result['latest_reply_classification']}")
    if result.get("has_watch_action"):
        reasons.append("seguimiento público activo")
    if result.get("commercial_status") and result.get("commercial_status") != "OPEN":
        reasons.append(f"estado comercial {result['commercial_status']}")
    result["opportunity_reasons"] = reasons
    return result
