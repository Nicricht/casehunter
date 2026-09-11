import argparse
import json
import sys
import unittest

import uvicorn

from .config import DEFAULT_LEY_LOBBY_URL
from .database import init_db
from .scanner_service import run_ley_lobby_scan
from .auto_service import run_auto_cycle, run_daemon
from .followup import process_due_followups
from .pilot_metrics import pilot_funnel, start_pilot
from .pilot_watch import build_watchlist
from .portfolio_watch import list_portfolios
from .reply_monitor import sync_replies


def run_tests():
    suite = unittest.defaultTestLoader.discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog="case-hunter", description="Case Hunter Resolve")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Inicializa la base de datos")
    sub.add_parser("verify", help="Ejecuta la suite de pruebas")

    serve = sub.add_parser("serve", help="Inicia la aplicación web local")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    auto = sub.add_parser("auto", help="Ejecuta Case Hunter Auto")
    auto.add_argument("--daemon", action="store_true", help="Mantiene ciclos automáticos en ejecución")
    auto.add_argument("--interval-minutes", type=int, default=None)

    sub.add_parser("mail-sync", help="Lee Gmail/IMAP, clasifica respuestas y actualiza casos")

    followups = sub.add_parser("followups", help="Procesa seguimientos vencidos")
    followups.add_argument("--send", action="store_true", help="Envía seguimientos vencidos si Gmail/SMTP está configurado")

    watchlist = sub.add_parser("watchlist", help="Prioriza casos activos y muestra la siguiente acción")
    watchlist.add_argument("--search", default=None, help="Filtra por empresa, contrato o identificador")
    watchlist.add_argument("--limit", type=int, default=20, help="Máximo de casos a mostrar")

    portfolios = sub.add_parser("portfolios", help="Agrupa empresas con múltiples casos activos para seguimiento recurrente")
    portfolios.add_argument("--search", default=None, help="Filtra por empresa, contrato o identificador")
    portfolios.add_argument("--min-cases", type=int, default=2, help="Cantidad mínima de casos para considerar una cartera recurrente")
    portfolios.add_argument("--all-statuses", action="store_true", help="Incluye también casos fuera de estados activos")

    pilot_metrics = sub.add_parser("pilot-metrics", help="Muestra el embudo medible de validación comercial")
    pilot_metrics.add_argument("--limit", type=int, default=100, help="Máximo de casos a evaluar")

    pilot_start = sub.add_parser("pilot-start", help="Marca un caso como piloto activo")
    pilot_start.add_argument("case_id", type=int, help="ID del caso")
    pilot_start.add_argument("--note", default=None, help="Contexto de aceptación del piloto")

    scan = sub.add_parser("scan", help="Ejecuta un escaneo de Ley del Lobby")
    scan.add_argument("url", nargs="?", default=DEFAULT_LEY_LOBBY_URL)
    scan.add_argument("--max-pages", type=int, default=10)
    scan.add_argument("--no-enrich", action="store_true")
    scan.add_argument("--enrich-limit", type=int, default=25)

    args = parser.parse_args(argv)
    if args.command == "init":
        init_db()
        print("Base de datos inicializada")
        return 0
    if args.command == "verify":
        return run_tests()
    if args.command == "serve":
        init_db()
        uvicorn.run("casehunter.webapp:app", host=args.host, port=args.port, reload=False)
        return 0
    if args.command == "auto":
        init_db()
        if args.daemon:
            run_daemon(args.interval_minutes)
            return 0
        result = run_auto_cycle()
        print(json.dumps({k: v for k, v in result.items() if k != "queue"}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "mail-sync":
        init_db()
        print(json.dumps(sync_replies(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "followups":
        init_db()
        print(json.dumps(process_due_followups(send=args.send), ensure_ascii=False, indent=2))
        return 0
    if args.command == "watchlist":
        init_db()
        print(json.dumps(build_watchlist(search=args.search, limit=args.limit), ensure_ascii=False, indent=2))
        return 0
    if args.command == "portfolios":
        init_db()
        print(json.dumps(
            list_portfolios(
                min_cases=args.min_cases,
                active_only=not args.all_statuses,
                search=args.search,
            ),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    if args.command == "pilot-metrics":
        init_db()
        print(json.dumps(pilot_funnel(limit=args.limit), ensure_ascii=False, indent=2))
        return 0
    if args.command == "pilot-start":
        init_db()
        try:
            print(json.dumps(start_pilot(args.case_id, args.note), ensure_ascii=False, indent=2))
            return 0
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "scan":
        init_db()
        result = run_ley_lobby_scan(args.url, args.max_pages, not args.no_enrich, args.enrich_limit)
        print(json.dumps({
            "scan_id": result["scan_id"],
            "pages_scanned": result["scan"]["pages_scanned"],
            "candidate_count": result["scan"]["candidate_count"],
            **result["import"],
        }, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
