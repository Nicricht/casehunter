from datetime import date, timedelta
import hashlib

from .blocker_engine import diagnose
from .database import json_dumps, json_loads, row_to_dict, transaction, utc_now
from .financial import calculate_priority, summarize_amounts
from .resolution_playbook import PLAYBOOKS, build_playbook, get_playbook

VALID_CASE_STATUSES = {
    "DETECTED", "VALIDATING", "BLOCKER_IDENTIFIED", "ACTION_REQUIRED", "DOCUMENT_SENT",
    "WAITING_AGENCY", "FOLLOW_UP", "RESOLVED", "DISMISSED",
}
VALID_DOCUMENT_STATUSES = {"UNKNOWN", "PRESENT", "MISSING", "REQUESTED", "NOT_APPLICABLE"}
VALID_ACTION_STATUSES = {"TODO", "DONE", "CANCELLED"}


def create_company(name, rut=None, db_path=None):
    now = utc_now()
    clean_name = (name or "").strip()
    clean_rut = (rut or "").strip() or None
    if not clean_name:
        raise ValueError("El nombre de la empresa es obligatorio")
    with transaction(db_path) as conn:
        try:
            cur = conn.execute(
                "INSERT INTO companies(rut,name,created_at,updated_at) VALUES(?,?,?,?)",
                (clean_rut, clean_name, now, now),
            )
        except Exception as exc:
            if "UNIQUE constraint failed: companies.rut" in str(exc):
                raise ValueError("Ya existe una empresa con ese RUT") from exc
            raise
        company_id = cur.lastrowid
    return get_company(company_id, db_path)


