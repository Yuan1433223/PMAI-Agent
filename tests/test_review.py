import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode
from urllib.request import urlopen

from pmai_agent.lists import connect
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
            finally:
                server.terminate()
                server.wait(timeout=10)
                server.stdout.close()
            db = connect(path)
            try:
                prepare(db)
                self.assertEqual(len(export(db, run)["feedback"]), 2)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM investigations").fetchone()[0], 1)
            finally:
                db.close()
