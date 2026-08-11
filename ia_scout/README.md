# IA Scout

Content-intelligence pipeline for the "Diario Vida IA" YouTube channel.
Monitors RSS + Reddit + YouTube, deduplicates, analyzes with Claude
(`claude-haiku-4-5-20251001`), writes results to Google Sheets, and posts
a Telegram summary of items worth grabbing.

## Setup

```bash
cd ia_scout
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in the values
```

Place your Google OAuth desktop-client secrets file at
`ia_scout/credentials.json` (download it from Google Cloud Console →
APIs & Services → Credentials → OAuth 2.0 Client IDs → Desktop app).

## First run

```bash
python ia_scout.py
```

The first execution opens a browser for Google OAuth consent. Approve and
close — `token.json` is written and reused silently on later runs.

## Schedule

```
0 */6 * * * cd /ruta/scout && /ruta/scout/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Google Sheet layout

The target spreadsheet (`GOOGLE_SHEETS_ID`) must have two tabs:

- **`Hashes`** — columns: `content_hash | timestamp`
- **`ScoutIA`** — 15 columns (see the header docstring of `ia_scout.py`)

## Files

| File               | Purpose                                       |
| ------------------ | --------------------------------------------- |
| `ia_scout.py`      | Pipeline entrypoint                           |
| `requirements.txt` | Python deps                                   |
| `.env.example`     | Template for `.env`                           |
| `.gitignore`       | Ignores secrets, token, logs, venv           |

Secrets (`.env`, `credentials.json`, `token.json`) are git-ignored — never
commit them.
