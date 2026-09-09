from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PlaybookStep:
    code: str
    title: str
    responsible: str
    due_days: int | None
    completion_evidence: str


@dataclass(frozen=True)
class ResolutionPlaybook:
    blocker: str
    title: str
    goal: str
    confirmation_questions: tuple[str, ...]
    steps: tuple[PlaybookStep, ...]
    escalation: tuple[str, ...]
    closure_criteria: tuple[str, ...]
    caution: str


COMMON_CAUTION = (
    "Las fuentes públicas permiten detectar señales y orientar la gestión, pero no prueban por sí solas "
    "que exista un monto exigible ni reemplazan la revisión de las bases, el contrato y el expediente del caso."
)


PLAYBOOKS: dict[str, ResolutionPlaybook] = {
    "DOCUMENT_MISSING": ResolutionPlaybook(
        blocker="DOCUMENT_MISSING",
        title="Completar antecedentes faltantes",
        goal="Identificar con precisión el antecedente que impide avanzar, entregarlo por el canal correcto y obtener constancia de recepción.",
        confirmation_questions=(
            "¿Qué documento o antecedente indicó el organismo que falta?",
            "¿La observación consta en un correo, oficio, resolución, minuta o sistema institucional?",
            "¿Quién dentro del organismo puede confirmar que el expediente quedó completo?",
            "¿El documento depende del proveedor, de un tercero o del propio organismo?",
        ),
        steps=(
            PlaybookStep("CONFIRM_MISSING_DOCUMENT", "Confirmar exactamente qué antecedente falta y conservar la evidencia de esa solicitud", "Proveedor", 0, "Nombre del documento y respaldo de la observación"),
            PlaybookStep("OBTAIN_MISSING_DOCUMENT", "Obtener, completar o corregir el antecedente faltante", "Proveedor", 2, "Documento final disponible"),
            PlaybookStep("SUBMIT_MISSING_DOCUMENT", "Enviar el antecedente por el canal formal aplicable al contrato", "Proveedor", 3, "Comprobante de envío o ingreso"),
            PlaybookStep("CONFIRM_FILE_COMPLETE", "Solicitar confirmación de que el expediente quedó completo y sin nuevas observaciones", "Proveedor", 5, "Respuesta del organismo o estado verificable"),
            PlaybookStep("FOLLOW_UP_DOCUMENT", "Hacer seguimiento si no existe respuesta o movimiento del expediente", "Proveedor", 12, "Respuesta, cambio de estado o nueva instrucción"),
        ),
        escalation=(
            "Si no se identifica el documento exacto, solicitar al responsable del expediente que detalle la observación pendiente.",
            "Si el documento fue entregado y no existe movimiento, pedir confirmación de recepción y de la unidad que mantiene el trámite.",
            "Si aparecen requisitos contradictorios, escalar para revisión contractual o jurídica interna antes de insistir.",
        ),
        closure_criteria=(
            "El antecedente faltante quedó identificado.",
            "El antecedente fue entregado o se documentó que no corresponde exigirlo.",
            "Existe confirmación de expediente completo o el trámite avanzó a la siguiente etapa.",
        ),
        caution=COMMON_CAUTION,
    ),
    "AGENCY_APPROVAL_PENDING": ResolutionPlaybook(
        blocker="AGENCY_APPROVAL_PENDING",
        title="Destrabar aprobación interna del organismo",
        goal="Identificar la unidad, firma o acto administrativo pendiente y mantener trazabilidad hasta que la tramitación avance.",
        confirmation_questions=(
            "¿Qué aprobación, firma, visación o resolución está pendiente?",
            "¿Qué unidad tiene actualmente el expediente?",
            "¿Existen observaciones o antecedentes pendientes antes de la aprobación?",
            "¿Hay una fecha de último movimiento verificable?",
        ),
        steps=(
            PlaybookStep("IDENTIFY_APPROVAL_STAGE", "Confirmar la etapa administrativa exacta y la unidad responsable", "Proveedor", 0, "Unidad y etapa registradas"),
            PlaybookStep("VERIFY_NO_OPEN_OBSERVATIONS", "Confirmar que no existan observaciones o documentos pendientes del proveedor", "Proveedor", 1, "Respuesta o expediente revisado"),
            PlaybookStep("REQUEST_FORMAL_STATUS", "Solicitar estado actualizado y próximo hito del trámite", "Proveedor", 2, "Respuesta del organismo"),
            PlaybookStep("FOLLOW_UP_APPROVAL", "Programar seguimiento si la aprobación no presenta movimiento", "Proveedor", 9, "Nuevo estado o respuesta"),
        ),
        escalation=(
            "Si nadie identifica la ubicación del expediente, escalar a la contraparte administrativa del contrato.",
            "Si existen observaciones, convertirlas en tareas concretas y suspender la espera pasiva.",
            "Si el expediente está completo pero permanece inmóvil, documentar los seguimientos y solicitar una definición del siguiente hito.",
        ),
        closure_criteria=(
            "La aprobación, firma o resolución fue emitida, o",
            "el expediente avanzó formalmente a una etapa posterior claramente identificada.",
        ),
        caution=COMMON_CAUTION,
    ),
    "LIQUIDATION_PENDING": ResolutionPlaybook(
        blocker="LIQUIDATION_PENDING",
        title="Cerrar la liquidación contractual",
        goal="Determinar la etapa real de la liquidación, completar requisitos pendientes y llevar el expediente hasta un acto de cierre verificable.",
        confirmation_questions=(
            "¿Existe recepción final o hito equivalente?",
            "¿La liquidación fue preparada, observada, firmada o todavía no iniciada?",
            "¿Existen saldos, multas, retenciones, garantías u observaciones pendientes?",
            "¿Qué acto o documento acredita el cierre definitivo según el contrato?",
        ),
        steps=(
            PlaybookStep("VERIFY_FINAL_ACCEPTANCE", "Verificar recepción final y requisitos previos al cierre", "Proveedor", 0, "Acta, certificado o hito equivalente"),
            PlaybookStep("LOCATE_LIQUIDATION_STAGE", "Confirmar la etapa actual del expediente de liquidación", "Proveedor", 1, "Etapa y responsable registrados"),
            PlaybookStep("CLEAR_LIQUIDATION_OBSERVATIONS", "Resolver observaciones o requisitos que dependan del proveedor", "Proveedor", 4, "Observaciones cerradas o justificadas"),
            PlaybookStep("REQUEST_LIQUIDATION_ADVANCE", "Solicitar avance, firma o acto de liquidación que corresponda", "Proveedor", 5, "Respuesta o acto administrativo"),
            PlaybookStep("FOLLOW_UP_LIQUIDATION", "Hacer seguimiento hasta obtener cierre o nueva instrucción concreta", "Proveedor", 12, "Liquidación cerrada o siguiente hito documentado"),
        ),
        escalation=(
            "Si la etapa exacta es desconocida, reconstruir la cronología con recepción, liquidación, observaciones y reuniones públicas.",
            "Si el bloqueo corresponde a documentación, aplicar el playbook de antecedentes faltantes.",
            "Si la liquidación está cerrada pero quedan retenciones, garantías o pagos, abrir esos bloqueos como frentes separados.",
        ),
        closure_criteria=(
            "Existe un acto o antecedente verificable de liquidación/cierre, y",
            "las obligaciones posteriores identificadas quedaron cerradas o separadas en casos específicos.",
        ),
        caution=COMMON_CAUTION,
    ),
    "PAYMENT_PENDING": ResolutionPlaybook(
        blocker="PAYMENT_PENDING",
        title="Aclarar y gestionar pago pendiente",
        goal="Ubicar el pago en su etapa administrativa real, corregir dependencias y mantener seguimiento hasta pago o explicación verificable.",
        confirmation_questions=(
            "¿Existe factura o documento de cobro válido?",
            "¿La prestación o recepción conforme está acreditada?",
            "¿El pago está observado, aprobado, contabilizado, ordenado o simplemente no identificado?",
            "¿El monto detectado corresponde realmente a un saldo pendiente o solo a un monto histórico del contrato?",
        ),
        steps=(
            PlaybookStep("VERIFY_PAYMENT_EVIDENCE", "Verificar factura, estado de pago, recepción y monto realmente asociado al caso", "Proveedor", 0, "Documentos de pago revisados"),
            PlaybookStep("LOCATE_PAYMENT_STAGE", "Confirmar la etapa administrativa actual del pago", "Proveedor", 1, "Etapa, unidad y responsable registrados"),
            PlaybookStep("CLEAR_PAYMENT_OBSERVATIONS", "Resolver observaciones documentales o administrativas atribuibles al proveedor", "Proveedor", 3, "Observaciones cerradas"),
            PlaybookStep("REQUEST_PAYMENT_UPDATE", "Solicitar estado actualizado y próximo hito del pago", "Proveedor", 4, "Respuesta del organismo"),
            PlaybookStep("FOLLOW_UP_PAYMENT", "Hacer seguimiento hasta pago, rechazo fundado o nueva acción requerida", "Proveedor", 11, "Pago o respuesta verificable"),
        ),
        escalation=(
            "No presentar un monto público como deuda confirmada sin reconciliarlo con factura, recepción y estado de pago.",
            "Si la recepción está pendiente, resolver primero ese hito.",
            "Si existe controversia contractual, separar la gestión administrativa de cualquier análisis jurídico necesario.",
        ),
        closure_criteria=(
            "El pago fue acreditado, o",
            "se confirmó fundadamente que no existe saldo pendiente, o",
            "se identificó una nueva acción concreta y el caso cambió a su bloqueo correcto.",
        ),
        caution=COMMON_CAUTION,
    ),
    "RETENTION_RELEASE_PENDING": ResolutionPlaybook(
        blocker="RETENTION_RELEASE_PENDING",
        title="Gestionar devolución o canje de retenciones",
        goal="Confirmar si existe una retención vigente, qué condición habilita su liberación y llevar la solicitud hasta una respuesta verificable.",
        confirmation_questions=(
            "¿Existe una retención efectiva y cuál es su monto comprobado?",
            "¿Qué hito contractual habilita su devolución o canje?",
            "¿La solicitud de devolución/canje ya fue presentada?",
            "¿Existen observaciones, recepción final o liquidación pendiente que condicionen la liberación?",
        ),
        steps=(
            PlaybookStep("VERIFY_RETENTION_EXISTS", "Confirmar la existencia, monto y fundamento contractual de la retención", "Proveedor", 0, "Antecedente contractual y monto conciliado"),
            PlaybookStep("VERIFY_RELEASE_CONDITION", "Confirmar el hito que habilita devolución o canje", "Proveedor", 1, "Condición contractual identificada"),
            PlaybookStep("PREPARE_RETENTION_REQUEST", "Reunir antecedentes exigibles para la solicitud", "Proveedor", 3, "Expediente de solicitud completo"),
            PlaybookStep("SUBMIT_RETENTION_REQUEST", "Presentar o actualizar la solicitud de devolución/canje", "Proveedor", 4, "Comprobante de ingreso"),
            PlaybookStep("FOLLOW_UP_RETENTION", "Hacer seguimiento hasta devolución, canje, rechazo fundado o nueva observación", "Proveedor", 11, "Resultado verificable"),
        ),
        escalation=(
            "Si la liberación depende de liquidación o recepción final, priorizar ese bloqueo antes de insistir en la devolución.",
            "Si el monto no puede verificarse, mantenerlo como monto observado y no como dinero recuperable.",
        ),
        closure_criteria=(
            "La retención fue devuelta o canjeada, o",
            "se confirmó que no existe retención pendiente, o",
            "existe una causa documentada que requiere otro playbook.",
        ),
        caution=COMMON_CAUTION,
    ),
    "GUARANTEE_RELEASE_PENDING": ResolutionPlaybook(
        blocker="GUARANTEE_RELEASE_PENDING",
        title="Liberar o cerrar garantía contractual",
        goal="Determinar la condición real de la garantía y evitar renovaciones o capacidad financiera comprometida más tiempo del necesario.",
        confirmation_questions=(
            "¿Qué garantía está vigente y cuál es su fecha de vencimiento?",
            "¿Qué obligación garantiza y qué hito permite su devolución o liberación?",
            "¿La empresa solicitó formalmente su devolución?",
            "¿Existe una observación, liquidación o recepción pendiente que impida liberarla?",
        ),
        steps=(
            PlaybookStep("VERIFY_GUARANTEE", "Verificar instrumento, vigencia, monto nominal y obligación garantizada", "Proveedor", 0, "Garantía y contrato revisados"),
            PlaybookStep("VERIFY_GUARANTEE_RELEASE_CONDITION", "Confirmar el hito contractual para su liberación", "Proveedor", 1, "Condición de liberación identificada"),
            PlaybookStep("REQUEST_GUARANTEE_RELEASE", "Presentar o actualizar la solicitud de devolución/liberación", "Proveedor", 3, "Comprobante de solicitud"),
            PlaybookStep("FOLLOW_UP_GUARANTEE", "Hacer seguimiento antes de una renovación o costo adicional innecesario", "Proveedor", 8, "Respuesta o liberación"),
        ),
        escalation=(
            "No tratar el monto nominal de la garantía como efectivo retenido.",
            "Si existen renovaciones próximas, elevar la prioridad financiera del caso.",
            "Si la liberación depende del cierre contractual, resolver primero el hito que la condiciona.",
        ),
        closure_criteria=(
            "La garantía fue devuelta, liberada o terminó válidamente sin renovación adicional, o",
            "se confirmó que debe permanecer vigente por una obligación contractual todavía abierta.",
        ),
        caution=COMMON_CAUTION,
    ),
    "RECEPTION_PENDING": ResolutionPlaybook(
        blocker="RECEPTION_PENDING",
        title="Completar recepción conforme",
        goal="Acreditar la entrega o prestación, resolver observaciones y obtener el hito de recepción que habilite los pasos posteriores.",
        confirmation_questions=(
            "¿La entrega o prestación fue efectivamente completada?",
            "¿Existe evidencia de entrega y aceptación?",
            "¿Qué observación impide la recepción conforme?",
            "¿La recepción es requisito para facturar o avanzar al pago?",
        ),
        steps=(
            PlaybookStep("VERIFY_DELIVERY_EVIDENCE", "Reunir evidencia de entrega o prestación", "Proveedor", 0, "Guías, actas, informes o respaldo equivalente"),
            PlaybookStep("IDENTIFY_RECEPTION_OBSERVATIONS", "Confirmar observaciones que impiden la recepción", "Proveedor", 1, "Observaciones registradas"),
            PlaybookStep("CLEAR_RECEPTION_OBSERVATIONS", "Corregir observaciones atribuibles al proveedor", "Proveedor", 3, "Correcciones acreditadas"),
            PlaybookStep("REQUEST_RECEPTION_CONFIRMATION", "Solicitar recepción conforme o confirmación de aceptación", "Proveedor", 4, "Acta, certificado o estado verificable"),
            PlaybookStep("VERIFY_POST_RECEPTION", "Verificar facturación y pago después de la recepción", "Proveedor", 6, "Siguiente etapa confirmada"),
        ),
        escalation=(
            "Si la recepción es parcial, identificar exactamente ítems, cantidades o servicios todavía pendientes.",
            "Si la recepción ya ocurrió, cambiar el caso al bloqueo posterior correcto en lugar de mantenerlo como recepción pendiente.",
        ),
        closure_criteria=(
            "Existe recepción conforme o antecedente equivalente, o",
            "se identificó con precisión lo que queda pendiente y se abrió la acción correspondiente.",
        ),
        caution=COMMON_CAUTION,
    ),
    "CONTRACT_MODIFICATION_PENDING": ResolutionPlaybook(
        blocker="CONTRACT_MODIFICATION_PENDING",
        title="Cerrar modificación contractual",
        goal="Determinar la modificación en trámite, sus observaciones y el acto requerido para que produzca efectos administrativos.",
        confirmation_questions=(
            "¿Qué modificación contractual se está tramitando?",
            "¿Qué unidad la revisa y qué aprobación falta?",
            "¿Existen antecedentes técnicos, presupuestarios o administrativos observados?",
        ),
        steps=(
            PlaybookStep("LOCATE_MODIFICATION_STAGE", "Confirmar la etapa y unidad responsable de la modificación", "Proveedor", 0, "Etapa registrada"),
            PlaybookStep("CLEAR_MODIFICATION_OBSERVATIONS", "Resolver observaciones o antecedentes pendientes", "Proveedor", 3, "Observaciones cerradas"),
            PlaybookStep("REQUEST_MODIFICATION_STATUS", "Solicitar estado y próximo hito formal", "Proveedor", 4, "Respuesta del organismo"),
            PlaybookStep("FOLLOW_UP_MODIFICATION", "Hacer seguimiento hasta aprobación, rechazo fundado o nueva acción", "Proveedor", 11, "Resultado verificable"),
        ),
        escalation=(
            "Si la modificación condiciona pago o liquidación, mantener vinculados ambos frentes para evitar seguimientos duplicados.",
        ),
        closure_criteria=(
            "La modificación fue aprobada, rechazada fundadamente o sustituida por una decisión administrativa verificable.",
        ),
        caution=COMMON_CAUTION,
    ),
}


