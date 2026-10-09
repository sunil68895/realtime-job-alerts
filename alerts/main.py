"""Check every enabled company, alert on new SDE-2 jobs, remember what was sent.

  python -m alerts.main                     normal run (needs the two Telegram env vars)
  python -m alerts.main --dry-run           print messages instead of sending; save nothing
  python -m alerts.main --only Microsoft    check one company
  python -m alerts.main --show-all          print every fetched title and the filter's verdict
  python -m alerts.main --test-telegram     send one test message and stop
  python -m alerts.main --test-backup-telegram  test the optional backup bot
"""

import argparse
import os
import sys
import time

import yaml

from .filters import Filters
from .http import Http
from .logging_setup import configure_logging
from .models import FetchError
from .sources import SOURCES
from .state import State
from .telegram import Telegram, esc, job_message

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL_WARN_AFTER = 3   # runs in a row that error out


def load_yaml(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="SDE-2 job alerts to Telegram")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--only", help="check only this company (name as in companies.yaml)")
    p.add_argument("--show-all", action="store_true")
    p.add_argument("--test-telegram", action="store_true")
    p.add_argument("--test-backup-telegram", action="store_true")
    p.add_argument("--state", default=os.path.join(ROOT, "state", "seen.json"))
    return p.parse_args(argv)


def make_telegram(dry_run):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not dry_run and not (token and chat):
        sys.exit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, or use --dry-run.")
    return Telegram(token, chat, dry_run=dry_run)


def make_backup_telegram(dry_run, logger):
    token = os.environ.get("TELEGRAM_BACKUP_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_BACKUP_CHAT_ID", "")
    if not token and not chat:
        return None
    if not token or not chat:
        logger.error("Backup Telegram is disabled: configure both "
                     "TELEGRAM_BACKUP_BOT_TOKEN and TELEGRAM_BACKUP_CHAT_ID.")
        return None
    return Telegram(token, chat, dry_run=dry_run)


def run(args, http=None, telegram=None, backup_telegram=None) -> int:
    logger = configure_logging(os.path.dirname(os.path.abspath(args.state)) or ".")
    settings = load_yaml("filters.yaml")
    companies = load_yaml("companies.yaml").get("companies", [])
    filters = Filters(settings)
    backup_telegram = backup_telegram or make_backup_telegram(args.dry_run, logger)

    if args.test_backup_telegram:
        if backup_telegram is None:
            sys.exit("Set TELEGRAM_BACKUP_BOT_TOKEN and TELEGRAM_BACKUP_CHAT_ID to test the backup bot.")
        ok = backup_telegram.send("Job alerts backup bot is connected and ready for operational alerts.")
        return 0 if ok else 1

    telegram = telegram or make_telegram(args.dry_run)
    http = http or Http()

    if args.test_telegram:
        ok = telegram.send("Job alerts are connected. New SDE-2 jobs will appear here.")
        return 0 if ok else 1

    state = State(args.state)
    to_send, warnings, backup_notices = [], [], []
    started = time.monotonic()

    for cfg in companies:
        name = cfg["name"]
        if args.only and name.lower() != args.only.lower():
            continue
        if not cfg.get("enabled", True) and not args.only:
            continue
        source = SOURCES.get(cfg.get("source"))
        if source is None:
            logger.warning("[%s] unknown source %r; skipped", name, cfg.get("source"))
            continue

        health = state.company(name)
        try:
            raw = list(source(http, cfg))
        except (FetchError, KeyError, TypeError, ValueError, AttributeError) as exc:
            health["fail_streak"] += 1
            logger.error("[%s] fetch failed (%d consecutive runs): %s",
                         name, health["fail_streak"], exc, exc_info=True)
            if health["fail_streak"] >= FAIL_WARN_AFTER and not health["warned"]:
                warnings.append(f"<b>{esc(name)}</b>: failing for {health['fail_streak']} runs in a row. "
                                f"Last error: {esc(str(exc))[:300]}")
                health["warned"] = True
            if (backup_telegram and health["fail_streak"] >= FAIL_WARN_AFTER
                    and not health.get("backup_fetch_warned", False)):
                backup_notices.append(
                    f"{name}: fetch failed for {health['fail_streak']} consecutive runs. "
                    f"Latest error: {str(exc)[:250]}"
                )
                health["backup_fetch_warned"] = True
            continue

        if health["warned"]:
            logger.info("[%s] recovered after prior fetch failures", name)
        health.update(fail_streak=0, warned=False, backup_fetch_warned=False)
        if raw:
            health["zero_streak"] = 0
        else:
            health["zero_streak"] += 1
            logger.info("[%s] returned no jobs for %d consecutive successful fetches",
                        name, health["zero_streak"])
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
            logger.info("[%s] fetch succeeded: %d jobs; %d matched; bootstrapped without alerts",
                        name, len(raw), len(matched))
            continue

        logger.info("[%s] fetch succeeded: %d jobs; %d matched; %d new",
                    name, len(raw), len(matched), len(new))
        to_send.extend(new)

    sent = send_alerts(telegram, to_send)
    for job in sent:
        state.mark_seen(job)
    failed_alerts = len(to_send) - len(sent)
    for text in warnings:
        if telegram.send("Job alerts warning\n" + text):
            logger.warning("Sent company health warning: %s", text)
        else:
            failed_alerts += 1
            logger.error("Failed to send company health warning.")

    if failed_alerts:
        backup_notices.append(
            f"The primary Telegram bot failed to deliver {failed_alerts} alert(s). "
            "Unsent job alerts remain eligible for retry."
        )
    if backup_notices:
        notify_backup(backup_telegram, backup_notices, logger)

    pruned = state.prune()
    if not args.dry_run:
        state.save()
    logger.info("Run complete in %.0fs: %d sent, %d failed to send, %d warnings, "
                "%d old IDs forgotten.",
                time.monotonic() - started, len(sent), len(to_send) - len(sent),
                len(warnings), pruned)
    return 0 if len(sent) == len(to_send) else 1


def send_alerts(telegram, jobs):
    """Send one message per job and return the jobs that went out."""
    return [job for job in jobs if telegram.send(job_message(job))]


def notify_backup(telegram, notices, logger):
    """Send one operational notice without allowing backup delivery to interrupt job alerts."""
    if telegram is None:
        return
    message = "Job alerts operational notice\n" + "\n".join(
        f"• {esc(notice)}" for notice in notices
    )
    try:
        if not telegram.send(message):
            logger.error("Backup Telegram could not deliver an operational notice.")
    except Exception:
        logger.exception("Backup Telegram raised an error while delivering an operational notice.")


def main(argv=None):
    sys.exit(run(parse_args(argv)))


if __name__ == "__main__":
    main()
