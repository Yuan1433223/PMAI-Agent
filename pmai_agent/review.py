"""Local review UI; reading a report never starts an investigation."""
import json
import secrets
from contextlib import closing
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from .investigation import report, setup
from .lists import connect


LABELS = {"city": "工作地点", "role": "岗位方向", "cohort": "毕业届别", "validity": "有效性"}
ACTIONS = ("值得跟进", "原已知道", "判断有误", "暂缓")


def prepare(db):
    setup(db)
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


def link(url):
    safe = escape(url, quote=True)
    if url.startswith("https://"):
        return f'<a href="{safe}" rel="noreferrer">打开招聘原页</a>'
    return safe


def document(title, body):
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
<style>body{{max-width:64rem;margin:2rem auto;padding:0 1rem;font:16px/1.65 system-ui;color:#19302c}}
a{{color:#096452}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #cedbd6;
text-align:left;padding:.5rem}}article,details{{margin:1em 0;padding:.8em;border:1px solid #cedbd6}}
input,button,select{{font:inherit;margin:.25em}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}</style>
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
    return document("求职调查", f'<form><input name="q" aria-label="企业名" placeholder="企业名" '
                    f'value="{escape(query)}"><button>筛选</button></form>'
                    '<table><tr><th>企业</th><th>调查</th><th>进度</th><th>结果</th></tr>'
                    + "".join(rows) + "</table>")


def detail(result, token):
    run = result["id"]
    config = result["config"]
    target = " · ".join(str(config[k]) for k in ("city", "role", "cohort") if config.get(k))
    parts = [f'<a href="/">调查列表</a> · <a href="/export?id={run}">导出证据与反馈</a>',
             f'<p>{escape(target)} · {escape(config["mode"])} · {escape(result["reason"] or result["phase"])}</p>']
    options = ['<option value="">整次调查</option>']
    for job in result["jobs"]:
        options.append(f'<option value="{escape(job["job"])}">{escape(job["title"])}</option>')
        parts.append(f'<article><h2>{escape(job["title"])}</h2><p>{escape(job["tier"])}</p><dl>')
        for field, label in LABELS.items():
            parts.append(f"<dt>{label}</dt>")
            for c in job["fields"].get(field, []):
                verdict = "支持" if c["verdict"] == "supports" else "不匹配"
                parts.append(f'<dd>{verdict} · {escape(c["quote"])} · {link(c["url"])}</dd>')
            if field in job["unknown"]:
                parts.append("<dd>未知</dd>")
        parts.append("</dl></article>")
    for page in result["pages"]:
        parts.append(f'<details><summary>{escape(page["title"] or page["url"])} · '
                     f'{escape(page["status"])}</summary>{link(page["url"])} '
                     f'{escape(page["note"])}<pre>{escape(page["body"] or "")}</pre></details>')
    parts.append(f'<form method="post" action="/feedback"><input type="hidden" name="token" value="{token}">'
                 f'<input type="hidden" name="id" value="{run}"><select aria-label="目标" name="job">'
                 + "".join(options) + '</select><select aria-label="标注" name="action">'
                 + "".join(f"<option>{a}</option>" for a in ACTIONS) + '</select>'
                 '<input name="note" placeholder="纠错依据或跟进备注" maxlength="2000"><button>保存反馈</button></form>')
    for item in result["feedback"]:
        parts.append(f'<p>{escape(item["created"])} · {escape(item["job"] or "整次调查")} · '
                     f'{escape(item["action"])} · {escape(item["note"])}</p>')
    return document(result["company"], "".join(parts))


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
            if self.path != "/feedback" or self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                return self.send_error(403)
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size < 16000:
                    return self.send_error(400)
                data = parse_qs(self.rfile.read(size).decode(), keep_blank_values=True)
                if not secrets.compare_digest(data["token"][0], token):
                    return self.send_error(403)
                run = int(data["id"][0])
                with closing(connect(path)) as db:
                    export(db, run)
                    save(db, run, data["job"][0], data["action"][0], data["note"][0])
            except (ValueError, KeyError):
                return self.send_error(400)
            self.send_response(303)
            self.send_header("Content-Length", "0")
            self.send_header("Location", f"/run?id={run}")
            self.end_headers()

    with HTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
