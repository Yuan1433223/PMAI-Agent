import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pmai_agent.cli import main
from pmai_agent.lists import connect, import_list


class Batch(unittest.TestCase):
    @patch("pmai_agent.cli.settings", return_value={"PMAI_LOCAL_MODEL": "synthetic"})
    @patch("pmai_agent.cli.PublicJobs.discover", return_value=[])
    def test_document_range(self, discover, settings):
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "batch.sqlite3")
            db = connect(path)
            try:
                doc = import_list(db, Path(__file__).resolve().parents[1] / "pmai_agent/samples/companies.pdf")
            finally:
                db.close()
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--db", path, "investigate", "--document", str(doc),
                                       "--first-row", "2", "--count", "2"]), 0)
            runs = json.loads(output.getvalue())
            self.assertEqual([r["company"] for r in runs], ["Example Systems", "Example Robotics"])
            self.assertEqual([r["discovery"] for r in runs], ["not_found", "not_found"])
