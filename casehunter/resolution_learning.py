from collections import defaultdict
from datetime import date
import math
import re
import unicodedata

from .company_identity import normalize_company_name
from .database import transaction, utc_now
from .repository import add_timeline_event, create_action, get_case, list_cases


PATHWAYS = (
    {
        "action_type": "VERIFY_PAYMENT_COMMITMENT",
        "title": "Validar un compromiso o calendario de pago concreto",
        "tokens": ("plan de pago", "compromiso de pago", "calendario de pago", "fecha de pago", "programacion de pago"),
    },
    {
        "action_type": "VERIFY_FUNDING_MOVEMENT",
        "title": "Verificar remesa, transferencia o disponibilidad de recursos para el caso",
        "tokens": ("solicitud de recursos", "transferencia de recursos", "remesa", "disponibilidad presupuestaria", "recursos municipales"),
    },
    {
        "action_type": "ESCALATE_FINANCE",
        "title": "Escalar el seguimiento a Finanzas, Contabilidad o Tesorería con preguntas verificables",
        "tokens": ("finanzas", "contabilidad", "tesoreria", "administracion y finanzas", "direccion de administracion y finanzas"),
    },
    {
        "action_type": "REVIEW_FORMAL_ACT",
        "title": "Obtener y revisar el acto formal que respalda el siguiente hito",
        "tokens": ("resolucion", "decreto", "folio", "oficio", "ordinario", "memorandum"),
    },
    {
        "action_type": "REQUEST_INSTITUTIONAL_ESCALATION",
        "title": "Escalar por un canal institucional formal y dejar trazabilidad del caso",
        "tokens": ("audiencia", "reunion", "ley lobby", "gestor de intereses", "solicita audiencia"),
    },
    {
        "action_type": "VERIFY_PUBLIC_RESOLUTION",
        "title": "Verificar documentalmente el pago o regularización antes de cerrar el caso",
        "tokens": ("pago realizado", "pago efectuado", "fueron pagadas", "fue pagada", "deuda saldada", "situacion regularizada"),
    },
)

STOPWORDS = {
    "de", "la", "el", "los", "las", "del", "y", "en", "para", "por", "con", "a", "al",
    "un", "una", "que", "se", "su", "sus", "organismo", "publico", "publica", "hospital",
    "municipalidad", "servicio", "direccion", "departamento",
}


def _fold(value):
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _tokens(value):
    return {token for token in _fold(value).split() if len(token) > 2 and token not in STOPWORDS}


def _jaccard(left, right):
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _case_company(case):
    return normalize_company_name(case.get("company_name") or case.get("detected_company_name"))


def _case_problems(case):
    return {str(item.get("type") or "") for item in case.get("problems", []) if item.get("type")}


def _largest_amount(case):
    values = [int(value or 0) for value in case.get("amounts_clp", [])]
    return max(values, default=0)


def _amount_similarity(a, b):
    if not a or not b:
        return 0.0
    ratio = max(a, b) / max(1, min(a, b))
    if ratio <= 2:
        return 1.0
    if ratio <= 5:
        return 0.5
    return 0.0


def _similarity(target, precedent):
    target_problems = _case_problems(target)
    precedent_problems = _case_problems(precedent)
    problem_score = _jaccard(target_problems, precedent_problems)
    blocker_score = 1.0 if target.get("current_blocker") and target.get("current_blocker") == precedent.get("current_blocker") else 0.0
    agency_score = _jaccard(_tokens(target.get("agency")), _tokens(precedent.get("agency")))
    company_score = 1.0 if _case_company(target) and _case_company(target) == _case_company(precedent) else 0.0
    amount_score = _amount_similarity(_largest_amount(target), _largest_amount(precedent))
    source_score = 1.0 if target.get("source") and target.get("source") == precedent.get("source") else 0.0

    score = (
        0.42 * problem_score
        + 0.18 * blocker_score
        + 0.14 * agency_score
        + 0.14 * company_score
        + 0.07 * amount_score
        + 0.05 * source_score
    )
    matched = []
    if target_problems & precedent_problems:
        matched.append("problemas similares")
    if blocker_score:
        matched.append("mismo bloqueo")
    if agency_score >= 0.25:
        matched.append("organismo/sector parecido")
    if company_score:
        matched.append("misma empresa")
    if amount_score:
        matched.append("magnitud comparable")
    return round(score, 4), matched


