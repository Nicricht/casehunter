from collections import Counter
from datetime import datetime, timedelta, timezone
import re
import unicodedata

from .company_identity import company_matches, normalize_company_name
from .database import transaction, utc_now
from .discovery.ley_lobby import scan_ley_lobby_listing
from .repository import create_company, get_case, import_candidate, link_case_company, list_companies


PORTFOLIO_SCHEMA = """
CREATE TABLE IF NOT EXISTS pilot_portfolio_refresh (
    portfolio_key TEXT PRIMARY KEY,
    last_refreshed_at TEXT,
    last_case_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL
);
"""


REGISTERED_PILOT_PORTFOLIOS = {
    "alembic_pharmaceuticals": {
        "canonical_name": "Alembic Pharmaceuticals SpA",
        "aliases": (
            "Alembic Pharmaceuticals",
            "Alembic Pharmaceuticals SpA",
            "ALEMBIC PHARMACEUTICALS SPA",
        ),
        # Official source lists where Alembic has appeared in public-sector
        # payment, procurement or administrative follow-up matters.
        "sources": (
            "https://www.leylobby.gob.cl/instituciones/MU271/audiencias/2026/800758",
            "https://www.leylobby.gob.cl/instituciones/AO019/cargos-pasivos/74169/audiencias",
            "https://www.leylobby.gob.cl/instituciones/AO020/audiencias/2025/728404",
            "https://www.leylobby.gob.cl/instituciones/AO032/audiencias/2026/4761",
            "https://www.leylobby.gob.cl/instituciones/AO003/audiencias/2026/865194",
        ),
    },
}


def _ensure_schema(db_path=None):
    with transaction(db_path) as conn:
        conn.executescript(PORTFOLIO_SCHEMA)


def _fold(value):
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _candidate_matches(candidate, aliases):
    represented = list(candidate.get("represented_entities") or [])
    works_for = list(candidate.get("works_for") or [])
    for value in represented + works_for:
        if company_matches(value, aliases):
            return True

    haystack = _fold("\n".join(filter(None, [candidate.get("raw_text"), candidate.get("detail_text")])))
    for alias in aliases:
        folded = _fold(alias)
        if folded and folded in haystack:
            return True
    return False


def _find_or_create_company(config, db_path=None):
    aliases = tuple(config["aliases"]) + (config["canonical_name"],)
    for company in list_companies(db_path):
        if company_matches(company.get("name"), aliases):
            return company
    return create_company(config["canonical_name"], db_path=db_path)


def _cancel_resolved_actions(case_id, db_path=None):
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE actions SET status='CANCELLED',updated_at=? WHERE case_id=? AND status='TODO'",
            (utc_now(), int(case_id)),
        )
        conn.execute(
            "UPDATE cases SET status='RESOLVED',financial_priority=0,current_blocker=NULL,blocker_reason=?,updated_at=? WHERE id=?",
            ("El antecedente público indica que la gestión que originó el caso fue resuelta.", utc_now(), int(case_id)),
        )


def _portfolio_summary(company_id, db_path=None):
    with transaction(db_path) as conn:
        rows = conn.execute(
            "SELECT id FROM cases WHERE company_id=? ORDER BY event_date DESC,id DESC",
            (int(company_id),),
        ).fetchall()
    cases = [get_case(int(row["id"]), db_path) for row in rows]
    agencies = Counter(str(case.get("agency") or "Sin organismo identificado") for case in cases)
    blockers = Counter(str(case.get("current_blocker") or "RESOLVED_OR_UNCLASSIFIED") for case in cases)
    return {
        "company_id": int(company_id),
        "case_count": len(cases),
        "open_case_count": sum(case.get("status") != "RESOLVED" for case in cases),
        "resolved_case_count": sum(case.get("status") == "RESOLVED" for case in cases),
        "public_amount_clp": sum(sum(int(value or 0) for value in case.get("amounts_clp", [])) for case in cases),
        "agencies": [{"name": name, "case_count": count} for name, count in agencies.most_common()],
        "blockers": [{"type": name, "case_count": count} for name, count in blockers.most_common()],
        "case_ids": [int(case["id"]) for case in cases],
    }


