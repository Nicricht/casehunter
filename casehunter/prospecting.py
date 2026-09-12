from .contact_discovery import discover_contacts_for_case, list_contacts
from .outreach import build_outreach_email, ensure_outreach_draft, list_outreach
from .repository import get_case


TRUSTED_CONTACT_DECISIONS = {"AUTO_SEND"}


def _dedupe_sources(case):
    sources = []
    seen = set()

    def add(url, title, event_date=None, kind="PUBLIC_SOURCE"):
        value = (url or "").strip()
        if not value or value in seen:
            return
        seen.add(value)
        sources.append({
            "url": value,
            "title": title,
            "event_date": event_date,
            "kind": kind,
        })

    add(case.get("detail_url"), "Detalle público del caso", case.get("event_date"), "PRIMARY")
    add(case.get("source_url"), "Fuente pública de origen", case.get("event_date"), "PRIMARY")
    for event in case.get("timeline", []):
        add(
            event.get("source_url"),
            event.get("title") or "Antecedente público",
            event.get("event_date"),
            event.get("event_type") or "TIMELINE",
        )
    return sources[:8]


def _confirmed_facts(case):
    facts = []

    def add(label, value):
        if value not in (None, "", [], {}):
            facts.append({"label": label, "value": value})

    company = case.get("company_name") or case.get("detected_company_name")
    add("Empresa detectada", company)
    add("Contrato / referencia", case.get("contract_ref") or case.get("external_id"))
    add("Organismo público", case.get("agency"))
    add("Fecha del antecedente", case.get("event_date"))
    if case.get("amounts_clp"):
        add("Mayor monto mencionado en antecedentes públicos", max(int(v or 0) for v in case["amounts_clp"]))
    problem_types = [item.get("type") for item in case.get("problems", []) if item.get("type")]
    add("Señales detectadas", problem_types)
    blocker = case.get("current_blocker")
    if blocker and blocker != "UNKNOWN_BLOCKER":
        add("Bloqueo operativo registrado", blocker)
    add("Confianza de evidencia", case.get("confidence_label"))
    return facts


def _pending_validation(case, contacts, evidence_sources):
    pending = []
    if not case.get("company_id") or not case.get("company_rut"):
        pending.append("Validar razón social/RUT con la empresa antes de tratar el caso como identidad confirmada.")
    if not evidence_sources:
        pending.append("Vincular una fuente pública primaria verificable al caso.")
    if not case.get("current_blocker") or case.get("current_blocker") == "UNKNOWN_BLOCKER":
        pending.append("Confirmar con la empresa cuál es el bloqueo administrativo o financiero actual.")
    missing_docs = [
        item.get("name")
        for item in case.get("documents", [])
        if item.get("required") and item.get("status") != "PRESENT" and item.get("name")
    ]
    if missing_docs:
        pending.append("Validar documentación pendiente: " + ", ".join(missing_docs[:5]) + ".")
    trusted = [
        item for item in contacts
        if item.get("status") != "REJECTED" and item.get("trust_decision") in TRUSTED_CONTACT_DECISIONS
    ]
    if not trusted:
        pending.append("Encontrar o validar un contacto corporativo con evidencia suficiente antes de aprobar el primer correo.")
    return pending


def _case_outreach(case_id, db_path=None):
    messages = [item for item in list_outreach(db_path=db_path) if int(item.get("case_id") or 0) == int(case_id)]
    if not messages:
        return None
    priority = {
        "READY_FOR_APPROVAL": 0,
        "APPROVED": 1,
        "NEEDS_CONTACT": 2,
        "SENT": 3,
        "REPLIED": 4,
        "FAILED": 5,
        "REJECTED": 6,
        "SKIPPED_DUPLICATE": 7,
    }
    messages.sort(key=lambda item: (priority.get(item.get("status"), 99), -int(item.get("id") or 0)))
    return messages[0]


def build_prospect_dossier(case_id, db_path=None):
    """Build a one-page commercial dossier from facts already stored by Case Hunter.

    The dossier is evidence-grounded and intentionally separates public facts from
    items that still require validation. It never approves or sends outreach.
    """
    case = get_case(case_id, db_path)
    contacts = list_contacts(case_id=case_id, db_path=db_path)
    active_contacts = [item for item in contacts if item.get("status") != "REJECTED"]
    trusted_contacts = [item for item in active_contacts if item.get("trust_decision") in TRUSTED_CONTACT_DECISIONS]
    best_contact = trusted_contacts[0] if trusted_contacts else (active_contacts[0] if active_contacts else None)
    existing = _case_outreach(case_id, db_path)
    recommended = build_outreach_email(case)
    sources = _dedupe_sources(case)
    confirmed = _confirmed_facts(case)
    pending = _pending_validation(case, contacts, sources)

    if existing:
        message = {
            "id": existing.get("id"),
            "status": existing.get("status"),
            "recipient_email": existing.get("recipient_email"),
            "subject": existing.get("subject"),
            "body": existing.get("body"),
        }
    else:
        message = {
            "id": None,
            "status": "NOT_PREPARED",
            "recipient_email": best_contact.get("email") if best_contact and best_contact.get("trust_decision") in TRUSTED_CONTACT_DECISIONS else None,
            "subject": recommended["subject"],
            "body": recommended["body"],
        }

    company = case.get("company_name") or case.get("detected_company_name") or "Empresa por confirmar"
    return {
        "case_id": int(case_id),
        "company": company,
        "contract_ref": case.get("contract_ref") or case.get("external_id"),
        "agency": case.get("agency"),
        "case_status": case.get("status"),
        "financial_priority": int(case.get("financial_priority") or 0),
        "confirmed_facts": confirmed,
        "pending_validation": pending,
        "evidence_sources": sources,
        "best_contact": best_contact,
        "trusted_contact_found": bool(trusted_contacts),
        "recommended_message": message,
        "ready_for_review": message.get("status") == "READY_FOR_APPROVAL",
        "requires_human_approval": True,
        "automatic_send_allowed": False,
        "evidence_notice": "Síntesis operativa de antecedentes públicos. No acredita por sí sola deuda, pago pendiente ni responsabilidad de una contraparte.",
    }


def prepare_prospect(case_id, db_path=None, discover_contacts=True):
    """Prepare a prospect dossier and a reviewable outreach draft without sending."""
    discovery = None
    if discover_contacts:
        discovery = discover_contacts_for_case(case_id, db_path=db_path, search_web=True)

    contacts = list_contacts(case_id=case_id, db_path=db_path)
    trusted = [
        item for item in contacts
        if item.get("status") != "REJECTED" and item.get("trust_decision") in TRUSTED_CONTACT_DECISIONS
    ]
    selected = trusted[0] if trusted else None
    if selected:
        draft_result = ensure_outreach_draft(
            case_id,
            recipient_email=selected.get("email"),
            contact_id=selected.get("id"),
            db_path=db_path,
        )
    else:
        draft_result = ensure_outreach_draft(case_id, db_path=db_path)

    dossier = build_prospect_dossier(case_id, db_path=db_path)
    return {
        "dossier": dossier,
        "preparation": {
            "contact_discovery_performed": bool(discover_contacts),
            "contacts_found": len(contacts),
            "trusted_contact_selected": selected,
            "draft_created": bool(draft_result.get("created")),
            "draft": draft_result.get("message"),
            "requires_human_approval": True,
            "sent": False,
        },
        "discovery": discovery,
    }