def _precedent_text(case):
    parts = [case.get("raw_text") or "", case.get("detail_text") or ""]
    for event in case.get("timeline", []):
        parts.append(event.get("title") or "")
        parts.append(event.get("details") or "")
    for action in case.get("actions", []):
        parts.append(action.get("title") or "")
        parts.append(action.get("note") or "")
    return _fold("\n".join(parts))


def _pathways(case):
    text = _precedent_text(case)
    found = []

    # Completed actions are stronger evidence than text co-occurrence.
    for action in case.get("actions", []):
        if action.get("status") != "DONE":
            continue
        action_type = str(action.get("action_type") or "").strip()
        if not action_type:
            continue
        found.append({
            "action_type": action_type,
            "title": action.get("title") or action_type,
            "basis": "completed_action",
            "strength": 1.0,
            "evidence": action.get("title") or action_type,
        })

    for pathway in PATHWAYS:
        matched = [token for token in pathway["tokens"] if _fold(token) in text]
        if not matched:
            continue
        found.append({
            "action_type": pathway["action_type"],
            "title": pathway["title"],
            "basis": "public_text_signal",
            "strength": min(0.8, 0.45 + 0.1 * len(matched)),
            "evidence": ", ".join(matched[:4]),
        })

    # Deduplicate by action type, keeping the strongest basis.
    best = {}
    for item in found:
        current = best.get(item["action_type"])
        if current is None or item["strength"] > current["strength"]:
            best[item["action_type"]] = item
    return list(best.values())


def _resolved_cases(case_id, db_path=None):
    items = []
    for row in list_cases(status="RESOLVED", db_path=db_path):
        if int(row["id"]) == int(case_id):
            continue
        items.append(get_case(int(row["id"]), db_path))
    return items


def resolution_recommendation(case_id, db_path=None, limit=5, min_similarity=0.12):
    target = get_case(case_id, db_path)
    if target.get("status") == "RESOLVED":
        return {
            "case_id": int(case_id),
            "status": "CASE_ALREADY_RESOLVED",
            "recommendation": None,
            "precedents": [],
            "generated_at": utc_now(),
        }

    precedents = []
    for precedent in _resolved_cases(case_id, db_path):
        similarity, matched = _similarity(target, precedent)
        if similarity < float(min_similarity):
            continue
        pathways = _pathways(precedent)
        if not pathways:
            continue
        precedents.append({
            "case_id": int(precedent["id"]),
            "similarity": similarity,
            "company": precedent.get("company_name") or precedent.get("detected_company_name"),
            "agency": precedent.get("agency"),
            "event_date": precedent.get("event_date"),
            "source_url": precedent.get("detail_url") or precedent.get("source_url"),
            "matched_features": matched,
            "pathways": pathways,
        })

    precedents.sort(key=lambda item: item["similarity"], reverse=True)
    precedents = precedents[:max(1, min(20, int(limit)))]

    if not precedents:
        return {
            "case_id": int(case_id),
            "status": "INSUFFICIENT_PRECEDENTS",
            "recommendation": None,
            "precedents": [],
            "generated_at": utc_now(),
            "causality_notice": "No hay suficientes precedentes resueltos comparables para recomendar una acción basada en evidencia histórica.",
        }

    support = defaultdict(float)
    titles = {}
    basis_strength = defaultdict(float)
    supporters = defaultdict(set)
    evidence = defaultdict(list)
    for precedent in precedents:
        for pathway in precedent["pathways"]:
            action_type = pathway["action_type"]
            weight = precedent["similarity"] * pathway["strength"]
            support[action_type] += weight
            basis_strength[action_type] = max(basis_strength[action_type], pathway["strength"])
            titles[action_type] = pathway["title"]
            supporters[action_type].add(precedent["case_id"])
            evidence[action_type].append({
                "case_id": precedent["case_id"],
                "basis": pathway["basis"],
                "evidence": pathway["evidence"],
                "source_url": precedent["source_url"],
            })

    ranked = sorted(support, key=lambda action: (support[action], len(supporters[action])), reverse=True)
    best = ranked[0]
    top_support = support[best]
    precedent_count = len(supporters[best])
    average_similarity = sum(
        item["similarity"] for item in precedents if item["case_id"] in supporters[best]
    ) / max(1, precedent_count)

    confidence = 30 + 42 * min(1.0, average_similarity) + 8 * min(3, precedent_count)
    if basis_strength[best] >= 1.0:
        confidence += 10
    else:
        confidence = min(confidence, 82)
    confidence = int(max(0, min(95, round(confidence))))

    alternatives = []
    for action_type in ranked[1:4]:
        alternatives.append({
            "action_type": action_type,
            "title": titles[action_type],
            "support_score": round(support[action_type], 3),
            "precedent_count": len(supporters[action_type]),
        })

    recommendation = {
        "action_type": best,
        "title": titles[best],
        "confidence": confidence,
        "support_score": round(top_support, 3),
        "precedent_count": precedent_count,
        "rationale": (
            f"La acción aparece en {precedent_count} precedente(s) resuelto(s) comparable(s). "
            f"La similitud media ponderada es {average_similarity:.0%}."
        ),
        "evidence": evidence[best][:5],
    }
    return {
        "case_id": int(case_id),
        "status": "READY",
        "recommendation": recommendation,
        "alternatives": alternatives,
        "precedents": precedents,
        "generated_at": utc_now(),
        "causality_notice": (
            "La recomendación identifica patrones observados en precedentes resueltos. "
            "No demuestra que una acción haya causado por sí sola la resolución."
        ),
    }


