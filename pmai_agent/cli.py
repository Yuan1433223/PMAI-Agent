import argparse
import json
import sqlite3
import sys
from contextlib import closing

from .lists import connect, entries, import_list
from .investigation import report, run_to_end, setup
from .replay import Replay, demo
from .investigation import create
from .live import Models, PublicJobs, model_config, settings


def main(argv=None):
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
    live.add_argument("--city", default="深圳")
    live.add_argument("--role", default="Agent")
    live.add_argument("--cohort", default="")
    live.add_argument("--url")
    live.add_argument("--limit", type=int, default=3)
    args = parser.parse_args(argv)
    try:
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
                company = args.company_id
                if company is None:
                    with db:
                        company = db.execute("INSERT INTO companies(raw_name) VALUES(?)",
                                             (args.company,)).lastrowid
                run = create(db, company, config)
                print(f"investigation_id={run}", file=sys.stderr, flush=True)
                result = run_to_end(db, run, PublicJobs(), Models(values))
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
