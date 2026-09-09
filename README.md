# Case Hunter Auto v2.3.0

**Repositorio oficial:** `Nicricht/casehunter`

Sistema para detectar, priorizar y gestionar casos administrativos de proveedores del Estado a partir de fuentes públicas, con prospección, seguimiento y monitoreo de respuestas.

## Flujo completo

```text
Fuentes públicas
→ detectar caso
→ deduplicar
→ priorizar
→ buscar contacto público
→ generar correo
→ aprobación humana del primer contacto
→ envío
→ verificar duplicados en Gmail
→ programar follow-up
→ leer respuestas por IMAP
→ clasificar respuesta
→ actualizar caso
→ crear siguiente acción
→ cancelar follow-up si hubo respuesta
→ continuar hasta cierre
```

## Funcionalidades principales

- Descubrimiento desde Ley del Lobby.
- Integración opcional con Mercado Público por RUT mediante ticket oficial.
- Extracción de SAFI, montos y señales contractuales.
- Deduplicación de casos.
- Diagnóstico de bloqueos.
- Resolution Playbook por tipo de bloqueo.
- Checklist documental.
- Acciones, responsables y fechas de seguimiento.
- Línea de tiempo por caso.
- Priorización financiera con advertencia sobre montos no confirmados.
- Descubrimiento de contactos públicos con filtros de seguridad.
- Generación de primer correo personalizado.
- Aprobación humana obligatoria antes del primer envío.
- Detección de contactos ya utilizados mediante Gmail/IMAP antes del envío.
- Envío autenticado por Gmail/SMTP.
- Monitoreo automático de respuestas por Gmail/IMAP.
- Clasificación automática de respuestas: `POSITIVE`, `REQUESTS_INFO`, `STILL_PENDING`, `RESOLVED`, `NOT_INTERESTED`, `NEGATIVE`, `OTHER`.
- Creación automática de la siguiente acción según la respuesta.
- Follow-up programado después del primer envío y cancelado automáticamente cuando llega una respuesta.
- Ejecución cloud cada 6 horas mediante GitHub Actions.
- Persistencia SQLite.
- API FastAPI y frontend web.
- Autenticación Basic opcional.
- Tests automatizados en GitHub Actions.

## Inicio rápido

```bash
python -m pip install -r requirements.txt
python -m casehunter init
python -m casehunter serve
```

Abre `http://127.0.0.1:8000`.

## Comandos

```bash
python -m casehunter auto
python -m casehunter auto --daemon --interval-minutes 360
python -m casehunter mail-sync
python -m casehunter followups
python -m casehunter followups --send
python -m casehunter verify
```

## Gmail

Case Hunter usa SMTP para enviar e IMAP para verificar duplicados y leer respuestas.

Nunca guardes una contraseña normal de Gmail en el repositorio. Usa una contraseña de aplicación y variables de entorno o GitHub Actions Secrets.

Variables relevantes:

```text
CASE_HUNTER_SMTP_USERNAME
CASE_HUNTER_SMTP_PASSWORD
CASE_HUNTER_IMAP_USERNAME
CASE_HUNTER_IMAP_PASSWORD
```

En GitHub Actions el workflow espera estos secretos:

```text
CASE_HUNTER_GMAIL_USERNAME
CASE_HUNTER_GMAIL_APP_PASSWORD
```

Si esos secretos no existen, Case Hunter sigue detectando casos y preparando prospectos, pero no envía ni lee Gmail.

## Seguridad del outreach

- El primer contacto nunca se envía sin aprobación humana previa.
- Antes de enviar, si Gmail está configurado, Case Hunter comprueba si ese destinatario ya fue contactado.
- Si detecta un contacto previo, el mensaje queda `SKIPPED_DUPLICATE`.
- Los contactos de fuentes bloqueadas o buscadores no confiables se rechazan automáticamente.
- Solo contactos con confianza `HIGH` pasan directamente a `READY_FOR_APPROVAL`.
- Los montos públicos no se presentan como dinero recuperable.

## Respuestas y siguiente acción

Ejemplos:

```text
"Sí, envíamela"
→ REQUESTS_INFO
→ caso VALIDATING
→ acción SEND_PUBLIC_SUMMARY

"Sigue pendiente"
→ STILL_PENDING
→ caso VALIDATING
→ acción CONFIRM_CURRENT_BLOCKER

"Ya está resuelto"
→ RESOLVED
→ caso RESOLVED
→ follow-up cancelado

"No nos interesa"
→ NOT_INTERESTED
→ acción NO_FURTHER_OUTREACH
→ follow-up cancelado
```

Por privacidad, el modo cloud no persiste por defecto el cuerpo ni el asunto de las respuestas recibidas. Solo conserva los metadatos mínimos y la clasificación. Esto se controla con:

```text
CASE_HUNTER_STORE_REPLY_CONTENT=0
```

## Follow-up

Después de un primer mensaje enviado y previamente aprobado, Case Hunter programa un seguimiento. El plazo predeterminado es 5 días:

```text
CASE_HUNTER_AUTO_FOLLOWUP_DAYS=5
```

Si llega una respuesta antes, el seguimiento se cancela. En cloud el envío automático de follow-ups está preparado y solo se activa de forma efectiva cuando las credenciales SMTP existen.

## Cloud 24/7

El workflow está en:

```text
.github/workflows/case-hunter-auto.yml
```

Se ejecuta aproximadamente cada 6 horas y mantiene el estado entre ciclos mediante GitHub Actions cache. El artifact público de cada ejecución contiene únicamente el resumen JSON del ciclo, no la base SQLite.

## Resolution Playbook

Cuando el bloqueo cambia por información confirmada de la empresa, el caso puede reclasificarse. Por ejemplo, una liquidación pendiente puede convertirse en `DOCUMENT_MISSING` si el proveedor confirma que faltan antecedentes.

Cada playbook contiene preguntas de confirmación, acciones ordenadas, responsable sugerido, plazo operativo, evidencia esperada, escalamiento y condiciones de cierre.

Las recomendaciones deben contrastarse con las bases, el contrato y el expediente aplicable a cada caso.

## Pruebas

```bash
python -m casehunter verify
```

La suite cubre API, detector, casos públicos de regresión 2026, Mercado Público, repository, playbooks, outreach, seguridad de contactos, respuestas, follow-ups y deduplicación de Gmail.
