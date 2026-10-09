# SDE-2 job alerts to Telegram

Checks 26 company careers sites on a configurable schedule and posts each new
SDE-2-level job in Bengaluru, Hyderabad or NCR to your Telegram channel. The
GitHub Actions workflow is manual-only; for automatic checks, use a host timer
such as systemd on an Oracle Cloud VM. Seen jobs are stored in `state/seen.json`.

**Companies watched:** Airbnb, Stripe, Databricks, Rubrik, Okta, Twilio, Zscaler,
Harness, Razorpay, InMobi (Greenhouse) · CRED, Meesho, Paytm (Lever) · Confluent
(Ashby) · Rippling · Amazon · Microsoft · NetApp · Atlassian · AMD · Google ·
Apple · SAP Labs · Nutanix · Palo Alto Networks · Media.net.

16 more (NVIDIA, Salesforce, Adobe, Visa and others) are in `companies.yaml`,
switched off until you test them. See "Adding a company" below.

## Setup (about 20 minutes)

### 1. Create the Telegram bot and channel

1. In Telegram, open **@BotFather**, send `/newbot`, and follow the steps.
   Copy the token it gives you.
2. Create a channel (or use yours). In channel settings, open **Administrators**,
   add your bot, and allow **Post messages**.
3. Get the channel ID:
   - Public channel: `@your_channel_name`.
   - Private channel: post any message in it, then open
     `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the
     `chat.id` (it starts with `-100`). If the list is empty, post again and reload.

### 2. Put the code on GitHub

1. Create a repository. The Actions workflow can be run manually for testing; it
   has no automatic schedule, so it won't duplicate a VM timer.
2. Upload every file in this folder, including the hidden `.github` folder.
3. In the repo, open **Settings → Secrets and variables → Actions → New repository secret**
   and add:
   - `TELEGRAM_BOT_TOKEN` = the BotFather token
   - `TELEGRAM_CHAT_ID` = the channel ID
4. Open **Settings → Actions → General → Workflow permissions** and choose
   **Read and write permissions**, so the workflow can save `state/seen.json`.

### 3. First run

1. Open the **Actions** tab, choose **Check for SDE-2 jobs**, and click **Run workflow**.
2. The first run stores every job that's open today **without** sending anything,
   so your channel isn't flooded with old jobs. From the next run on, only jobs
   that appear later are sent.
3. For automatic checks on an Oracle VM, configure the cron schedule as described
   below. The GitHub Actions workflow remains manual-only.

To check Telegram is wired up before that, run locally:

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=...  TELEGRAM_CHAT_ID=...
python -m alerts.main --test-telegram
```

## What a message looks like

```

Company: Microsoft
Title: Software Engineer II
Job ID: 123456
Location: India, Telangana, Hyderabad
Posted: 2026-10-07
Open the job
```

Explicit senior and SDE-III roles are excluded. Titles with no level (such as
"Software Engineer") are still eligible and tagged "level not stated". Each job
is sent in its own message with its company, job ID, location, and a link.

## Tuning what gets sent

Everything is in `filters.yaml`: the title phrases to keep, tag or drop, and the
cities. To see how every fetched job is judged without sending anything:

```bash
python -m alerts.main --dry-run --show-all
python -m alerts.main --dry-run --show-all --only Google
```

Titles with no stated level can be switched off with `send_unleveled: false`.

## When a site breaks

If a company fails 3 runs in a row, or returns no jobs at all for 6 runs, you get
one warning in the channel. Run `--only <Company> --dry-run --show-all` to see
what's wrong. The usual causes:

- **Feed name changed** (Greenhouse, Lever, Ashby): open the company's careers
  page, click a job, and copy the new name from the job's web address.
- **Web page redesign** (Google, Apple, SAP, Nutanix, Palo Alto, Media.net):
  update `link_pattern` in `companies.yaml` to match the new job links.
- **Blocked**: lower how often the workflow runs.

## Adding a company

1. Find its hiring system (see the "Job Feed Map" doc): click any job on its
   careers site and look at the address.
2. Add an entry to `companies.yaml`, copying one with the same `source`.
3. Test it: `python -m alerts.main --only "<Name>" --dry-run --show-all`.
4. Commit. Its first run stores current jobs silently, like the first run above.

For the 16 entries marked `enabled: false`, step 3 is all that's needed: if it
lists jobs, change `enabled: false` to `true`.

## Files

| Path | What it does |
| --- | --- |
| `companies.yaml` | Which companies to check and how |
| `filters.yaml` | What counts as SDE-2, which cities |
| `alerts/main.py` | Runs everything: fetch, filter, dedupe, send, save |
| `alerts/sources/` | One fetch function per hiring system |
| `alerts/telegram.py` | Message format and sending |
| `state/seen.json` | Jobs already sent and each company's health (committed by the workflow) |
| `.github/workflows/check.yml` | Manual GitHub Actions run |
| `.github/workflows/keepalive.yml` | Monthly commit so GitHub doesn't switch the timer off |
| `tests/` | Offline tests: `pip install pytest && pytest` |

## Good manners

Requests use a normal browser User-Agent, wait at least a second between calls to
the same site, and back off on errors. Messages are sent individually with a delay
between them to respect Telegram rate limits. Use only one scheduler at a time so
the GitHub workflow and VM don't send duplicate alerts.
The alerts are for your own job search only.

## Oracle VM cron schedule

The VM cron runner reads both Telegram credentials and the five-field schedule
from `~/.config/job-alerts.env`. For example:

```text
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
JOB_ALERTS_CRON="*/10 * * * *"
```

Install cron and register or update this project's crontab entry:

```bash
sudo apt install -y cron
sudo systemctl enable --now cron
chmod 600 ~/.config/job-alerts.env
cd ~/realtime-job-alerts
.venv/bin/python -m scripts.install_cron
crontab -l
```

The installer replaces only its own marked entry and leaves unrelated crontab
entries intact. It accepts numeric five-field cron expressions, such as
`*/10 * * * *` (every ten minutes) or `7 * * * *` (hourly at minute 7). The app
logs every company's successful fetch (counts of fetched, matched, and new jobs)
and failed fetch, plus run summaries, to `~/.local/state/job-alerts/job-alerts.log`.
The installer creates `~/realtime-job-alerts/logs` as a symlink to that persistent
log directory for easy access from the project folder.
Telegram delivery errors and successes are also logged without recording credentials
or message contents.
Logs rotate hourly to timestamped files; rotated logs older than five days are
removed when the app starts. The cron runner reads the private env file at each
run and refuses to start without both Telegram credentials. Disable the systemd
timer if you previously configured one.
