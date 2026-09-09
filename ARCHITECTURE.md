# Arquitectura objetivo de Case Hunter 3

## Objetivo

Case Hunter debe operar como una plataforma de inteligencia y resolución de oportunidades administrativas, no como un simple enviador de correos.

La unidad central del sistema es el **caso**. Cada caso conserva trazabilidad desde la señal pública hasta el resultado final.

```text
FUENTES PÚBLICAS
      ↓
HUNTER ENGINE
      ↓
ENTITY / CASE RESOLUTION
      ↓
EVIDENCE + PRIORITY
      ↓
CONTACT TRUST ENGINE
      ↓
OUTREACH POLICY ENGINE
      ↓
EMAIL / FOLLOW-UP
      ↓
REPLY INTELLIGENCE
      ↓
RESOLUTION WORKFLOW
      ↓
OUTCOME
```

## 1. Hunter Engine

Responsabilidad:

- recorrer fuentes públicas;
- extraer empresa, contrato, SAFI, organismo, fechas y montos;
- detectar señales de retención, pago, liquidación, garantía u otros bloqueos;
- generar candidatos sin afirmar que una señal equivale a dinero recuperable.

Implementación actual:

- `casehunter/discovery/`
- `casehunter/scanner_service.py`
- `casehunter/mercado_publico.py`

## 2. Entity / Case Resolution

Responsabilidad:

- evitar duplicados;
- relacionar señales con empresa, RUT y contrato;
- mantener una cronología única por caso;
- permitir que múltiples señales públicas refuercen un mismo caso.

Implementación actual:

- `casehunter/repository.py`
- tablas `companies`, `cases`, `case_problems`, `case_amounts`, `timeline_events`.

Evolución prevista:

- normalización más robusta de razón social;
- RUT como identificador principal cuando esté disponible;
- resolución de alias y grupos empresariales;
- lineage de cada dato hasta su fuente.

## 3. Evidence / Priority Engine

Responsabilidad:

- separar hechos confirmados, inferencias y datos que requieren validación;
- priorizar oportunidades por impacto financiero, tipo de problema, actualidad y confianza;
- evitar convertir valor nominal de una garantía o retención en una promesa de recuperación.

Implementación actual:

- `casehunter/financial.py`
- `casehunter/blocker_engine.py`
- información de procedencia en casos y montos.

## 4. Contact Trust Engine

Archivo:

- `casehunter/engines/contact_trust.py`

Responsabilidad:

- determinar si un correo tiene suficiente evidencia de pertenencia a la empresa;
- puntuar la relación empresa ↔ fuente ↔ correo;
- permitir correos Gmail/Outlook o dominios externos cuando una fuente vinculada a la empresa los publica;
- impedir que una coincidencia encontrada únicamente en un buscador se transforme en autoenvío.

Decisiones:

```text
AUTO_SEND
REVIEW
REJECT
```

Persistencia:

- tabla `contact_assessments`.

## 5. Outreach Policy Engine

Archivo:

- `casehunter/engines/outreach_policy.py`

Responsabilidad:

- decidir si Case Hunter puede enviar el primer contacto sin intervención humana;
- aplicar umbral de prioridad;
- aplicar Trust Score;
- respetar límite diario;
- impedir envío de contactos rechazados.

La política nunca sustituye la deduplicación de Gmail. Ambas capas deben aprobar el envío.

```text
POLÍTICA APRUEBA
      +
GMAIL NO ENCUENTRA CONTACTO PREVIO
      ↓
ENVÍO
```

## 6. Email Gateway

Responsabilidad:

- entregar mensajes mediante SMTP;
- consultar Gmail mediante IMAP;
- detectar destinatarios ya contactados;
- conservar Message-ID para relacionar respuestas;
- no exponer credenciales a tests.

Implementación actual:

- `casehunter/gmail_service.py`
- `casehunter/outreach.py`
- GitHub Actions Secrets.

Evolución prevista:

- Gmail API OAuth en lugar de contraseña de aplicación para una operación multiusuario o comercial a escala.

## 7. Reply Intelligence Engine

Archivo:

- `casehunter/engines/reply_intelligence.py`

Responsabilidad:

- clasificar respuesta;
- expresar confianza de clasificación;
- recomendar nuevo estado del caso;
- generar siguiente acción;
- detener outreach cuando corresponda.

Las respuestas ambiguas deben terminar en `REVIEW_REPLY`, no en una acción irreversible.

## 8. Resolution Workflow

Responsabilidad:

- identificar el bloqueo actual;
- ejecutar Resolution Playbook;
- crear acciones, responsables y plazos;
- seguir al proveedor y organismo;
- cerrar el caso con una condición verificable.

Implementación actual:

- `casehunter/resolution_playbook.py`
- `casehunter/repository.py`
- `casehunter/followup.py`

## 9. Operations / Business Intelligence

Archivo:

- `casehunter/operations.py`

Endpoint:

```text
GET /api/operations
```

KPIs prioritarios:

```text
casos activos
casos resueltos
contactos aptos para autoenvío
primeros contactos enviados
respuestas recibidas
tasa de respuesta
acciones abiertas
follow-ups pendientes
tasa de resolución
```

La cantidad de correos enviados es una métrica secundaria.

## Arquitectura de ejecución actual

```text
GitHub Actions
      ↓ cada 6 h
Case Hunter Auto
      ↓
SQLite restaurado desde cache
      ↓
fuentes públicas + Gmail
      ↓
run summary
```

Ventajas:

- costo operativo muy bajo para validar;
- ejecución independiente del PC del operador;
- CI y producción comparten repo y versión.

Limitaciones:

- GitHub Actions no es un servidor de aplicaciones permanente;
- SQLite + cache no es la base ideal para concurrencia ni crecimiento;
- la interfaz web no está alojada permanentemente por este workflow.

## Arquitectura de producción futura

Cuando el volumen o la validación comercial lo justifiquen:

```text
                 ┌──────────────────┐
                 │ FastAPI / Web UI │
                 └────────┬─────────┘
                          │
                 ┌────────▼─────────┐
                 │    PostgreSQL    │
                 └────────┬─────────┘
                          │
            ┌─────────────┴─────────────┐
            │                           │
     ┌──────▼──────┐             ┌──────▼──────┐
     │ Hunt Worker │             │ Mail Worker │
     └──────┬──────┘             └──────┬──────┘
            │                           │
      fuentes públicas              Gmail API
```

Componentes recomendados:

- PostgreSQL persistente;
- API FastAPI siempre disponible;
- worker programado para hunting;
- worker de correo/respuestas;
- scheduler/queue;
- backups;
- observabilidad;
- secretos administrados por la plataforma.

## Regla de migración

No crear infraestructura de pago solo por anticipación.

La migración a PostgreSQL/worker permanente debe activarse cuando ocurra al menos una de estas condiciones:

1. Case Hunter consiga validación comercial real y necesite operación continua;
2. SQLite/cache genere pérdida o conflicto de estado;
3. haya más de un operador o cliente utilizando el sistema;
4. se requiera interfaz web 24/7;
5. la frecuencia de seis horas sea insuficiente.

Hasta entonces, la arquitectura cloud actual funciona como una etapa de validación con costo bajo.

## Principios no negociables

1. Toda afirmación importante conserva fuente o procedencia.
2. Una señal pública no equivale automáticamente a una deuda exigible o dinero recuperable.
3. No se inventan contactos.
4. El autoenvío exige política + deduplicación.
5. Respuestas ambiguas no producen decisiones irreversibles.
6. Los secretos nunca entran al repositorio ni a los tests.
7. La métrica final es el resultado del caso, no el volumen de mensajes.
