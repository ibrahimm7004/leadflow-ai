# Deployment

## Production shape

- Frontend: Vercel
- Backend API: Render web service
- Daily automation: Render cron job

## Vercel

- Root: repo root
- Build command: `npm run build`
- Output directory: `dist`
- Required env vars:

```env
VITE_API_BASE_URL=https://your-render-api.onrender.com
```

## Render web service

- Build command:

```text
pip install -r requirements.txt
```

- Start command:

```text
python -m uvicorn leadgen.web_api:app --host 0.0.0.0 --port $PORT
```

- Required env vars:

```env
APP_ENV=production
RUN_IN_PROCESS_SCHEDULER=false
GOOGLE_MAPS_API_KEY=...
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.5
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
RESEND_API_KEY=...
RESEND_FROM_EMAIL=...
ALLOWED_ORIGINS=https://your-vercel-app.vercel.app
```

## Render cron job

- Build command:

```text
pip install -r requirements.txt
```

- Start command:

```text
python -m leadgen.run_daily_job --require-new-york-hour 5
```

- Schedule:

```text
0 * * * *
```

- Use the same backend env vars as the web service.

## Notes

- Production should not rely on the FastAPI startup scheduler.
- Render cron expressions use UTC. The provided command guards on `America/New_York` hour `5`, so the hourly cron only performs the real run at 5 AM Eastern time.
- Resend is the primary production notification transport.
- SMTP remains an optional local fallback only.
