import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pmai_agent.business import BusinessPages, business_url
from pmai_agent.cli import main
from pmai_agent.leads import saved_leads
from pmai_agent.lists import connect


class BusinessDiscovery(unittest.TestCase):
    @patch("pmai_agent.cli.settings", return_value={"DEEPSEEK_API_KEY": "fixture"})
    @patch("pmai_agent.web_jobs.request_json")
    def test_cli_collects_company_evidence_without_creating_a_job(self, request, settings):
        company = "深圳测试科技有限公司"
        url = "https://example.com/agent"
        body = company + "（以下简称“测试科技”）\n自行开发面向制造业的生产调度智能体，已在工厂试用。"
        request.side_effect = [
            {"results": [{"url": url}]},
            {"results": [{"url": url}]},
            {"content": body},
            {"choices": [{"message": {"content": json.dumps(
                {"category": "business", "identity_line": 1, "signal_line": 2})}}]},
        ]
        with TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "db.sqlite3")
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--db", path, "investigate", "--business",
                                       "--company", company, "--role", "智能体 / 大模型"]), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["jobs"], [])
            self.assertEqual(result["pages"][0]["status"], "verified_business")
            self.assertEqual(request.call_count, 4)
            db = connect(path)
            try:
                lead = saved_leads(db, "new")[0]
                self.assertEqual(lead["id"], result["lead_id"])
                self.assertEqual(lead["quote"], body.splitlines()[1])
                self.assertEqual(lead["search_terms"].splitlines(),
                                 [company + " 智能体", company + " 大模型", "测试科技 智能体", "测试科技 大模型"])
                self.assertEqual(lead["alias"], "测试科技")
                self.assertEqual(lead["source_url"], url)
            finally:
                db.close()

    def test_rejects_unrelated_owner_and_nonpublic_url(self):
        self.assertIsNone(business_url("http://127.0.0.1/business"))
        self.assertIsNone(business_url("https://0x7f.0.0.1/business"))
        self.assertIsNone(business_url("https://www.liepin.com/job/123"))
        self.assertIsNone(business_url("https://www.quanzhi.com/company/123"))
        body = "另一家公司\n开发面向企业的智能体应用"
        with self.assertRaisesRegex(ValueError, "未找到"):
            BusinessPages({}, {}).checked("https://example.com/agent", body, body.splitlines(), "测试公司",
                                         {"category": "business", "identity_line": 1, "signal_line": 2})
