"""数据库访问层：原生 sqlite3，不依赖 ORM，便于直接部署到自建 Ubuntu 服务器。"""
import sqlite3
import os
from datetime import datetime, timedelta
from flask import g, current_app
from werkzeug.security import generate_password_hash

DB_PATH = os.environ.get("COACHING_DB_PATH", os.path.join(os.path.dirname(__file__), "coaching.db"))
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

DEFAULT_ADMIN_USER = os.environ.get("COACHING_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASS = os.environ.get("COACHING_ADMIN_PASS", "p@ssw0rd")


def get_db():
    if "db" not in g:
        db_dir = os.path.dirname(DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now_iso():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return datetime.utcnow().strftime("%Y-%m-%d")


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()


def init_db():
    """建表 + 首次运行的种子数据：管理员账号、3+6+3 场次占位、默认系统设置、第 1 期经营动态周期。"""
    db = get_db()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        db.executescript(f.read())

    # 种子：系统管理员账号（仅在用户表为空时创建，避免覆盖已有账号）
    row = db.execute("SELECT COUNT(*) c FROM users").fetchone()
    if row["c"] == 0:
        db.execute(
            "INSERT INTO users (username, password_hash, role, display_name, active, created_at) VALUES (?,?,?,?,1,?)",
            (DEFAULT_ADMIN_USER, generate_password_hash(DEFAULT_ADMIN_PASS), "admin", "系统管理员", now_iso()),
        )

    # 种子：三大权益场次占位（3 场集中辅导 + 6 次盘客辅导 + 3 场沙龙），字段留空待项目经理录入
    if db.execute("SELECT COUNT(*) c FROM central_sessions").fetchone()["c"] == 0:
        for seq in range(1, 4):
            db.execute(
                "INSERT INTO central_sessions (seq, date, title, summary, published) VALUES (?,?,?,?,0)",
                (seq, "", "", ""),
            )
    if db.execute("SELECT COUNT(*) c FROM panke_sessions").fetchone()["c"] == 0:
        for seq in range(1, 7):
            db.execute(
                "INSERT INTO panke_sessions (seq, date, focus, content, published) VALUES (?,?,?,?,0)",
                (seq, "", "", ""),
            )
    if db.execute("SELECT COUNT(*) c FROM salon_sessions").fetchone()["c"] == 0:
        for seq in range(1, 4):
            db.execute("INSERT INTO salon_sessions (seq, date) VALUES (?,?)", (seq, ""))

    if db.execute("SELECT COUNT(*) c FROM final_report").fetchone()["c"] == 0:
        db.execute("INSERT INTO final_report (id, content, published, updated_at) VALUES (1, '', 0, ?)", (now_iso(),))

    # 种子：第 1 期经营动态周期（双周），后续由项目经理在系统内新增
    if db.execute("SELECT COUNT(*) c FROM econ_periods").fetchone()["c"] == 0:
        start = datetime.utcnow().date()
        end = start + timedelta(days=13)
        db.execute(
            "INSERT INTO econ_periods (seq, start_date, end_date, is_current) VALUES (1, ?, ?, 1)",
            (start.isoformat(), end.isoformat()),
        )

    # 种子：系统设置默认值
    defaults = {
        "auto_backup": "1",
        "two_factor_required": "1",
        "audit_log_retention_days": "180",
        "lock_new_accounts": "0",
    }
    for k, v in defaults.items():
        exists = db.execute("SELECT 1 FROM settings WHERE key=?", (k,)).fetchone()
        if not exists:
            db.execute("INSERT INTO settings (key, value) VALUES (?,?)", (k, v))

    db.commit()


def get_setting(key, default=None):
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    db = get_db()
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    db.commit()


def log_action(user, action, detail=""):
    db = get_db()
    db.execute(
        "INSERT INTO audit_log (user_id, username, action, detail, created_at) VALUES (?,?,?,?,?)",
        (user["id"] if user else None, user["username"] if user else "-", action, detail, now_iso()),
    )
    db.commit()
