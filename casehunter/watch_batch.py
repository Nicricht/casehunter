from datetime import date

from .database import transaction, utc_now
from .public_watch import (
    ACTION_BY_SIGNAL,
    _candidate_urls,
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


def _source_budget(value):
    return max(1, min(2000, int(value)))


def _protected_urls(case):
    """Return the stable official/core URLs that must never be archived by the budget."""
    return {
        str(url).strip()
        for url in _candidate_urls(case)
        if str(url or "").strip()
    }


def _enforce_source_budget(case_id, max_sources=250, db_path=None):
    """Archive low-priority overflow while keeping official/core watch sources active."""
    budget = _source_budget(max_sources)
    case = get_case(case_id, db_path)
    protected_urls = _protected_urls(case)
    sources = [item for item in list_watch_sources(case_id, db_path) if item.get("status") == "ACTIVE"]

    protected = [item for item in sources if item.get("source_url") in protected_urls]
    dynamic = [item for item in sources if item.get("source_url") not in protected_urls]

    # Keep already-useful/healthy dynamic sources first. The batch selector still rotates
    # what gets checked, but the stored source set can no longer grow forever.
    dynamic.sort(
        key=lambda item: (
            0 if item.get("last_fingerprint") else 1,
            0 if not item.get("last_error") else 1,
            item.get("last_checked_at") or "",
            item.get("source_url") or "",
        )
    )

    effective_budget = max(budget, len(protected))
    keep_dynamic = max(0, effective_budget - len(protected))
    archive = dynamic[keep_dynamic:]
    now = utc_now()
    if archive:
        with transaction(db_path) as conn:
            for item in archive:
                conn.execute(
                    """UPDATE case_watch_sources
                       SET status='ARCHIVED',updated_at=?
                       WHERE case_id=? AND source_url=? AND status='ACTIVE'""",
                    (now, int(case_id), item["source_url"]),
                )

    return {
        "case_id": int(case_id),
        "max_sources": budget,
        "protected_sources": len(protected),
        "active_before": len(sources),
        "active_after": len(sources) - len(archive),
        "archived_sources": len(archive),
    }


def _new_discovery_urls(case_id, discovered_urls, remaining_capacity, db_path=None):
    """Only admit genuinely new discovered URLs; archived URLs stay archived."""
    slots = max(0, int(remaining_capacity))
    if slots <= 0:
        return []

    candidates = []
    for url in discovered_urls or []:
        value = str(url or "").strip()
        if value and value not in candidates:
            candidates.append(value)
    if not candidates:
        return []

    with transaction(db_path) as conn:
        rows = conn.execute(
            "SELECT source_url,status FROM case_watch_sources WHERE case_id=?",
            (int(case_id),),
        ).fetchall()
    existing = {row["source_url"]: row["status"] for row in rows}

    return [url for url in candidates if url not in existing][:slots]


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
    max_sources=250,
):
    """Run a bounded watch batch and enforce a hard per-case source budget."""
    _ensure_schema(db_path)

    # Re-activate only official/core candidates. Dynamic archived sources are not
    # reactivated automatically.
    configure_case_watch(case_id, db_path=db_path)
    budget = _enforce_source_budget(case_id, max_sources=max_sources, db_path=db_path)

    sources, available_sources = _source_batch(case_id, source_limit=source_limit, db_path=db_path)
    checked = 0
    baselined = 0
    changes = 0
    errors = 0
    discovered = 0
    events = []
    active_sources = int(budget["active_after"])
    capacity = max(0, int(budget["max_sources"]) - active_sources)

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

            discovered_urls = _new_discovery_urls(
                case_id,
                (document.get("discovered_urls") or [])[:12],
                capacity,
                db_path=db_path,
            )
            if discovered_urls:
                configured = configure_case_watch(
                    case_id,
                    source_urls=discovered_urls,
                    keywords=source.get("keywords") or None,
                    db_path=db_path,
                )
                created = int(configured.get("created") or 0)
                discovered += created
                active_sources += created
                capacity = max(0, int(budget["max_sources"]) - active_sources)

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
        "source_budget": int(budget["max_sources"]),
        "available_sources": available_sources,
        "selected_sources": len(sources),
        "archived_sources": int(budget["archived_sources"]),
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
    max_sources_per_case=250,
):
    """Watch active cases with bounded processing and bounded stored source growth."""
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
        results.append(
            run_case_watch_batch(
                case_id,
                fetcher=fetcher,
                mercado_fetcher=mercado_fetcher,
                db_path=db_path,
                source_limit=source_limit_per_case,
                max_sources=max_sources_per_case,
            )
        )

    return {
        "active_cases": len(results),
        "available_sources": sum(item["available_sources"] for item in results),
        "selected_sources": sum(item["selected_sources"] for item in results),
        "archived_sources": sum(item["archived_sources"] for item in results),
        "checked": sum(item["checked"] for item in results),
        "baselined": sum(item["baselined"] for item in results),
        "changes": sum(item["changes"] for item in results),
        "discovered_sources": sum(item["discovered_sources"] for item in results),
        "errors": sum(item["errors"] for item in results),
        "results": results,
    }
