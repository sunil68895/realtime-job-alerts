"""What has already been sent, and how healthy each source is.

Stored in state/seen.json and committed back to the repo by the workflow.
Dates are stored by day, so the file changes at most once a day per job
(plus whenever something new is sent): that keeps the commit history quiet.
"""

import json
import os
from datetime import date, timedelta

FORGET_AFTER_DAYS = 45


class State:
    def __init__(self, path: str):
        self.path = path
        data = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                text = fh.read().strip()
                data = json.loads(text) if text else {}
        self.jobs = data.get("jobs", {})
        self.companies = data.get("companies", {})
        self.today = date.today().isoformat()

    # ---- jobs ------------------------------------------------------------
    def is_seen(self, key: str) -> bool:
        return key in self.jobs

    def mark_seen(self, job) -> None:
        entry = self.jobs.setdefault(job.key, {"first_seen": self.today, "title": job.title})
        entry["last_seen"] = self.today

    def touch(self, key: str) -> None:
        if key in self.jobs:
            self.jobs[key]["last_seen"] = self.today

    def prune(self) -> int:
        cutoff = (date.today() - timedelta(days=FORGET_AFTER_DAYS)).isoformat()
        old = [k for k, v in self.jobs.items() if v.get("last_seen", v.get("first_seen", "")) < cutoff]
        for k in old:
            del self.jobs[k]
        return len(old)

    # ---- companies -------------------------------------------------------
    def company(self, name: str) -> dict:
        return self.companies.setdefault(name, {
            "bootstrapped": False, "fail_streak": 0, "zero_streak": 0, "warned": False,
        })

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        payload = {
            "version": 1,
            "jobs": dict(sorted(self.jobs.items())),
            "companies": dict(sorted(self.companies.items())),
        }
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, self.path)
