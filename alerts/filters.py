"""Decide whether a job is an SDE-2-level role in a target city.

Every rule lives in filters.yaml; this module only applies them.
Titles and locations are compared after normalising: lowercase, punctuation
turned into spaces, so "SDE-II", "Sde 2" and "SDE II" all look alike.
"""

import re

from .models import Job

KEEP, STRETCH, UNLEVELED, DROP = "keep", "stretch", "unleveled", "drop"


def normalise(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return f" {text.strip()} "


def _has_any(norm_text: str, phrases) -> bool:
    return any(f" {normalise(p).strip()} " in norm_text for p in phrases)


class Filters:
    def __init__(self, config: dict):
        title = config.get("title", {})
        self.keep = title.get("keep", [])
        self.stretch = title.get("stretch", [])
        self.unleveled = title.get("unleveled", [])
        self.drop = title.get("drop", [])
        self.drop_exceptions = title.get("drop_exceptions", [])
        self.send_stretch = config.get("send_stretch", True)
        self.send_unleveled = config.get("send_unleveled", True)

        loc = config.get("location", {})
        self.cities = loc.get("cities", [])
        self.remote_india = loc.get("remote_india", [])
        self.allow_india_without_city = loc.get("allow_india_without_city", True)
        self.allow_unknown = loc.get("allow_unknown", True)

    # ---- title -----------------------------------------------------------
    def title_verdict(self, title: str, extra_keep=()) -> str:
        norm = normalise(title)
        drop_hit = _has_any(norm, self.drop) and not _has_any(norm, self.drop_exceptions)
        if _has_any(norm, extra_keep) or _has_any(norm, self.keep):
            return DROP if drop_hit else KEEP
        if drop_hit:
            return DROP
        if _has_any(norm, self.stretch):
            return STRETCH if self.send_stretch else DROP
        if _has_any(norm, self.unleveled):
            return UNLEVELED if self.send_unleveled else DROP
        return DROP

    # ---- location --------------------------------------------------------
    def location_ok(self, location: str) -> bool:
        norm = normalise(location)
        if not norm.strip():
            return self.allow_unknown
        if _has_any(norm, self.cities) or _has_any(norm, self.remote_india):
            return True
        if " india " in norm:
            # "India" with no city named, e.g. "India" or "IN Remote India".
            return self.allow_india_without_city and not _names_other_indian_city(norm, self.cities)
        if re.search(r" \d+ locations? ", norm) or " multiple locations " in norm:
            return self.allow_unknown
        return False

    # ---- both ------------------------------------------------------------
    def apply(self, job: Job, company_cfg: dict):
        """Return the job with tags added if it passes, else None."""
        if company_cfg.get("title_filter", True):
            verdict = self.title_verdict(job.title, company_cfg.get("extra_keep", []))
            if verdict == DROP:
                return None
            if verdict == STRETCH:
                job.tags.append("stretch: senior level")
            elif verdict == UNLEVELED:
                job.tags.append("level not stated")
        if company_cfg.get("location_filter", True) and not self.location_ok(job.location):
            return None
        if not job.location.strip():
            job.tags.append("location not shown")
        return job


OTHER_INDIAN_CITIES = [
    "pune", "chennai", "mumbai", "kolkata", "ahmedabad", "kochi", "coimbatore",
    "trivandrum", "thiruvananthapuram", "jaipur", "indore", "mohali", "chandigarh",
    "vadodara", "nagpur", "bhubaneswar", "visakhapatnam", "mysore", "mysuru", "patna",
]


def _names_other_indian_city(norm: str, target_cities) -> bool:
    """True if the text names an Indian city that is not one of ours."""
    return _has_any(norm, OTHER_INDIAN_CITIES) and not _has_any(norm, target_cities)