GENERIC = ResolutionPlaybook(
    blocker="UNKNOWN_BLOCKER",
    title="Confirmar causa real del bloqueo",
    goal="Convertir una señal pública ambigua en un bloqueo verificable antes de ejecutar acciones específicas.",
    confirmation_questions=(
        "¿El caso sigue abierto hoy?",
        "¿Cuál fue el último movimiento verificable?",
        "¿Qué persona o unidad conoce el expediente?",
        "¿Qué falta exactamente para avanzar?",
    ),
    steps=(
        PlaybookStep("RECONSTRUCT_TIMELINE", "Reconstruir cronología con fuentes públicas y antecedentes de la empresa", "Proveedor", 0, "Cronología mínima disponible"),
        PlaybookStep("CONFIRM_CURRENT_STATE", "Confirmar con la empresa o el organismo si el caso sigue abierto", "Proveedor", 1, "Estado actual confirmado"),
        PlaybookStep("IDENTIFY_REAL_BLOCKER", "Identificar el bloqueo real y reclasificar el caso", "Proveedor", 2, "Bloqueo específico confirmado"),
    ),
    escalation=(
        "No ejecutar solicitudes específicas mientras el bloqueo siga siendo una inferencia.",
    ),
    closure_criteria=(
        "El caso fue descartado por estar resuelto, o",
        "el bloqueo real fue identificado y el caso pasó al playbook específico correspondiente.",
    ),
    caution=COMMON_CAUTION,
)


