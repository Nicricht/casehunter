# Case Hunter Resolve v2.2.0

**Repositorio oficial:** `Nicricht/casehunter`

Sistema para detectar y gestionar casos administrativos de proveedores del Estado a partir de fuentes públicas y seguimiento interno.

## Qué resuelve

Case Hunter Resolve convierte una señal pública en un caso gestionable. El flujo incluye detección, diagnóstico de bloqueo, checklist documental, Resolution Playbook, acciones, seguimiento, cronología y cierre.

## Funcionalidades principales

- Descubrimiento desde Ley del Lobby.
- Integración opcional con Mercado Público por RUT mediante ticket oficial.
- Extracción de SAFI, montos y señales contractuales.
- Deduplicación de casos.
- Diagnóstico de bloqueos.
- Resolution Playbook por tipo de bloqueo.
- Confirmación manual del bloqueo real cuando la información pública no basta.
- Checklist documental.
- Acciones, responsables y fechas de seguimiento.
- Línea de tiempo por caso.
- Priorización financiera con advertencia sobre montos no confirmados.
- Persistencia SQLite.
- API FastAPI y frontend web.
- Autenticación Basic opcional.
- Tests automatizados.

## Inicio rápido en Windows

1. Instala Python 3.11 o superior.
2. Copia `.env.example` a `.env` si necesitas configurar credenciales o Mercado Público.
3. Ejecuta `run_windows.bat`.
4. Abre `http://127.0.0.1:8000`.

## Inicio manual

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m casehunter
```

## Variables de entorno

- `CASE_HUNTER_DB`
- `CASE_HUNTER_LEY_LOBBY_URL`
- `MERCADO_PUBLICO_TICKET`
- `CASE_HUNTER_USERNAME`
- `CASE_HUNTER_PASSWORD`

El ticket de Mercado Público no se guarda en el código.

## Resolution Playbook

Cuando el bloqueo cambia por información confirmada de la empresa, el caso puede reclasificarse. Por ejemplo, una liquidación pendiente puede convertirse en `DOCUMENT_MISSING` si el proveedor confirma que faltan antecedentes. El sistema agrega la ruta operativa correspondiente sin eliminar la trazabilidad anterior.

Cada playbook contiene:

- preguntas de confirmación
- acciones ordenadas
- responsable sugerido
- plazo operativo sugerido
- evidencia esperada para completar cada acción
- ruta de escalamiento
- condiciones de cierre

Las recomendaciones son operativas y deben contrastarse con las bases, el contrato y el expediente aplicable a cada caso.

## Pruebas

```bash
python -m unittest discover -s tests -v
```

## Regresión con casos públicos 2026

La versión 2.1.1 incorpora pruebas basadas en redacciones observadas en fuentes públicas oficiales durante 2026 para:

- Constructora Valko: devolución de retenciones y SAFI 278592.
- Constructora Rincor: retenciones contractuales adeudadas y estado de pago sin fecha clara.
- CyD Ingeniería: contratos terminados consultados por estado de liquidación.
- PREVCONS SpA: cierre administrativo de obras y trazabilidad del proceso contractual.

Estas pruebas protegen el detector frente a variaciones reales de lenguaje administrativo sin convertir una señal pública en una afirmación de deuda o monto recuperable.

## Case Hunter Auto

La versión 2.2.0 incorpora el primer orquestador de prospección automática:

1. expande índices anuales de Ley del Lobby y rota automáticamente por sujetos pasivos para no sobrecargar la fuente;
2. importa y deduplica los casos;
3. aplica prioridad financiera;
4. intenta descubrir correos publicados en fuentes y sitios web públicos;
5. genera un primer correo personalizado sin afirmar deuda o recuperabilidad como hecho;
6. deja el mensaje en una cola de aprobación;
7. solo envía mensajes aprobados;
8. registra ciclos, borradores y envíos en SQLite.

Ejecución de un ciclo:

```bash
python -m casehunter auto
```

Ejecución continua (intervalo mínimo 60 minutos):

```bash
python -m casehunter auto --daemon --interval-minutes 360
```

La interfaz web incluye una vista **Auto** con la cola de prospección. Cuando SMTP está configurado, el botón **Aprobar y enviar** envía por el servidor autenticado configurado. Para Gmail se recomienda una contraseña de aplicación y `smtp.gmail.com`; las credenciales se guardan únicamente como variables de entorno.

### Ejecución cloud sin PC

Case Hunter Auto se ejecuta mediante GitHub Actions desde el repositorio oficial. El workflow está en `.github/workflows/case-hunter-auto.yml` y ejecuta un ciclo aproximadamente cada 6 horas.

El runner cloud:

- hace checkout de `Nicricht/casehunter` en la rama `main`;
- restaura la base SQLite del ciclo anterior mediante cache de GitHub Actions;
- ejecuta el escaneo y la priorización;
- busca contactos públicos para un número limitado de los casos más prioritarios;
- genera la cola de aprobación;
- no envía mensajes automáticamente porque `CASE_HUNTER_AUTO_SEND_APPROVED=0`;
- genera un resumen del ciclo en GitHub Actions;
- guarda la base y el resultado del ciclo como artifact privado durante 30 días.

La ejecución cloud está limitada por ciclo para evitar timeouts y gasto innecesario de minutos de GitHub Actions. Los índices se recorren progresivamente usando un cursor persistente, por lo que cada ciclo continúa desde el punto anterior en vez de comenzar siempre por los mismos sujetos.

### Guardas de seguridad operativa

- No se envían mensajes encontrados automáticamente sin aprobación humana previa por defecto.
- Un primer contacto tiene una clave de deduplicación por caso y destinatario.
- Los contactos descubiertos conservan la URL pública donde se encontraron.
- Los montos públicos siguen siendo solo montos observados y no se presentan como dinero recuperable.
- La búsqueda web de contactos puede fallar o devolver candidatos incompletos; por eso el destinatario sigue pasando por la cola de aprobación.
