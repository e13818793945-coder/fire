import os
import json
from flask import Flask, request, session, redirect, url_for, render_template, flash, g, abort

import db as dbmod
from db import get_db, now_iso, today, get_setting, set_setting, log_action
from auth import load_logged_in_user, login_required, role_required, ROLE_LABEL, ROLE_HOME, all_agents
from kyc import generate_kyc_text
from werkzeug.security import generate_password_hash, check_password_hash
import ai_report

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("COACHING_SECRET_KEY", "dev-secret-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

dbmod.init_app(app)

NAV = {
    "admin": [("admin_users", "角色与权限管理"), ("admin_settings", "系统设置"), ("admin_audit_log", "操作日志")],
    "agent": [
        ("agent_clients", "我的客户"),
        ("agent_econ", "双周经营动态"),
        ("agent_feedback", "教练反馈"),
        ("agent_central", "线上辅导会总结"),
        ("agent_panke", "盘客报告"),
        ("agent_growth", "个人成长报告"),
    ],
    "coach": [("coach_updates", "经营动态反馈")],
    "pm": [
        ("pm_periods", "经营动态周期"),
        ("pm_central", "集中辅导会录入"),
        ("pm_panke", "盘客报告录入"),
        ("pm_salon", "沙龙陪谈录入"),
        ("pm_growth", "成长报告录入"),
        ("pm_final", "结业报告录入"),
    ],
    "insurer": [
        ("insurer_overview", "经营动态总览"),
        ("insurer_central", "集中辅导会情况"),
        ("insurer_panke", "盘客辅导情况"),
        ("insurer_salon", "沙龙陪谈情况"),
        ("insurer_growth", "代理人成长报告"),
        ("insurer_final", "结业报告"),
    ],
}


@app.before_request
def _load_user():
    load_logged_in_user()


@app.context_processor
def _inject_nav():
    if g.get("user"):
        return {"nav_items": NAV.get(g.user["role"], []), "role_label": ROLE_LABEL.get(g.user["role"], "")}
    return {}


def render(template, **ctx):
    return render_template(template, **ctx)


# ---------------- auth ----------------
@app.route("/", methods=["GET"])
def index():
    if g.user is None:
        return redirect(url_for("login"))
    return redirect(url_for(ROLE_HOME[g.user["role"]]))


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for(ROLE_HOME[g.user["role"]]))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row is None or not check_password_hash(row["password_hash"], password):
            flash("账号或密码不正确，请重试", "error")
        elif not row["active"]:
            flash("该账号已被停用，请联系系统管理员", "error")
        else:
            session.clear()
            session["user_id"] = row["id"]
            log_action(row, "登录", "")
            return redirect(url_for(ROLE_HOME[row["role"]]))
    return render("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    if g.user is not None:
        log_action(g.user, "退出登录", "")
    session.clear()
    return redirect(url_for("login"))


# ================= 系统管理员 =================
@app.route("/admin/users")
@role_required("admin")
def admin_users():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'pm' THEN 1 WHEN 'coach' THEN 2 WHEN 'agent' THEN 3 ELSE 4 END, display_name").fetchall()
    return render("admin/users.html", users=users, role_choices=[k for k in ROLE_LABEL if k != "admin"] + ["admin"], role_labels=ROLE_LABEL)


@app.route("/admin/users/new", methods=["POST"])
@role_required("admin")
def admin_users_new():
    db = get_db()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    display_name = request.form.get("display_name", "").strip()
    role = request.form.get("role", "")
    if not username or not password or not display_name or role not in ROLE_LABEL:
        flash("请完整填写账号、密码、姓名并选择角色", "error")
        return redirect(url_for("admin_users"))
    exists = db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
    if exists:
        flash(f"账号「{username}」已存在，请更换", "error")
        return redirect(url_for("admin_users"))
    lock_new = get_setting("lock_new_accounts", "0") == "1"
    db.execute(
        "INSERT INTO users (username, password_hash, role, display_name, active, created_at) VALUES (?,?,?,?,?,?)",
        (username, generate_password_hash(password), role, display_name, 0 if lock_new else 1, now_iso()),
    )
    db.commit()
    log_action(g.user, "创建账号", f"{username} / {ROLE_LABEL[role]}")
    flash(f"已创建账号「{username}」（{ROLE_LABEL[role]}）" + ("，账号默认锁定，需手动启用" if lock_new else ""), "ok")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@role_required("admin")
def admin_users_toggle(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        abort(404)
    if row["role"] == "admin" and row["active"]:
        # 防止把自己或最后一个管理员锁死
        remaining = db.execute("SELECT COUNT(*) c FROM users WHERE role='admin' AND active=1 AND id!=?", (user_id,)).fetchone()["c"]
        if remaining == 0:
            flash("至少需要保留一个已启用的系统管理员账号", "error")
            return redirect(url_for("admin_users"))
    db.execute("UPDATE users SET active=? WHERE id=?", (0 if row["active"] else 1, user_id))
    db.commit()
    log_action(g.user, "启用/禁用账号", row["username"])
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/reset-password", methods=["POST"])
@role_required("admin")
def admin_users_reset_password(user_id):
    db = get_db()
    new_pass = request.form.get("new_password", "")
    row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        abort(404)
    if not new_pass or len(new_pass) < 6:
        flash("新密码至少 6 位", "error")
        return redirect(url_for("admin_users"))
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_pass), user_id))
    db.commit()
    log_action(g.user, "重置密码", row["username"])
    flash(f"已重置「{row['username']}」的密码", "ok")
    return redirect(url_for("admin_users"))


