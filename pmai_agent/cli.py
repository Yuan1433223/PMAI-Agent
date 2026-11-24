import argparse
import json
import sqlite3
import sys
from contextlib import closing

from .lists import connect, entries, import_list
from .investigation import create, report, run_to_end, setup
from .replay import Replay, demo
from .live import Models, PublicJobs, model_config, settings


def main(argv=None):
    if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="pmai")
    parser.add_argument("--db", default="data/app.sqlite3")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("import-list").add_argument("pdf")
    subs.add_parser("list").add_argument("document", type=int)
    subs.add_parser("demo")
    for name in ("show", "resume"):
        subs.add_parser(name).add_argument("run", type=int)
    live = subs.add_parser("investigate")
    identity = live.add_mutually_exclusive_group(required=True)
    identity.add_argument("--company")
    identity.add_argument("--company-id", type=int)
    identity.add_argument("--document", type=int)
    live.add_argument("--first-row", type=int, default=1)
    live.add_argument("--count", type=int, default=1)
    live.add_argument("--city", default="深圳")
    live.add_argument("--role", default="Agent")
    live.add_argument("--cohort", default="")
    live.add_argument("--url")
    live.add_argument("--limit", type=int, default=3)
    subs.add_parser("review").add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        if args.command == "review":
            from .review import serve
            serve(args.db, args.port)
            return 0
        with closing(connect(args.db)) as db:
            if args.command == "import-list":
                doc = import_list(db, args.pdf)
                result = {"document_id": doc, "rows": len(entries(db, doc))}
            elif args.command == "list":
                result = entries(db, args.document)
            elif args.command == "demo":
                result = demo(db)
            elif args.command == "investigate":
                values = settings()
                config = dict(mode="live", city=args.city, role=args.role, cohort=args.cohort,
                              url=args.url, limit=args.limit, **model_config(values))
                if not config["complex_enabled"] and not config["local_model"]:
                    raise ValueError("请先参照 .env.example 配置模型")
                if not 1 <= args.count <= 20 or args.first_row < 1 or not 1 <= args.limit <= 20:
                    raise ValueError("每批 1 至 20 家，每家 1 至 20 页，起始序号至少为 1")
                model = Models(values)
                if args.document is not None:
                    if args.url:
                        raise ValueError("指定岗位链接时请选择单个企业")
                    companies = [r[0] for r in db.execute(
                        "SELECT company_id FROM source_entries WHERE document_id=? AND row_no>=? "
                        "ORDER BY row_no LIMIT ?", (args.document, args.first_row, args.count))]
                    if not companies:
                        raise ValueError("名单所选范围为空")
                elif args.company_id is not None:
                    companies = [args.company_id]
                else:
                    with db:
                        company = db.execute("INSERT INTO companies(raw_name) VALUES(?)",
                                             (args.company,)).lastrowid
                    companies = [company]
                runs = [create(db, company, config) for company in companies]
                print(f"investigation_ids={runs}", file=sys.stderr, flush=True)
                reports = [run_to_end(db, run, PublicJobs(), model) for run in runs]
                result = reports if args.document is not None else reports[0]
            else:
                setup(db)
                result = report(db, args.run)
                if args.command == "resume":
                    if result["config"]["mode"] == "live":
                        result = run_to_end(db, args.run, PublicJobs(), Models(settings()))
                    else:
                        replay = Replay()
                        result = run_to_end(db, args.run, replay, replay)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0
