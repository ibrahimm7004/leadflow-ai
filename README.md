# LeadFlow

LeadFlow is a local FastAPI + React app for daily Google Places lead discovery, Supabase-hosted lead storage, and optional email enrichment.

## What It Does

- Runs a scheduled Google Places search at 5:00 AM America/New_York when the backend is running.
- Stores daily leads in Supabase.
- Shows a mobile-first `Today's Leads` workflow where leads can be ticked off after outreach.
- Provides an `All Leads` archive with filters.
- Lets you configure the weekly search calendar, visible columns, and notification settings.
- Supports email enrichment modes:
  - Local scraper only
  - Local scraper + GPT decision
  - GPT Web Search

## Required Local Setup

Install Python dependencies:

```powershell
pip install -r requirements.txt
```

Install frontend dependencies:

```powershell
npm install
```

Create `.env` in the repo root with:

```env
GOOGLE_MAPS_API_KEY=...
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.5

SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
ENABLE_DAILY_AUTOMATION=true

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=ibrahim.m7004@gmail.com
SMTP_PASSWORD=...
SMTP_FROM=ibrahim.m7004@gmail.com
SMTP_USE_TLS=true
```

Do not expose `SUPABASE_SERVICE_ROLE_KEY` in frontend env vars. The browser talks to FastAPI only.

## Supabase

Run `supabase_schema.sql` in the Supabase SQL editor. It creates:

- `search_runs`
- `leads`
- `app_settings`
- `weekly_schedule`

It also grants the backend service role access to these tables.

More detail: `SETUP_SUPABASE_AUTOMATION.md`.

## Run Locally

Backend:

```powershell
python -m uvicorn leadgen.web_api:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## Useful Checks

Backend health:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Config status:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/config-status
```

Run the daily job manually without email notification:

```powershell
$body = @{ notify = $false } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/app/run-daily -Method Post -ContentType 'application/json' -Body $body
```

## Tests

```powershell
python -m unittest tests.test_ai_email_enrichment tests.test_local_scrape_suite tests.test_email_scraper tests.test_search_storage -v
npm run build
```

## Important Files

- `leadgen/web_api.py` - FastAPI API, Places orchestration, enrichment endpoints, scheduler.
- `leadgen/hosted_store.py` - Supabase REST storage layer.
- `leadgen/places.py` - Google Places paging and result collection.
- `leadgen/local_scrape_suite.py` - local website crawling/email evidence extraction.
- `leadgen/ai_email_enrichment.py` - local ranking and GPT decision logic.
- `src/main.jsx` - React app.
- `src/styles.css` - responsive app styling.
- `supabase_schema.sql` - hosted DB schema.