def apply_resolution_recommendation(case_id, db_path=None, min_confidence=55):
    result = resolution_recommendation(case_id, db_path=db_path)
    recommendation = result.get("recommendation")
    if result.get("status") != "READY" or not recommendation:
        result["materialized"] = False
        return result
    if int(recommendation.get("confidence") or 0) < int(min_confidence):
        result["materialized"] = False
        result["materialization_reason"] = "confidence_below_threshold"
        return result

    action_type = recommendation["action_type"]
    with transaction(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM actions WHERE case_id=? AND action_type=? AND status='TODO' ORDER BY id DESC LIMIT 1",
            (int(case_id), action_type),
        ).fetchone()
    if existing:
        result["materialized"] = False
        result["materialization_reason"] = "equivalent_action_already_open"
        return result

    note = (
        f"Recomendación basada en {recommendation['precedent_count']} precedente(s) resuelto(s). "
        f"Confianza {recommendation['confidence']}%. {result['causality_notice']}"
    )
    action = create_action(
        case_id,
        recommendation["title"],
        action_type=action_type,
        due_date=date.today().isoformat(),
        responsible="Nicolás / Case Hunter",
        note=note,
        db_path=db_path,
    )
    add_timeline_event(
        case_id,
        title=f"Recomendación por precedentes: {action_type}",
        details=note,
        event_type="RESOLUTION_RECOMMENDATION",
        event_date=date.today().isoformat(),
        source_url=(recommendation.get("evidence") or [{}])[0].get("source_url"),
        db_path=db_path,
    )
    result["materialized"] = True
    result["action_id"] = action.get("id")
    return result


def refresh_active_pilot_recommendations(db_path=None, limit=100, min_confidence=55):
    with transaction(db_path) as conn:
        rows = conn.execute(
            """SELECT DISTINCT k.id
               FROM cases k
               JOIN timeline_events te ON te.case_id=k.id AND te.event_type='PILOT_STARTED'
               WHERE k.status NOT IN ('RESOLVED','DISMISSED')
               ORDER BY k.id
               LIMIT ?""",
            (max(1, min(500, int(limit))),),
        ).fetchall()

    results = []
    for row in rows:
        try:
            results.append(apply_resolution_recommendation(
                int(row["id"]), db_path=db_path, min_confidence=min_confidence
            ))
        except Exception as exc:
            results.append({"case_id": int(row["id"]), "status": "ERROR", "error": str(exc)[:1000], "materialized": False})
    return {
        "active_pilots": len(rows),
        "ready": sum(item.get("status") == "READY" for item in results),
        "materialized": sum(bool(item.get("materialized")) for item in results),
        "results": results,
    }
