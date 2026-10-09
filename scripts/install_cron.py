#!/usr/bin/env python3
"""Install or update the job-alert cron entry from JOB_ALERTS_CRON."""

import subprocess
import sys
from pathlib import Path

from alerts.schedule import read_env_file, validate_cron_expression


BEGIN_MARKER = "# BEGIN realtime-job-alerts"
END_MARKER = "# END realtime-job-alerts"


def replace_managed_entry(existing: str, entry: str) -> str:
    lines = existing.splitlines()
    start = lines.index(BEGIN_MARKER) if BEGIN_MARKER in lines else None
    end = lines.index(END_MARKER) if END_MARKER in lines else None
    if (start is None) != (end is None) or (start is not None and start >= end):
        raise ValueError("Existing crontab has an incomplete job-alerts managed block")

    if start is not None:
        del lines[start:end + 1]
    while lines and not lines[-1]:
        lines.pop()
    lines.extend((BEGIN_MARKER, entry, END_MARKER))
    return "\n".join(lines) + "\n"


def main() -> int:
    home = Path.home()
    env_file = home / ".config" / "job-alerts.env"
    env = read_env_file(env_file)
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if not env.get(key):
            raise ValueError(f"Set {key} in {env_file} before installing the cron job")
    expression = validate_cron_expression(env.get("JOB_ALERTS_CRON", ""))

    project = Path(__file__).resolve().parents[1]
    state_dir = home / ".local" / "state" / "job-alerts"
    state_dir.mkdir(parents=True, exist_ok=True)
    command = (
        f"{expression} cd {project} && {project}/.venv/bin/python "
        f"-m alerts.cron_runner >/dev/null 2>&1"
    )

    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if current.returncode == 0:
        existing = current.stdout
    elif "no crontab for" in current.stderr.lower():
        existing = ""
    else:
        raise RuntimeError(f"Could not read current crontab: {current.stderr.strip()}")

    updated = replace_managed_entry(existing, command)
    result = subprocess.run(["crontab", "-"], input=updated, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"Could not install cron entry: {result.stderr.strip()}")

    print(f"Installed job-alerts schedule: {expression}")
    print(f"Application logs: {state_dir / 'job-alerts.log'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Could not install job-alerts cron entry: {exc}", file=sys.stderr)
        raise SystemExit(1)
