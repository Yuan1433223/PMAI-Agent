"""Coverage counts and review candidates for a fixed investigation batch."""
from .investigation import report


def batch_report(db, run_ids):
    companies = []
    seen = set()
    for run_id in run_ids:
        run = report(db, run_id)
        origin = run["company_source"]
        if (not origin or not origin["publication"] or not run["config"].get("web_search")
                or run["config"].get("business_search")):
            raise ValueError(f"调查 {run_id} 不是官方名单招聘调查")
        key = (origin["document_id"], origin["row_no"])
        if key in seen:
            raise ValueError("同一名单行只能计入一次")
        seen.add(key)
        entries = [{"url": page["url"], "kind": page["source"]["kind"],
                    "employer_quote": page["source"]["employer_quote"]}
                   for page in run["pages"] if "source" in page]
        leads, screened_out = [], []
        for job in run["jobs"]:
            states = {field: {item["verdict"] for item in claims}
                      for field, claims in job["fields"].items()}
            if states.get("role") != {"supports"}:
                continue
            blockers = [f for f in ("city", "cohort", "validity") if "contradicts" in states.get(f, set())]
            if job.get("experience") or blockers:
                screened_out.append({"title": job["title"], "url": job["job"],
                                     "contradictions": blockers, "experience": job.get("experience")})
                continue
            leads.append({"title": job["title"], "url": job["job"], "evidence": job["fields"],
                          "unknown": job["unknown"], "experience": job.get("experience"),
                          "status": "初筛符合" if all(states.get(f) == {"supports"} for f in ("city", "cohort"))
                          else "地点或届别待核查"})
        companies.append({
            "run": run_id, "company": run["company"], "origin": origin, "phase": run["phase"],
            "discovery": run["discovery"], "entrances": entries, "leads": leads, "screened_out": screened_out,
            "attempts": [{"url": p["url"], "status": p["status"], "note": p["note"]} for p in run["pages"]],
        })
    return {
        "sample_size": len(companies),
        "complete": sum(c["phase"] == "done" for c in companies),
        "companies_with_verified_entrance": sum(bool(c["entrances"]) for c in companies),
        "companies_with_job_text": sum(any(e["kind"] == "job" for e in c["entrances"]) for c in companies),
        "jobs_for_review": sum(len(c["leads"]) for c in companies),
        "jobs_with_city_and_cohort": sum(lead["status"] == "初筛符合" for c in companies for lead in c["leads"]),
        "companies": companies,
    }
