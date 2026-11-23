import argparse
import json
import sqlite3
import sys
from contextlib import closing

from .lists import connect, entries, import_list


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pmai")
    parser.add_argument("--db", default="data/app.sqlite3")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("import-list").add_argument("pdf")
    subs.add_parser("list").add_argument("document", type=int)
    args = parser.parse_args(argv)
    try:
        with closing(connect(args.db)) as db:
            if args.command == "import-list":
                doc = import_list(db, args.pdf)
                result = {"document_id": doc, "rows": len(entries(db, doc))}
            else:
                result = entries(db, args.document)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0
