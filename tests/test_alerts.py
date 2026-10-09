"""Offline tests: every source is fed a sample response shaped like the live one."""

import json

import pytest

from alerts import main as main_mod
from alerts.filters import DROP, KEEP, STRETCH, UNLEVELED, Filters
from alerts.main import load_yaml, parse_args, run, send_alerts
from alerts.models import FetchError, Job
from alerts.sources import SOURCES
from alerts.telegram import job_message


class FakeHttp:
    """Answers by matching a substring of the URL."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def _find(self, url, params=None):
        self.calls.append((url, params))
        for key, value in self.routes.items():
            if key in url:
                return value(params) if callable(value) else value
        raise FetchError(f"no route for {url}")

    def get_json(self, url, params=None, headers=None):
        return self._find(url, params)

    def post_json(self, url, body, headers=None):
        return self._find(url, body)

    def get_text(self, url, params=None):
        return self._find(url, params), url


@pytest.fixture
def filters():
    return Filters(load_yaml("filters.yaml"))


# ---------------------------------------------------------------- filters
@pytest.mark.parametrize("title,expected", [
    ("Software Engineer II", KEEP),
    ("SDE-II, Payments", KEEP),
    ("Sde 2 - Backend", KEEP),
    ("Software Development Engineer II", KEEP),
    ("Member of Technical Staff", UNLEVELED),
    ("Backend Engineer (Go)", UNLEVELED),
    ("Senior Software Engineer", DROP),
    ("SDE III", DROP),
    ("Software Engineer", UNLEVELED),
    ("Staff Software Engineer", DROP),
    ("Principal Engineer", DROP),
    ("Engineering Manager", DROP),
    ("Software Engineer Intern", DROP),
    ("Lead Software Engineer", DROP),
    ("Account Executive", DROP),
    ("Support Engineer II", DROP),
    ("Software Engineer III", DROP),
])
def test_title_verdicts(filters, title, expected):
    assert filters.title_verdict(title) == expected


def test_strict_level_filter_skips_stretch_but_keeps_unleveled_roles():
    config = load_yaml("filters.yaml")
    config["send_stretch"] = False
    strict_filters = Filters(config)

    assert strict_filters.title_verdict("Senior Backend Engineer") == DROP
    assert strict_filters.title_verdict("Software Engineer III, Google Cloud") == DROP
    assert strict_filters.title_verdict("Software Engineer") == UNLEVELED
    assert strict_filters.title_verdict("Software Engineer II") == KEEP


@pytest.mark.parametrize("location,ok", [
    ("Bengaluru, Karnataka, India", True),
    ("Bangalore", True),
    ("India, Telangana, Hyderabad", True),
    ("Gurugram, India", True),
    ("Noida, Uttar Pradesh", True),
    ("Remote - India", True),
    ("IN Remote India", True),
    ("India", True),
    ("Pune, India", False),
    ("Mumbai", False),
    ("San Francisco, CA", False),
    ("Remote - US", False),
    ("3 Locations", True),
    ("", True),
    ("Bengaluru, India; Mumbai, India", True),
])
def test_locations(filters, location, ok):
    assert filters.location_ok(location) is ok


# ---------------------------------------------------------------- sources
def run_source(name, cfg, routes):
    cfg = {"name": "Co", **cfg}
    return list(SOURCES[name](FakeHttp(routes), cfg))


def test_greenhouse():
    jobs = run_source("greenhouse", {"board": "airbnb"}, {"boards-api.greenhouse.io/v1/boards/airbnb/jobs": {
        "jobs": [{"id": 7, "title": "Software Engineer II", "location": {"name": "Bangalore, India"},
                  "absolute_url": "https://x/7", "updated_at": "2026-10-01T00:00:00Z"}]}})
    assert jobs[0].id == "7" and jobs[0].location == "Bangalore, India" and jobs[0].posted == "2026-10-01"


def test_greenhouse_eu_host():
    http = FakeHttp({"boards-api.eu.greenhouse.io": {"jobs": []}})
    list(SOURCES["greenhouse"](http, {"name": "Groww", "board": "groww", "region": "eu"}))
    assert "boards-api.eu.greenhouse.io" in http.calls[0][0]


def test_lever():
    jobs = run_source("lever", {"board": "cred"}, {"api.lever.co": [
        {"id": "abc", "text": "SDE 2", "categories": {"location": "bengaluru", "allLocations": ["bengaluru", "hyderabad"]},
         "hostedUrl": "https://jobs.lever.co/cred/abc", "createdAt": 1790000000000}]})
    assert jobs[0].location == "bengaluru, hyderabad" and jobs[0].posted.startswith("2026")


def test_ashby_skips_unlisted():
    jobs = run_source("ashby", {"board": "confluent"}, {"api.ashbyhq.com": {"jobs": [
        {"id": "1", "title": "A", "location": "Bengaluru", "jobUrl": "u1", "isListed": True},
        {"id": "2", "title": "B", "location": "Bengaluru", "jobUrl": "u2", "isListed": False}]}})
    assert [j.id for j in jobs] == ["1"]


def test_rippling_merges_locations():
    rows = [{"name": "SWE II", "workLocation": {"label": "Bengaluru"}, "url": "https://ats.rippling.com/rippling/jobs/u1"},
            {"name": "SWE II", "workLocation": {"label": "Hyderabad"}, "url": "https://ats.rippling.com/rippling/jobs/u1"}]
    jobs = run_source("rippling", {"board": "rippling"}, {"api.rippling.com": rows})
    assert len(jobs) == 1 and jobs[0].location == "Bengaluru, Hyderabad"


def test_amazon_paging():
    def page(params):
        if params["offset"] == 0:
            return {"hits": 101, "jobs": [{"id_icims": str(i), "title": "Software Development Engineer II",
                                           "normalized_location": "Bengaluru, KA, IND",
                                           "job_path": f"/en/jobs/{i}/sde"} for i in range(100)]}
        return {"hits": 101, "jobs": [{"id_icims": "100", "title": "SDE", "city": "Hyderabad", "job_path": "/en/jobs/100/sde"}]}
    jobs = run_source("amazon", {}, {"amazon.jobs": page})
    assert len(jobs) == 101 and jobs[-1].url == "https://www.amazon.jobs/en/jobs/100/sde"


def test_microsoft_pcsx():
    def page(params):
        if params["start"] == 0:
            return {"data": {"count": 11, "positions": [
                {"id": i, "name": "Software Engineer II", "locations": ["India, Telangana, Hyderabad"],
                 "postedTs": 1789708865, "positionUrl": f"/careers/job/{i}"} for i in range(10)]}}
        return {"data": {"count": 11, "positions": [{"id": 99, "name": "X", "locations": [], "positionUrl": "/careers/job/99"}]}}
    jobs = run_source("eightfold_pcsx", {"host": "apply.careers.microsoft.com", "domain": "microsoft.com"},
                      {"api/pcsx/search": page})
    assert len(jobs) == 11 and jobs[0].url == "https://apply.careers.microsoft.com/careers/job/0"


def test_netapp_v2():
    jobs = run_source("eightfold_v2", {"host": "netapp.eightfold.ai", "domain": "netapp.com"}, {"api/apply/v2/jobs": {
        "count": 1, "positions": [{"id": 44220066, "name": "Software Engineer", "location": "Bangalore, India Office",
                                   "t_create": 1787916729, "canonicalPositionUrl": "https://netapp.eightfold.ai/careers/job/44220066"}]}})
    assert jobs[0].id == "44220066" and jobs[0].posted


def test_atlassian():
    jobs = run_source("atlassian", {}, {"atlassian.com/endpoint/careers/listings": [
        {"id": 25480, "title": "Software Engineer", "locations": ["Bengaluru - India - Bengaluru, 560071 India"],
         "applyUrl": "https://x/apply", "portalJobPost": {"updatedDate": "2026-10-02T10:00:00"}}]})
    assert jobs[0].location.startswith("Bengaluru") and jobs[0].posted == "2026-10-02"


def test_amd_jibe():
    jobs = run_source("jibe", {"host": "careers.amd.com"}, {"careers.amd.com/api/jobs": {"totalCount": 1, "jobs": [
        {"data": {"req_id": "90958", "title": "System Software Engineer", "city": "Hyderabad", "country": "India",
                  "posted_date": "2026-09-08T10:35:00+0000"}}]}})
    assert jobs[0].url == "https://careers.amd.com/careers-home/jobs/90958" and jobs[0].location == "Hyderabad, India"


def test_workday_paging():
    def page(body):
        n = 20 if body["offset"] == 0 else 1
        return {"total": 21, "jobPostings": [{"title": "Software Engineer II", "locationsText": "India, Bengaluru",
                                              "externalPath": f"/job/Bengaluru/SWE-II_JR{body['offset'] + i}",
                                              "postedOn": "Posted Today"} for i in range(n)]}
    jobs = run_source("workday", {"tenant": "nvidia", "shard": "wd5", "site": "Ext"}, {"myworkdayjobs.com": page})
    assert len(jobs) == 21 and jobs[0].id == "JR0"
    assert jobs[0].url == "https://nvidia.wd5.myworkdayjobs.com/Ext/job/Bengaluru/SWE-II_JR0"


def test_html_links_google():
    html = """<ul>
      <li><h3>Software Engineer III, Google Cloud</h3><span>Bengaluru, Karnataka, India</span>
          <a href="jobs/results/128780495415583430-software-engineer-iii-google-cloud?location=India">Learn more</a></li>
      <li><h3>Staff Software Engineer</h3><span>Hyderabad, Telangana, India</span>
          <a href="jobs/results/102597024011952838-staff-software-engineer?location=India">Learn more</a></li>
    </ul>"""
    cfg = load_company("Google")
    http = FakeHttp({"google.com": html})
    jobs = list(SOURCES["html_links"](http, {**cfg, "pages": 1}))
    assert [j.id for j in jobs] == ["128780495415583430", "102597024011952838"]
    assert jobs[0].title == "Software engineer iii google cloud"
    assert "Bengaluru" in jobs[0].location
    assert jobs[0].url.startswith("https://www.google.com/about/careers/applications/jobs/results/1287")


def test_html_links_sap_city_from_url():
    html = '<table><tr><td><a href="/job/Bangalore-Sr-DevOps-Engineer-560066/1225119601/">Sr DevOps Engineer</a></td></tr></table>'
    cfg = load_company("SAP Labs")
    jobs = list(SOURCES["html_links"](FakeHttp({"jobs.sap.com": html}), {**cfg, "pages": 1}))
    assert jobs[0].id == "1225119601" and "Bangalore" in jobs[0].location


def test_html_links_medianet_count_change_is_new():
    cfg = load_company("Media.net")
    one = '<a href="https://careers.media.net/engineering">Engineering 3 positions</a><a href="/sales">Sales</a>'
    two = '<a href="https://careers.media.net/engineering">Engineering 4 positions</a>'
    a = list(SOURCES["html_links"](FakeHttp({"media.net": one}), cfg))
    b = list(SOURCES["html_links"](FakeHttp({"media.net": two}), cfg))
    assert len(a) == 1 and a[0].id != b[0].id


def load_company(name):
    return next(c for c in load_yaml("companies.yaml")["companies"] if c["name"] == name)


def test_every_company_has_a_known_source():
    for c in load_yaml("companies.yaml")["companies"]:
        assert c["source"] in SOURCES, c["name"]
    enabled = [c for c in load_yaml("companies.yaml")["companies"] if c.get("enabled", True)]
    assert len(enabled) == 26


# ---------------------------------------------------------------- messages
def test_message_escapes_html():
    job = Job("A&B", "1", "SDE <2>", "Bengaluru", "https://x?a=1&b=2", tags=["stretch: senior level"])
    msg = job_message(job)
    assert "Company:</b> A&amp;B" in msg
    assert "Title:</b> SDE &lt;2&gt;" in msg
    assert "Job ID:</b> <code>1</code>" in msg
    assert "Location:</b> Bengaluru" in msg
    assert 'href="https://x?a=1&amp;b=2"' in msg


def test_send_alerts_sends_one_message_per_job():
    jobs = [Job("Co", str(i), f"Software Engineer II {i}", "Bengaluru", f"https://x/{i}") for i in range(20)]
    tg = FakeTelegram()

    sent = send_alerts(tg, jobs)

    assert sent == jobs
    assert len(tg.sent) == len(jobs)
    assert all(f"Job ID:</b> <code>{i}</code>" in message for i, message in enumerate(tg.sent))


# ---------------------------------------------------------------- end to end
class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return True


def greenhouse_feed(ids):
    return {"jobs": [{"id": i, "title": "Software Engineer II", "location": {"name": "Bengaluru, India"},
                      "absolute_url": f"https://x/{i}"} for i in ids]
                    + [{"id": 999, "title": "Account Executive", "location": {"name": "Bengaluru"}, "absolute_url": "y"}]}


def test_first_run_is_silent_then_only_new_jobs_are_sent(tmp_path):
    state_file = str(tmp_path / "seen.json")
    args = parse_args(["--only", "Airbnb", "--state", state_file])
    tg = FakeTelegram()

    assert run(args, http=FakeHttp({"greenhouse.io": greenhouse_feed([1, 2])}), telegram=tg) == 0
    assert tg.sent == []  # bootstrap: nothing sent

    assert run(args, http=FakeHttp({"greenhouse.io": greenhouse_feed([1, 2, 3])}), telegram=tg) == 0
    assert len(tg.sent) == 1 and "https://x/3" in tg.sent[0]

    assert run(args, http=FakeHttp({"greenhouse.io": greenhouse_feed([1, 2, 3])}), telegram=tg) == 0
    assert len(tg.sent) == 1  # nothing new, nothing sent

    saved = json.load(open(state_file))
    assert set(saved["jobs"]) == {"Airbnb:1", "Airbnb:2", "Airbnb:3"}


def test_repeated_failures_warn_once(tmp_path):
    args = parse_args(["--only", "Airbnb", "--state", str(tmp_path / "seen.json")])
    tg = FakeTelegram()
    for _ in range(5):
        run(args, http=FakeHttp({}), telegram=tg)
    warnings = [m for m in tg.sent if "warning" in m.lower()]
    assert len(warnings) == 1 and "failing for 3 runs" in warnings[0]


def test_failed_send_is_retried_next_run(tmp_path):
    args = parse_args(["--only", "Airbnb", "--state", str(tmp_path / "seen.json")])
    run(args, http=FakeHttp({"greenhouse.io": greenhouse_feed([1])}), telegram=FakeTelegram())

    class Down(FakeTelegram):
        def send(self, text):
            return False
    assert run(args, http=FakeHttp({"greenhouse.io": greenhouse_feed([1, 2])}), telegram=Down()) == 1

    tg = FakeTelegram()
    run(args, http=FakeHttp({"greenhouse.io": greenhouse_feed([1, 2])}), telegram=tg)
    assert len(tg.sent) == 1 and "https://x/2" in tg.sent[0]


def test_dry_run_saves_nothing(tmp_path):
    state_file = tmp_path / "seen.json"
    args = parse_args(["--only", "Airbnb", "--state", str(state_file), "--dry-run"])
    run(args, http=FakeHttp({"greenhouse.io": greenhouse_feed([1])}), telegram=FakeTelegram())
    assert not state_file.exists()
