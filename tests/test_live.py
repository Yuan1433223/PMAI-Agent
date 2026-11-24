import unittest
from unittest.mock import patch

from pmai_agent.investigation import check_claims
from pmai_agent.live import Models, PublicJobs, listing


class Sources(unittest.TestCase):
    def test_experience_and_invitation_are_unknown(self):
        quotes = {"cohort": "8 年以上经验", "validity": "We encourage you to apply"}
        claims = {k: {"verdict": "supports", "quote": v} for k, v in quotes.items()}
        self.assertEqual(check_claims(" ".join(quotes.values()), claims), [])

    def test_supported_url_only(self):
        with self.assertRaises(ValueError):
            listing("http://localhost/internal", "腾讯")
        with self.assertRaises(ValueError):
            listing("https://careers.tencent.com/jobdesc.html?postId=1", "其他企业")

    @patch("pmai_agent.live.request_json", return_value={"id": 1, "company_name": "Other"})
    def test_wrong_company(self, request):
        with self.assertRaisesRegex(ValueError, "主体"):
            PublicJobs().fetch("https://job-boards.greenhouse.io/acme/jobs/1", "Acme")

    @patch.object(Models, "decide", return_value={})
    def test_model_routing(self, decide):
        Models({"DEEPSEEK_API_KEY": "synthetic"}).assess(
            "public text", {"local_model": "qwen", "complex_enabled": True, "cohort": "2027"})
        self.assertEqual([(c.args[2], c.args[3]) for c in decide.call_args_list],
                         [(["city"], False), (["role", "validity", "cohort"], True)])

    @patch("pmai_agent.live.request_json")
    def test_local_city_uses_only_workplace(self, request):
        request.return_value = {"choices": [{"message": {"content": '{"city":"深圳"}'}}]}
        model = Models({})
        config = {"city": "深圳", "local_model": "qwen"}
        claims = model.decide("岗位\nWorkplace: 深圳\n公司总部位于北京", config, ["city"], False)
        self.assertEqual(claims["city"], {"quote": "深圳", "verdict": "supports"})
        self.assertEqual(model.decide("岗位\nWorkplace: 上海\n深圳总部", config, ["city"], False), {})

    @patch("pmai_agent.live.request_json", side_effect=OSError("model unavailable"))
    def test_model_unavailable(self, request):
        with self.assertRaises(OSError):
            Models({}).assess("text", dict(local_model="qwen", complex_enabled=False, model="qwen"))
