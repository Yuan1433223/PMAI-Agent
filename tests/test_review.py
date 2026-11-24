import json
import csv
import io
import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode
from urllib.request import urlopen

from pmai_agent.lists import connect
from pmai_agent.leads import save_lead, saved_leads
from pmai_agent.replay import demo
from pmai_agent.review import export, prepare


class Review(unittest.TestCase):
    def test_normal_http_flow(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.sqlite3"
            db = connect(path)
            run = demo(db)["id"]
            db.close()
            server = subprocess.Popen([sys.executable, "-m", "pmai_agent", "--db", str(path),
                                       "review", "--port", "0"], stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True)
            try:
                base = server.stdout.readline().strip()
                with urlopen(base + "/?q=Example", timeout=10) as response:
                    self.assertIn(b"Example Robotics", response.read())
                with urlopen(f"{base}/run?id={run}", timeout=10) as response:
                    page = response.read().decode()
                self.assertIn("毕业届别", page)
                token = re.search('name="token" value="([^"]+)"', page)[1]
                for action in ("判断有误", "值得跟进"):
                    data = urlencode(dict(token=token, id=run, job="A01", action=action,
                                          note="回到原文核对")).encode()
                    with urlopen(base + "/feedback", data, timeout=10) as response:
                        self.assertIn(action, response.read().decode())
                with urlopen(f"{base}/export?id={run}", timeout=10) as response:
                    self.assertEqual(len(json.load(response)["feedback"]), 2)
                for job in ("", "A01", ""):
                    data = urlencode(dict(token=token, id=run, job=job)).encode()
                    with urlopen(base + "/leads/save", data, timeout=10) as response:
                        self.assertIn("招聘软件搜索词", response.read().decode())
                with urlopen(base + "/leads?view=new", timeout=10) as response:
                    self.assertEqual(response.read().decode().count("招聘软件搜索词"), 2)
                db = connect(path)
                try:
                    company_lead = next(row["id"] for row in saved_leads(db) if not row["job"])
                finally:
                    db.close()
                data = urlencode(dict(token=token, id=company_lead, stage="verified",
                                      note="已搜索到岗位")).encode()
                with urlopen(base + "/leads/update", data, timeout=10) as response:
                    self.assertIn("已搜索到岗位", response.read().decode())
                with urlopen(base + "/leads.csv", timeout=10) as response:
                    rows = list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig"))))
                self.assertEqual(len(rows), 2)
                company_row = next(row for row in rows if not row["岗位"])
                self.assertEqual(company_row["状态"], "已在招聘软件确认")
                self.assertEqual(company_row["搜索词"], "Example Robotics Agent")
            finally:
                server.terminate()
                server.wait(timeout=10)
                server.stdout.close()
            db = connect(path)
            try:
                prepare(db)
                self.assertEqual(len(export(db, run)["feedback"]), 2)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM investigations").fetchone()[0], 1)
                second = demo(db)["id"]
                self.assertEqual(save_lead(db, second), company_lead)
                self.assertEqual(len(saved_leads(db, "new")), 1)
                kept = saved_leads(db, "verified")[0]
                self.assertEqual(kept["note"], "已搜索到岗位")
                self.assertEqual(kept["observations"], 2)
            finally:
                db.close()
