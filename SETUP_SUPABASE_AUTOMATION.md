# Supabase + Daily Automation Setup

## 1. Create Supabase database

1. Create a Supabase project.
2. Open the Supabase SQL editor.
3. Paste and run `supabase_schema.sql` from this repo.
4. In Project Settings, copy:
   - Project URL
   - Service role key

## 2. Add backend env vars

Add these to `.env`:

```env
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
APP_ENV=development
RUN_IN_PROCESS_SCHEDULER=true
ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
```

Keep the service role key server-side only. Do not put it in frontend env vars.

## 3. Email notifications

Production notifications use Resend. Add:

```env
RESEND_API_KEY=your-resend-api-key
RESEND_FROM_EMAIL=your-verified-resend-sender
```

Optional local fallback: SMTP is still supported if you explicitly set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_FROM`.
The recipient defaults to `ibrahim.m7004@gmail.com` and can be changed from the app Settings page.

## 4. Run locally

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

## 5. Daily run behavior

For local development, `RUN_IN_PROCESS_SCHEDULER=true` starts a background scheduler that runs every day at 5:00 AM America/New_York.

For production, use a dedicated cron job instead of relying on the web process. This repo includes a cron-safe entrypoint:

```text
python -m leadgen.run_daily_job
```

Recommended deployment:

- Vercel for the frontend
- Render web service for FastAPI
- Render cron job for `python -m leadgen.run_daily_job`
