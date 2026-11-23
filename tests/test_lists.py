import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pmai_agent.lists import connect, entries, import_list, parse_pages


class Imports(unittest.TestCase):
    def test_import(self):
        sample = Path(__file__).resolve().parents[1] / "pmai_agent/samples/companies.pdf"
        with TemporaryDirectory() as directory:
            db = connect(Path(directory) / "test.sqlite3")
            try:
                doc = import_list(db, sample)
                self.assertEqual(doc, import_list(db, sample))
                rows = entries(db, doc)
                self.assertEqual([r["page_no"] for r in rows], [1, 1, 2])
                self.assertEqual(rows[0]["raw_name"], rows[2]["raw_name"])
                self.assertNotEqual(rows[0]["company_id"], rows[2]["company_id"])
            finally:
                db.close()

    def test_reject_partial(self):
        for invalid in ("3 Wrong", "", "1 Duplicate", "unreadable"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "第 2 页"):
                parse_pages(["1 Company", invalid])
