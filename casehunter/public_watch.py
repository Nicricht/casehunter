import hashlib
import re
from datetime import date
from urllib.parse import urlsplit, urlunsplit

from .database import json_dumps, json_loads, row_to_dict, transaction, utc_now
from .discovery.collector import fetch_public_text
from .repository import add_timeline_event, create_action, get_case

WATCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS case_watch_sources (
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    keywords TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    last_fingerprint TEXT,
    last_relevant_text TEXT,
    last_checked_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(case_id, source_url)
);

CREATE TABLE IF NOT EXISTS case_watch_events (
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    signal TEXT NOT NULL,
    snippet TEXT,
    detected_at TEXT NOT NULL,
    PRIMARY KEY(case_id, source_url, fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_watch_sources_status ON case_watch_sources(status, case_id);
CREATE INDEX IF NOT EXISTS idx_watch_events_case ON case_watch_events(case_id, detected_at);
"""

SIGNALS = (
    ("PAYMENT_CONFIRMED", ("pago realizado", "pago efectuado", "pagado", "remesa recibida", "transferencia realizada")),
    ("PAYMENT_COMMITMENT", ("compromiso de pago", "fecha de pago", "calendario de pago", "programación de pago", "programacion de pago")),
    ("FUNDING_MOVEMENT", ("solicitud de recursos", "transferencia de recursos", "remesa", "disponibilidad presupuestaria", "recursos municipales")),
    ("FORMAL_ACT", ("resolución", "resolucion", "decreto", "folio", "ordinario", "memorándum", "memorandum")),
    ("RESPONSIBLE_CHANGE", ("director", "directora", "finanzas", "contabilidad", "administrador municipal", "administradora municipal")),
)

ACTION_BY_SIGNAL = {
    "PAYMENT_CONFIRMED": ("VERIFY_PUBLIC_RESOLUTION", "Verificar si el nuevo antecedente confirma pago o regularización del caso"),
    "PAYMENT_COMMITMENT": ("VERIFY_PAYMENT_COMMITMENT", "Validar fecha, alcance y condiciones del nuevo compromiso de pago"),
    "FUNDING_MOVEMENT": ("VERIFY_FUNDING_MOVEMENT", "Verificar si el movimiento de recursos alcanza al caso y cuál es el siguiente hito"),
    "FORMAL_ACT": ("REVIEW_FORMAL_ACT", "Revisar el nuevo acto formal y determinar cómo cambia el siguiente paso"),
    "RESPONSIBLE_CHANGE": ("VERIFY_RESPONSIBLE_UNIT", "Verificar si cambió la unidad o persona responsable del seguimiento"),
    "PUBLIC_CHANGE": ("REVIEW_PUBLIC_CHANGE", "Revisar el cambio público detectado y determinar si modifica el caso"),
}

DEFAULT_KEYWORDS = (
    "pago", "factura", "deuda", "retención", "retencion", "garantía", "garantia",
    "recursos", "remesa", "resolución", "resolucion", "folio", "compromiso",
    "finanzas", "contabilidad", "liquidación", "liquidacion", "cierre",
)


def _ensure_schema(db_path=None):
    with transaction(db_path) as conn:
        conn.executescript(WATCH_SCHEMA)


def _normalize(text):
    return "\n".join(" ".join(line.split()) for line in str(text or "").splitlines() if line.strip())


def _fingerprint(text):
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


def _case_terms(case):
    terms = list(DEFAULT_KEYWORDS)
    for value in (case.get("company_name"), case.get("detected_company_name"), case.get("agency"), case.get("contract_ref")):
        value = " ".join(str(value or "").split()).strip().lower()
        if len(value) >= 3:
            terms.append(value)
    return list(dict.fromkeys(terms))


def _relevant_text(text, keywords):
    lines = _normalize(text).splitlines()
    terms = [str(k).strip().lower() for k in keywords if str(k).strip()]
    selected = [line for line in lines if any(term in line.lower() for term in terms)]
    return "\n".join(selected[-250:])


def _signal(text):
    value = str(text or "").lower()
    for label, tokens in SIGNALS:
        if any(token in value for token in tokens):
            return label
    return "PUBLIC_CHANGE"


def _ley_lobby_parent(url):
    parts = urlsplit(str(url or ""))
    path = parts.path.rstrip("/")
    match = re.match(r"^(/instituciones/[^/]+/audiencias/\d{4})/[^/]+$", path)
    if not match:
        return None
    return urlunsplit((parts.scheme, parts.netloc, match.group(1), "", ""))


def _candidate_urls(case):
    urls = []
    for value in (case.get("detail_url"), case.get("source_url")):
        value = str(value or "").strip()
        if value.startswith(("http://", "https://")):
            urls.append(value)
            parent = _ley_lobby_parent(value)
            if parent:
                urls.append(parent)
    return list(dict.fromkeys(urls))


def configure_case_watch(case_id, source_urls=None, keywords=None, db_path=None):
    _ensure_schema(db_path)
    case = get_case(case_id, db_path)
    urls = list(source_urls or _candidate_urls(case))
    terms = list(keywords or _case_terms(case))
    now = utc_now()
    created = 0
    with transaction(db_path) as conn:
        for url in urls:
            existing = conn.execute(
                "SELECT case_id FROM case_watch_sources WHERE case_id=? AND source_url=?",
                (int(case_id), url),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE case_watch_sources SET keywords=?,status='ACTIVE',updated_at=? WHERE case_id=? AND source_url=?",
                    (json_dumps(terms), now, int(case_id), url),
                )
            else:
                conn.execute(
                    """INSERT INTO case_watch_sources(case_id,source_url,keywords,status,created_at,updated_at)
                       VALUES(?,?,?,'ACTIVE',?,?)""",
                    (int(case_id), url, json_dumps(terms), now, now),
                )
                created += 1
    return {"case_id": int(case_id), "created": created, "source_urls": urls, "keywords": terms}


def list_watch_sources(case_id=None, db_path=None):
    _ensure_schema(db_path)
    query = "SELECT * FROM case_watch_sources"
    params = []
    if case_id is not None:
        query += " WHERE case_id=?"
        params.append(int(case_id))
    query += " ORDER BY case_id, source_url"
    with transaction(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    result = []
    for row in rows:
        item = row_to_dict(row)
        item["keywords"] = json_loads(item.get("keywords"), [])
        result.append(item)
    return result


def _new_lines(previous, current):
    old = set(_normalize(previous).splitlines())
    return [line for line in _normalize(current).splitlines() if line not in old]


def _ensure_action(case_id, action_type, title, note, db_path=None):
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM actions WHERE case_id=? AND action_type=? AND status='TODO' ORDER BY id DESC LIMIT 1",
            (int(case_id), action_type),
        ).fetchone()
    if row:
        return None
    return create_action(
        case_id,
        title,
        action_type=action_type,
        due_date=date.today().isoformat(),
        responsible="Nicolás / Case Hunter",
        note=note,
        db_path=db_path,
    )


def run_case_watch(case_id, fetcher=None, db_path=None):
    _ensure_schema(db_path)
    sources = list_watch_sources(case_id, db_path)
    if not sources:
        configure_case_watch(case_id, db_path=db_path)
        sources = list_watch_sources(case_id, db_path)
    fetch = fetcher or fetch_public_text
    checked = 0
    baselined = 0
    changes = 0
    errors = 0
    events = []
    for source in sources:
        if source.get("status") != "ACTIVE":
            continue
        now = utc_now()
        try:
            document = fetch(source["source_url"])
            relevant = _relevant_text(document.get("text"), source.get("keywords") or [])
            fingerprint = _fingerprint(relevant)
            checked += 1
            previous_fp = source.get("last_fingerprint")
            previous_text = source.get("last_relevant_text") or ""
            if not previous_fp:
                baselined += 1
            elif fingerprint != previous_fp:
                added = _new_lines(previous_text, relevant)
                changed_text = "\n".join(added) or relevant
                signal = _signal(changed_text)
                snippet = changed_text[:4000]
                with transaction(db_path) as conn:
                    existing = conn.execute(
                        "SELECT fingerprint FROM case_watch_events WHERE case_id=? AND source_url=? AND fingerprint=?",
                        (int(case_id), source["source_url"], fingerprint),
                    ).fetchone()
                    if not existing:
                        conn.execute(
                            """INSERT INTO case_watch_events(case_id,source_url,fingerprint,signal,snippet,detected_at)
                               VALUES(?,?,?,?,?,?)""",
                            (int(case_id), source["source_url"], fingerprint, signal, snippet, now),
                        )
                        changes += 1
                        events.append({"source_url": source["source_url"], "signal": signal, "snippet": snippet})
                if events and events[-1]["source_url"] == source["source_url"]:
                    action_type, title = ACTION_BY_SIGNAL[signal]
                    _ensure_action(
                        case_id,
                        action_type,
                        title,
                        f"Cambio detectado automáticamente en {source['source_url']}. Señal: {signal}.",
                        db_path,
                    )
                    add_timeline_event(
                        case_id,
                        title=f"Cambio público detectado: {signal}",
                        details=snippet,
                        event_type="PUBLIC_WATCH_CHANGE",
                        event_date=date.today().isoformat(),
                        source_url=source["source_url"],
                        db_path=db_path,
                    )
            with transaction(db_path) as conn:
                conn.execute(
                    """UPDATE case_watch_sources
                       SET last_fingerprint=?,last_relevant_text=?,last_checked_at=?,last_error=NULL,updated_at=?
                       WHERE case_id=? AND source_url=?""",
                    (fingerprint, relevant[-20000:], now, now, int(case_id), source["source_url"]),
                )
        except Exception as exc:
            errors += 1
            with transaction(db_path) as conn:
                conn.execute(
                    "UPDATE case_watch_sources SET last_checked_at=?,last_error=?,updated_at=? WHERE case_id=? AND source_url=?",
                    (now, str(exc)[:1000], now, int(case_id), source["source_url"]),
                )
    return {"case_id": int(case_id), "checked": checked, "baselined": baselined, "changes": changes, "errors": errors, "events": events}


def run_active_watches(db_path=None, fetcher=None, limit=100):
    _ensure_schema(db_path)
    with transaction(db_path) as conn:
        rows = conn.execute(
            """SELECT DISTINCT case_id FROM actions
               WHERE action_type='WATCH_PUBLIC_CASE' AND status='TODO'
               ORDER BY case_id LIMIT ?""",
            (max(1, min(500, int(limit))),),
        ).fetchall()
    results = []
    for row in rows:
        case_id = int(row["case_id"])
        configure_case_watch(case_id, db_path=db_path)
        results.append(run_case_watch(case_id, fetcher=fetcher, db_path=db_path))
    return {
        "active_cases": len(results),
        "checked": sum(item["checked"] for item in results),
        "baselined": sum(item["baselined"] for item in results),
        "changes": sum(item["changes"] for item in results),
        "errors": sum(item["errors"] for item in results),
        "results": results,
    }
