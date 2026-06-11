create extension if not exists pgcrypto;

create table if not exists search_runs (
  id uuid primary key default gen_random_uuid(),
  run_date date not null,
  search_query text not null,
  business_type text not null,
  search_location text not null,
  params jsonb not null default '{}'::jsonb,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists leads (
  id uuid primary key default gen_random_uuid(),
  lead_date date not null,
  search_run_id uuid references search_runs(id) on delete set null,
  search_query text not null,
  business_type text not null,
  search_location text not null,
  place_id text,
  name text not null,
  phone text,
  address text,
  website_url text,
  raw_website_uri text,
  google_maps_uri text,
  rating numeric,
  user_rating_count integer,
  website_kind text,
  social_platform text,
  social_url text,
  has_external_website boolean not null default false,
  external_website_url text,
  ticked boolean not null default false,
  ticked_at timestamptz,
  best_email text,
  best_email_type text,
  best_email_confidence text,
  best_email_source_url text,
  best_email_evidence text,
  contact_name text,
  contact_title text,
  all_emails_json jsonb,
  email_scrape_status text,
  email_scrape_error text,
  email_selection_method text,
  email_pages_fetched integer,
  email_candidate_count integer,
  email_debug_json jsonb,
  raw_data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop index if exists leads_unique_daily_place;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'leads_unique_daily_place'
  ) then
    alter table leads
    add constraint leads_unique_daily_place unique (lead_date, place_id);
  end if;
end $$;

create index if not exists leads_date_ticked_reviews_idx
on leads (lead_date desc, ticked asc, user_rating_count asc);

create index if not exists leads_search_idx
on leads using gin (
  to_tsvector('simple', coalesce(name, '') || ' ' || coalesce(address, '') || ' ' || coalesce(search_query, '') || ' ' || coalesce(best_email, ''))
);

create table if not exists app_settings (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists weekly_schedule (
  day_of_week integer primary key check (day_of_week between 0 and 6),
  business_type text not null,
  location text not null,
  num_leads integer not null default 25,
  search_mode text not null default 'all_businesses',
  min_rating numeric not null default 3.5,
  max_user_reviews integer not null default 300,
  enabled boolean not null default true,
  updated_at timestamptz not null default now()
);

create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists leads_set_updated_at on leads;
create trigger leads_set_updated_at
before update on leads
for each row execute function set_updated_at();

drop trigger if exists app_settings_set_updated_at on app_settings;
create trigger app_settings_set_updated_at
before update on app_settings
for each row execute function set_updated_at();

drop trigger if exists weekly_schedule_set_updated_at on weekly_schedule;
create trigger weekly_schedule_set_updated_at
before update on weekly_schedule
for each row execute function set_updated_at();

grant usage on schema public to service_role;
grant select, insert, update, delete on table search_runs to service_role;
grant select, insert, update, delete on table leads to service_role;
grant select, insert, update, delete on table app_settings to service_role;
grant select, insert, update, delete on table weekly_schedule to service_role;
grant usage, select on all sequences in schema public to service_role;
