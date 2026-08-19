# IA Scout

Content intelligence pipeline for the **Diario Vida IA** YouTube channel
(Paco, `@PacoVidaIA`). Monitors RSS blogs, Reddit, and YouTube RSS feeds;
deduplicates via a Google Sheet; analyses candidates with Claude; persists
results back to the Sheet; and sends a Telegram summary of the "SI" picks.

## Setup

```bash
cd ia_scout
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then fill in ANTHROPIC_API_KEY and TELEGRAM_BOT_TOKEN
```

Put your Google OAuth desktop client secrets in `credentials.json` (download
from Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client
IDs → Desktop app).

The Google Sheet must exist and have two worksheets:

- **Hashes** — columns: `content_hash`, `timestamp`
- **ScoutIA** — columns A–O: `content_hash`, `fecha_detectado`, `fuente`,
  `titulo`, `url`, `autor`, `preview`, `keywords`, `notificado`, `vale`,
  `formato`, `puntuacion`, `gancho`, `angulo`, `estado_revision`

## First run

```bash
python ia_scout.py
```

A browser window opens for Google OAuth. Approve it once; `token.json` is
written and reused thereafter without interaction.

## Scheduling

```cron
0 */6 * * * cd /path/to/ia_scout && /path/to/ia_scout/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Files

```
ia_scout/
├── ia_scout.py        # pipeline
├── requirements.txt   # deps
├── .env.example       # copy to .env
├── .gitignore         # excludes .env, credentials.json, token.json
└── logs/              # scout.log written here
```

Credentials never leave the machine — `.env`, `credentials.json`, and
`token.json` are all gitignored.
