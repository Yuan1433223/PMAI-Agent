"""A resumable investigation. Each source page describes one identified job."""
import json
import re

from .lists import provenance


FIELDS = ("role", "city", "cohort", "validity")


class UnsupportedCompany(ValueError):
    """No installed discovery adapter covers this company name."""


def setup(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS investigations (
            id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies,
            config TEXT NOT NULL, phase TEXT NOT NULL, queue TEXT NOT NULL DEFAULT '[]',
            discovery TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS visits (
            run INTEGER NOT NULL REFERENCES investigations, url TEXT NOT NULL,
            job TEXT, title TEXT, body TEXT, status TEXT NOT NULL, note TEXT NOT NULL,
            captured TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(run,url)
        );
        CREATE TABLE IF NOT EXISTS claims (
            run INTEGER NOT NULL, url TEXT NOT NULL, field TEXT NOT NULL, verdict TEXT NOT NULL,
            quote TEXT NOT NULL, offset INTEGER NOT NULL, PRIMARY KEY(run,url,field),
            FOREIGN KEY(run,url) REFERENCES visits(run,url)
        );
        CREATE TABLE IF NOT EXISTS verified_sources (
            run INTEGER NOT NULL, url TEXT NOT NULL, kind TEXT NOT NULL,
            employer_quote TEXT NOT NULL, snapshot TEXT,
            PRIMARY KEY(run,url), FOREIGN KEY(run,url) REFERENCES visits(run,url)
        );
    """)


def create(db, company_id, config):
    setup(db)
    if not 1 <= config["limit"] <= 20:
        raise ValueError("页数上限必须在 1 到 20 之间")
    with db:
        return db.execute("INSERT INTO investigations(company_id,config,phase) VALUES(?,?,'discover')",
                          (company_id, json.dumps(config))).lastrowid


def get_run(db, run):
    row = db.execute("""SELECT i.*, c.raw_name AS company FROM investigations i
                        JOIN companies c ON c.id=i.company_id WHERE i.id=?""", (run,)).fetchone()
    if row is None:
        raise ValueError(f"调查不存在: {run}")
    return dict(row)


def check_claims(body, response):
    if not isinstance(response, dict) or set(response) - set(FIELDS):
        raise ValueError("模型输出字段不符合契约")
    claims = []
    for field, item in response.items():
        if item is None:
            continue
        if not isinstance(item, dict):
            raise ValueError("判断格式错误")
        quote = item.get("quote")
        verdict = item.get("verdict")
        if verdict not in ("supports", "contradicts") or not isinstance(quote, str) or not quote.strip():
            raise ValueError("判断缺少有效状态或引文")
        offset = body.find(quote)
        if offset < 0:
            raise ValueError(f"{field} 引文不在该岗位快照中")
        if field == "city" and re.search(r"有限公司|股份公司|总部|单位地址|办公地址|企业名称", quote):
            continue
        if field == "cohort" and not re.search(r"毕业|应届|\d{4}\s*届|graduat|class of", quote, re.I):
            continue
        if field == "validity" and not re.search(
                r"已截止|招聘中|已关闭|停止招募|暂停招聘|currently open|no longer accepting|applications? (?:are )?closed",
                quote, re.I):
            continue
        claims.append((field, verdict, quote, offset))
    return claims


def step(db, run, source, model):
    # Serialize one bounded step. A crash rolls it back; completed steps survive.
    with db:
        db.execute("BEGIN IMMEDIATE")
        state = get_run(db, run)
        phase = state["phase"]
        if phase == "done":
            return False
        config = json.loads(state["config"])
        queue = json.loads(state["queue"])
        if phase == "discover":
            try:
                queue = list(dict.fromkeys(source.discover(state["company"], config)))
                status = "found" if queue else "not_found"
                reason = "" if queue else "未找到入口或岗位"
            except UnsupportedCompany as exc:
                status, reason = "not_investigated", str(exc)
            except (OSError, ValueError) as exc:
                status, reason = "inaccessible", str(exc)
            db.execute("UPDATE investigations SET queue=?,phase=?,discovery=?,reason=? WHERE id=?",
                       (json.dumps(queue), "visit" if queue else "done", status, reason, run))
            return True
        count = db.execute("SELECT COUNT(*) FROM visits WHERE run=?", (run,)).fetchone()[0]
        if count >= config["limit"]:
            db.execute("UPDATE investigations SET phase='done',reason='达到页数上限' WHERE id=?", (run,))
            return True
        url = queue.pop(0)
        job = title = body = None
        claims = []
        note = ""
        status = "inaccessible"
        source_evidence = None
        try:
            page = source.fetch(url, state["company"])
            job, title, body = page["job"], page["title"], page["body"]
            if not body.strip():
                raise ValueError("正文为空")
            source_evidence = page.get("source")
            status = "unverified" if job else "verified_entrance"
            if source_evidence and source_evidence["kind"] == "business":
                quote = page.get("business_quote", "")
                offset = body.find(quote) if quote else -1
                if offset < 0:
                    source_evidence = None
                    status = "unverified"
                    raise ValueError("业务引文不在原文快照中")
                claims.append(("business", "supports", quote, offset))
                status = "verified_business"
            response = model.assess(body, config) if job else {}
            if not isinstance(response, dict):
                raise ValueError("模型输出应为字段对象")
            rejected = []
            for field, item in response.items():
                try:
                    claims.extend(check_claims(body, {field: item}))
                except ValueError as exc:
                    rejected.append(str(exc))
            if job:
                status = "assessed" if not rejected or claims else "unverified"
            note = "；".join(rejected)
            # Supplement only an already relevant job and only for an explicit target cohort.
            known = {item[0]: item[1] for item in claims}
            if known.get("role") == "supports" and config.get("cohort") and "cohort" not in known:
                extra = page.get("cohort_url")
                visited = db.execute("SELECT 1 FROM visits WHERE run=? AND url=?", (run, extra)).fetchone()
                if extra and extra != url and extra not in queue and not visited:
                    queue.insert(0, extra)
        except (ValueError, OSError) as exc:
            note = str(exc)
        db.execute("INSERT INTO visits(run,url,job,title,body,status,note) VALUES(?,?,?,?,?,?,?)",
                   (run, url, job, title, body, status, note))
        if source_evidence:
            db.execute("INSERT INTO verified_sources VALUES(?,?,?,?,?)",
                       (run, url, source_evidence["kind"], source_evidence["employer_quote"],
                        source_evidence.get("snapshot")))
        db.executemany("INSERT INTO claims VALUES(?,?,?,?,?,?)", [(run, url, *c) for c in claims])
        db.execute("UPDATE investigations SET phase=?,queue=?,reason=? WHERE id=?",
                   ("visit" if queue else "done", json.dumps(queue), "" if queue else "材料已查完", run))
        return True


def run_to_end(db, run, source, model):
    while step(db, run, source, model):
        pass
    return report(db, run)


def report(db, run):
    state = get_run(db, run)
    config = json.loads(state["config"])
    pages, jobs = [], {}
    for visit in db.execute("SELECT * FROM visits WHERE run=? ORDER BY rowid", (run,)):
        page = dict(visit)
        page["claims"] = [dict(r) for r in db.execute(
            "SELECT field,verdict,quote,offset FROM claims WHERE run=? AND url=?", (run, page["url"]))]
        source = db.execute("SELECT kind,employer_quote,snapshot FROM verified_sources WHERE run=? AND url=?",
                            (run, page["url"])).fetchone()
        if source:
            page["source"] = dict(source)
        pages.append(page)
        if page["job"] is None:
            continue
        job = jobs.setdefault(page["job"], {"job": page["job"], "title": page["title"], "fields": {}})
        experience = required_experience(page["body"] or "")
        if experience:
            job.setdefault("experience", {"quote": experience, "url": page["url"]})
        for claim in page["claims"]:
            job["fields"].setdefault(claim["field"], []).append(dict(claim, url=page["url"]))
    for job in jobs.values():
        states = {field: {c["verdict"] for c in values} for field, values in job["fields"].items()}
        job["unknown"] = [field for field in FIELDS if field not in states]
        if any(len(values) > 1 for values in states.values()):
            job["tier"] = "证据冲突，待核查"
        elif any("contradicts" in values for values in states.values()):
            job["tier"] = "明确不匹配"
        elif "supports" in states.get("role", set()):
            job["tier"] = "有招聘依据"
        else:
            job["tier"] = "待确认机会"
    return {"id": run, "company": state["company"], "phase": state["phase"], "reason": state["reason"],
            "company_source": provenance(db, state["company_id"]),
            "discovery": state["discovery"], "config": config, "jobs": list(jobs.values()), "pages": pages}


def required_experience(body):
    for line in body.splitlines():
        # A structured header can explicitly give a years range with no “经验” suffix.
        header = re.match(r"^\s*(?:[\u4e00-\u9fff]+[-－][\u4e00-\u9fff]+|深圳市?)\s+"
                          r"([1-9]\d*\s*(?:[-–至]\s*\d+\s*年|年及?以上))", line)
        if header:
            return header.group(0).strip()
        clauses = re.split(r"[；。;\n]", line)
        for clause in clauses:
            match = re.search(r"(?:[1-9]\d*\s*年(?:及?以上)?[^。\n]{0,28}经验|"
                              r"[1-9]\d*\+?\s+years.{0,35}experience)", clause, re.I)
            if match and not re.search(r"优先|加分|可放宽|preferred|nice to have", clause, re.I):
                return match.group(0)
    return None
