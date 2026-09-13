import os

from .commercial_lifecycle import get_commercial_opportunity
from .repository import get_case


DEFAULT_PILOT_PRICE_CLP = max(0, int(os.getenv("CASE_HUNTER_PILOT_PRICE_CLP", "0")))
DEFAULT_MONTHLY_PRICE_CLP = max(0, int(os.getenv("CASE_HUNTER_MONTHLY_PRICE_CLP", "149000")))


def _money_text(value):
    value = int(value or 0)
    if value == 0:
        return "sin costo"
    return f"${value:,.0f} CLP".replace(",", ".")


def generate_pilot_proposal(case_id, cases_limit=5, pilot_days=30, price_clp=None, db_path=None):
    case = get_case(int(case_id), db_path)
    commercial = get_commercial_opportunity(case_id, db_path)
    cases_limit = max(1, min(20, int(cases_limit)))
    pilot_days = max(7, min(90, int(pilot_days)))
    pilot_price = DEFAULT_PILOT_PRICE_CLP if price_clp is None else max(0, int(price_clp))
    monthly_price = commercial.get("monthly_price_clp")
    if monthly_price is None:
        monthly_price = DEFAULT_MONTHLY_PRICE_CLP

    company = case.get("company_name") or case.get("detected_company_name") or "Empresa por confirmar"
    context = " · ".join(item for item in [case.get("agency"), case.get("contract_ref")] if item)
    body = (
        f"Propuesta de piloto Case Hunter\n\n"
        f"Empresa: {company}\n"
        f"Contexto inicial: {context or 'caso público en validación'}\n\n"
        f"Objetivo\n"
        f"Validar durante {pilot_days} días si Case Hunter reduce el trabajo manual necesario para seguir casos administrativos o financieros vinculados a organismos públicos.\n\n"
        f"Alcance\n"
        f"- Hasta {cases_limit} casos priorizados.\n"
        f"- Ficha inicial de una página por caso con cronología y fuentes públicas.\n"
        f"- Separación entre hechos confirmados y puntos que requieren validación de la empresa.\n"
        f"- Monitoreo de cambios públicos materiales.\n"
        f"- Alertas cuando exista una novedad accionable.\n"
        f"- Próxima gestión sugerida y reporte de seguimiento.\n\n"
        f"Regla de evidencia\n"
        f"Case Hunter no afirma que una situación histórica siga pendiente sin evidencia actual y no representa al organismo público.\n\n"
        f"Precio piloto\n{_money_text(pilot_price)}.\n\n"
        f"Continuidad sugerida\n{_money_text(monthly_price)}/mes, ajustable según cantidad de casos y frecuencia de seguimiento.\n\n"
        f"Criterio de éxito\n"
        f"El piloto se considera útil si permite detectar cambios relevantes, ordenar evidencia y reducir tiempo manual de seguimiento en al menos uno de los casos incluidos."
    )
    return {
        "case_id": int(case_id),
        "company_name": company,
        "commercial_status": commercial.get("status") or "OPEN",
        "cases_limit": cases_limit,
        "pilot_days": pilot_days,
        "pilot_price_clp": pilot_price,
        "monthly_price_clp": monthly_price,
        "title": f"Propuesta de piloto Case Hunter para {company}",
        "body": body,
    }
