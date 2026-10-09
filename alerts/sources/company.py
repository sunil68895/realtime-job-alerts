"""Adapters for companies that run their own job feed."""

from datetime import datetime, timezone

from ..models import FetchError, Job


def amazon(http, cfg):
    url = "https://www.amazon.jobs/en/search.json"
    offset, limit, max_pages = 0, 100, cfg.get("max_pages", 5)
    for _ in range(max_pages):
        params = {
            "base_query": cfg.get("query", "software development engineer"),
            "loc_query": cfg.get("location", "India"),
            "result_limit": limit, "offset": offset, "sort": "recent",
        }
        data = http.get_json(url, params=params)
        jobs = data.get("jobs", [])
        for j in jobs:
            path = j.get("job_path", "")
            yield Job(
                company=cfg["name"], id=str(j.get("id_icims") or j.get("id") or path), title=j.get("title", ""),
                location=j.get("normalized_location") or j.get("location") or j.get("city", ""),
                url=f"https://www.amazon.jobs{path}", posted=j.get("posted_date", ""),
            )
        offset += limit
        if not jobs or offset >= int(data.get("hits", 0)):
            break


def eightfold_pcsx(http, cfg):
    """Newer Eightfold careers sites (Microsoft). 10 results a page."""
    host = cfg["host"]
    start, max_pages = 0, cfg.get("max_pages", 15)
    for _ in range(max_pages):
        data = http.get_json(f"https://{host}/api/pcsx/search", params={
            "domain": cfg["domain"], "query": cfg.get("query", "software engineer"),
            "location": cfg.get("location", "India"), "start": start, "sort_by": "timestamp",
        })
        payload = data.get("data") or {}
        positions = payload.get("positions", [])
        for p in positions:
            yield Job(
                company=cfg["name"], id=str(p["id"]), title=p.get("name", ""),
                location="; ".join(p.get("locations") or p.get("standardizedLocations") or []),
                url=f"https://{host}{p.get('positionUrl', '')}", posted=_unix_to_date(p.get("postedTs")),
            )
        start += len(positions)
        if not positions or start >= payload.get("count", 0):
            break


def eightfold_v2(http, cfg):
    """Older Eightfold careers sites (NetApp, PayPal). 10 results a page."""
    host = cfg["host"]
    start, max_pages = 0, cfg.get("max_pages", 15)
    for _ in range(max_pages):
        data = http.get_json(f"https://{host}/api/apply/v2/jobs", params={
            "domain": cfg["domain"], "location": cfg.get("location", "India"),
            "query": cfg.get("query", ""), "num": 10, "start": start, "sort_by": "relevance",
        })
        positions = data.get("positions", [])
        for p in positions:
            yield Job(
                company=cfg["name"], id=str(p["id"]), title=p.get("name", ""),
                location=p.get("location", "") or "; ".join(p.get("locations") or []),
                url=p.get("canonicalPositionUrl") or f"https://{host}/careers/job/{p['id']}",
                posted=_unix_to_date(p.get("t_create")),
            )
        start += len(positions)
        if not positions or start >= data.get("count", 0):
            break


def atlassian(http, cfg):
    data = http.get_json("https://www.atlassian.com/endpoint/careers/listings")
    if not isinstance(data, list):
        raise FetchError("Atlassian listings were not a list")
    for j in data:
        locations = j.get("locations") or []
        post = j.get("portalJobPost") or {}
        yield Job(
            company=cfg["name"], id=str(j["id"]), title=j.get("title", ""),
            location="; ".join(locations if isinstance(locations, list) else [str(locations)]),
            url=j.get("applyUrl") or post.get("portalUrl") or "https://www.atlassian.com/company/careers/all-jobs",
            posted=(post.get("updatedDate") or "")[:10],
        )


def jibe(http, cfg):
    """Jibe careers sites (AMD). Each item is either flat or wrapped in "data"."""
    page, max_pages = 1, cfg.get("max_pages", 10)
    seen_total = 0
    while page <= max_pages:
        data = http.get_json(f"https://{cfg['host']}/api/jobs", params={
            "keywords": cfg.get("query", "software"), "country": cfg.get("country", "India"), "page": page,
        })
        items = data.get("jobs", [])
        for raw in items:
            j = raw.get("data", raw)
            req = str(j.get("req_id") or j.get("slug"))
            yield Job(
                company=cfg["name"], id=req, title=j.get("title", ""),
                location=", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x),
                url=cfg.get("job_url", "https://{host}/careers-home/jobs/{id}").format(host=cfg["host"], id=req)
                if req else j.get("apply_url", ""),
                posted=(j.get("posted_date") or "")[:10],
            )
        seen_total += len(items)
        if not items or seen_total >= int(data.get("totalCount") or data.get("count") or 0):
            break
        page += 1


def _unix_to_date(ts) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
