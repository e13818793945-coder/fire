-- 精英顾问陪跑系统 · 数据库结构（SQLite）
-- 角色: admin / agent / coach / pm / insurer  (对应 Role.txt: 系统管理员/代理人/教练/项目经理/保司内勤)

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK(role IN ('admin','agent','coach','pm','insurer')),
    display_name  TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clients (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id          INTEGER NOT NULL REFERENCES users(id),
    name              TEXT NOT NULL,
    phone             TEXT,
    tier              TEXT NOT NULL DEFAULT 'B' CHECK(tier IN ('A','B','C')),
    source            TEXT NOT NULL DEFAULT '自有存量' CHECK(source IN ('自有存量','孤儿单')),
    age_range         TEXT,
    family_status     TEXT,
    income_range      TEXT,
    existing_policies TEXT,
    risk_notes        TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orphan_pool (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT UNIQUE NOT NULL,
    tier          TEXT NOT NULL DEFAULT 'B' CHECK(tier IN ('A','B','C')),
    age_range     TEXT,
    family_status TEXT,
    income_range  TEXT,
    imported_by   INTEGER REFERENCES users(id),
    imported_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kyc_reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id    INTEGER UNIQUE NOT NULL REFERENCES clients(id),
    content      TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS econ_periods (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    seq        INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS econ_updates (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id    INTEGER NOT NULL REFERENCES econ_periods(id),
    agent_id     INTEGER NOT NULL REFERENCES users(id),
    content      TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    UNIQUE(period_id, agent_id)
);

CREATE TABLE IF NOT EXISTS coach_feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    econ_update_id  INTEGER UNIQUE NOT NULL REFERENCES econ_updates(id),
    coach_id        INTEGER NOT NULL REFERENCES users(id),
    content         TEXT NOT NULL,
    submitted_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS central_sessions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    seq       INTEGER NOT NULL,
    date      TEXT,
    title     TEXT,
    summary   TEXT,
    published INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS central_attendance (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES central_sessions(id),
    agent_id   INTEGER NOT NULL REFERENCES users(id),
    present    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(session_id, agent_id)
);

CREATE TABLE IF NOT EXISTS panke_sessions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    seq       INTEGER NOT NULL,
    date      TEXT,
    focus     TEXT,
    content   TEXT,
    published INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS panke_attendance (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES panke_sessions(id),
    agent_id   INTEGER NOT NULL REFERENCES users(id),
    present    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(session_id, agent_id)
);

CREATE TABLE IF NOT EXISTS salon_sessions (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    seq  INTEGER NOT NULL,
    date TEXT
);

CREATE TABLE IF NOT EXISTS salon_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES salon_sessions(id),
    agent_id   INTEGER NOT NULL REFERENCES users(id),
    note       TEXT,
    present    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(session_id, agent_id)
);

CREATE TABLE IF NOT EXISTS growth_reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id     INTEGER UNIQUE NOT NULL REFERENCES users(id),
    metrics_json TEXT NOT NULL DEFAULT '{}',
    narrative    TEXT,
    status       TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published')),
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS final_report (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    content    TEXT,
    published  INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    username   TEXT,
    action     TEXT NOT NULL,
    detail     TEXT,
    created_at TEXT NOT NULL
);
