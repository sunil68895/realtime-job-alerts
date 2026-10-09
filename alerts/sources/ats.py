"""Adapters for hiring systems that publish a public JSON job feed."""

from ..models import FetchError, Job


def _join(*parts) -> str:
    return ", ".join(p for p in parts if p)


def greenhouse(http, cfg):
    # Some boards live on Greenhouse's EU servers (e.g. Groww): set `region: eu`.
    host = "boards-api.eu.greenhouse.io" if cfg.get("region") == "eu" else "boards-api.greenhouse.io"
    data = http.get_json(f"https://{host}/v1/boards/{cfg['board']}/jobs")
    for j in data.get("jobs", []):
        yield Job(
            company=cfg["name"], id=str(j["id"]), title=j.get("title", ""),
            location=(j.get("location") or {}).get("name", ""),
            url=j.get("absolute_url", ""), posted=(j.get("first_published") or j.get("updated_at") or "")[:10],
        )


def lever(http, cfg):
    data = http.get_json(f"https://api.lever.co/v0/postings/{cfg['board']}", params={"mode": "json"})
    if not isinstance(data, list):
        raise FetchError(f"Lever returned {type(data).__name__}, expected a list")
    for j in data:
        cats = j.get("categories") or {}
        locations = cats.get("allLocations") or [cats.get("location", "")]
        yield Job(
            company=cfg["name"], id=j["id"], title=j.get("text", ""),
            location=_join(*locations, j.get("workplaceType", "") if j.get("workplaceType") == "remote" else ""),
            url=j.get("hostedUrl", ""), posted=_ms_to_date(j.get("createdAt")),
        )


def ashby(http, cfg):
    data = http.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{cfg['board']}")
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        extra = [s.get("location", "") for s in j.get("secondaryLocations") or []]
        yield Job(
            company=cfg["name"], id=str(j.get("id") or j.get("jobUrl")), title=j.get("title", ""),
            location=_join(j.get("location", ""), *extra, "Remote" if j.get("isRemote") else ""),
            url=j.get("jobUrl", ""), posted=(j.get("publishedAt") or "")[:10],
        )


def smartrecruiters(http, cfg):
    offset, limit = 0, 100
    while True:
        data = http.get_json(
            f"https://api.smartrecruiters.com/v1/companies/{cfg['board']}/postings",
            params={"country": cfg.get("country", "in"), "limit": limit, "offset": offset},
        )
        items = data.get("content", [])
        for j in items:
            loc = j.get("location") or {}
            yield Job(
                company=cfg["name"], id=str(j["id"]), title=j.get("name", ""),
                location=_join(loc.get("city", ""), loc.get("region", ""), loc.get("country", "").upper(),
                               "Remote" if loc.get("remote") else ""),
                url=f"https://jobs.smartrecruiters.com/{cfg['board']}/{j['id']}",
                posted=(j.get("releasedDate") or "")[:10],
            )
        offset += limit
        if not items or offset >= data.get("totalFound", 0):
            break


def rippling(http, cfg):
    data = http.get_json(f"https://api.rippling.com/platform/api/ats/v1/board/{cfg['board']}/jobs")
    if isinstance(data, dict):
        data = data.get("items") or data.get("jobs") or []
    merged = {}
    for j in data:  # one row per location; merge them by job id
        url = j.get("url", "")
        job_id = str(j.get("uuid") or url.rstrip("/").rsplit("/", 1)[-1])
        loc = j.get("workLocation")
        loc = loc.get("label", "") if isinstance(loc, dict) else (loc or "")
        if job_id in merged:
            if loc and loc not in merged[job_id].location:
                merged[job_id].location = _join(merged[job_id].location, loc)
            continue
        merged[job_id] = Job(company=cfg["name"], id=job_id, title=j.get("name", ""), location=loc, url=url)
    yield from merged.values()


def workday(http, cfg):
    """Workday's careers-site API. Not an official API, so keep it isolated here.

    cfg: tenant (e.g. nvidia), shard (e.g. wd5), site (e.g. NVIDIAExternalCareerSite)
    """
    base = f"https://{cfg['tenant']}.{cfg['shard']}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{cfg['tenant']}/{cfg['site']}/jobs"
    offset, limit, max_pages = 0, 20, cfg.get("max_pages", 10)
    for _ in range(max_pages):
        body = {"appliedFacets": cfg.get("facets", {}), "limit": limit, "offset": offset,
                "searchText": cfg.get("query", "software engineer")}
        data = http.post_json(api, body)
        postings = data.get("jobPostings", [])
        for j in postings:
            path = j.get("externalPath", "")
            yield Job(
                company=cfg["name"], id=path.rsplit("_", 1)[-1] or path, title=j.get("title", ""),
                location=j.get("locationsText", ""), url=f"{base}/{cfg['site']}{path}",
                posted=j.get("postedOn", ""),
            )
        offset += limit
        if not postings or offset >= data.get("total", 0):
            break


def _ms_to_date(ms) -> str:
    if not ms:
        return ""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
