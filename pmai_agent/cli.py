import argparse
import json
import sqlite3
import sys
from contextlib import closing

from .lists import connect, entries, import_list
from .investigation import report, run_to_end, setup
from .replay import Replay, demo


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pmai")
    parser.add_argument("--db", default="data/app.sqlite3")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("import-list").add_argument("pdf")
    subs.add_parser("list").add_argument("document", type=int)
    subs.add_parser("demo")
    for name in ("show", "resume"):
        subs.add_parser(name).add_argument("run", type=int)
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
            else:
                setup(db)
                result = report(db, args.run)
                if args.command == "resume":
                    replay = Replay()
                    result = run_to_end(db, args.run, replay, replay)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0
