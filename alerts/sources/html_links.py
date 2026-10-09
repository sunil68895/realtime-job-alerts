"""Read job links straight out of a careers web page.

Used only where a company has no JSON feed (Google, Apple, SAP, Nutanix,
Palo Alto Networks, Media.net). Each company in companies.yaml gives:

  url:          the search page; may contain {page} and {offset}
  pages:        how many pages to read (default 1)
  page_size:    used to work out {offset} (default 25)
  base:         address that relative job links start from (default: the
                page's <base> tag, else the page address)
  link_pattern: a regex for job links. Named groups:
                  id   (required) - unique job ID
                  slug (optional) - the title in the address, used if the
                                    link text isn't a usable title
                  city (optional) - the city in the address
  id_includes_text: true to treat a change in the link text as a new item
                (Media.net's team pages show a role count)

The location comes from the text around each link (the job card), so the
city filter still works on pages that don't put the city in the address.
If a page redesign breaks the pattern, the source returns zero jobs; the
successful empty result is logged for diagnosis without a Telegram warning.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Job

GENERIC_LINK_TEXT = {"", "learn more", "apply", "apply now", "view job", "view details", "details", "read more"}


def html_links(http, cfg):
    pattern = re.compile(cfg["link_pattern"])
    pages = cfg.get("pages", 1)
    page_size = cfg.get("page_size", 25)
    found = {}
    for n in range(pages):
        url = cfg["url"].format(page=n + 1, offset=n * page_size)
        html, final_url = http.get_text(url)
        soup = BeautifulSoup(html, "html.parser")
        base_tag = soup.find("base", href=True)
        base = cfg.get("base") or (urljoin(final_url, base_tag["href"]) if base_tag else final_url)
        new_on_page = 0
        for a in soup.find_all("a", href=True):
            m = pattern.search(a["href"])
            if not m:
                continue
            job_id = m.group("id")
            if job_id in found:
                continue
            groups = m.groupdict()
            title = _clean(a.get_text(" "))
            if title.lower() in GENERIC_LINK_TEXT or len(title) < 4:
                title = _title_from_slug(groups.get("slug") or groups.get("id") or "")
            if cfg.get("id_includes_text"):
                # Alert when the link text changes, e.g. a team page's role count.
                job_id = f"{job_id}|{title}"
            found[job_id] = Job(
                company=cfg["name"], id=job_id, title=title,
                location=_location_near(a, groups.get("city"), cfg.get("location_words", [])),
                url=urljoin(base, a["href"]),
            )
            new_on_page += 1
        if new_on_page == 0:
            break
    return list(found.values())


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _title_from_slug(slug: str) -> str:
    words = re.sub(r"[-_+]+", " ", slug).strip()
    return words[:1].upper() + words[1:] if words else ""


CITY_WORDS = [
    "bengaluru", "bangalore", "hyderabad", "gurugram", "gurgaon", "noida", "new delhi", "delhi",
    "pune", "chennai", "mumbai", "india", "remote",
]


def _location_near(link, city_from_url, extra_words) -> str:
    """Find place names in the job card around a link."""
    words = CITY_WORDS + [w.lower() for w in extra_words]
    hits = []
    if city_from_url:
        hits.append(_title_from_slug(city_from_url))
    node = link
    for _ in range(4):  # walk up to the job card, but not to the whole page
        node = node.parent
        if node is None:
            break
        text = _clean(node.get_text(" "))
        if len(text) > 700:
            break
        low = text.lower()
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", low) and w.title() not in hits:
                hits.append(w.title())
        if hits:
            break
    return ", ".join(hits)