def get_playbook(blocker: str | None) -> ResolutionPlaybook:
    return PLAYBOOKS.get(blocker or "", GENERIC)


def _step_dict(step: PlaybookStep) -> dict:
    return {
        "code": step.code,
        "title": step.title,
        "responsible": step.responsible,
        "due_days": step.due_days,
        "completion_evidence": step.completion_evidence,
    }


def build_playbook(
    blocker: str | None,
    problem_types: Iterable[str] = (),
    documents: Iterable[dict] = (),
    actions: Iterable[dict] = (),
) -> dict:
    playbook = get_playbook(blocker)
    docs = list(documents)
    acts = list(actions)

    required_docs = [d for d in docs if int(d.get("required", 1)) == 1]
    unresolved_docs = [d for d in required_docs if d.get("status") in {"UNKNOWN", "MISSING", "REQUESTED"}]
    open_actions = [a for a in acts if a.get("status") == "TODO"]

    next_step = None
    if open_actions:
        next_step = {
            "action_type": open_actions[0].get("action_type"),
            "title": open_actions[0].get("title"),
            "due_date": open_actions[0].get("due_date"),
            "responsible": open_actions[0].get("responsible"),
        }
    elif playbook.steps:
        step = playbook.steps[0]
        next_step = {
            "action_type": step.code,
            "title": step.title,
            "due_date": None,
            "responsible": step.responsible,
        }

    if any(d.get("status") == "MISSING" for d in required_docs):
        recommended_status = "ACTION_REQUIRED"
    elif unresolved_docs:
        recommended_status = "VALIDATING"
    elif open_actions:
        recommended_status = "ACTION_REQUIRED"
    else:
        recommended_status = "WAITING_AGENCY"

    return {
        "blocker": playbook.blocker,
        "title": playbook.title,
        "goal": playbook.goal,
        "problem_types": list(problem_types),
        "confirmation_questions": list(playbook.confirmation_questions),
        "steps": [_step_dict(s) for s in playbook.steps],
        "escalation": list(playbook.escalation),
        "closure_criteria": list(playbook.closure_criteria),
        "caution": playbook.caution,
        "next_step": next_step,
        "recommended_status": recommended_status,
        "required_documents": len(required_docs),
        "unresolved_documents": len(unresolved_docs),
        "open_actions": len(open_actions),
        "ready_for_closure_review": len(unresolved_docs) == 0 and len(open_actions) == 0,
    }


def list_playbooks() -> list[dict]:
    rows = []
    for key, playbook in sorted(PLAYBOOKS.items(), key=lambda item: item[1].title):
        rows.append({"blocker": key, "title": playbook.title, "goal": playbook.goal})
    rows.append({"blocker": "UNKNOWN_BLOCKER", "title": GENERIC.title, "goal": GENERIC.goal})
    return rows
