import hashlib
import io
import re
import sqlite3
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS document_snapshots (
            id INTEGER PRIMARY KEY, digest TEXT UNIQUE NOT NULL, filename TEXT NOT NULL,
            imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY, raw_name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source_entries (
            document_id INTEGER NOT NULL REFERENCES document_snapshots,
            row_no INTEGER NOT NULL, page_no INTEGER NOT NULL, raw_name TEXT NOT NULL,
            company_id INTEGER NOT NULL REFERENCES companies,
            PRIMARY KEY (document_id, row_no)
        );
    """)
    return db


def parse_pages(pages):
    rows = []
    for page_no, text in enumerate(pages, 1):
        start = len(rows)
        for line in text.splitlines():
            line = line.strip()
            if not line or re.fullmatch(r"(?:序号\s*(?:企业名称|单位名称)|No\.\s+Company)", line):
                continue
            match = re.fullmatch(r"(\d+)[\s、.]+(.+)", line)
            if not match or int(match[1]) != len(rows) + 1:
                raise ValueError(f"第 {page_no} 页，预期序号 {len(rows)+1}，遇到 {line!r}")
            rows.append((len(rows) + 1, page_no, match[2].strip()))
        if len(rows) == start:
            raise ValueError(f"第 {page_no} 页没有可读取的名单行")
    if not rows:
        raise ValueError("名单为空")
    return rows


def import_list(db, path):
    path = Path(path)
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(data))
        rows = parse_pages(page.extract_text() for page in reader.pages)
    except PdfReadError as exc:
        raise ValueError(f"PDF 无法读取: {exc}") from exc
    with db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT id FROM document_snapshots WHERE digest=?", (digest,)).fetchone()
        if existing:
            return existing["id"]
        doc = db.execute("INSERT INTO document_snapshots(digest, filename) VALUES (?,?)",
                         (digest, path.name)).lastrowid
        for number, page, name in rows:
            company = db.execute("INSERT INTO companies(raw_name) VALUES (?)", (name,)).lastrowid
            db.execute("INSERT INTO source_entries VALUES (?,?,?,?,?)", (doc, number, page, name, company))
    return doc


def entries(db, doc):
    return [dict(row) for row in db.execute(
        "SELECT * FROM source_entries WHERE document_id=? ORDER BY row_no", (doc,))]
