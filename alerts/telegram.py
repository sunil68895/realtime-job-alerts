"""Send messages to a Telegram channel through a bot.

Telegram limits how quickly messages can be sent, so messages go out 3 seconds
apart. Each job is sent as its own message.
"""

import html
import logging
import time

import requests

logger = logging.getLogger("alerts.telegram")


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
                logger.warning("Telegram request failed: %s", exc)
                time.sleep(5)
                continue
            self._last = time.monotonic()
            if resp.ok:
                logger.info("Telegram message sent successfully")
                return True
            if resp.status_code == 429:
                retry = resp.json().get("parameters", {}).get("retry_after", 10)
                logger.warning("Telegram rate limited the send; retrying after %s seconds", retry)
                time.sleep(int(retry) + 1)
                continue
            logger.error("Telegram rejected message: HTTP %s: %s", resp.status_code, resp.text[:300])
            return False
        logger.error("Telegram send failed after all retries")
        return False


def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def job_message(job) -> str:
    lines = [
        f"<b>Company:</b> {esc(job.company)}",
        f"<b>Title:</b> {esc(job.title)}",
        f"<b>Job ID:</b> <code>{esc(job.id)}</code>",
        f"<b>Location:</b> {esc(job.location or 'Not listed')}",
    ]
    if job.posted:
        lines.append(f"<b>Posted:</b> {esc(job.posted)}")
    if job.tags:
        lines.append(f"<i>{esc(', '.join(job.tags))}</i>")
    lines.append(f'<a href="{html.escape(job.url)}">Open the job</a>')
    return "\n".join(lines)
