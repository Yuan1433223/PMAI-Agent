import hashlib
import unittest
from dataclasses import replace
from pathlib import Path

from pmai_agent.batch import batch_report
from pmai_agent.city_lists import SHENZHEN
from pmai_agent.investigation import check_claims, create, required_experience, run_to_end
from pmai_agent.lists import city_document, connect, entries, import_list, parse_pages
from pmai_agent.web_jobs import candidate_url, checked_page


class CityPipeline(unittest.TestCase):
    def setUp(self):
        self.db = connect(":memory:")
        self.addCleanup(self.db.close)

    def test_legacy_pdf_can_be_registered_without_duplicating_identity(self):
        path = Path(__file__).resolve().parents[1] / "pmai_agent/samples/companies.pdf"
        official = replace(SHENZHEN, digest=hashlib.sha256(path.read_bytes()).hexdigest(), count=3)
        doc = import_list(self.db, path)
        original = entries(self.db, doc)
        self.assertEqual(import_list(self.db, path, official), doc)
        self.assertEqual(city_document(self.db, official), doc)
        self.assertEqual(entries(self.db, doc), original)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM entry_positions").fetchone()[0], 3)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            import_list(self.db, path, SHENZHEN)

    def test_official_layout_preserves_original_row_location(self):
        rows = parse_pages(["附件1\n" + SHENZHEN.title + "\n序号 企业名称\n1 示例公司"],
                           replace(SHENZHEN, count=1))
        self.assertEqual(rows, [(1, 1, "示例公司", 4, "1 示例公司")])

    def test_recruitment_evidence_and_coverage(self):
        company = "示例（深圳）有限公司"
        snapshot = "招聘单位：示例(深圳)有限公司\n应用开发实习生\n工作地深圳；职责是开发智能体应用。\n要求接受 2027 届毕业生。"
        url = "https://career.example.edu.cn/jobs/1"
        self.assertEqual(candidate_url(url + "#ignored"), url)
        self.assertIsNone(candidate_url("https://career.example.edu.cn.evil.example/jobs/1"))
        self.assertIsNone(candidate_url("http://localhost/jobs"))
        verdict = {"category": "job", "employer_line": 1, "start": 2, "end": 4, "title": "应用开发实习生"}
        page = checked_page(url, snapshot, snapshot.splitlines(), company, verdict)
        self.assertEqual(page["body"].splitlines()[0], "应用开发实习生")
        with self.assertRaisesRegex(ValueError, "未核实"):
            checked_page(url, snapshot, snapshot.splitlines(), "其他企业", verdict)
        client = snapshot.replace("招聘单位", "客户公司")
        with self.assertRaisesRegex(ValueError, "招聘主体待核实"):
            checked_page(url, client, client.splitlines(), company, verdict)
        path = Path(__file__).resolve().parents[1] / "pmai_agent/samples/companies.pdf"
        official = replace(SHENZHEN, digest=hashlib.sha256(path.read_bytes()).hexdigest(), count=3)
        doc = import_list(self.db, path, official)

        class Source:
            def discover(self, company, config):
                return [url]

            def fetch(self, address, company):
                return page

            def assess(self, body, config):
                return {field: {"verdict": "supports", "quote": quote} for field, quote in (
                    ("role", "开发智能体应用"), ("city", "工作地深圳"), ("cohort", "2027 届毕业生"))}

        run = create(self.db, entries(self.db, doc)[0]["company_id"], {"limit": 1, "web_search": True})
        source = Source()
        run_to_end(self.db, run, source, source)
        summary = batch_report(self.db, [run])
        self.assertEqual(summary["companies_with_verified_entrance"], 1)
        self.assertEqual(summary["companies_with_job_text"], 1)
        self.assertEqual(summary["companies"][0]["leads"][0]["status"], "初筛符合")

    def test_company_address_and_preferred_experience_are_not_hard_evidence(self):
        body = "办公地址：深圳市南山区\n项目相关经验优先"
        self.assertEqual(check_claims(body, {"city": {
            "quote": "办公地址：深圳市南山区", "verdict": "supports"}}), [])
        self.assertIsNone(required_experience("1年以上实习经验优先"))
        self.assertEqual(required_experience("深圳-福田区 3-5年 硕士"), "深圳-福田区 3-5年")
        self.assertEqual(required_experience("2年以上Python语言开发经验"), "2年以上Python语言开发经验")
