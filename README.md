# Case Hunter Auto v3.0.0

**Repositorio oficial:** `Nicricht/casehunter`

Case Hunter detecta, prioriza y gestiona oportunidades administrativas de proveedores del Estado a partir de fuentes públicas. Su objetivo no es maximizar correos enviados, sino convertir señales públicas en casos validados, conversaciones útiles, bloqueos identificados y resultados medibles.

## Flujo operativo

```text
Fuentes públicas
→ Hunter / Scanner
→ detectar y deduplicar caso
→ priorizar oportunidad
→ descubrir contactos públicos
→ Contact Trust Engine
→ Outreach Policy Engine
→ enviar automáticamente cuando la evidencia supera la política
→ comprobar duplicados en Gmail
→ programar follow-up
→ leer respuestas por IMAP
→ Reply Intelligence Engine
→ actualizar caso y crear siguiente acción
→ continuar hasta cierre
→ medir respuesta y resolución
```

## Motores de decisión

### Contact Trust Engine

`casehunter/engines/contact_trust.py`

Evalúa la evidencia de identidad del contacto. La igualdad de dominio es una señal fuerte, pero ya no es obligatoria.

Ejemplos:

```text
contacto@valko.cl publicado en valko.cl
→ evidencia fuerte

prevcons@gmail.com publicado en prevcons.cl
→ puede ser evidencia fuerte aunque el dominio del correo sea Gmail

correo aleatorio publicado solo en un directorio no relacionado
→ no habilita autoenvío
```

El resultado incluye `trust_score`, decisión y razones auditables.

### Outreach Policy Engine

`casehunter/engines/outreach_policy.py`

Decide si un primer contacto puede enviarse sin intervención humana. Evalúa, entre otros factores:

- prioridad financiera mínima;
- estado del contacto;
- score de confianza;
- relación entre empresa y fuente del contacto;
- límite diario de primeros contactos.

Decisiones posibles: `AUTO_SEND`, `REVIEW`, `HOLD` y `REJECT`.

### Reply Intelligence Engine

`casehunter/engines/reply_intelligence.py`

Convierte respuestas en intención y siguiente acción estructurada.

```text
"Sí, envíamela"
→ REQUESTS_INFO
→ VALIDATING
→ SEND_PUBLIC_SUMMARY

"Sigue pendiente"
→ STILL_PENDING
→ VALIDATING
→ CONFIRM_CURRENT_BLOCKER

"Ya está resuelto"
→ RESOLVED
→ caso RESOLVED

"No nos interesa"
→ NOT_INTERESTED
→ NO_FURTHER_OUTREACH
```

## Contactos y evidencia

Case Hunter no trata `@gmail.com`, `@outlook.com` u otro dominio externo como falso por defecto. Lo importante es la evidencia que vincula el correo con la empresa.

Los contactos guardan una evaluación separada en `contact_assessments` con:

- `trust_score`;
- `decision`;
- razones de la decisión;
- dominio de la fuente;
- dominio del correo;
- fecha de evaluación.

Las páginas de buscadores, dominios gubernamentales usados como fuente de contacto y hosts bloqueados no habilitan autoenvío. Los contactos inseguros se ponen en cuarentena o se rechazan.

## Envío automático

En cloud, el autoenvío está gobernado por política. No requiere aprobación humana cuando el caso y el contacto superan todos los controles configurados.

Antes del envío real, Gmail/IMAP comprueba si el destinatario ya fue contactado. Si existe un contacto anterior, el mensaje queda `SKIPPED_DUPLICATE`.

Variables principales:

```text
CASE_HUNTER_AUTO_POLICY_SEND=1
CASE_HUNTER_AUTO_SEND_APPROVED=1
CASE_HUNTER_AUTO_SEND_MIN_PRIORITY=70
CASE_HUNTER_AUTO_MAX_FIRST_CONTACTS_PER_DAY=10
```

## Gmail

Case Hunter usa SMTP para enviar e IMAP para verificar duplicados y leer respuestas.

Nunca guardes la contraseña normal de Gmail en el repositorio. Usa una contraseña de aplicación y GitHub Actions Secrets.

El workflow espera:

```text
CASE_HUNTER_GMAIL_USERNAME
CASE_HUNTER_GMAIL_APP_PASSWORD
```

Los secretos de Gmail se exponen únicamente al paso real de producción, no a las pruebas unitarias.

## Operaciones y KPIs

El endpoint:

```text
GET /api/operations
```

presenta métricas orientadas al negocio:

- casos totales, activos y resueltos;
- contactos encontrados;
- contactos aptos para autoenvío;
- primeros contactos enviados;
- respuestas recibidas;
- acciones abiertas;
- follow-ups pendientes;
- tasa de respuesta;
- tasa de resolución;
- oportunidades principales ordenadas por prioridad y confianza de contacto.

## Resolution Playbooks

Case Hunter mantiene playbooks operativos por tipo de bloqueo. Una señal pública no se convierte automáticamente en una afirmación de dinero recuperable. Cuando la empresa confirma información privada o actual, el caso puede reclasificarse y el playbook cambia según el bloqueo real.

Ejemplos de rutas:

```text
DOCUMENT_MISSING
→ identificar documento
→ responsable
→ envío
→ evidencia de presentación
→ seguimiento

RETENTION_RELEASE_PENDING
→ validar requisitos
→ solicitud
→ unidad responsable
→ seguimiento

LIQUIDATION_PENDING
→ verificar hitos
→ detectar hito faltante
→ antecedentes
→ escalamiento
```

## Cloud

El workflow principal está en:

```text
.github/workflows/case-hunter-auto.yml
```

Se ejecuta aproximadamente cada 6 horas y también permite ejecución manual. Actualmente conserva el estado SQLite mediante GitHub Actions cache.

Esta es una arquitectura válida para validación y operación inicial. La arquitectura objetivo de producción persistente está documentada en `ARCHITECTURE.md` e incluye una futura migración controlada a PostgreSQL y un worker/servicio permanente. Esa migración no se activa automáticamente para evitar crear infraestructura de pago sin una decisión explícita.

## API y frontend

```bash
python -m pip install -r requirements.txt
python -m casehunter init
python -m casehunter serve
```

Luego abre:

```text
http://127.0.0.1:8000
```

Endpoints principales:

```text
/api/dashboard
/api/operations
/api/cases
/api/contacts
/api/outreach
/api/replies
/api/followups
/api/auto/status
/api/auto/runs
```

## Privacidad

Por defecto, el modo cloud no persiste el cuerpo ni el asunto completo de las respuestas recibidas:

```text
CASE_HUNTER_STORE_REPLY_CONTENT=0
```

Se conserva la clasificación y los metadatos mínimos necesarios para continuar el caso.

## Pruebas

```bash
python -m casehunter verify
```

La suite cubre API, detector, casos públicos de regresión 2026, Mercado Público, repository, playbooks, confianza de contactos, política de autoenvío, Gmail, clasificación de respuestas, follow-ups, métricas operativas y deduplicación.

## Principio del producto

```text
NO optimizar por:
"cantidad de emails enviados"

SÍ optimizar por:
casos confirmados
→ bloqueos identificados
→ respuestas útiles
→ acciones completadas
→ casos resueltos
→ resultados comerciales medibles
```
