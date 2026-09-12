from datetime import date

from .database import transaction, utc_now
from .public_watch import (
    ACTION_BY_SIGNAL,
    _ensure_action,
    _ensure_schema,
    _fingerprint,
    _new_lines,
    _normalize,
    _relevant_text,
    _signal,
    configure_case_watch,
    list_watch_sources,
)
from .repository import add_timeline_event, get_case
from .watch_source_adapters import fetch_watch_source, source_kind


def _source_batch(case_id, source_limit=25, db_path=None):
    """Select a bounded rotating batch while always including the case's primary sources."""
    limit = max(1, min(100, int(source_limit)))
    case = get_case(case_id, db_path)
    primary_urls = {
        str(value).strip()
        for value in (case.get("detail_url"), case.get("source_url"))
        if str(value or "").strip()
    }
    sources = [item for item in list_watch_sources(case_id, db_path) if item.get("status") == "ACTIVE"]

    primary = [item for item in sources if item.get("source_url") in primary_urls]
    secondary = [item for item in sources if item.get("source_url") not in primary_urls]
    secondary.sort(
        key=lambda item: (
            0 if not item.get("last_checked_at") else 1,
            item.get("last_checked_at") or "",
            item.get("source_url") or "",
        )
    )

    selected = primary[:limit]
    remaining = max(0, limit - len(selected))
    selected.extend(secondary[:remaining])
    return selected, len(sources)


def run_case_watch_batch(
    case_id,
    fetcher=None,
    mercado_fetcher=None,
    db_path=None,
    source_limit=25,
):
    """Run a bounded watch batch for one case and rotate secondary sources over time."""
    _ensure_schema(db_path)
    if not list_watch_sources(case_id, db_path):
        configure_case_watch(case_id, db_path=db_path)

    sources, available_sources = _source_batch(case_id, source_limit=source_limit, db_path=db_path)
    checked = 0
    baselined = 0
    changes = 0
    errors = 0
    discovered = 0
    events = []

    for source in sources:
        now = utc_now()
        try:
            document = fetch_watch_source(
                source["source_url"],
                http_fetcher=fetcher,
                mercado_fetcher=mercado_fetcher,
            )
            source_type = document.get("kind") or source_kind(source["source_url"])
            if source_type == "MERCADO_PUBLICO_OC":
                relevant = _normalize(document.get("text"))
            else:
                relevant = _relevant_text(document.get("text"), source.get("keywords") or [])
            fingerprint = _fingerprint(relevant)
            checked += 1

            discovered_urls = document.get("discovered_urls") or []
            if discovered_urls:
                configured = configure_case_watch(
                    case_id,
                    source_urls=discovered_urls[:12],
                    keywords=source.get("keywords") or None,
                    db_path=db_path,
                )
                discovered += int(configured.get("created") or 0)

            previous_fp = source.get("last_fingerprint")
            previous_text = source.get("last_relevant_text") or ""
            if not previous_fp:
                baselined += 1
            elif fingerprint != previous_fp:
                added = _new_lines(previous_text, relevant)
                changed_text = "\n".join(added) or relevant
                signal = _signal(changed_text)
                snippet = changed_text[:4000]
                event_created = False
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
                        event_created = True
                        events.append(
                            {
                                "source_url": source["source_url"],
                                "source_kind": source_type,
                                "signal": signal,
                                "snippet": snippet,
                            }
                        )
                if event_created:
                    action_type, title = ACTION_BY_SIGNAL[signal]
                    _ensure_action(
                        case_id,
                        action_type,
                        title,
                        f"Cambio detectado automáticamente en {source['source_url']}. Fuente: {source_type}. Señal: {signal}.",
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

    return {
        "case_id": int(case_id),
        "available_sources": available_sources,
        "selected_sources": len(sources),
        "checked": checked,
        "baselined": baselined,
        "changes": changes,
        "discovered_sources": discovered,
        "errors": errors,
        "events": events,
    }


def run_bounded_active_watches(
    db_path=None,
    fetcher=None,
    mercado_fetcher=None,
    case_limit=100,
    source_limit_per_case=25,
):
    """Watch active pilot cases without letting source discovery create unbounded cycles."""
    _ensure_schema(db_path)
    with transaction(db_path) as conn:
        rows = conn.execute(
            """SELECT DISTINCT case_id FROM actions
               WHERE action_type='WATCH_PUBLIC_CASE' AND status='TODO'
               ORDER BY case_id LIMIT ?""",
            (max(1, min(500, int(case_limit))),),
        ).fetchall()

    results = []
    for row in rows:
        case_id = int(row["case_id"])
        configure_case_watch(case_id, db_path=db_path)
        results.append(
            run_case_watch_batch(
                case_id,
                fetcher=fetcher,
                mercado_fetcher=mercado_fetcher,
                db_path=db_path,
                source_limit=source_limit_per_case,
            )
        )

    return {
        "active_cases": len(results),
        "available_sources": sum(item["available_sources"] for item in results),
        "selected_sources": sum(item["selected_sources"] for item in results),
        "checked": sum(item["checked"] for item in results),
        "baselined": sum(item["baselined"] for item in results),
        "changes": sum(item["changes"] for item in results),
        "discovered_sources": sum(item["discovered_sources"] for item in results),
        "errors": sum(item["errors"] for item in results),
        "results": results,
    }
