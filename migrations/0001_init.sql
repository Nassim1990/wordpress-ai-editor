-- wpctl spine schema (Supabase / Postgres).
-- The SQLite dev store mirrors this; keep them in sync.

-- Site registry. Secrets are stored as *references*, resolved server-side.
create table if not exists sites (
    slug             text primary key,
    domain           text not null,
    wp_path          text not null,
    ssh_host         text,
    ssh_user         text,
    ssh_port         integer not null default 22,
    ssh_key_ref      text,          -- reference, not the key
    rest_base        text,          -- defaults to https://{domain}/wp-json
    app_password_ref text,          -- reference, not the password
    app_user         text,          -- WP username the app password belongs to
    da_host          text,
    da_account       text,
    dns_provider     text not null default 'directadmin',  -- directadmin | cloudflare | external
    active           boolean not null default true,        -- false = test/disabled
    notes            text,
    created_at       timestamptz not null default now()
);

-- Plans back the R1 confirm and the R2 plan/apply flow.
create table if not exists plans (
    id                  text primary key,            -- short id, shown to operator
    site                text not null references sites(slug),
    tool                text not null,
    tier                text not null,               -- R1 | R2
    params_json         jsonb not null,
    diff_text           text,                        -- dry-run / computed diff shown at approval
    target_hash         text,                        -- drift guard: hash of target at plan time
    backup_tier         text not null default 'none',-- none | file | db | account
    preflight_backup_ref text,                       -- set when the pre-flight backup runs
    snapshot_ref        text,                        -- R1 lightweight snapshot / WP revision
    status              text not null default 'pending', -- pending|approved|rejected|applied|expired|failed
    approved_by         text,
    ttl_expires_at      timestamptz not null,
    used                boolean not null default false,
    result_json         jsonb,
    created_at          timestamptz not null default now(),
    applied_at          timestamptz
);
create index if not exists plans_site_status_idx on plans(site, status);

-- Per-site advisory lock to serialize writes (acquire across plan->apply).
create table if not exists site_locks (
    site        text primary key references sites(slug),
    holder      text not null,         -- plan id holding the lock
    acquired_at timestamptz not null default now()
);

-- Audit log: every call, reads included.
create table if not exists audit_log (
    id              bigserial primary key,
    ts              timestamptz not null default now(),
    site            text,
    tool            text not null,
    tier            text not null,
    input_hash      text not null,
    plan_id         text,
    actor           text not null default 'claude',
    outcome         text not null,     -- ok | error | denied
    result_summary  text
);
create index if not exists audit_site_ts_idx on audit_log(site, ts desc);
