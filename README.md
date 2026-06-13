# LeadFlow

LeadFlow is a FastAPI + React app for daily Google Places lead discovery, Supabase-hosted lead storage, and optional email enrichment.

## What It Does

- Runs a daily Google Places search at 5:00 AM America/New_York via a cron-safe backend job.
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
APP_ENV=development
RUN_IN_PROCESS_SCHEDULER=true

RESEND_API_KEY=...
RESEND_FROM_EMAIL=...

ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
```

Do not expose `SUPABASE_SERVICE_ROLE_KEY` in frontend env vars. The browser talks to FastAPI only.
In production, set `VITE_API_BASE_URL` in Vercel to the Render backend URL.

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
python -m leadgen.run_daily_job --no-notify
```

Run the daily job for a specific date:

```powershell
python -m leadgen.run_daily_job --date 2026-06-12
```

Production cron-safe execution:

```powershell
python -m leadgen.run_daily_job --require-new-york-hour 5
```

## Tests

```powershell
python -m unittest tests.test_ai_email_enrichment tests.test_local_scrape_suite tests.test_email_scraper tests.test_search_storage -v
npm run build
```

## Important Files

- `leadgen/web_api.py` - FastAPI API, Places orchestration, enrichment endpoints, scheduler.
- `leadgen/run_daily_job.py` - cron-safe one-shot daily job entrypoint.
- `leadgen/hosted_store.py` - Supabase REST storage layer.
- `leadgen/places.py` - Google Places paging and result collection.
- `leadgen/local_scrape_suite.py` - local website crawling/email evidence extraction.
- `leadgen/ai_email_enrichment.py` - local ranking and GPT decision logic.
- `src/main.jsx` - React app.
- `src/styles.css` - responsive app styling.
- `supabase_schema.sql` - hosted DB schema.
- `render.yaml` - Render web service + cron deployment config.
- `vercel.json` - Vercel frontend build config.
