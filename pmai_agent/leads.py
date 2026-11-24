"""Persistent local job-search leads, linked to the investigations that found them."""
import csv
import io
import re
import unicodedata

from .investigation import get_run, report


STAGES = {
    "pending": "待搜索",
    "known": "已知",
    "verified": "已在招聘软件确认",
    "applied": "已投递",
}


def setup_leads(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS saved_leads (
            id INTEGER PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies,
            job TEXT NOT NULL,
            job_title TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT 'pending',
            note TEXT NOT NULL DEFAULT '',
            first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TEXT,
            UNIQUE(company_id, job)
        );
        CREATE TABLE IF NOT EXISTS lead_observations (
            lead_id INTEGER NOT NULL REFERENCES saved_leads,
            run INTEGER NOT NULL REFERENCES investigations,
            reason TEXT NOT NULL,
            quote TEXT NOT NULL,
            source_url TEXT NOT NULL,
            search_terms TEXT NOT NULL,
            evidence_rank INTEGER NOT NULL,
            PRIMARY KEY(lead_id, run)
        );
    """)


def supporting_evidence(result, job):
    for item in result["jobs"] if not job else [job]:
        for claim in item["fields"].get("role", []):
            if claim["verdict"] == "supports":
                return ("发现相关岗位，可继续搜该企业", claim["quote"], claim["url"], 3)
    if job:
        for page in result["pages"]:
            if page["job"] == job["job"] and page["body"]:
                return ("有岗位原文，匹配条件待核查", job["title"], page["url"], 2)
    for page in result["pages"]:
        if page.get("source", {}).get("kind") == "business":
            for claim in page["claims"]:
                if claim["field"] == "business":
                    return ("有相关业务证据，岗位和届别待搜索", claim["quote"], page["url"], 3)
    for page in result["pages"]:
        if "source" in page:
            return ("已核实招聘入口，相关岗位待搜索", page["source"]["employer_quote"], page["url"], 1)
    origin = result["company_source"]
    if origin and origin["publication"]:
        location = f'第 {origin["page_no"]} 页，序号 {origin["row_no"]}'
        return ("来自城市官方候选名单，业务和招聘待核查", location, origin["publication"], 0)
    return ("来自本地调查，相关性待核查", "", "", 0)


def documented_alias(company, identity_quote):
    text = unicodedata.normalize("NFKC", identity_quote or "")
    name = unicodedata.normalize("NFKC", company)
    match = re.search(re.escape(name) + r"\*{0,2}\s*\(\s*(?:以下)?简称\s*[“\"「]([^”\"」\r\n]{1,40})[”\"」]", text)
    return match[1].strip() if match else ""


def save_lead(db, run_id, job_key=""):
    run = get_run(db, run_id)
    result = report(db, run_id)
    job = next((j for j in result["jobs"] if j["job"] == job_key), None) if job_key else None
    if job_key and not job:
        raise ValueError("该岗位不属于本次调查")
    title = job["title"] if job else ""
    reason, quote, url, rank = supporting_evidence(result, job)
    identity_quote = next((page.get("source", {}).get("employer_quote")
                           for page in result["pages"] if page["url"] == url), None)
    alias = documented_alias(result["company"], identity_quote)
    directions = [title] if title else re.split(r"[/／、|]+", result["config"].get("role") or "")
    names = [result["company"], alias] if alias else [result["company"]]
    terms = "\n".join(dict.fromkeys(f"{name} {item.strip()}".rstrip()
                                   for name in names for item in directions))
    with db:
        db.execute("INSERT INTO saved_leads(company_id,job,job_title) VALUES(?,?,?) "
                   "ON CONFLICT(company_id,job) DO NOTHING", (run["company_id"], job_key, title))
        lead_id = db.execute("SELECT id FROM saved_leads WHERE company_id=? AND job=?",
                             (run["company_id"], job_key)).fetchone()[0]
        db.execute("INSERT INTO lead_observations VALUES(?,?,?,?,?,?,?) ON CONFLICT(lead_id,run) "
                   "DO UPDATE SET reason=excluded.reason, quote=excluded.quote, source_url=excluded.source_url, "
                   "search_terms=excluded.search_terms, evidence_rank=excluded.evidence_rank",
                   (lead_id, run_id, reason, quote, url, terms, rank))
    return lead_id


def collect_business_lead(db, result):
    if any(page.get("source", {}).get("kind") == "business" for page in result["pages"]):
        setup_leads(db)
        return save_lead(db, result["id"])


def update_lead(db, lead_id, stage, note):
    if stage not in STAGES or len(note) > 2000:
        raise ValueError("清单状态或备注无效")
    with db:
        cursor = db.execute("UPDATE saved_leads SET stage=?, note=?, "
                            "reviewed_at=COALESCE(reviewed_at,CURRENT_TIMESTAMP) WHERE id=?",
                            (stage, note, lead_id))
        if cursor.rowcount != 1:
            raise ValueError("清单条目不存在")


def saved_leads(db, view="all"):
    conditions = {
        "inbox": "l.stage='pending'",
        "new": "l.reviewed_at IS NULL",
        "all": "1=1",
    }
    if view not in conditions and view not in STAGES:
        raise ValueError("清单筛选条件无效")
    condition = conditions.get(view, "l.stage=?")
    params = (view,) if view in STAGES else ()
    rows = [dict(row) for row in db.execute(f"""
        SELECT l.*, c.raw_name AS company, o.run, o.reason, o.quote, o.source_url, o.search_terms,
               source.employer_quote AS identity_quote,
               (SELECT COUNT(*) FROM lead_observations h WHERE h.lead_id=l.id) AS observations
        FROM saved_leads l JOIN companies c ON c.id=l.company_id
        JOIN lead_observations o ON o.lead_id=l.id AND o.run=(
            SELECT history.run FROM lead_observations history WHERE history.lead_id=l.id
            ORDER BY history.evidence_rank DESC, history.run DESC LIMIT 1
        )
        LEFT JOIN verified_sources source ON source.run=o.run AND source.url=o.source_url
        WHERE {condition}
        ORDER BY l.reviewed_at IS NOT NULL, l.id DESC
    """, params)]
    for row in rows:
        row["alias"] = documented_alias(row["company"], row["identity_quote"])
    return rows


def export_csv(rows):
    def cell(value):
        text = str(value)
        if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
            return "'" + text
        return text

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("企业全称", "网页所列简称", "岗位", "搜索词", "状态", "首次保存时间（UTC）", "发现依据",
                     "原文", "来源链接", "备注"))
    for row in rows:
        writer.writerow([cell(value) for value in (
            row["company"], row["alias"], row["job_title"], row["search_terms"], STAGES[row["stage"]],
            row["first_seen"], row["reason"], row["quote"], row["source_url"], row["note"],
        )])
    return "\ufeff" + output.getvalue()
