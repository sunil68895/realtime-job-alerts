"""Load Telegram credentials from the private env file and run the checker."""

import os
import sys
from pathlib import Path

from .schedule import read_env_file


def main() -> None:
    env_file = Path.home() / ".config" / "job-alerts.env"
    env = os.environ.copy()
    env.update(read_env_file(env_file))
    if not env.get("TELEGRAM_BOT_TOKEN") or not env.get("TELEGRAM_CHAT_ID"):
        raise RuntimeError(f"Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in {env_file}")

    state_file = Path.home() / ".local" / "state" / "job-alerts" / "seen.json"
    os.execve(
        sys.executable,
        [sys.executable, "-m", "alerts.main", "--state", str(state_file)],
        env,
    )


if __name__ == "__main__":
    main()