def list_companies(db_path=None):
    with transaction(db_path) as conn:
        rows = conn.execute(
            "SELECT c.*, COUNT(k.id) case_count FROM companies c LEFT JOIN cases k ON k.company_id=c.id GROUP BY c.id ORDER BY c.name"
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def get_company(company_id, db_path=None):
    with transaction(db_path) as conn:
        row = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
    if row is None:
        raise KeyError("Empresa no encontrada")
    return row_to_dict(row)


def _upsert_problem(conn, case_id, problem):
    conn.execute(
        """INSERT INTO case_problems(case_id,type,matched_patterns) VALUES(?,?,?)
           ON CONFLICT(case_id,type) DO UPDATE SET matched_patterns=excluded.matched_patterns""",
        (case_id, problem["type"], json_dumps(problem.get("matched_patterns", []))),
    )


def _seed_resolution_plan(conn, case_id, diagnosis):
    now = utc_now()
    for doc in diagnosis["documents"]:
        conn.execute(
            """INSERT INTO documents(case_id,code,name,status,required,note,updated_at)
               VALUES(?,?,?,'UNKNOWN',1,NULL,?)
               ON CONFLICT(case_id,code) DO UPDATE SET name=excluded.name""",
            (case_id, doc["code"], doc["name"], now),
        )

    existing = {
        row["action_type"]
        for row in conn.execute("SELECT action_type FROM actions WHERE case_id=?", (case_id,)).fetchall()
    }

    diagnostic_due = (date.today() + timedelta(days=7)).isoformat()
    for index, action in enumerate(diagnosis["actions"]):
        if action["action_type"] in existing:
            continue
        conn.execute(
            """INSERT INTO actions(case_id,action_type,title,status,due_date,responsible,note,created_at)
               VALUES(?,?,?,'TODO',?,?,NULL,?)""",
            (
                case_id,
                action["action_type"],
                action["title"],
                diagnostic_due if index == 0 else None,
                "Proveedor",
                now,
            ),
        )
        existing.add(action["action_type"])

    playbook = get_playbook(diagnosis["primary_blocker"])
    for step in playbook.steps:
        if step.code in existing:
            continue
        due = (date.today() + timedelta(days=step.due_days)).isoformat() if step.due_days is not None else None
        conn.execute(
            """INSERT INTO actions(case_id,action_type,title,status,due_date,responsible,note,created_at)
               VALUES(?,?,?,'TODO',?,?,?,?)""",
            (case_id, step.code, step.title, due, step.responsible, f"Evidencia de cierre: {step.completion_evidence}", now),
        )
        existing.add(step.code)


def import_candidate(candidate, source="LEY_DEL_LOBBY", source_url=None, db_path=None):
    external_id = candidate.get("audience_id") or candidate.get("detail_url")
    if not external_id:
        safis = ",".join(candidate.get("safis", []))
        digest = hashlib.sha256((candidate.get("raw_text") or "").encode("utf-8")).hexdigest()[:16]
        external_id = f"{candidate.get('date') or 'unknown'}:{safis}:{digest}"

    problems = candidate.get("problems", [])
    problem_types = [p["type"] for p in problems]
    diagnosis = diagnose(problem_types)
    amounts = candidate.get("amounts_clp", [])
    confidence = candidate.get("confidence", {"label": "LOW", "score": 0})
    priority = calculate_priority(amounts, problem_types, confidence.get("label", "LOW"))
    represented = candidate.get("represented_entities") or []
    works_for = candidate.get("works_for") or []
    company_name = represented[0] if represented else (works_for[0] if works_for else None)
    contract_ref = candidate.get("contract_ref") or (", ".join(f"SAFI {s}" for s in candidate.get("safis", [])) or None)
    agency = candidate.get("agency") or "MOP / organismo público por confirmar"
    now = utc_now()

    with transaction(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM cases WHERE source=? AND external_id=?", (source, str(external_id))
        ).fetchone()
        if existing:
            case_id = existing["id"]
            conn.execute(
                """UPDATE cases SET source_url=?,detail_url=?,event_date=?,detected_company_name=?,agency=?,contract_ref=?,
                   confidence_label=?,confidence_score=?,financial_priority=?,current_blocker=?,blocker_reason=?,raw_text=?,detail_text=?,updated_at=?
                   WHERE id=?""",
                (
                    source_url or candidate.get("source_url"), candidate.get("detail_url"), candidate.get("date"), company_name, agency,
                    contract_ref, confidence.get("label", "LOW"), float(confidence.get("score", 0)), priority,
                    diagnosis["primary_blocker"], diagnosis["reason"], candidate.get("raw_text"), candidate.get("detail_text"), now, case_id,
                ),
            )
            created = False
        else:
            cur = conn.execute(
                """INSERT INTO cases(source,external_id,source_url,detail_url,event_date,detected_company_name,agency,contract_ref,status,
                   confidence_label,confidence_score,financial_priority,current_blocker,blocker_reason,raw_text,detail_text,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,'DETECTED',?,?,?,?,?,?,?,?,?)""",
                (
                    source, str(external_id), source_url or candidate.get("source_url"), candidate.get("detail_url"), candidate.get("date"),
                    company_name, agency, contract_ref, confidence.get("label", "LOW"),
                    float(confidence.get("score", 0)), priority, diagnosis["primary_blocker"], diagnosis["reason"],
                    candidate.get("raw_text"), candidate.get("detail_text"), now, now,
                ),
            )
            case_id = cur.lastrowid
            created = True

        for problem in problems:
            _upsert_problem(conn, case_id, problem)
        for amount in amounts:
            conn.execute(
                "INSERT OR IGNORE INTO case_amounts(case_id,amount_clp,provenance,note) VALUES(?,?,'public_record',NULL)",
                (case_id, int(amount)),
            )

        _seed_resolution_plan(conn, case_id, diagnosis)
        if created:
            event_date = candidate.get("date") or date.today().isoformat()
            conn.execute(
                """INSERT INTO timeline_events(case_id,event_type,event_date,title,details,source_url,created_at)
                   VALUES(?,'DETECTED',?,'Caso detectado desde fuente pública',?,?,?)""",
                (case_id, event_date, diagnosis["reason"], candidate.get("detail_url") or source_url, now),
            )

    return {"case": get_case(case_id, db_path), "created": created}


def import_scan_result(scan_result, db_path=None):
    created = 0
    updated = 0
    ids = []
    for candidate in scan_result.get("candidates", []):
        result = import_candidate(candidate, scan_result.get("source", "UNKNOWN"), scan_result.get("source_url"), db_path)
        ids.append(result["case"]["id"])
        if result["created"]:
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated, "case_ids": ids}


