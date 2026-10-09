"""Send messages to a Telegram channel through a bot.

Telegram allows about 1 message a second in one chat and 20 a minute in a
group, so messages go out 3 seconds apart, and a big batch becomes a digest.
"""

import html
import time

import requests

MAX_MESSAGE = 3800  # Telegram's hard limit is 4096 characters.


class Telegram:
    def __init__(self, token: str, chat_id: str, dry_run: bool = False, gap_seconds: float = 3.0):
        self.token = token
        self.chat_id = chat_id
        self.dry_run = dry_run
        self.gap = gap_seconds
        self._last = 0.0

    def send(self, text: str) -> bool:
        if self.dry_run:
            print("---- Telegram (dry run) ----\n" + text + "\n")
            return True
        wait = self.gap - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        body = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        for _ in range(4):
            try:
                resp = requests.post(url, json=body, timeout=30)
            except requests.RequestException as exc:
                print(f"Telegram request failed: {exc}")
                time.sleep(5)
                continue
            self._last = time.monotonic()
            if resp.ok:
                return True
            if resp.status_code == 429:
                retry = resp.json().get("parameters", {}).get("retry_after", 10)
                time.sleep(int(retry) + 1)
                continue
            print(f"Telegram error {resp.status_code}: {resp.text[:300]}")
            return False
        return False


def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def job_message(job) -> str:
    lines = [f"<b>{esc(job.company)}</b> · {esc(job.title)}"]
    meta = [m for m in (job.location, job.posted) if m]
    if meta:
        lines.append(esc(" · ".join(meta)))
    if job.tags:
        lines.append(f"<i>{esc(', '.join(job.tags))}</i>")
    lines.append(f'<a href="{html.escape(job.url)}">Open the job</a>')
    return "\n".join(lines)


def digest_messages(jobs) -> list:
    header = f"<b>{len(jobs)} new SDE-2 jobs</b>\n"
    messages, current = [], header
    for job in jobs:
        where = f" ({esc(job.location)})" if job.location else ""
        tag = f" <i>[{esc(', '.join(job.tags))}]</i>" if job.tags else ""
        line = (f'\n• <b>{esc(job.company)}</b>: <a href="{html.escape(job.url)}">'
                f"{esc(job.title)}</a>{where}{tag}")
        if len(current) + len(line) > MAX_MESSAGE:
            messages.append(current)
            current = "<b>(continued)</b>\n"
        current += line
    messages.append(current)
    return messages
