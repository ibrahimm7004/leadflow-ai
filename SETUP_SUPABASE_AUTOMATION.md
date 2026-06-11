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
ENABLE_DAILY_AUTOMATION=true
```

Keep the service role key server-side only. Do not put it in frontend env vars.

## 3. Email notifications

Daily notification emails use SMTP. Add:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-smtp-login
SMTP_PASSWORD=your-smtp-app-password
SMTP_FROM=your-sender-email
SMTP_USE_TLS=true
```

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

When `ENABLE_DAILY_AUTOMATION=true`, the backend starts a background scheduler that runs every day at 5:00 AM America/New_York.

The backend process must be running at that time. For production, deploy the backend on an always-on host or use an external cron service to call:

```text
POST /api/app/run-daily
```
