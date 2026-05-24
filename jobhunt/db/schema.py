SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS pipeline_stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL,
    color TEXT NOT NULL DEFAULT '#5b5b5b'
);

CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    legal_name TEXT,
    preferred_name TEXT,
    email TEXT,
    phone TEXT,
    address TEXT,
    linkedin_url TEXT,
    portfolio_url TEXT,
    github_url TEXT,
    work_auth TEXT,
    citizenship TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    eeo_gender TEXT,
    eeo_race TEXT,
    eeo_veteran TEXT,
    eeo_disability TEXT
);

CREATE TABLE IF NOT EXISTS resume_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS resume_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_type_id INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    label TEXT,
    content_json TEXT,
    source_format TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (resume_type_id) REFERENCES resume_types(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cover_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER,
    content TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS story_bank (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    theme_tag TEXT,
    title TEXT,
    body TEXT
);

CREATE TABLE IF NOT EXISTS synonym_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    terms_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    source TEXT,
    date_applied TEXT,
    current_stage_id INTEGER,
    fit_score INTEGER,
    resume_version_id INTEGER,
    cover_letter_id INTEGER,
    listing_url TEXT,
    listing_text TEXT,
    autonomous_flag INTEGER DEFAULT 0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (current_stage_id) REFERENCES pipeline_stages(id) ON DELETE SET NULL,
    FOREIGN KEY (resume_version_id) REFERENCES resume_versions(id) ON DELETE SET NULL,
    FOREIGN KEY (cover_letter_id) REFERENCES cover_letters(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS imap_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT,
    server TEXT NOT NULL,
    username TEXT NOT NULL,
    encrypted_password BLOB,
    port INTEGER DEFAULT 993,
    use_ssl INTEGER DEFAULT 1,
    folder_filter TEXT,
    last_uid INTEGER DEFAULT 0,
    last_scan_at TEXT,
    enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    message_id TEXT UNIQUE,
    application_id INTEGER,
    detected_stage TEXT,
    subject TEXT,
    sender TEXT,
    raw_body TEXT,
    received_at TEXT,
    processed_flag INTEGER DEFAULT 0,
    FOREIGN KEY (account_id) REFERENCES imap_accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    interview_datetime TEXT,
    round_type TEXT,
    prep_notes TEXT,
    debrief TEXT,
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS interview_attendees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interview_id INTEGER NOT NULL,
    name TEXT,
    title TEXT,
    linkedin_url TEXT,
    FOREIGN KEY (interview_id) REFERENCES interviews(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER,
    name TEXT,
    title TEXT,
    company TEXT,
    last_interaction TEXT,
    notes TEXT,
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    criteria_json TEXT,
    schedule_cron TEXT,
    mode TEXT DEFAULT 'queue',
    threshold INTEGER DEFAULT 75,
    daily_cap INTEGER DEFAULT 15,
    enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    details_json TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    provider TEXT PRIMARY KEY,
    encrypted_key BLOB
);

CREATE TABLE IF NOT EXISTS trusted_ats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ats_name TEXT NOT NULL UNIQUE,
    enabled INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    base INTEGER,
    equity TEXT,
    bonus INTEGER,
    benefits_json TEXT,
    deadline TEXT,
    notes TEXT,
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings_kv (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_applications_stage ON applications(current_stage_id);
CREATE INDEX IF NOT EXISTS idx_applications_date ON applications(date_applied);
CREATE INDEX IF NOT EXISTS idx_emails_application ON emails(application_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
"""
