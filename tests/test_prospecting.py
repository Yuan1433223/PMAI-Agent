import hashlib
import io
import json
import unittest
from contextlib import closing, redirect_stdout
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pmai_agent.city_lists import SHENZHEN
from pmai_agent.cli import main
from pmai_agent.investigation import report
from pmai_agent.leads import saved_leads, update_lead
from pmai_agent.lists import connect, import_list
from pmai_agent.prospecting import extract_candidates, prospect


class Prospecting(unittest.TestCase):
    @patch("pmai_agent.cli.settings", return_value={"DEEPSEEK_API_KEY": "fixture"})
    @patch("pmai_agent.web_jobs.request_json")
    def test_cli_distinguishes_official_roster_and_keeps_saved_progress(self, request, settings):
        roster_company = "深圳名单科技有限公司"
        extra_company = "深圳额外制造科技有限公司"
        url = "https://example.com/factory"
        body = "\n".join((
            roster_company + "开发视觉大模型质检方案，用于产线外观检测。",
            "项目已部署在深圳市的工业园区。",
            extra_company + "（简称“额外制造”）推出用视觉大模型检测划痕的工业设备。",
            extra_company + "在深圳光明区运营其工业试验线。",
        ))
        choices = {"companies": [
            {"company": roster_company, "identity_line": 1, "signal_line": 1, "city_line": 2},
            {"company": extra_company, "identity_line": 3, "signal_line": 3, "city_line": 4},
        ]}
        request.side_effect = [
            {"results": [{"url": url}]},
            {"results": [{"url": url + "#copy"}]},
            {"content": body},
            {"choices": [{"message": {"content": json.dumps(choices)}}]},
        ] * 2
        with TemporaryDirectory() as directory, closing(connect(str(Path(directory) / "test.sqlite3"))) as db:
            path = str(Path(directory) / "test.sqlite3")
            sample = Path(__file__).resolve().parents[1] / "pmai_agent/samples/companies.pdf"
            official = replace(SHENZHEN, digest=hashlib.sha256(sample.read_bytes()).hexdigest(), count=3)
            doc = import_list(db, sample, official)
            with db:
                db.execute("UPDATE source_entries SET raw_name=? WHERE document_id=? AND row_no=1",
                           (roster_company, doc))
            command = ["--db", path, "prospect", "--keywords", "视觉大模型 工业质检", "--limit", "1",
                       "--outside-roster"]
            with patch.dict("pmai_agent.prospecting.CITY_LISTS", {"深圳": official}):
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(main(command), 0)
                first = json.loads(out.getvalue())
                self.assertEqual(first["qualified_companies"], 2)
                self.assertEqual(first["skipped"], [{"company": roster_company, "reason": "已在名单"}])
                self.assertEqual(first["new_to_shortlist"], 1)
                lead = first["leads"][0]
                self.assertEqual(lead["company"], extra_company)
                self.assertEqual(lead["roster_membership"], "outside_roster")
                self.assertEqual(report(db, lead["investigation_id"])["jobs"], [])
                update_lead(db, lead["lead_id"], "known", "留作下次核查")
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(main(command), 0)
                repeated = json.loads(out.getvalue())
                self.assertEqual(repeated["new_to_shortlist"], 0)
                self.assertEqual(repeated["leads"][0]["lead_id"], lead["lead_id"])
                row = saved_leads(db, "known")[0]
                self.assertEqual(row["note"], "留作下次核查")
                self.assertEqual(row["place_quote"], body.splitlines()[3])
                self.assertEqual(row["observations"], 2)
                self.assertEqual(row["alias"], "额外制造")
        self.assertEqual(request.call_count, 8)

    def test_outside_filter_requires_actual_roster(self):
        db = connect(":memory:")
        self.addCleanup(db.close)
        with self.assertRaisesRegex(ValueError, "先导入"):
            prospect(db, {}, city="深圳", keywords="智能客服", role="Agent", limit=1, outside_only=True)

    def test_rejects_invented_company_and_unrelated_city_line(self):
        body = "示例科技有限公司推出视觉质检工具，用于工业产线缺陷检测。\n项目部署在广州。"
        verdict = {"companies": [
            {"company": "示例科技有限公司", "identity_line": 1, "signal_line": 1, "city_line": 2},
            {"company": "深圳某大模型公司", "identity_line": 1, "signal_line": 1, "city_line": 1},
        ]}
        self.assertEqual(list(extract_candidates(body, body.splitlines(), verdict, "深圳")), [])

    def test_city_in_legal_name_alone_does_not_establish_city_link(self):
        company = "深圳示例科技有限公司"
        verdict = {"companies": [{"company": company, "identity_line": 1, "signal_line": 2, "city_line": 1}]}
        body = company + "\n推出视觉质检工具，用于工业产线缺陷检测。"
        self.assertEqual(list(extract_candidates(body, body.splitlines(), verdict, "深圳")), [])
        body += "其产品在深圳龙华区的试验工厂投入使用。"
        lead = list(extract_candidates(body, body.splitlines(), verdict, "深圳"))[0][1]
        self.assertIn("试验工厂", lead["business_place_quote"])
