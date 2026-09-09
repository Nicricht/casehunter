from dataclasses import dataclass


@dataclass(frozen=True)
class BlockerRule:
    blocker: str
    reason: str
    priority: int
    documents: tuple[tuple[str, str], ...]
    actions: tuple[tuple[str, str], ...]


RULES = {
    "DOCUMENT_MISSING": BlockerRule(
        "DOCUMENT_MISSING",
        "El antecedente público contiene señales de documentación o antecedentes faltantes.",
        100,
        (
            ("FINAL_ACCEPTANCE", "Acta o certificado de recepción final"),
            ("SIGNED_LIQUIDATION", "Liquidación firmada o acto equivalente"),
            ("LABOR_TAX_CERTIFICATES", "Certificados laborales y tributarios exigibles"),
            ("SUPPORTING_DOCUMENTS", "Antecedentes de respaldo solicitados por el organismo"),
        ),
        (
            ("VERIFY_DOCUMENTS", "Verificar exactamente qué documento o antecedente falta"),
            ("SUBMIT_DOCUMENTS", "Completar y enviar los antecedentes faltantes"),
            ("REQUEST_RECEIPT", "Solicitar confirmación de recepción al organismo"),
        ),
    ),
    "INTERNAL_APPROVAL_PENDING": BlockerRule(
        "AGENCY_APPROVAL_PENDING",
        "El caso muestra una aprobación, firma, revisión o tramitación administrativa pendiente.",
        90,
        (("PENDING_RESOLUTION", "Resolución, aprobación o firma pendiente"),),
        (
            ("IDENTIFY_UNIT", "Identificar la unidad y responsable de la aprobación"),
            ("REQUEST_STATUS", "Solicitar estado formal de la tramitación"),
            ("FOLLOW_UP", "Programar seguimiento si no existe respuesta"),
        ),
    ),
    "LIQUIDATION_PENDING": BlockerRule(
        "LIQUIDATION_PENDING",
        "El contrato presenta señales de liquidación o cierre administrativo que requiere seguimiento.",
        80,
        (
            ("FINAL_ACCEPTANCE", "Acta o certificado de recepción final"),
            ("LIQUIDATION_DRAFT", "Borrador, resolución o expediente de liquidación"),
            ("SIGNED_LIQUIDATION", "Liquidación firmada o acto equivalente"),
        ),
        (
            ("VERIFY_LIQUIDATION_STAGE", "Confirmar la etapa exacta de la liquidación"),
            ("VERIFY_PENDING_REQUIREMENTS", "Revisar requisitos pendientes para cerrar el contrato"),
            ("REQUEST_CLOSURE", "Solicitar avance o cierre administrativo"),
        ),
    ),
    "PAYMENT_PENDING": BlockerRule(
        "PAYMENT_PENDING",
        "El antecedente contiene señales de pago, estado de pago, factura o saldo que requiere revisión.",
        75,
        (
            ("PAYMENT_STATE", "Estado de pago o documento equivalente"),
            ("INVOICE", "Factura asociada"),
            ("PAYMENT_APPROVAL", "Aprobación u orden de pago"),
        ),
        (
            ("VERIFY_PAYMENT_STAGE", "Confirmar la etapa administrativa del pago"),
            ("VERIFY_INVOICE", "Verificar factura y antecedentes asociados"),
            ("REQUEST_PAYMENT_STATUS", "Solicitar estado formal del pago"),
        ),
    ),
    "RETENTION_PENDING": BlockerRule(
        "RETENTION_RELEASE_PENDING",
        "El antecedente contiene señales relacionadas con devolución, canje o liberación de retenciones.",
        70,
        (
            ("RETENTION_RECORD", "Antecedente contractual de retenciones"),
            ("RETENTION_RELEASE_REQUEST", "Solicitud de devolución o canje de retenciones"),
            ("FINAL_ACCEPTANCE", "Recepción final o hito habilitante"),
        ),
        (
            ("VERIFY_RETENTION_CONDITION", "Confirmar condiciones para liberar o canjear retenciones"),
            ("VERIFY_RELEASE_REQUEST", "Verificar si la solicitud de devolución fue presentada"),
            ("REQUEST_RETENTION_STATUS", "Solicitar estado formal de la devolución o canje"),
        ),
    ),
    "GUARANTEE_PENDING": BlockerRule(
        "GUARANTEE_RELEASE_PENDING",
        "El antecedente contiene señales sobre devolución, renovación o liberación de garantías.",
        65,
        (
            ("GUARANTEE", "Boleta, póliza o garantía asociada"),
            ("GUARANTEE_RELEASE_REQUEST", "Solicitud de devolución o liberación de garantía"),
            ("FINAL_ACCEPTANCE", "Recepción final o hito habilitante"),
        ),
        (
            ("VERIFY_GUARANTEE_STATUS", "Confirmar vigencia y condición actual de la garantía"),
            ("VERIFY_RELEASE_REQUIREMENTS", "Revisar requisitos para su devolución o liberación"),
            ("REQUEST_GUARANTEE_RELEASE", "Solicitar devolución o estado de la garantía"),
        ),
    ),
    "CONTRACT_MODIFICATION_PENDING": BlockerRule(
        "CONTRACT_MODIFICATION_PENDING",
        "El antecedente muestra una modificación contractual pendiente, en revisión o en tramitación.",
        85,
        (
            ("MODIFICATION_FILE", "Expediente de modificación contractual"),
            ("MODIFICATION_APPROVAL", "Resolución o aprobación de la modificación"),
        ),
        (
            ("VERIFY_MODIFICATION_STAGE", "Confirmar la etapa exacta de la modificación contractual"),
            ("IDENTIFY_MODIFICATION_REVIEWER", "Identificar la unidad que revisa o aprueba la modificación"),
            ("REQUEST_MODIFICATION_STATUS", "Solicitar estado formal de la modificación"),
        ),
    ),
    "FINAL_ADJUSTMENT_PENDING": BlockerRule(
        "FINAL_ADJUSTMENT_PENDING",
        "El antecedente muestra un ajuste final pendiente o en tramitación que puede condicionar el cierre o pago.",
        82,
        (
            ("FINAL_ADJUSTMENT_FILE", "Antecedentes del ajuste final"),
            ("FINAL_ADJUSTMENT_APPROVAL", "Aprobación o resolución del ajuste final"),
        ),
        (
            ("VERIFY_FINAL_ADJUSTMENT", "Confirmar la etapa exacta del ajuste final"),
            ("VERIFY_ADJUSTMENT_OBSERVATIONS", "Revisar observaciones o antecedentes pendientes"),
            ("REQUEST_FINAL_ADJUSTMENT_STATUS", "Solicitar estado formal del ajuste final"),
        ),
    ),
    "PURCHASE_ORDER_IN_PROCESS": BlockerRule(
        "PURCHASE_ORDER_IN_PROCESS",
        "La orden de compra aparece en proceso y requiere verificar el hito administrativo pendiente.",
        55,
        (("PURCHASE_ORDER", "Orden de compra"), ("DELIVERY_EVIDENCE", "Antecedente de entrega o prestación")),
        (("VERIFY_ORDER_STAGE", "Confirmar el hito pendiente de la orden de compra"), ("CONTACT_BUYER_UNIT", "Solicitar estado a la unidad compradora")),
    ),
    "RECEPTION_PENDING": BlockerRule(
        "RECEPTION_PENDING",
        "La orden de compra aparece pendiente de recepción, hito que puede condicionar facturación o pago.",
        78,
        (("DELIVERY_EVIDENCE", "Antecedente de entrega o prestación"), ("RECEPTION_CERTIFICATE", "Recepción conforme"), ("INVOICE", "Factura asociada")),
        (("VERIFY_DELIVERY", "Verificar evidencia de entrega o prestación"), ("REQUEST_RECEPTION", "Solicitar recepción conforme"), ("VERIFY_INVOICE_AFTER_RECEPTION", "Verificar facturación y pago después de la recepción")),
    ),
    "RECEPTION_PARTIAL": BlockerRule(
        "RECEPTION_PARTIAL",
        "La orden de compra registra una recepción parcial y requiere determinar qué parte sigue pendiente.",
        76,
        (("DELIVERY_EVIDENCE", "Antecedentes de entrega"), ("PARTIAL_RECEPTION", "Recepción parcial"), ("PENDING_ITEMS", "Detalle de ítems pendientes")),
        (("IDENTIFY_PENDING_ITEMS", "Identificar bienes o servicios pendientes de recepción"), ("COMPLETE_RECEPTION", "Gestionar recepción de lo pendiente")),
    ),
    "RECEPTION_INCOMPLETE": BlockerRule(
        "RECEPTION_INCOMPLETE",
        "La orden de compra registra recepción conforme incompleta y requiere revisar el saldo administrativo pendiente.",
        77,
        (("RECEPTION_CERTIFICATE", "Recepción conforme"), ("PENDING_ITEMS", "Detalle pendiente"), ("INVOICE", "Factura asociada")),
        (("VERIFY_INCOMPLETE_RECEPTION", "Confirmar qué falta para completar la recepción"), ("COMPLETE_RECEPTION", "Completar el hito de recepción"), ("VERIFY_PAYMENT_AFTER_RECEPTION", "Verificar pago posterior a la recepción")),
    ),
    "ADMINISTRATIVE_DISPUTE": BlockerRule(
        "ADMINISTRATIVE_REVIEW",
        "El antecedente contiene una controversia o recurso administrativo que puede condicionar el cierre.",
        60,
        (("ADMINISTRATIVE_RECORD", "Expediente, recurso o pronunciamiento administrativo"),),
        (
            ("IDENTIFY_PROCEEDING", "Identificar el procedimiento administrativo vigente"),
            ("VERIFY_DEADLINES", "Revisar hitos y plazos aplicables"),
            ("REQUEST_PROCEEDING_STATUS", "Solicitar estado del procedimiento"),
        ),
    ),
}

