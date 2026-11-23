import unittest

from pmai_agent.investigation import check_claims, create, run_to_end, step
from pmai_agent.lists import connect
from pmai_agent.replay import Replay, demo


class Investigations(unittest.TestCase):
    def setUp(self):
        self.db = connect(":memory:")
        self.addCleanup(self.db.close)
        self.source = Replay()
        self.db.execute("INSERT INTO companies(raw_name) VALUES ('Synthetic')")
        self.run_id = create(self.db, 1, dict(limit=2, cohort="2027", mode="demo"))

    def test_resume(self):
        step(self.db, self.run_id, self.source, self.source)
        step(self.db, self.run_id, self.source, self.source)
        result = run_to_end(self.db, self.run_id, self.source, self.source)
        self.assertEqual(result["jobs"][0]["unknown"], ["validity"])
        self.assertEqual(result, run_to_end(self.db, self.run_id, self.source, self.source))

    def test_wrong_page(self):
        with self.assertRaises(ValueError):
            check_claims("甲岗位的深圳地点", {"city": {"quote": "乙岗位的深圳地点", "verdict": "supports"}})

    def test_limits_and_failures(self):
        run = create(self.db, 1, dict(limit=1, cohort="2027"))
        result = run_to_end(self.db, run, self.source, self.source)
        self.assertIn("上限", result["reason"])
        self.assertIn("cohort", result["jobs"][0]["unknown"])
        self.source.fetch = lambda *_: dict(job="A", title="A", body="")
        result = run_to_end(self.db, self.run_id, self.source, self.source)
        self.assertEqual(result["pages"][0]["status"], "inaccessible")

    def test_no_source(self):
        self.source.discover = lambda *_: []
        self.assertEqual(run_to_end(self.db, self.run_id, self.source, self.source)["discovery"], "not_found")

    def test_demo(self):
        self.assertEqual(demo(self.db)["jobs"][0]["tier"], "有招聘依据")
