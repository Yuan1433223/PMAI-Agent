import hashlib
import io
import re
import sqlite3
import unicodedata
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
        CREATE TABLE IF NOT EXISTS official_lists (
            document_id INTEGER PRIMARY KEY REFERENCES document_snapshots,
            city TEXT NOT NULL, year INTEGER NOT NULL, status TEXT NOT NULL,
            publication TEXT NOT NULL, attachment TEXT NOT NULL,
            parser_version TEXT NOT NULL, original_pdf BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS entry_positions (
            document_id INTEGER NOT NULL, row_no INTEGER NOT NULL,
            line_no INTEGER NOT NULL, raw_line TEXT NOT NULL,
            PRIMARY KEY(document_id, row_no),
            FOREIGN KEY(document_id, row_no) REFERENCES source_entries
        );
    """)
    return db


def parse_pages(pages, official=None):
    rows = []
    for page_no, text in enumerate(pages, 1):
        start = len(rows)
        for line_no, raw_line in enumerate(text.splitlines(), 1):
            line = raw_line.strip()
            if not line or re.fullmatch(r"(?:序号\s*(?:企业名称|单位名称)|No\.\s+Company)", line):
                continue
            if official and page_no == 1 and line in {"附件1", "附件 1", official.title}:
                continue
            match = re.fullmatch(r"(\d+)[\s、.]+(.+)", line)
            if not match or int(match[1]) != len(rows) + 1:
                raise ValueError(f"第 {page_no} 页，预期序号 {len(rows)+1}，遇到 {line!r}")
            name = match[2].strip()
            if official and ("\ufffd" in name or not re.search(r"[\u3400-\u9fffA-Za-z]", name)):
                raise ValueError(f"第 {page_no} 页第 {line_no} 行企业名不可读")
            rows.append((len(rows) + 1, page_no, name, line_no, raw_line))
        if len(rows) == start:
            raise ValueError(f"第 {page_no} 页没有可读取的名单行")
    if not rows:
        raise ValueError("名单为空")
    if official and len(rows) != official.count:
        raise ValueError(f"名单应有 {official.count} 条，实际读取 {len(rows)} 条")
    return rows


def import_list(db, path, official=None):
    path = Path(path)
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if official and digest != official.digest:
        raise ValueError("原件 SHA-256 与已核实的官方附件不符")
    try:
        reader = PdfReader(io.BytesIO(data), strict=bool(official))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF 需要密码")
        rows = parse_pages((page.extract_text() or "" for page in reader.pages), official)
    except PdfReadError as exc:
        raise ValueError(f"PDF 无法读取: {exc}") from exc
    with db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT id FROM document_snapshots WHERE digest=?", (digest,)).fetchone()
        if existing:
            doc = existing["id"]
        else:
            doc = db.execute("INSERT INTO document_snapshots(digest, filename) VALUES (?,?)",
                             (digest, path.name)).lastrowid
            for number, page, name, _, _ in rows:
                company = db.execute("INSERT INTO companies(raw_name) VALUES (?)", (name,)).lastrowid
                db.execute("INSERT INTO source_entries VALUES (?,?,?,?,?)", (doc, number, page, name, company))
        if official:
            db.execute("INSERT OR IGNORE INTO official_lists VALUES (?,?,?,?,?,?,?,?)",
                       (doc, official.city, official.year, official.status, official.publication,
                        official.attachment, "sz-2025-text-v1", data))
            db.executemany("INSERT OR IGNORE INTO entry_positions VALUES (?,?,?,?)",
                           [(doc, number, line, raw) for number, _, _, line, raw in rows])
    return doc


def city_document(db, official):
    row = db.execute("""SELECT l.document_id FROM official_lists l
                        JOIN document_snapshots d ON d.id=l.document_id
                        WHERE l.city=? AND d.digest=?""", (official.city, official.digest)).fetchone()
    return row["document_id"] if row else None


def manual_company(db, name):
    name = name.strip()
    if not name:
        raise ValueError("企业名称不能为空")
    with db:
        db.execute("BEGIN IMMEDIATE")
        key = unicodedata.normalize("NFKC", name).casefold()
        for row in db.execute("""SELECT c.id, c.raw_name FROM companies c
                                 WHERE NOT EXISTS (SELECT 1 FROM source_entries e WHERE e.company_id=c.id)
                                 ORDER BY c.id"""):
            if unicodedata.normalize("NFKC", row["raw_name"]).casefold() == key:
                return row["id"]
        return db.execute("INSERT INTO companies(raw_name) VALUES(?)", (name,)).lastrowid


def provenance(db, company_id):
    row = db.execute("""SELECT d.id AS document_id, d.digest, l.city, l.year, l.status,
                               l.publication, l.attachment, e.row_no, e.page_no, p.line_no
                        FROM source_entries e JOIN document_snapshots d ON d.id=e.document_id
                        LEFT JOIN official_lists l ON l.document_id=d.id
                        LEFT JOIN entry_positions p ON p.document_id=d.id AND p.row_no=e.row_no
                        WHERE e.company_id=?""", (company_id,)).fetchone()
    return dict(row) if row else None


def entries(db, doc):
    return [dict(row) for row in db.execute(
        "SELECT * FROM source_entries WHERE document_id=? ORDER BY row_no", (doc,))]