GENERIC = BlockerRule(
    "UNKNOWN_BLOCKER",
    "Existe una señal relevante, pero la información pública no permite identificar el bloqueo con precisión.",
    10,
    (("CASE_FILE", "Expediente y antecedentes del contrato"),),
    (
        ("HUMAN_REVIEW", "Revisar el expediente y confirmar el bloqueo real"),
        ("CONTACT_RESPONSIBLE_UNIT", "Identificar la unidad responsable del trámite"),
    ),
)


def diagnose(problem_types):
    matches = [RULES[p] for p in problem_types if p in RULES]
    if not matches:
        matches = [GENERIC]
    matches.sort(key=lambda rule: rule.priority, reverse=True)
    primary = matches[0]

    documents = []
    actions = []
    seen_docs = set()
    seen_actions = set()
    for rule in matches:
        for code, name in rule.documents:
            if code not in seen_docs:
                seen_docs.add(code)
                documents.append({"code": code, "name": name})
        for action_type, title in rule.actions:
            if action_type not in seen_actions:
                seen_actions.add(action_type)
                actions.append({"action_type": action_type, "title": title})

    return {
        "primary_blocker": primary.blocker,
        "reason": primary.reason,
        "all_blockers": [rule.blocker for rule in matches],
        "documents": documents,
        "actions": actions,
    }
