"""Local review UI; reading a report never starts an investigation."""
import json
import secrets
from contextlib import closing
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from .investigation import report, setup
from .leads import STAGES, export_csv, save_lead, saved_leads, setup_leads, update_lead
from .lists import connect


LABELS = {"city": "工作地点", "role": "岗位方向", "cohort": "毕业届别", "validity": "有效性"}
ACTIONS = ("值得跟进", "原已知道", "判断有误", "暂缓")


def prepare(db):
    setup(db)
    setup_leads(db)
    db.execute("""CREATE TABLE IF NOT EXISTS feedback (
               id INTEGER PRIMARY KEY, run INTEGER NOT NULL REFERENCES investigations,
               job TEXT NOT NULL, action TEXT NOT NULL, note TEXT NOT NULL,
               created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")


def export(db, run):
    result = report(db, run)
    result["feedback"] = [dict(r) for r in db.execute(
        "SELECT job,action,note,created FROM feedback WHERE run=? ORDER BY id", (run,))]
    return result


def save(db, run, job, action, note):
    if action not in ACTIONS or len(note) > 2000:
        raise ValueError("反馈内容无效")
    if job and not db.execute("SELECT 1 FROM visits WHERE run=? AND job=?", (run, job)).fetchone():
        raise ValueError("该岗位不属于本次调查")
    with db:
        db.execute("INSERT INTO feedback(run,job,action,note) VALUES(?,?,?,?)", (run, job, action, note))


def link(url, label="打开招聘原页"):
    safe = escape(url, quote=True)
    if url.startswith(("https://", "http://")):
        return f'<a href="{safe}" rel="noreferrer">{escape(label)}</a>'
    return safe


def document(title, body):
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
<style>body{{max-width:64rem;margin:2rem auto;padding:0 1rem;font:16px/1.65 system-ui;color:#19302c}}
a{{color:#096452}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #cedbd6;
text-align:left;padding:.5rem}}article,details{{margin:1em 0;padding:.8em;border:1px solid #cedbd6}}
input,button,select{{font:inherit;margin:.25em}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}
nav a{{margin-right:1rem}}input.search-terms{{width:min(36rem,90%)}}blockquote{{margin-left:1rem}}</style>
<h1>{escape(title)}</h1>{body}</html>"""


def index(db, query=""):
    rows = []
    for row in db.execute("""SELECT i.id,c.raw_name,i.phase,i.reason,i.discovery FROM investigations i
                             JOIN companies c ON c.id=i.company_id ORDER BY i.id DESC"""):
        if query.casefold() not in row["raw_name"].casefold():
            continue
        rows.append(f'<tr><td><a href="/run?id={row["id"]}">{escape(row["raw_name"])}</a></td>'
                    f'<td>{row["id"]}</td><td>{escape(row["phase"])}</td>'
                    f'<td>{escape(row["reason"] or row["discovery"])}</td></tr>')
    return document("求职调查", f'<nav><a href="/leads">我的求职清单</a></nav>'
                    f'<form><input name="q" aria-label="企业名" placeholder="企业名" '
                    f'value="{escape(query)}"><button>筛选</button></form>'
                    '<table><tr><th>企业</th><th>调查</th><th>进度</th><th>结果</th></tr>'
                    + "".join(rows) + "</table>")


def detail(result, token):
    run = result["id"]
    config = result["config"]
    target = " · ".join(str(config[k]) for k in ("city", "role", "cohort") if config.get(k))
    parts = [f'<nav><a href="/">调查列表</a><a href="/leads">我的求职清单</a>'
             f'<a href="/export?id={run}">导出证据与反馈</a></nav>',
             f'<p>{escape(target)} · {escape(config["mode"])} · {escape(result["reason"] or result["phase"])}</p>']
    origin = result["company_source"]
    if origin and origin["publication"]:
        parts.append(f'<p>名单来源 · {escape(origin["city"])} {origin["year"]} 年 {escape(origin["status"])} · '
                     f'第 {origin["page_no"]} 页 / 序号 {origin["row_no"]} · '
                     f'<a href="{escape(origin["publication"])}">主管部门公示</a></p>')
    elif config["mode"] == "live":
        parts.append("<p>名单来源 · 非官方名单批次</p>")
    parts.append(save_lead_form(run, "", token))
    options = ['<option value="">整次调查</option>']
    for job in result["jobs"]:
        options.append(f'<option value="{escape(job["job"])}">{escape(job["title"])}</option>')
        parts.append(f'<article><h2>{escape(job["title"])}</h2><p>{escape(job["tier"])}</p><dl>')
        if "experience" in job:
            item = job["experience"]
            parts.append(f'<dt>经验要求原文</dt><dd>{escape(item["quote"])} · {link(item["url"])}</dd>')
        for field, label in LABELS.items():
            parts.append(f"<dt>{label}</dt>")
            for c in job["fields"].get(field, []):
                verdict = "支持" if c["verdict"] == "supports" else "不匹配"
                parts.append(f'<dd>{verdict} · {escape(c["quote"])} · {link(c["url"])}</dd>')
            if field in job["unknown"]:
                parts.append("<dd>未知</dd>")
        parts.append("</dl>" + save_lead_form(run, job["job"], token) + "</article>")
    for page in result["pages"]:
        evidence = page.get("source")
        proof = f'<p>招聘主体原文：{escape(evidence["employer_quote"])}</p>' if evidence else ""
        parts.append(f'<details><summary>{escape(page["title"] or page["url"])} · '
                     f'{escape(page["status"])}</summary>{link(page["url"])} '
                     f'{escape(page["note"])}{proof}<pre>{escape(page["body"] or "")}</pre></details>')
    parts.append(f'<form method="post" action="/feedback"><input type="hidden" name="token" value="{token}">'
                 f'<input type="hidden" name="id" value="{run}"><select aria-label="目标" name="job">'
                 + "".join(options) + '</select><select aria-label="标注" name="action">'
                 + "".join(f"<option>{a}</option>" for a in ACTIONS) + '</select>'
                 '<input name="note" placeholder="纠错依据或跟进备注" maxlength="2000"><button>保存反馈</button></form>')
    for item in result["feedback"]:
        parts.append(f'<p>{escape(item["created"])} · {escape(item["job"] or "整次调查")} · '
                     f'{escape(item["action"])} · {escape(item["note"])}</p>')
    return document(result["company"], "".join(parts))


def save_lead_form(run, job, token):
    label = "保存岗位线索" if job else "保存企业线索"
    return (f'<form method="post" action="/leads/save"><input type="hidden" name="token" value="{token}">'
            f'<input type="hidden" name="id" value="{run}"><input type="hidden" name="job" value="{escape(job)}">'
            f'<button>{label}</button></form>')


def leads_view(rows, view, token):
    filters = {"inbox": "待核查", "new": "新增未看", "all": "全部",
               **{key: label for key, label in STAGES.items() if key != "pending"}}
    parts = ['<nav><a href="/">调查列表</a><a href="/leads.csv">导出清单 CSV</a></nav><nav>']
    for value, label in filters.items():
        current = ' aria-current="page"' if view == value else ""
        parts.append(f'<a href="/leads?view={value}"{current}>{label}</a>')
    parts.append("</nav>")
    if not rows:
        parts.append("<p>当前没有线索。可从调查详情保存企业或岗位。</p>")
    for row in rows:
        lead_id = row["id"]
        title = escape(row["company"]) + (" · " + escape(row["job_title"]) if row["job"] else "")
        label = "岗位线索" if row["job"] else "企业线索"
        unread = " · 新增未看" if row["reviewed_at"] is None else ""
        parts.append(f'<article id="lead-{lead_id}"><h2>{title}</h2>'
                     f'<p>{label}{unread} · 首次保存 {escape(row["first_seen"])} UTC</p>'
                     f'<p>{escape(row["reason"])}</p>')
        if row["quote"]:
            parts.append(f'<blockquote>{escape(row["quote"])}</blockquote>')
        if row["source_url"]:
            parts.append(link(row["source_url"], "打开线索原页") + " · ")
        parts.append(f'<a href="/run?id={row["run"]}">查看调查</a>'
                     f'<p><label>招聘软件搜索词 <input class="search-terms" readonly '
                     f'value="{escape(row["search_terms"])}"></label></p>')
        options = "".join(f'<option value="{value}"{" selected" if row["stage"] == value else ""}>{name}</option>'
                          for value, name in STAGES.items())
        parts.append(f'<form method="post" action="/leads/update"><input type="hidden" name="token" value="{token}">'
                     f'<input type="hidden" name="id" value="{lead_id}">'
                     f'<label>进度 <select name="stage">{options}</select></label>'
                     f'<label>核查备注 <input name="note" value="{escape(row["note"])}" maxlength="2000"></label>'
                     '<button>保存进度并标记已看</button></form></article>')
    return document("我的求职清单", "".join(parts))


def serve(path, port):
    token = secrets.token_urlsafe(32)
    with closing(connect(path)) as db:
        prepare(db)

    class Handler(BaseHTTPRequestHandler):
        def respond(self, body, kind="text/html", status=200, filename=None):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(data)))
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                return self.send_error(403)
            route = urlsplit(self.path)
            params = parse_qs(route.query)
            with closing(connect(path)) as db:
                if route.path == "/":
                    return self.respond(index(db, params.get("q", [""])[0]))
                if route.path == "/leads.csv":
                    return self.respond(export_csv(saved_leads(db)), "text/csv", filename="pmai-leads.csv")
                if route.path == "/leads":
                    view = params.get("view", ["inbox"])[0]
                    try:
                        return self.respond(leads_view(saved_leads(db, view), view, token))
                    except ValueError:
                        return self.send_error(400)
                if route.path not in ("/run", "/export"):
                    return self.send_error(404)
                try:
                    result = export(db, int(params.get("id", [""])[0]))
                except ValueError:
                    return self.send_error(404)
                if route.path == "/export":
                    return self.respond(json.dumps(result, ensure_ascii=False, indent=2), "application/json",
                                        filename=f'investigation-{result["id"]}.json')
                self.respond(detail(result, token))

        def do_POST(self):
            if (self.path not in ("/feedback", "/leads/save", "/leads/update")
                    or self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}"):
                return self.send_error(403)
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size < 16000:
                    return self.send_error(400)
                data = parse_qs(self.rfile.read(size).decode(), keep_blank_values=True)
                if not secrets.compare_digest(data["token"][0], token):
                    return self.send_error(403)
                record_id = int(data["id"][0])
                with closing(connect(path)) as db:
                    if self.path == "/feedback":
                        export(db, record_id)
                        save(db, record_id, data["job"][0], data["action"][0], data["note"][0])
                        target = f"/run?id={record_id}"
                    elif self.path == "/leads/save":
                        lead_id = save_lead(db, record_id, data["job"][0])
                        target = f"/leads?view=all#lead-{lead_id}"
                    else:
                        update_lead(db, record_id, data["stage"][0], data["note"][0])
                        target = f"/leads?view=all#lead-{record_id}"
            except (ValueError, KeyError):
                return self.send_error(400)
            self.send_response(303)
            self.send_header("Content-Length", "0")
            self.send_header("Location", target)
            self.end_headers()

    with HTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
