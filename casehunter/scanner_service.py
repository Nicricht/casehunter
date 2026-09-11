from .database import json_dumps, transaction, utc_now
from .discovery.ley_lobby import scan_ley_lobby_listing
from .repository import import_scan_result


def _apply_public_outcomes(candidates, case_ids, db_path=None):
    """Preserve public resolution evidence without treating it as fresh debt.

    Fully resolved public records are kept as historical precedents, but are
    removed from active work queues. Partial resolution evidence remains active
    and is recorded on the timeline for later comparison.
    """
    applied = {"resolved": 0, "partial": 0}
    now = utc_now()
    for candidate, case_id in zip(candidates, case_ids):
        outcome = candidate.get("outcome") or {}
        state = outcome.get("state")
        if state not in {"RESOLVED", "PARTIAL"}:
            continue
        event_date = candidate.get("date") or now[:10]
        details = json_dumps({
            "state": state,
            "resolved_signals": outcome.get("resolved_signals", []),
            "pending_signals": outcome.get("pending_signals", []),
        })
        with transaction(db_path) as conn:
            existing = conn.execute(
                """SELECT id FROM timeline_events
                   WHERE case_id=? AND event_type='PUBLIC_RESOLUTION_SIGNAL' AND details=? LIMIT 1""",
                (int(case_id), details),
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO timeline_events(case_id,event_type,event_date,title,details,source_url,created_at)
                       VALUES(?,'PUBLIC_RESOLUTION_SIGNAL',?,?,?,?,?)""",
                    (
                        int(case_id), event_date,
                        "Fuente pública indica resolución" if state == "RESOLVED" else "Fuente pública indica resolución parcial",
                        details,
                        candidate.get("detail_url") or candidate.get("source_url"),
                        now,
                    ),
                )
            if state == "RESOLVED":
                conn.execute(
                    """UPDATE cases
                       SET status='RESOLVED',financial_priority=0,current_blocker=NULL,
                           blocker_reason='La fuente pública indica que el antecedente que originó la gestión fue resuelto.',updated_at=?
                       WHERE id=?""",
                    (now, int(case_id)),
                )
                conn.execute(
                    """UPDATE actions SET status='CANCELLED',completed_at=?
                       WHERE case_id=? AND status='TODO'""",
                    (now, int(case_id)),
                )
                applied["resolved"] += 1
            else:
                applied["partial"] += 1
    return applied


def run_ley_lobby_scan(url, max_pages=10, enrich=True, enrich_limit=25, db_path=None):
    started = utc_now()
    with transaction(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO scans(source,source_url,started_at) VALUES('LEY_DEL_LOBBY',?,?)",
            (url, started),
        )
        scan_id = cur.lastrowid
    try:
        result = scan_ley_lobby_listing(
            url,
            max_pages=max(1, min(int(max_pages), 50)),
            enrich=bool(enrich),
            enrich_limit=max(0, min(int(enrich_limit), 100)),
        )
        imported = import_scan_result(result, db_path)
        outcomes = _apply_public_outcomes(result.get("candidates", []), imported.get("case_ids", []), db_path)
        imported["public_outcomes"] = outcomes
        with transaction(db_path) as conn:
            conn.execute(
                """UPDATE scans SET finished_at=?,pages_scanned=?,candidate_count=?,imported_count=? WHERE id=?""",
                (utc_now(), result["pages_scanned"], result["candidate_count"], imported["created"], scan_id),
            )
        return {"scan_id": scan_id, "scan": result, "import": imported}
    except Exception as exc:
        with transaction(db_path) as conn:
            conn.execute("UPDATE scans SET finished_at=?,error=? WHERE id=?", (utc_now(), str(exc), scan_id))
        raise


def list_scans(limit=20, db_path=None):
    with transaction(db_path) as conn:
        rows = conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 100)),)).fetchall()
    return [dict(row) for row in rows]


def run_mercado_publico_sync(company_id, start_date, end_date, ticket=None, db_path=None):
    from .mercado_publico import scan_purchase_orders_for_rut
    from .repository import get_company, link_case_company

    company = get_company(company_id, db_path)
    if not company.get("rut"):
        raise ValueError("La empresa necesita un RUT para sincronizar Mercado Público")

    started = utc_now()
    with transaction(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO scans(source,source_url,started_at) VALUES('MERCADO_PUBLICO','https://api.mercadopublico.cl/',?)",
            (started,),
        )
        scan_id = cur.lastrowid
    try:
        result = scan_purchase_orders_for_rut(company["rut"], start_date, end_date, ticket=ticket)
        imported = import_scan_result(result, db_path)
        for case_id in imported["case_ids"]:
            link_case_company(case_id, company_id, db_path)
        with transaction(db_path) as conn:
            conn.execute(
                "UPDATE scans SET finished_at=?,pages_scanned=?,candidate_count=?,imported_count=? WHERE id=?",
                (utc_now(), result["pages_scanned"], result["candidate_count"], imported["created"], scan_id),
            )
        return {"scan_id": scan_id, "scan": result, "import": imported}
    except Exception as exc:
        with transaction(db_path) as conn:
            conn.execute("UPDATE scans SET finished_at=?,error=? WHERE id=?", (utc_now(), str(exc), scan_id))
        raise
