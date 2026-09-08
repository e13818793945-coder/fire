"""登录会话与角色权限控制。"""
from functools import wraps
from flask import session, redirect, url_for, g, abort, flash
from db import get_db

ROLE_LABEL = {
    "admin": "系统管理员",
    "agent": "代理人",
    "coach": "教练",
    "pm": "项目经理",
    "insurer": "保司内勤",
}

ROLE_HOME = {
    "admin": "admin_users",
    "agent": "agent_clients",
    "coach": "coach_updates",
    "pm": "pm_orphan",
    "insurer": "insurer_overview",
}


def load_logged_in_user():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        db = get_db()
        g.user = db.execute("SELECT * FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
        if g.user is None:
            session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("login"))
            if g.user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def all_agents(db):
    return db.execute(
        "SELECT * FROM users WHERE role='agent' AND active=1 ORDER BY display_name"
    ).fetchall()