def _fetch_case_children(conn, case_id):
    problems = []
    for row in conn.execute("SELECT type, matched_patterns FROM case_problems WHERE case_id=? ORDER BY type", (case_id,)):
        problems.append({"type": row["type"], "matched_patterns": json_loads(row["matched_patterns"], [])})
    amounts = [row["amount_clp"] for row in conn.execute("SELECT amount_clp FROM case_amounts WHERE case_id=? ORDER BY amount_clp DESC", (case_id,))]
    documents = [row_to_dict(row) for row in conn.execute("SELECT * FROM documents WHERE case_id=? ORDER BY required DESC,name", (case_id,))]
    actions = [row_to_dict(row) for row in conn.execute("SELECT * FROM actions WHERE case_id=? ORDER BY CASE status WHEN 'TODO' THEN 0 WHEN 'DONE' THEN 1 ELSE 2 END, due_date IS NULL, due_date, id", (case_id,))]
    timeline = [row_to_dict(row) for row in conn.execute("SELECT * FROM timeline_events WHERE case_id=? ORDER BY event_date DESC,id DESC", (case_id,))]
    return problems, amounts, documents, actions, timeline


def get_case(case_id, db_path=None):
    with transaction(db_path) as conn:
        row = conn.execute(
            """SELECT k.*, c.name company_name, c.rut company_rut FROM cases k
               LEFT JOIN companies c ON c.id=k.company_id WHERE k.id=?""",
            (case_id,),
        ).fetchone()
        if row is None:
            raise KeyError("Caso no encontrado")
        result = row_to_dict(row)
        problems, amounts, documents, actions, timeline = _fetch_case_children(conn, case_id)
    result["problems"] = problems
    result["amounts_clp"] = amounts
    result["financial"] = summarize_amounts(amounts)
    result["documents"] = documents
    result["actions"] = actions
    result["timeline"] = timeline
    result["playbook"] = build_playbook(
        result.get("current_blocker"),
        [p["type"] for p in problems],
        documents,
        actions,
    )
    return result