def scan_registered_portfolio(portfolio_key, db_path=None, scanner=None, max_pages=5, enrich_limit=40):
    config = REGISTERED_PILOT_PORTFOLIOS.get(portfolio_key)
    if not config:
        raise KeyError("Cartera piloto no registrada")

    company = _find_or_create_company(config, db_path)
    aliases = tuple(config["aliases"]) + (config["canonical_name"],)
    run_scan = scanner or scan_ley_lobby_listing
    matched = 0
    created = 0
    updated = 0
    scanned_sources = 0
    errors = []

    for source_url in config["sources"]:
        try:
            result = run_scan(
                source_url,
                max_pages=max(1, int(max_pages)),
                enrich=True,
                enrich_limit=max(1, int(enrich_limit)),
            )
            scanned_sources += 1
        except Exception as exc:
            errors.append({"source_url": source_url, "error": str(exc)[:500]})
            continue

        for candidate in result.get("candidates", []):
            if not _candidate_matches(candidate, aliases):
                continue
            matched += 1
            candidate = dict(candidate)
            # Canonicalize the portfolio identity only after a positive match.
            # This prevents similarly named suppliers from being merged by force.
            candidate["represented_entities"] = [config["canonical_name"]]
            imported = import_candidate(
                candidate,
                source=result.get("source", "LEY_DEL_LOBBY"),
                source_url=result.get("source_url") or source_url,
                db_path=db_path,
            )
            case_id = int(imported["case"]["id"])
            link_case_company(case_id, company["id"], db_path)
            if (candidate.get("outcome") or {}).get("state") == "RESOLVED":
                _cancel_resolved_actions(case_id, db_path)
            if imported["created"]:
                created += 1
            else:
                updated += 1

    summary = _portfolio_summary(company["id"], db_path)
    summary.update({
        "portfolio_key": portfolio_key,
        "canonical_name": config["canonical_name"],
        "sources_scanned": scanned_sources,
        "matched_candidates": matched,
        "created": created,
        "updated": updated,
        "errors": errors,
    })
    return summary


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _active_pilot_names(db_path=None):
    with transaction(db_path) as conn:
        rows = conn.execute(
            """SELECT DISTINCT COALESCE(c.name,k.detected_company_name) AS company_name
               FROM cases k
               LEFT JOIN companies c ON c.id=k.company_id
               JOIN timeline_events te ON te.case_id=k.id AND te.event_type='PILOT_STARTED'
               WHERE k.status NOT IN ('RESOLVED','DISMISSED')"""
        ).fetchall()
    return [str(row["company_name"] or "").strip() for row in rows if str(row["company_name"] or "").strip()]


def refresh_due_pilot_portfolios(db_path=None, force=False, interval_hours=24, scanner=None):
    _ensure_schema(db_path)
    now = datetime.now(timezone.utc)
    active_names = _active_pilot_names(db_path)
    results = []
    skipped = []

    for key, config in REGISTERED_PILOT_PORTFOLIOS.items():
        aliases = tuple(config["aliases"]) + (config["canonical_name"],)
        if not any(company_matches(name, aliases) for name in active_names):
            continue

        with transaction(db_path) as conn:
            state = conn.execute(
                "SELECT * FROM pilot_portfolio_refresh WHERE portfolio_key=?",
                (key,),
            ).fetchone()
        last = _parse_time(state["last_refreshed_at"]) if state else None
        due = force or last is None or now - last >= timedelta(hours=max(1, int(interval_hours)))
        if not due:
            skipped.append(key)
            continue

        try:
            result = scan_registered_portfolio(key, db_path=db_path, scanner=scanner)
            with transaction(db_path) as conn:
                conn.execute(
                    """INSERT INTO pilot_portfolio_refresh(portfolio_key,last_refreshed_at,last_case_count,last_error,updated_at)
                       VALUES(?,?,?,NULL,?)
                       ON CONFLICT(portfolio_key) DO UPDATE SET
                         last_refreshed_at=excluded.last_refreshed_at,
                         last_case_count=excluded.last_case_count,
                         last_error=NULL,
                         updated_at=excluded.updated_at""",
                    (key, now.isoformat(), int(result["case_count"]), utc_now()),
                )
            results.append(result)
        except Exception as exc:
            with transaction(db_path) as conn:
                conn.execute(
                    """INSERT INTO pilot_portfolio_refresh(portfolio_key,last_refreshed_at,last_case_count,last_error,updated_at)
                       VALUES(?,NULL,0,?,?)
                       ON CONFLICT(portfolio_key) DO UPDATE SET last_error=excluded.last_error,updated_at=excluded.updated_at""",
                    (key, str(exc)[:1000], utc_now()),
                )
            results.append({"portfolio_key": key, "error": str(exc)})

    return {
        "active_pilot_names": active_names,
        "refreshed": len([item for item in results if not item.get("error")]),
        "skipped": skipped,
        "results": results,
    }