@app.route("/admin/settings", methods=["GET"])
@role_required("admin")
def admin_settings():
    keys = ["auto_backup", "audit_log_retention_days", "lock_new_accounts"]
    settings = {k: get_setting(k) for k in keys}
    return render("admin/settings.html", settings=settings)


@app.route("/admin/settings/toggle/<key>", methods=["POST"])
@role_required("admin")
def admin_settings_toggle(key):
    if key not in ("auto_backup", "lock_new_accounts"):
        abort(404)
    current = get_setting(key, "0")
    set_setting(key, "0" if current == "1" else "1")
    log_action(g.user, "修改系统设置", f"{key} -> {'0' if current == '1' else '1'}")
    return redirect(url_for("admin_settings"))


@app.route("/admin/audit-log")
@role_required("admin")
def admin_audit_log():
    db = get_db()
    rows = db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200").fetchall()
    return render("admin/audit_log.html", rows=rows)


# ================= 代理人 =================
@app.route("/agent/clients")
@role_required("agent")
def agent_clients():
    db = get_db()
    clients = db.execute("SELECT * FROM clients WHERE agent_id=? ORDER BY created_at DESC", (g.user["id"],)).fetchall()
    return render("agent/clients.html", clients=clients)


@app.route("/agent/clients/new", methods=["POST"])
@role_required("agent")
def agent_clients_new():
    db = get_db()
    f = request.form
    name = f.get("name", "").strip()
    if not name:
        flash("请填写客户编码", "error")
        return redirect(url_for("agent_clients"))
    ts = now_iso()
    cur = db.execute(
        """INSERT INTO clients (agent_id, name, phone, tier, source, age_range, family_status, income_range, existing_policies, risk_notes, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (g.user["id"], name, f.get("phone", ""), f.get("tier", "B"), "自有存量",
         f.get("age_range", ""), f.get("family_status", ""), f.get("income_range", ""),
         f.get("existing_policies", ""), f.get("risk_notes", ""), ts, ts),
    )
    client_id = cur.lastrowid
    client = db.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    kyc_text = generate_kyc_text(client)
    db.execute("INSERT INTO kyc_reports (client_id, content, generated_at) VALUES (?,?,?)", (client_id, kyc_text, now_iso()))
    db.commit()
    log_action(g.user, "录入客户", name)
    flash(f"已录入客户「{name}」，KYC 报告已自动生成", "ok")
    return redirect(url_for("agent_clients"))


@app.route("/agent/clients/<int:client_id>")
@role_required("agent")
def agent_client_detail(client_id):
    db = get_db()
    client = db.execute("SELECT * FROM clients WHERE id=? AND agent_id=?", (client_id, g.user["id"])).fetchone()
    if client is None:
        abort(404)
    kyc = db.execute("SELECT * FROM kyc_reports WHERE client_id=?", (client_id,)).fetchone()
    return render("agent/client_detail.html", client=client, kyc=kyc)


@app.route("/agent/econ", methods=["GET"])
@role_required("agent")
def agent_econ():
    db = get_db()
    periods = db.execute("SELECT * FROM econ_periods ORDER BY seq DESC").fetchall()
    current = db.execute("SELECT * FROM econ_periods WHERE is_current=1").fetchone()
    my_updates = {r["period_id"]: r for r in db.execute("SELECT * FROM econ_updates WHERE agent_id=?", (g.user["id"],)).fetchall()}
    feedback_map = {}
    if my_updates:
        rows = db.execute(
            f"SELECT * FROM coach_feedback WHERE econ_update_id IN ({','.join('?' * len(my_updates))})",
            tuple(u["id"] for u in my_updates.values()),
        ).fetchall()
        feedback_map = {r["econ_update_id"]: r for r in rows}
    return render("agent/econ.html", periods=periods, current=current, my_updates=my_updates, feedback_map=feedback_map)


@app.route("/agent/econ/submit", methods=["POST"])
@role_required("agent")
def agent_econ_submit():
    db = get_db()
    current = db.execute("SELECT * FROM econ_periods WHERE is_current=1").fetchone()
    if current is None:
        flash("项目经理尚未开启当前周期", "error")
        return redirect(url_for("agent_econ"))
    content = request.form.get("content", "").strip()
    if not content:
        flash("请填写本期经营动态", "error")
        return redirect(url_for("agent_econ"))

    def _non_negative_int(name):
        try:
            v = int(request.form.get(name, "0") or "0")
        except ValueError:
            v = 0
        return max(0, v)

    def _non_negative_float(name):
        try:
            v = float(request.form.get(name, "0") or "0")
        except ValueError:
            v = 0.0
        return max(0.0, v)

    new_policies_count = _non_negative_int("new_policies_count")
    premium_amount = _non_negative_float("premium_amount")
    fyc_amount = _non_negative_float("fyc_amount")
    referral_count = _non_negative_int("referral_count")

    existing = db.execute("SELECT * FROM econ_updates WHERE period_id=? AND agent_id=?", (current["id"], g.user["id"])).fetchone()
    if existing:
        db.execute(
            """UPDATE econ_updates SET content=?, new_policies_count=?, premium_amount=?, fyc_amount=?,
               referral_count=?, submitted_at=? WHERE id=?""",
            (content, new_policies_count, premium_amount, fyc_amount, referral_count, now_iso(), existing["id"]),
        )
    else:
        db.execute(
            """INSERT INTO econ_updates
               (period_id, agent_id, content, new_policies_count, premium_amount, fyc_amount, referral_count, submitted_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (current["id"], g.user["id"], content, new_policies_count, premium_amount, fyc_amount, referral_count, now_iso()),
        )
    db.commit()
    log_action(g.user, "提交经营动态", f"第{current['seq']}期")
    flash("本期经营动态已提交", "ok")
    return redirect(url_for("agent_econ"))


@app.route("/agent/feedback")
@role_required("agent")
def agent_feedback():
    db = get_db()
    rows = db.execute(
        """SELECT eu.*, ep.seq as period_seq, cf.content as fb_content, cf.submitted_at as fb_at, u.display_name as coach_name
           FROM econ_updates eu
           JOIN econ_periods ep ON ep.id = eu.period_id
           LEFT JOIN coach_feedback cf ON cf.econ_update_id = eu.id
           LEFT JOIN users u ON u.id = cf.coach_id
           WHERE eu.agent_id=? ORDER BY ep.seq DESC""",
        (g.user["id"],),
    ).fetchall()
    return render("agent/feedback.html", rows=rows)


@app.route("/agent/central")
@role_required("agent")
def agent_central():
    db = get_db()
    sessions = db.execute("SELECT * FROM central_sessions ORDER BY seq").fetchall()
    attendance = {r["session_id"]: r["present"] for r in db.execute("SELECT * FROM central_attendance WHERE agent_id=?", (g.user["id"],)).fetchall()}
    return render("agent/central.html", sessions=sessions, attendance=attendance)


@app.route("/agent/panke")
@role_required("agent")
def agent_panke():
    db = get_db()
    sessions = db.execute("SELECT * FROM panke_sessions ORDER BY seq").fetchall()
    attendance = {r["session_id"]: r["present"] for r in db.execute("SELECT * FROM panke_attendance WHERE agent_id=?", (g.user["id"],)).fetchall()}
    return render("agent/panke.html", sessions=sessions, attendance=attendance)


@app.route("/agent/growth")
@role_required("agent")
def agent_growth():
    db = get_db()
    report = db.execute("SELECT * FROM growth_reports WHERE agent_id=? AND status='published'", (g.user["id"],)).fetchone()
    metrics = json.loads(report["metrics_json"]) if report else {}
    return render("agent/growth.html", report=report, metrics=metrics)


# ================= 教练 =================
@app.route("/coach/updates")
@role_required("coach")
def coach_updates():
    db = get_db()
    current = db.execute("SELECT * FROM econ_periods WHERE is_current=1").fetchone()
    agents = all_agents(db)
    rows = []
    if current:
        updates = {r["agent_id"]: r for r in db.execute("SELECT * FROM econ_updates WHERE period_id=?", (current["id"],)).fetchall()}
        fb = {r["econ_update_id"]: r for r in db.execute(
            "SELECT * FROM coach_feedback WHERE econ_update_id IN (SELECT id FROM econ_updates WHERE period_id=?)", (current["id"],)
        ).fetchall()}
        for a in agents:
            u = updates.get(a["id"])
            rows.append({
                "agent": a,
                "econ_update": u,
                "feedback": fb.get(u["id"]) if u else None,
            })
    return render("coach/updates.html", current=current, rows=rows)


@app.route("/coach/updates/<int:update_id>/feedback", methods=["POST"])
@role_required("coach")
def coach_feedback_submit(update_id):
    db = get_db()
    u = db.execute("SELECT * FROM econ_updates WHERE id=?", (update_id,)).fetchone()
    if u is None:
        abort(404)
    content = request.form.get("content", "").strip()
    if not content:
        flash("请填写反馈内容", "error")
        return redirect(url_for("coach_updates"))
    existing = db.execute("SELECT * FROM coach_feedback WHERE econ_update_id=?", (update_id,)).fetchone()
    if existing:
        db.execute("UPDATE coach_feedback SET content=?, coach_id=?, submitted_at=? WHERE id=?", (content, g.user["id"], now_iso(), existing["id"]))
    else:
        db.execute(
            "INSERT INTO coach_feedback (econ_update_id, coach_id, content, submitted_at) VALUES (?,?,?,?)",
            (update_id, g.user["id"], content, now_iso()),
        )
    db.commit()
    log_action(g.user, "提交教练反馈", f"econ_update={update_id}")
    flash("反馈已提交", "ok")
    return redirect(url_for("coach_updates"))


# ================= 项目经理 =================
@app.route("/pm/periods")
@role_required("pm")
def pm_periods():
    db = get_db()
    periods = db.execute("SELECT * FROM econ_periods ORDER BY seq DESC").fetchall()
    return render("pm/periods.html", periods=periods)


@app.route("/pm/periods/new", methods=["POST"])
@role_required("pm")
def pm_periods_new():
    db = get_db()
    start = request.form.get("start_date", "")
    end = request.form.get("end_date", "")
    if not start or not end:
        flash("请填写周期起止日期", "error")
        return redirect(url_for("pm_periods"))
    last = db.execute("SELECT MAX(seq) m FROM econ_periods").fetchone()["m"] or 0
    db.execute("UPDATE econ_periods SET is_current=0")
    db.execute("INSERT INTO econ_periods (seq, start_date, end_date, is_current) VALUES (?,?,?,1)", (last + 1, start, end))
    db.commit()
    log_action(g.user, "新增经营动态周期", f"第{last+1}期 {start}~{end}")
    flash(f"已开启第 {last + 1} 期，并设为当前周期", "ok")
    return redirect(url_for("pm_periods"))


@app.route("/pm/periods/<int:period_id>/set-current", methods=["POST"])
@role_required("pm")
def pm_periods_set_current(period_id):
    db = get_db()
    db.execute("UPDATE econ_periods SET is_current=0")
    db.execute("UPDATE econ_periods SET is_current=1 WHERE id=?", (period_id,))
    db.commit()
    log_action(g.user, "切换当前周期", str(period_id))
    return redirect(url_for("pm_periods"))


def _session_view(kind):
    db = get_db()
    table = "central_sessions" if kind == "central" else "panke_sessions"
    att_table = "central_attendance" if kind == "central" else "panke_attendance"
    sessions = db.execute(f"SELECT * FROM {table} ORDER BY seq").fetchall()
    agents = all_agents(db)
    att = {}
    for r in db.execute(f"SELECT * FROM {att_table}").fetchall():
        att[(r["session_id"], r["agent_id"])] = r["present"]
    return sessions, agents, att


@app.route("/pm/central")
@role_required("pm")
def pm_central():
    sessions, agents, att = _session_view("central")
    return render("pm/central.html", sessions=sessions, agents=agents, att=att)


@app.route("/pm/central/<int:session_id>/update", methods=["POST"])
@role_required("pm")
def pm_central_update(session_id):
    db = get_db()
    f = request.form
    db.execute(
        "UPDATE central_sessions SET date=?, title=?, summary=?, published=? WHERE id=?",
        (f.get("date", ""), f.get("title", ""), f.get("summary", ""), 1 if f.get("published") == "on" else 0, session_id),
    )
    db.commit()
    log_action(g.user, "更新集中辅导会总结", f"session={session_id}")
    flash("已保存", "ok")
    return redirect(url_for("pm_central"))


@app.route("/pm/central/<int:session_id>/attendance/<int:agent_id>/toggle", methods=["POST"])
@role_required("pm")
def pm_central_attendance_toggle(session_id, agent_id):
    db = get_db()
    row = db.execute("SELECT * FROM central_attendance WHERE session_id=? AND agent_id=?", (session_id, agent_id)).fetchone()
    if row:
        db.execute("UPDATE central_attendance SET present=? WHERE id=?", (0 if row["present"] else 1, row["id"]))
    else:
        db.execute("INSERT INTO central_attendance (session_id, agent_id, present) VALUES (?,?,1)", (session_id, agent_id))
    db.commit()
    return redirect(url_for("pm_central"))


@app.route("/pm/panke")
@role_required("pm")
def pm_panke():
    sessions, agents, att = _session_view("panke")
    return render("pm/panke.html", sessions=sessions, agents=agents, att=att)


@app.route("/pm/panke/<int:session_id>/update", methods=["POST"])
@role_required("pm")
def pm_panke_update(session_id):
    db = get_db()
    f = request.form
    db.execute(
        "UPDATE panke_sessions SET date=?, focus=?, content=?, published=? WHERE id=?",
        (f.get("date", ""), f.get("focus", ""), f.get("content", ""), 1 if f.get("published") == "on" else 0, session_id),
    )
    db.commit()
    log_action(g.user, "更新盘客报告", f"session={session_id}")
    flash("已保存", "ok")
    return redirect(url_for("pm_panke"))


@app.route("/pm/panke/<int:session_id>/attendance/<int:agent_id>/toggle", methods=["POST"])
@role_required("pm")
def pm_panke_attendance_toggle(session_id, agent_id):
    db = get_db()
    row = db.execute("SELECT * FROM panke_attendance WHERE session_id=? AND agent_id=?", (session_id, agent_id)).fetchone()
    if row:
        db.execute("UPDATE panke_attendance SET present=? WHERE id=?", (0 if row["present"] else 1, row["id"]))
    else:
        db.execute("INSERT INTO panke_attendance (session_id, agent_id, present) VALUES (?,?,1)", (session_id, agent_id))
    db.commit()
    return redirect(url_for("pm_panke"))


@app.route("/pm/salon")
@role_required("pm")
def pm_salon():
    db = get_db()
    sessions = db.execute("SELECT * FROM salon_sessions ORDER BY seq").fetchall()
    agents = all_agents(db)
    notes = {(r["session_id"], r["agent_id"]): r for r in db.execute("SELECT * FROM salon_notes").fetchall()}
    return render("pm/salon.html", sessions=sessions, agents=agents, notes=notes)


@app.route("/pm/salon/<int:session_id>/save", methods=["POST"])
@role_required("pm")
def pm_salon_save(session_id):
    db = get_db()
    agents = all_agents(db)
    for a in agents:
        note = request.form.get(f"note_{a['id']}", "").strip()
        present = 1 if request.form.get(f"present_{a['id']}") == "on" else 0
        row = db.execute("SELECT * FROM salon_notes WHERE session_id=? AND agent_id=?", (session_id, a["id"])).fetchone()
        if row:
            db.execute("UPDATE salon_notes SET note=?, present=? WHERE id=?", (note, present, row["id"]))
        else:
            db.execute("INSERT INTO salon_notes (session_id, agent_id, note, present) VALUES (?,?,?,?)", (session_id, a["id"], note, present))
    db.commit()
    log_action(g.user, "更新沙龙陪谈记录", f"session={session_id}")
    flash("已保存", "ok")
    return redirect(url_for("pm_salon"))


def compute_agent_metrics(db, agent_id):
    """给 AI 生成成长报告用的结构化统计——全部是数字，不含任何客户或文本原文。"""
    tiers = {"A": 0, "B": 0, "C": 0}
    for row in db.execute("SELECT tier, COUNT(*) as c FROM clients WHERE agent_id=? GROUP BY tier", (agent_id,)).fetchall():
        tiers[row["tier"]] = row["c"]
    kyc_count = db.execute(
        "SELECT COUNT(*) as c FROM kyc_reports k JOIN clients cl ON cl.id=k.client_id WHERE cl.agent_id=?", (agent_id,)
    ).fetchone()["c"]
    econ_total = db.execute("SELECT COUNT(*) as c FROM econ_periods").fetchone()["c"]
    econ_submitted = db.execute("SELECT COUNT(*) as c FROM econ_updates WHERE agent_id=?", (agent_id,)).fetchone()["c"]
    feedback_count = db.execute(
        "SELECT COUNT(*) as c FROM coach_feedback cf JOIN econ_updates eu ON eu.id=cf.econ_update_id WHERE eu.agent_id=?",
        (agent_id,),
    ).fetchone()["c"]
    central_total = db.execute("SELECT COUNT(*) as c FROM central_sessions").fetchone()["c"]
    central_present = db.execute(
        "SELECT COUNT(*) as c FROM central_attendance WHERE agent_id=? AND present=1", (agent_id,)
    ).fetchone()["c"]
    panke_total = db.execute("SELECT COUNT(*) as c FROM panke_sessions").fetchone()["c"]
    panke_present = db.execute(
        "SELECT COUNT(*) as c FROM panke_attendance WHERE agent_id=? AND present=1", (agent_id,)
    ).fetchone()["c"]
    salon_total = db.execute("SELECT COUNT(*) as c FROM salon_sessions").fetchone()["c"]
    salon_present = db.execute(
        "SELECT COUNT(*) as c FROM salon_notes WHERE agent_id=? AND present=1", (agent_id,)
    ).fetchone()["c"]
    perf = db.execute(
        """SELECT COALESCE(SUM(new_policies_count),0) as policies, COALESCE(SUM(premium_amount),0) as premium,
           COALESCE(SUM(fyc_amount),0) as fyc, COALESCE(SUM(referral_count),0) as referrals
           FROM econ_updates WHERE agent_id=?""",
        (agent_id,),
    ).fetchone()
    return {
        "tier_a": tiers["A"], "tier_b": tiers["B"], "tier_c": tiers["C"],
        "kyc_count": kyc_count,
        "econ_total": econ_total, "econ_submitted": econ_submitted,
        "feedback_count": feedback_count,
        "central_total": central_total, "central_present": central_present,
        "panke_total": panke_total, "panke_present": panke_present,
        "salon_total": salon_total, "salon_present": salon_present,
        "policies": perf["policies"], "premium": perf["premium"],
        "fyc": perf["fyc"], "referrals": perf["referrals"],
    }


def compute_cohort_maxes(db):
    """五维打分里「客户经营能力/业绩转化能力/转介绍开发」目前没有公司统一的目标基准数字
    （验收口径里的成功判据还没定），只能算成「跟同期学员里最高值相比」的相对分，
    不是对绝对目标的完成率——等公司定了具体目标数字，这里可以直接换成目标完成率。"""
    agents = all_agents(db)
    max_client_raw = max_policies = max_premium = max_fyc = max_referrals = 0
    for a in agents:
        m = compute_agent_metrics(db, a["id"])
        client_raw = m["tier_a"] * 3 + m["tier_b"] * 2 + m["tier_c"] * 1
        max_client_raw = max(max_client_raw, client_raw)
        max_policies = max(max_policies, m["policies"])
        max_premium = max(max_premium, m["premium"])
        max_fyc = max(max_fyc, m["fyc"])
        max_referrals = max(max_referrals, m["referrals"])
    return {
        "max_client_raw": max_client_raw,
        "max_policies": max_policies, "max_premium": max_premium,
        "max_fyc": max_fyc, "max_referrals": max_referrals,
    }


def compute_growth_score_suggestions(db, agent_id):
    """成长报告四个可计算维度的建议分（0-100），供项目经理/教练参考，不会自动写入已保存的分数。
    「KYC应用能力」现状下每个客户都会自动生成报告、覆盖率恒为 100%，没有区分度，不给建议分，只能人工评。"""
    m = compute_agent_metrics(db, agent_id)
    maxes = compute_cohort_maxes(db)

    attendance_rates = []
    if m["central_total"]:
        attendance_rates.append(m["central_present"] / m["central_total"])
    if m["panke_total"]:
        attendance_rates.append(m["panke_present"] / m["panke_total"])
    if m["salon_total"]:
        attendance_rates.append(m["salon_present"] / m["salon_total"])
    attendance_rate = sum(attendance_rates) / len(attendance_rates) if attendance_rates else 0
    econ_rate = (m["econ_submitted"] / m["econ_total"]) if m["econ_total"] else 0
    activity_score = round(100 * (attendance_rate * 0.5 + econ_rate * 0.5))

    client_raw = m["tier_a"] * 3 + m["tier_b"] * 2 + m["tier_c"] * 1
    client_score = round(100 * client_raw / maxes["max_client_raw"]) if maxes["max_client_raw"] else 0

    perf_components = []
    if maxes["max_policies"]:
        perf_components.append(m["policies"] / maxes["max_policies"])
    if maxes["max_premium"]:
        perf_components.append(m["premium"] / maxes["max_premium"])
    if maxes["max_fyc"]:
        perf_components.append(m["fyc"] / maxes["max_fyc"])
    perf_score = round(100 * sum(perf_components) / len(perf_components)) if perf_components else 0

    referral_score = round(100 * m["referrals"] / maxes["max_referrals"]) if maxes["max_referrals"] else 0

    return {
        "客户经营能力": client_score,
        "活动量达成": activity_score,
        "业绩转化能力": perf_score,
        "转介绍开发": referral_score,
    }


def compute_final_summary(db):
    """给 AI 生成结业报告用的全员汇总统计。"""
    agents = all_agents(db)
    if not agents:
        return None
    per_agent = []
    for a in agents:
        m = compute_agent_metrics(db, a["id"])
        econ_rate = (m["econ_submitted"] / m["econ_total"]) if m["econ_total"] else 0
        feedback_rate = (m["feedback_count"] / m["econ_submitted"]) if m["econ_submitted"] else 0
        central_rate = (m["central_present"] / m["central_total"]) if m["central_total"] else 0
        panke_rate = (m["panke_present"] / m["panke_total"]) if m["panke_total"] else 0
        salon_rate = (m["salon_present"] / m["salon_total"]) if m["salon_total"] else 0
        attendance_pool = [r for r, t in ((central_rate, m["central_total"]), (panke_rate, m["panke_total"]), (salon_rate, m["salon_total"])) if t]
        overall_attendance = sum(attendance_pool) / len(attendance_pool) if attendance_pool else 0
        per_agent.append({
            "name": a["display_name"], "metrics": m,
            "econ_rate": econ_rate, "feedback_rate": feedback_rate,
            "central_rate": central_rate, "panke_rate": panke_rate, "salon_rate": salon_rate,
            "overall_attendance": overall_attendance,
        })
    n = len(per_agent)
    avg = lambda key: sum(p[key] for p in per_agent) / n
    top = max(per_agent, key=lambda p: p["overall_attendance"])
    return {
        "agent_count": n,
        "avg_tier_a": sum(p["metrics"]["tier_a"] for p in per_agent) / n,
        "avg_tier_b": sum(p["metrics"]["tier_b"] for p in per_agent) / n,
        "avg_tier_c": sum(p["metrics"]["tier_c"] for p in per_agent) / n,
        "avg_econ_rate": avg("econ_rate"),
        "avg_feedback_rate": avg("feedback_rate"),
        "avg_central_rate": avg("central_rate"),
        "avg_panke_rate": avg("panke_rate"),
        "avg_salon_rate": avg("salon_rate"),
        "total_policies": sum(p["metrics"]["policies"] for p in per_agent),
        "total_premium": sum(p["metrics"]["premium"] for p in per_agent),
        "total_fyc": sum(p["metrics"]["fyc"] for p in per_agent),
        "total_referrals": sum(p["metrics"]["referrals"] for p in per_agent),
        "top_attendance_name": top["name"],
        "top_attendance_rate": top["overall_attendance"],
    }


@app.route("/pm/growth")
@role_required("pm")
def pm_growth():
    db = get_db()
    agents = all_agents(db)
    reports = {r["agent_id"]: r for r in db.execute("SELECT * FROM growth_reports").fetchall()}
    return render("pm/growth.html", agents=agents, reports=reports)


@app.route("/pm/growth/<int:agent_id>/edit")
@role_required("pm")
def pm_growth_edit(agent_id):
    db = get_db()
    agent = db.execute("SELECT * FROM users WHERE id=? AND role='agent'", (agent_id,)).fetchone()
    if agent is None:
        abort(404)
    report = db.execute("SELECT * FROM growth_reports WHERE agent_id=?", (agent_id,)).fetchone()
    metrics = json.loads(report["metrics_json"]) if report else {}
    dims = ["客户经营能力", "KYC应用能力", "活动量达成", "业绩转化能力", "转介绍开发"]
    suggestions = compute_growth_score_suggestions(db, agent_id)
    return render("pm/growth_edit.html", agent=agent, report=report, metrics=metrics, dims=dims, suggestions=suggestions)


@app.route("/pm/growth/<int:agent_id>/save", methods=["POST"])
@role_required("pm")
def pm_growth_save(agent_id):
    db = get_db()
    dims = ["客户经营能力", "KYC应用能力", "活动量达成", "业绩转化能力", "转介绍开发"]
    metrics = {}
    for d in dims:
        try:
            metrics[d] = max(0, min(100, int(request.form.get(f"metric_{d}", "0"))))
        except ValueError:
            metrics[d] = 0
    narrative = request.form.get("narrative", "").strip()
    status = "published" if request.form.get("published") == "on" else "draft"
    row = db.execute("SELECT * FROM growth_reports WHERE agent_id=?", (agent_id,)).fetchone()
    if row:
        db.execute(
            "UPDATE growth_reports SET metrics_json=?, narrative=?, status=?, updated_at=? WHERE id=?",
            (json.dumps(metrics, ensure_ascii=False), narrative, status, now_iso(), row["id"]),
        )
    else:
        db.execute(
            "INSERT INTO growth_reports (agent_id, metrics_json, narrative, status, updated_at) VALUES (?,?,?,?,?)",
            (agent_id, json.dumps(metrics, ensure_ascii=False), narrative, status, now_iso()),
        )
    db.commit()
    log_action(g.user, "更新成长报告", f"agent={agent_id} status={status}")
    flash("成长报告已保存", "ok")
    return redirect(url_for("pm_growth"))


@app.route("/pm/growth/<int:agent_id>/ai_draft", methods=["POST"])
@role_required("pm")
def pm_growth_ai_draft(agent_id):
    db = get_db()
    agent = db.execute("SELECT * FROM users WHERE id=? AND role='agent'", (agent_id,)).fetchone()
    if agent is None:
        abort(404)
    metrics = compute_agent_metrics(db, agent_id)
    try:
        narrative = ai_report.generate_growth_narrative(agent["display_name"], metrics)
    except ai_report.AIReportError as e:
        flash(f"AI 生成失败：{e}", "error")
        return redirect(url_for("pm_growth_edit", agent_id=agent_id))

    row = db.execute("SELECT * FROM growth_reports WHERE agent_id=?", (agent_id,)).fetchone()
    was_published = bool(row and row["status"] == "published")
    if row:
        # AI 重新生成会改动评语内容，一律打回草稿，需要项目经理重新确认发布，不悄悄覆盖已发布内容
        db.execute(
            "UPDATE growth_reports SET narrative=?, status='draft', updated_at=? WHERE id=?",
            (narrative, now_iso(), row["id"]),
        )
    else:
        db.execute(
            "INSERT INTO growth_reports (agent_id, metrics_json, narrative, status, updated_at) VALUES (?,?,?,?,?)",
            (agent_id, json.dumps({}, ensure_ascii=False), narrative, "draft", now_iso()),
        )
    db.commit()
    log_action(g.user, "AI生成成长报告草稿", f"agent={agent_id}")
    if was_published:
        flash("AI 已生成新的评语草稿，原已发布内容已被替换为草稿，请检查后重新发布", "ok")
    else:
        flash("AI 已生成评语草稿，请检查修改后再保存/发布", "ok")
    return redirect(url_for("pm_growth_edit", agent_id=agent_id))


@app.route("/pm/final")
@role_required("pm")
def pm_final():
    db = get_db()
    report = db.execute("SELECT * FROM final_report WHERE id=1").fetchone()
    return render("pm/final.html", report=report)


@app.route("/pm/final/save", methods=["POST"])
@role_required("pm")
def pm_final_save():
    db = get_db()
    content = request.form.get("content", "").strip()
    published = 1 if request.form.get("published") == "on" else 0
    db.execute("UPDATE final_report SET content=?, published=?, updated_at=? WHERE id=1", (content, published, now_iso()))
    db.commit()
    log_action(g.user, "更新结业报告", f"published={published}")
    flash("结业报告已保存", "ok")
    return redirect(url_for("pm_final"))


@app.route("/pm/final/ai_draft", methods=["POST"])
@role_required("pm")
def pm_final_ai_draft():
    db = get_db()
    summary = compute_final_summary(db)
    if summary is None:
        flash("暂无代理人账号，无法生成结业报告", "error")
        return redirect(url_for("pm_final"))
    try:
        content = ai_report.generate_final_report_narrative(summary)
    except ai_report.AIReportError as e:
        flash(f"AI 生成失败：{e}", "error")
        return redirect(url_for("pm_final"))

    row = db.execute("SELECT * FROM final_report WHERE id=1").fetchone()
    was_published = bool(row and row["published"])
    db.execute("UPDATE final_report SET content=?, published=0, updated_at=? WHERE id=1", (content, now_iso()))
    db.commit()
    log_action(g.user, "AI生成结业报告草稿", "")
    if was_published:
        flash("AI 已生成新的结业报告草稿，原已发布内容已被替换为草稿，请检查后重新发布", "ok")
    else:
        flash("AI 已生成结业报告草稿，请检查修改后再发布", "ok")
    return redirect(url_for("pm_final"))


# ================= 保司内勤（只读） =================
@app.route("/insurer/overview")
@role_required("insurer")
def insurer_overview():
    db = get_db()
    current = db.execute("SELECT * FROM econ_periods WHERE is_current=1").fetchone()
    agents = all_agents(db)
    rows = []
    if current:
        updates = {r["agent_id"]: r for r in db.execute("SELECT * FROM econ_updates WHERE period_id=?", (current["id"],)).fetchall()}
        fb_ids = {u["id"] for u in updates.values()}
        fb = {}
        if fb_ids:
            fb = {r["econ_update_id"]: r for r in db.execute(
                f"SELECT * FROM coach_feedback WHERE econ_update_id IN ({','.join('?' * len(fb_ids))})", tuple(fb_ids)
            ).fetchall()}
        for a in agents:
            u = updates.get(a["id"])
            rows.append({"agent": a, "submitted": bool(u), "feedback": bool(u and u["id"] in fb)})
    return render("insurer/overview.html", current=current, rows=rows)


@app.route("/insurer/central")
@role_required("insurer")
def insurer_central():
    db = get_db()
    sessions = db.execute("SELECT * FROM central_sessions ORDER BY seq").fetchall()
    agents = all_agents(db)
    att = {(r["session_id"], r["agent_id"]): r["present"] for r in db.execute("SELECT * FROM central_attendance").fetchall()}
    return render("insurer/central.html", sessions=sessions, agents=agents, att=att)


@app.route("/insurer/panke")
@role_required("insurer")
def insurer_panke():
    db = get_db()
    sessions = db.execute("SELECT * FROM panke_sessions ORDER BY seq").fetchall()
    agents = all_agents(db)
    att = {(r["session_id"], r["agent_id"]): r["present"] for r in db.execute("SELECT * FROM panke_attendance").fetchall()}
    return render("insurer/panke.html", sessions=sessions, agents=agents, att=att)


@app.route("/insurer/salon")
@role_required("insurer")
def insurer_salon():
    db = get_db()
    sessions = db.execute("SELECT * FROM salon_sessions ORDER BY seq").fetchall()
    agents = all_agents(db)
    notes = {(r["session_id"], r["agent_id"]): r for r in db.execute("SELECT * FROM salon_notes").fetchall()}
    return render("insurer/salon.html", sessions=sessions, agents=agents, notes=notes)


@app.route("/insurer/growth")
@role_required("insurer")
def insurer_growth():
    db = get_db()
    agents = all_agents(db)
    reports = {r["agent_id"]: r for r in db.execute("SELECT * FROM growth_reports WHERE status='published'").fetchall()}
    parsed = {aid: json.loads(r["metrics_json"]) for aid, r in reports.items()}
    return render("insurer/growth.html", agents=agents, reports=reports, metrics=parsed)


@app.route("/insurer/final")
@role_required("insurer")
def insurer_final():
    db = get_db()
    report = db.execute("SELECT * FROM final_report WHERE id=1").fetchone()
    return render("insurer/final.html", report=report)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