def list_cases(status=None, company_id=None, search=None, db_path=None):
    clauses = []
    params = []
    if status:
        clauses.append("k.status=?")
        params.append(status)
    if company_id:
        clauses.append("k.company_id=?")
        params.append(company_id)
    if search:
        clauses.append("(k.detected_company_name LIKE ? OR k.contract_ref LIKE ? OR k.external_id LIKE ?)")
        token = f"%{search}%"
        params.extend([token, token, token])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with transaction(db_path) as conn:
        rows = conn.execute(
            f"""SELECT k.id,k.source,k.external_id,k.event_date,k.detected_company_name,k.contract_ref,k.status,
                       k.confidence_label,k.financial_priority,k.current_blocker,k.detail_url,k.company_id,c.name company_name,
                       COALESCE(MAX(a.amount_clp),0) largest_amount_clp,
                       COUNT(DISTINCT CASE WHEN ac.status='TODO' THEN ac.id END) open_actions
                FROM cases k
                LEFT JOIN companies c ON c.id=k.company_id
                LEFT JOIN case_amounts a ON a.case_id=k.id
                LEFT JOIN actions ac ON ac.case_id=k.id
                {where}
                GROUP BY k.id ORDER BY k.financial_priority DESC,k.event_date DESC,k.id DESC""",
            params,
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def update_case_status(case_id, status, db_path=None):
    if status not in VALID_CASE_STATUSES:
        raise ValueError("Estado de caso no válido")
    now = utc_now()
    with transaction(db_path) as conn:
        row = conn.execute("SELECT status FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            raise KeyError("Caso no encontrado")
        old = row["status"]
        conn.execute("UPDATE cases SET status=?,updated_at=? WHERE id=?", (status, now, case_id))
        if old != status:
            conn.execute(
                "INSERT INTO timeline_events(case_id,event_type,event_date,title,details,created_at) VALUES(?,?,?,?,?,?)",
                (case_id, "STATUS_CHANGED", date.today().isoformat(), f"Estado cambiado a {status}", f"Estado anterior {old}", now),
            )
    return get_case(case_id, db_path)


def update_case_blocker(case_id, blocker, reason=None, db_path=None):
    valid = set(PLAYBOOKS) | {"UNKNOWN_BLOCKER"}
    if blocker not in valid:
        raise ValueError("Bloqueo no válido")
    now = utc_now()
    with transaction(db_path) as conn:
        row = conn.execute("SELECT current_blocker FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            raise KeyError("Caso no encontrado")
        old = row["current_blocker"]
        playbook = get_playbook(blocker)
        blocker_reason = (reason or "").strip() or playbook.goal
        conn.execute(
            "UPDATE cases SET current_blocker=?,blocker_reason=?,status='BLOCKER_IDENTIFIED',updated_at=? WHERE id=?",
            (blocker, blocker_reason, now, case_id),
        )
        diagnosis = {"primary_blocker": blocker, "documents": [], "actions": []}
        problem_rows = conn.execute("SELECT type FROM case_problems WHERE case_id=?", (case_id,)).fetchall()
        detected = diagnose([r["type"] for r in problem_rows])
        diagnosis["documents"] = detected["documents"]
        diagnosis["actions"] = detected["actions"]
        _seed_resolution_plan(conn, case_id, diagnosis)
        if old != blocker:
            conn.execute(
                "INSERT INTO timeline_events(case_id,event_type,event_date,title,details,created_at) VALUES(?,?,?,?,?,?)",
                (case_id, "BLOCKER_CONFIRMED", date.today().isoformat(), f"Bloqueo confirmado: {blocker}", blocker_reason, now),
            )
    return get_case(case_id, db_path)


def link_case_company(case_id, company_id, db_path=None):
    get_company(company_id, db_path)
    with transaction(db_path) as conn:
        if conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone() is None:
            raise KeyError("Caso no encontrado")
        conn.execute("UPDATE cases SET company_id=?,updated_at=? WHERE id=?", (company_id, utc_now(), case_id))
    return get_case(case_id, db_path)


def update_document(document_id, status, note=None, db_path=None):
    if status not in VALID_DOCUMENT_STATUSES:
        raise ValueError("Estado documental no válido")
    with transaction(db_path) as conn:
        row = conn.execute("SELECT case_id,name FROM documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            raise KeyError("Documento no encontrado")
        conn.execute("UPDATE documents SET status=?,note=?,updated_at=? WHERE id=?", (status, note, utc_now(), document_id))
        if status in {"PRESENT", "MISSING", "REQUESTED"}:
            conn.execute(
                "INSERT INTO timeline_events(case_id,event_type,event_date,title,details,created_at) VALUES(?,?,?,?,?,?)",
                (row["case_id"], "DOCUMENT", date.today().isoformat(), f"Documento {status.lower()}", row["name"], utc_now()),
            )
    return get_case(row["case_id"], db_path)


def create_action(case_id, title, action_type="MANUAL", due_date=None, responsible=None, note=None, db_path=None):
    clean = (title or "").strip()
    if not clean:
        raise ValueError("El título de la acción es obligatorio")
    with transaction(db_path) as conn:
        if conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone() is None:
            raise KeyError("Caso no encontrado")
        cur = conn.execute(
            "INSERT INTO actions(case_id,action_type,title,status,due_date,responsible,note,created_at) VALUES(?,?,?,'TODO',?,?,?,?)",
            (case_id, action_type, clean, due_date, responsible, note, utc_now()),
        )
        action_id = cur.lastrowid
    return get_action(action_id, db_path)


def get_action(action_id, db_path=None):
    with transaction(db_path) as conn:
        row = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
    if row is None:
        raise KeyError("Acción no encontrada")
    return row_to_dict(row)


def update_action(action_id, status, note=None, db_path=None):
    if status not in VALID_ACTION_STATUSES:
        raise ValueError("Estado de acción no válido")
    now = utc_now()
    with transaction(db_path) as conn:
        row = conn.execute("SELECT case_id,title FROM actions WHERE id=?", (action_id,)).fetchone()
        if row is None:
            raise KeyError("Acción no encontrada")
        completed = now if status == "DONE" else None
        conn.execute("UPDATE actions SET status=?,note=COALESCE(?,note),completed_at=? WHERE id=?", (status, note, completed, action_id))
        conn.execute(
            "INSERT INTO timeline_events(case_id,event_type,event_date,title,details,created_at) VALUES(?,?,?,?,?,?)",
            (row["case_id"], "ACTION", date.today().isoformat(), f"Acción {status.lower()}", row["title"], now),
        )
    return get_action(action_id, db_path)


def add_timeline_event(case_id, title, details=None, event_type="NOTE", event_date=None, source_url=None, db_path=None):
    clean = (title or "").strip()
    if not clean:
        raise ValueError("El título del evento es obligatorio")
    with transaction(db_path) as conn:
        if conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone() is None:
            raise KeyError("Caso no encontrado")
        cur = conn.execute(
            "INSERT INTO timeline_events(case_id,event_type,event_date,title,details,source_url,created_at) VALUES(?,?,?,?,?,?,?)",
            (case_id, event_type, event_date or date.today().isoformat(), clean, details, source_url, utc_now()),
        )
        event_id = cur.lastrowid
    return {"id": event_id, "case_id": case_id, "title": clean}


def apply_resolution_playbook(case_id, db_path=None):
    with transaction(db_path) as conn:
        row = conn.execute("SELECT current_blocker FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            raise KeyError("Caso no encontrado")
        problem_rows = conn.execute("SELECT type FROM case_problems WHERE case_id=?", (case_id,)).fetchall()
        problem_types = [r["type"] for r in problem_rows]
        diagnosis = diagnose(problem_types)
        if row["current_blocker"]:
            diagnosis["primary_blocker"] = row["current_blocker"]
        _seed_resolution_plan(conn, case_id, diagnosis)
        conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (utc_now(), case_id))
    return get_case(case_id, db_path)


def dashboard(db_path=None):
    with transaction(db_path) as conn:
        totals = conn.execute(
            """SELECT COUNT(*) total_cases,
                      COALESCE(SUM(CASE WHEN status='RESOLVED' THEN 1 ELSE 0 END),0) resolved_cases,
                      COALESCE(SUM(CASE WHEN status NOT IN ('RESOLVED','DISMISSED') THEN 1 ELSE 0 END),0) active_cases,
                      COALESCE(SUM(CASE WHEN status NOT IN ('RESOLVED','DISMISSED') THEN financial_priority ELSE 0 END),0) priority_points
               FROM cases"""
        ).fetchone()
        amount = conn.execute(
            """SELECT COALESCE(MAX(amount_clp),0) largest_observed_amount_clp,
                      COALESCE(SUM(amount_clp),0) sum_observed_amounts_clp
               FROM case_amounts"""
        ).fetchone()
        open_actions = conn.execute("SELECT COUNT(*) count FROM actions WHERE status='TODO'").fetchone()["count"]
        missing_docs = conn.execute("SELECT COUNT(*) count FROM documents WHERE status='MISSING'").fetchone()["count"]
        blockers = conn.execute(
            "SELECT current_blocker blocker,COUNT(*) count FROM cases WHERE status NOT IN ('RESOLVED','DISMISSED') GROUP BY current_blocker ORDER BY count DESC"
        ).fetchall()
    return {
        **row_to_dict(totals),
        **row_to_dict(amount),
        "open_actions": open_actions,
        "missing_documents": missing_docs,
        "blockers": [row_to_dict(row) for row in blockers],
        "amount_warning": "Los montos observados no equivalen automáticamente a dinero recuperable.",
    }
