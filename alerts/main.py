"""Check every enabled company, alert on new SDE-2 jobs, remember what was sent.

  python -m alerts.main                     normal run (needs the two Telegram env vars)
  python -m alerts.main --dry-run           print messages instead of sending; save nothing
  python -m alerts.main --only Microsoft    check one company
  python -m alerts.main --show-all          print every fetched title and the filter's verdict
  python -m alerts.main --test-telegram     send one test message and stop
"""

import argparse
import os
import sys
import time

import yaml

from .filters import Filters
from .http import Http
from .models import FetchError
from .sources import SOURCES
from .state import State
from .telegram import Telegram, esc, job_message

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL_WARN_AFTER = 3   # runs in a row that error out
ZERO_WARN_AFTER = 6   # runs in a row that return no jobs at all


def load_yaml(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="SDE-2 job alerts to Telegram")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--only", help="check only this company (name as in companies.yaml)")
    p.add_argument("--show-all", action="store_true")
    p.add_argument("--test-telegram", action="store_true")
    p.add_argument("--state", default=os.path.join(ROOT, "state", "seen.json"))
    return p.parse_args(argv)


def make_telegram(dry_run):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not dry_run and not (token and chat):
        sys.exit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, or use --dry-run.")
    return Telegram(token, chat, dry_run=dry_run)


def run(args, http=None, telegram=None) -> int:
    settings = load_yaml("filters.yaml")
    companies = load_yaml("companies.yaml").get("companies", [])
    filters = Filters(settings)
    telegram = telegram or make_telegram(args.dry_run)
    http = http or Http()

    if args.test_telegram:
        ok = telegram.send("Job alerts are connected. New SDE-2 jobs will appear here.")
        return 0 if ok else 1

    state = State(args.state)
    to_send, warnings = [], []
    started = time.monotonic()

    for cfg in companies:
        name = cfg["name"]
        if args.only and name.lower() != args.only.lower():
            continue
        if not cfg.get("enabled", True) and not args.only:
            continue
        source = SOURCES.get(cfg.get("source"))
        if source is None:
            print(f"[{name}] unknown source {cfg.get('source')!r}, skipped")
            continue

        health = state.company(name)
        try:
            raw = list(source(http, cfg))
        except (FetchError, KeyError, TypeError, ValueError, AttributeError) as exc:
            health["fail_streak"] += 1
            print(f"[{name}] FAILED ({health['fail_streak']} in a row): {exc}")
            if health["fail_streak"] >= FAIL_WARN_AFTER and not health["warned"]:
                warnings.append(f"<b>{esc(name)}</b>: failing for {health['fail_streak']} runs in a row. "
                                f"Last error: {esc(str(exc))[:300]}")
                health["warned"] = True
            continue

        if not raw:
            health["zero_streak"] += 1
            if health["zero_streak"] >= ZERO_WARN_AFTER and not health["warned"]:
                warnings.append(f"<b>{esc(name)}</b>: no jobs at all for {health['zero_streak']} runs. "
                                "The careers site may have changed.")
                health["warned"] = True
        else:
            if health["warned"]:
                print(f"[{name}] recovered")
            health.update(fail_streak=0, zero_streak=0, warned=False)
        health["last_ok"] = state.today
        health["last_count"] = len(raw)

        matched = []
        for job in raw:
            kept = filters.apply(job, cfg)
            if args.show_all:
                verdict = "SEND" if kept else "skip"
                print(f"  {verdict:4} | {job.title} | {job.location}")
            if kept:
                matched.append(kept)

        new = [j for j in matched if not state.is_seen(j.key)]
        for j in matched:
            state.touch(j.key)

        if not health["bootstrapped"]:
            # First time we see this company: remember what's open now, alert only on later jobs.
            for j in matched:
                state.mark_seen(j)
            health["bootstrapped"] = True
            print(f"[{name}] first run: {len(raw)} jobs, {len(matched)} match, stored without alerting")
            continue

        print(f"[{name}] {len(raw)} jobs, {len(matched)} match, {len(new)} new")
        to_send.extend(new)

    sent = send_alerts(telegram, to_send)
    for job in sent:
        state.mark_seen(job)
    for text in warnings:
        telegram.send("Job alerts warning\n" + text)

    pruned = state.prune()
    if not args.dry_run:
        state.save()
    print(f"Done in {time.monotonic() - started:.0f}s: {len(sent)} sent, "
          f"{len(to_send) - len(sent)} failed to send, {len(warnings)} warnings, {pruned} old IDs forgotten.")
    return 0 if len(sent) == len(to_send) else 1


def send_alerts(telegram, jobs):
    """Send one message per job and return the jobs that went out."""
    return [job for job in jobs if telegram.send(job_message(job))]


def main(argv=None):
    sys.exit(run(parse_args(argv)))


if __name__ == "__main__":
    main()
