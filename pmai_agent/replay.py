from pathlib import Path

from .investigation import create, run_to_end
from .lists import import_list


class Replay:
    initial = "demo://jobs/A01"
    campus = "demo://campus/A01"
    role = "开发求职调查 Agent"
    city = "工作地点为深圳"
    cohort = "接受 2027 届毕业生"

    def discover(self, company, config):
        return [self.initial]

    def fetch(self, url, company):
        page = {"job": "A01", "title": "Agent 开发实习生"}
        if url == self.initial:
            return dict(page, body=f"A01 {self.role}。{self.city}。", cohort_url=self.campus)
        if url == self.campus:
            return dict(page, body=f"A01 校园招聘补充：{self.cohort}。")
        raise ValueError("回放没有此页")

    def assess(self, body, config):
        return {field: {"quote": text, "verdict": "supports"} for field, text in
                (("role", self.role), ("city", self.city), ("cohort", self.cohort)) if text in body}


def demo(db):
    doc = import_list(db, Path(__file__).parent / "samples" / "companies.pdf")
    company = db.execute("SELECT company_id FROM source_entries WHERE document_id=? AND row_no=1",
                         (doc,)).fetchone()[0]
    config = dict(mode="demo", model="fixture-v1", rule="v1", role="Agent", city="深圳",
                  cohort="2027", limit=2)
    run = create(db, company, config)
    replay = Replay()
    return run_to_end(db, run, replay, replay)
