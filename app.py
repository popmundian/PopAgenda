#!/usr/bin/env python3
"""
Agendador de Mensagens Telegram — Painel Web + Bot integrado
v3: múltiplos usuários com permissões (admin/user), contatos com nomes
amigáveis para Chat IDs, e envio de teste com confirmação de senha.
"""

import os
import logging
import sqlite3
import secrets
from datetime import datetime, date, time as dtime, timedelta
from zoneinfo import ZoneInfo
from functools import wraps

import requests
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify
)
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

# ── Configurações ────────────────────────────────────────────────────────────
TOKEN           = os.getenv("TELEGRAM_TOKEN", "")
TIMEZONE        = os.getenv("TIMEZONE", "America/Sao_Paulo")
DB_PATH         = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedules.db"))
SECRET_KEY      = os.getenv("SECRET_KEY", secrets.token_hex(32))
CRON_SECRET     = os.getenv("CRON_SECRET", "")
WEBHOOK_SECRET  = os.getenv("WEBHOOK_SECRET", "")

# Chat (pessoal ou de grupo) do Telegram que recebe alertas de falha de
# envio. Opcional — se vazio, os alertas simplesmente não são enviados
# (mas continuam registrados no log de auditoria normalmente).
ADMIN_CHAT_ID   = os.getenv("ADMIN_CHAT_ID", "")

# Usados SÓ para criar a primeira conta admin, na primeira vez que o app
# roda (banco vazio). Depois disso, gerenciamento de usuário é todo feito
# pela tela "Usuários" — estas variáveis podem até ser removidas do .env.
SEED_ADMIN_USER = os.getenv("WEB_USER", "admin")
SEED_ADMIN_PASS = os.getenv("WEB_PASS", "")

TZ = ZoneInfo(TIMEZONE)
TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = SECRET_KEY


# ── Banco de dados ───────────────────────────────────────────────────────────
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     TEXT    NOT NULL,
                label       TEXT    NOT NULL DEFAULT '',
                message     TEXT    NOT NULL,
                period_days INTEGER NOT NULL,
                start_date  TEXT    NOT NULL,
                end_date    TEXT,
                send_time   TEXT    NOT NULL DEFAULT '08:00',
                last_sent   TEXT,
                active      INTEGER NOT NULL DEFAULT 1,
                created_by  TEXT,
                created_at  TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS send_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_id INTEGER NOT NULL,
                sent_at     TEXT    NOT NULL,
                status      TEXT    NOT NULL,
                detail      TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'user',
                created_at    TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id       TEXT NOT NULL UNIQUE,
                friendly_name TEXT NOT NULL,
                created_by    TEXT,
                created_at    TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                actor     TEXT,
                action    TEXT NOT NULL,
                details   TEXT
            )
        """)
        conn.commit()

        # Migração: quem já tinha o banco criado antes desta atualização não
        # tem a coluna send_time — adiciona agora, sem apagar nada existente.
        cols = [c[1] for c in conn.execute("PRAGMA table_info(schedules)").fetchall()]
        if "send_time" not in cols:
            conn.execute("ALTER TABLE schedules ADD COLUMN send_time TEXT NOT NULL DEFAULT '08:00'")
            conn.commit()
            logger.info("Migração aplicada: coluna send_time adicionada.")

        # Semeia a primeira conta admin — só roda se AINDA não existir
        # nenhum usuário na tabela (ou seja, só na primeira execução).
        existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if existing == 0 and SEED_ADMIN_PASS:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
                (SEED_ADMIN_USER, generate_password_hash(SEED_ADMIN_PASS), "admin",
                 datetime.now(TZ).isoformat())
            )
            conn.commit()
            logger.info("Conta admin inicial criada a partir do .env: %s", SEED_ADMIN_USER)


# Roda ao importar o módulo — inclusive quando o PythonAnywhere importa
# "app" pelo arquivo WSGI (que nunca executa o "if __name__ == '__main__'").
init_db()


# ── Helpers de data ──────────────────────────────────────────────────────────
def hoje() -> date:
    return datetime.now(TZ).date()


def parse_date(s):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except (ValueError, AttributeError):
            pass
    return None


def next_occurrence(start: date, period: int, last_sent) -> date:
    if last_sent:
        ref = last_sent if isinstance(last_sent, date) else date.fromisoformat(last_sent)
    else:
        ref = start - timedelta(days=period)
    n = ref + timedelta(days=period)
    while n < start:
        n += timedelta(days=period)
    return n


def parse_time_str(s) -> dtime:
    try:
        h, m = str(s).split(":")
        return dtime(int(h), int(m))
    except (ValueError, AttributeError):
        return dtime(8, 0)


def enrich(row):
    d = dict(row)
    start = date.fromisoformat(d["start_date"])
    last  = date.fromisoformat(d["last_sent"]) if d["last_sent"] else None
    prox  = next_occurrence(start, d["period_days"], last)
    today = hoje()
    d["next_date"]    = prox.isoformat()
    d["next_display"] = prox.strftime("%d/%m/%Y")
    d["send_time"]     = d.get("send_time") or "08:00"
    # "atrasado" agora também considera o horário: só fica pendente de
    # verdade se a data já chegou E o horário marcado já passou (ou se a
    # data já é passada há mais de um dia, aí não faz sentido esperar).
    agora = datetime.now(TZ).time()
    horario_alvo = parse_time_str(d["send_time"])
    pendente_hoje = prox == today and agora >= horario_alvo
    d["overdue"]       = (prox < today or pendente_hoje) and d["active"]
    d["end_display"]   = date.fromisoformat(d["end_date"]).strftime("%d/%m/%Y") if d["end_date"] else "—"
    d["start_display"] = start.strftime("%d/%m/%Y")
    return d


def get_contacts_map():
    with get_conn() as conn:
        rows = conn.execute("SELECT chat_id, friendly_name FROM contacts").fetchall()
    return {r["chat_id"]: r["friendly_name"] for r in rows}


# ── Telegram: envio simples via HTTP ─────────────────────────────────────────
def enviar_telegram(chat_id: str, texto: str) -> tuple[bool, str]:
    if not TOKEN:
        return False, "TELEGRAM_TOKEN não configurado"
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"},
            timeout=15,
        )
        if resp.ok and resp.json().get("ok"):
            return True, "ok"
        return False, resp.text[:300]
    except requests.RequestException as exc:
        return False, str(exc)[:300]


def alertar_admin(texto: str):
    """Envia um aviso para o chat do admin no Telegram, se configurado.
    Usado hoje só para falhas de envio (as que mais precisam de atenção
    imediata) — dá pra ampliar depois se fizer sentido."""
    if ADMIN_CHAT_ID:
        enviar_telegram(ADMIN_CHAT_ID, f"🔔 *PopAgenda*\n{texto}")


def registrar_auditoria(action: str, details: str = "", actor: str = None):
    actor = actor or session.get("username", "sistema")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (timestamp, actor, action, details) VALUES (?,?,?,?)",
            (datetime.now(TZ).isoformat(), actor, action, details)
        )
        conn.commit()


# ── Auth ─────────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            flash("Essa ação é restrita ao administrador.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
        if row and check_password_hash(row["password_hash"], p):
            session["logged_in"] = True
            session["user_id"]   = row["id"]
            session["username"]  = row["username"]
            session["role"]      = row["role"]
            registrar_auditoria("login", "login bem-sucedido", actor=u)
            return redirect(url_for("index"))
        registrar_auditoria("login_falhou", f"tentativa com usuário '{u}'", actor=u or "desconhecido")
        flash("Usuário ou senha incorretos.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/minha-conta", methods=["GET", "POST"])
@login_required
def minha_conta():
    if request.method == "POST":
        atual = request.form.get("current_password", "")
        nova  = request.form.get("new_password", "")
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if not row or not check_password_hash(row["password_hash"], atual):
            flash("Senha atual incorreta.", "danger")
        elif len(nova) < 6:
            flash("A nova senha precisa ter pelo menos 6 caracteres.", "danger")
        else:
            with get_conn() as conn:
                conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                             (generate_password_hash(nova), session["user_id"]))
                conn.commit()
            registrar_auditoria("trocar_senha", "usuário trocou a própria senha")
            flash("Senha alterada com sucesso! ✅", "success")
            return redirect(url_for("index"))
    return render_template("conta.html", user=session.get("username"),
                           is_admin=(session.get("role") == "admin"))


# ── Gerenciamento de usuários (admin) ────────────────────────────────────────
@app.route("/usuarios")
@admin_required
def usuarios():
    with get_conn() as conn:
        rows = conn.execute("SELECT id, username, role, created_at FROM users ORDER BY id").fetchall()
    return render_template("usuarios.html", usuarios=rows, user=session.get("username"), is_admin=True)


@app.route("/usuarios/novo", methods=["POST"])
@admin_required
def usuarios_novo():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role     = request.form.get("role", "user")
    if role not in ("admin", "user"):
        role = "user"
    if not username or len(password) < 6:
        flash("Informe um usuário e uma senha com pelo menos 6 caracteres.", "danger")
        return redirect(url_for("usuarios"))
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
                (username, generate_password_hash(password), role, datetime.now(TZ).isoformat())
            )
            conn.commit()
        registrar_auditoria("criar_usuario", f"'{username}' como {role}")
        flash(f"Usuário '{username}' criado como {role}. ✅", "success")
    except sqlite3.IntegrityError:
        flash("Já existe um usuário com esse nome.", "danger")
    return redirect(url_for("usuarios"))


@app.route("/usuarios/resetar/<int:uid>", methods=["POST"])
@admin_required
def usuarios_resetar(uid):
    nova_senha = request.form.get("password", "")
    if len(nova_senha) < 6:
        flash("Senha muito curta (mínimo 6 caracteres).", "danger")
        return redirect(url_for("usuarios"))
    with get_conn() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                     (generate_password_hash(nova_senha), uid))
        conn.commit()
    registrar_auditoria("resetar_senha", f"senha de user_id={uid} redefinida pelo admin")
    flash("Senha redefinida com sucesso.", "success")
    return redirect(url_for("usuarios"))


@app.route("/usuarios/remover/<int:uid>", methods=["POST"])
@admin_required
def usuarios_remover(uid):
    if uid == session.get("user_id"):
        flash("Você não pode remover a própria conta.", "danger")
        return redirect(url_for("usuarios"))
    with get_conn() as conn:
        row = conn.execute("SELECT role, username FROM users WHERE id=?", (uid,)).fetchone()
        if row and row["role"] == "admin":
            total_admins = conn.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
            if total_admins <= 1:
                flash("Não é possível remover o último administrador.", "danger")
                return redirect(url_for("usuarios"))
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.commit()
    registrar_auditoria("remover_usuario", f"'{row['username'] if row else uid}' removido")
    flash("Usuário removido.", "warning")
    return redirect(url_for("usuarios"))


@app.route("/auditoria")
@admin_required
def auditoria():
    filtro = request.args.get("acao", "")
    with get_conn() as conn:
        if filtro:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE action=? ORDER BY id DESC LIMIT 300", (filtro,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 300").fetchall()
        acoes = conn.execute("SELECT DISTINCT action FROM audit_log ORDER BY action").fetchall()
    return render_template("auditoria.html", logs=rows, acoes=[a["action"] for a in acoes],
                           filtro=filtro, user=session.get("username"), is_admin=True)


# ── Contatos (nomes amigáveis para Chat IDs) ─────────────────────────────────
@app.route("/contatos")
@login_required
def contatos():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM contacts ORDER BY friendly_name").fetchall()
    return render_template("contatos.html", contatos=rows, user=session.get("username"),
                           is_admin=(session.get("role") == "admin"))


@app.route("/contatos/novo", methods=["POST"])
@login_required
def contatos_novo():
    chat_id = request.form.get("chat_id", "").strip()
    nome    = request.form.get("friendly_name", "").strip()
    if not chat_id or not nome:
        flash("Preencha o Chat ID e o nome amigável.", "danger")
        return redirect(url_for("contatos"))
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO contacts (chat_id, friendly_name, created_by, created_at) VALUES (?,?,?,?)",
                (chat_id, nome, session.get("username"), datetime.now(TZ).isoformat())
            )
            conn.commit()
        flash(f"Contato '{nome}' cadastrado! ✅", "success")
    except sqlite3.IntegrityError:
        flash("Esse Chat ID já está cadastrado como contato.", "danger")
    return redirect(url_for("contatos"))


@app.route("/contatos/remover/<int:cid>", methods=["POST"])
@login_required
def contatos_remover(cid):
    with get_conn() as conn:
        conn.execute("DELETE FROM contacts WHERE id=?", (cid,))
        conn.commit()
    flash("Contato removido.", "warning")
    return redirect(url_for("contatos"))


# ── Rotas do painel (agendamentos) ───────────────────────────────────────────
@app.route("/")
@login_required
def index():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM schedules ORDER BY active DESC, id DESC").fetchall()
    contacts_map = get_contacts_map()
    schedules = []
    for r in rows:
        s = enrich(r)
        s["friendly_name"] = contacts_map.get(s["chat_id"])
        schedules.append(s)
    return render_template("index.html", schedules=schedules, user=session.get("username"),
                           is_admin=(session.get("role") == "admin"))


@app.route("/novo", methods=["GET", "POST"])
@login_required
def novo():
    with get_conn() as conn:
        contacts = conn.execute("SELECT * FROM contacts ORDER BY friendly_name").fetchall()

    if request.method == "POST":
        label       = request.form.get("label", "").strip()
        chat_id     = request.form.get("chat_id", "").strip()
        period_str  = request.form.get("period_days", "").strip()
        start_str   = request.form.get("start_date", "").strip()
        end_str     = request.form.get("end_date", "").strip()
        send_time   = request.form.get("send_time", "").strip() or "08:00"
        message     = request.form.get("message", "").strip()

        errors = []
        if not chat_id:
            errors.append("Informe o Chat ID do grupo.")
        if not period_str.isdigit() or int(period_str) < 1:
            errors.append("Período deve ser um número inteiro positivo.")
        start = parse_date(start_str)
        if not start:
            errors.append("Data de início inválida.")
        end = parse_date(end_str) if end_str else None
        if end and start and end <= start:
            errors.append("Data final deve ser posterior à inicial.")
        if not message:
            errors.append("A mensagem não pode ser vazia.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("form.html", action="novo", data=request.form,
                                   contacts=contacts, user=session.get("username"),
                                   is_admin=(session.get("role") == "admin"))

        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO schedules
                  (chat_id, label, message, period_days, start_date, end_date, send_time, created_by, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                chat_id, label, message, int(period_str),
                start.isoformat(),
                end.isoformat() if end else None,
                send_time,
                session.get("username"),
                datetime.now(TZ).isoformat(),
            ))
            conn.commit()
        registrar_auditoria("criar_agendamento", f"#{cur.lastrowid} - {label or 'sem rótulo'}")
        flash("Agendamento criado com sucesso! ✅", "success")
        return redirect(url_for("index"))

    return render_template("form.html", action="novo", data={}, contacts=contacts,
                           user=session.get("username"), is_admin=(session.get("role") == "admin"))


@app.route("/editar/<int:sid>", methods=["GET", "POST"])
@login_required
def editar(sid):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM schedules WHERE id=?", (sid,)).fetchone()
        contacts = conn.execute("SELECT * FROM contacts ORDER BY friendly_name").fetchall()
    if not row:
        flash("Agendamento não encontrado.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        label      = request.form.get("label", "").strip()
        period_str = request.form.get("period_days", "").strip()
        start_str  = request.form.get("start_date", "").strip()
        end_str    = request.form.get("end_date", "").strip()
        send_time  = request.form.get("send_time", "").strip() or "08:00"
        message    = request.form.get("message", "").strip()

        errors = []
        if not period_str.isdigit() or int(period_str) < 1:
            errors.append("Período inválido.")
        start = parse_date(start_str)
        if not start:
            errors.append("Data de início inválida.")
        end = parse_date(end_str) if end_str else None
        if end and start and end <= start:
            errors.append("Data final deve ser posterior à inicial.")
        if not message:
            errors.append("A mensagem não pode ser vazia.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("form.html", action="editar", sid=sid, data=request.form,
                                   contacts=contacts, user=session.get("username"),
                                   is_admin=(session.get("role") == "admin"))

        with get_conn() as conn:
            conn.execute("""
                UPDATE schedules SET label=?, message=?, period_days=?,
                  start_date=?, end_date=?, send_time=? WHERE id=?
            """, (label, message, int(period_str),
                  start.isoformat(), end.isoformat() if end else None, send_time, sid))
            conn.commit()
        registrar_auditoria("editar_agendamento", f"#{sid}")
        flash("Agendamento atualizado! ✅", "success")
        return redirect(url_for("index"))

    data = dict(row)
    return render_template("form.html", action="editar", sid=sid, data=data, contacts=contacts,
                           user=session.get("username"), is_admin=(session.get("role") == "admin"))


@app.route("/toggle/<int:sid>")
@login_required
def toggle(sid):
    with get_conn() as conn:
        row = conn.execute("SELECT active FROM schedules WHERE id=?", (sid,)).fetchone()
        if row:
            novo_estado = 0 if row["active"] else 1
            conn.execute("UPDATE schedules SET active=? WHERE id=?", (novo_estado, sid))
            conn.commit()
            registrar_auditoria("alterar_status", f"#{sid} -> {'ativo' if novo_estado else 'pausado'}")
            flash(f"Agendamento #{sid} {'ativado ✅' if novo_estado else 'pausado ⏸'}.", "info")
    return redirect(url_for("index"))


@app.route("/remover/<int:sid>", methods=["POST"])
@admin_required
def remover(sid):
    with get_conn() as conn:
        conn.execute("DELETE FROM schedules WHERE id=?", (sid,))
        conn.execute("DELETE FROM send_log WHERE schedule_id=?", (sid,))
        conn.commit()
    registrar_auditoria("apagar_agendamento", f"#{sid}")
    flash(f"Agendamento #{sid} removido.", "warning")
    return redirect(url_for("index"))


@app.route("/testar/<int:sid>", methods=["POST"])
@login_required
def testar_envio(sid):
    senha = request.form.get("password", "")
    with get_conn() as conn:
        u = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if not u or not check_password_hash(u["password_hash"], senha):
        flash("Senha incorreta — envio de teste cancelado.", "danger")
        return redirect(url_for("index"))

    with get_conn() as conn:
        r = conn.execute("SELECT * FROM schedules WHERE id=?", (sid,)).fetchone()
    if not r:
        flash("Agendamento não encontrado.", "danger")
        return redirect(url_for("index"))

    ok, detail = enviar_telegram(r["chat_id"], f"🧪 *[TESTE]* {r['message']}")
    registrar_auditoria("teste_envio", f"#{sid} -> {'ok' if ok else 'falhou: ' + detail[:100]}")
    if ok:
        flash(f"Mensagem de teste enviada! Confira o grupo/canal. ✅", "success")
    else:
        flash(f"Falha ao enviar teste: {detail}", "danger")
    return redirect(url_for("index"))


@app.route("/log/<int:sid>")
@login_required
def log_schedule(sid):
    with get_conn() as conn:
        sched = conn.execute("SELECT * FROM schedules WHERE id=?", (sid,)).fetchone()
        logs  = conn.execute(
            "SELECT * FROM send_log WHERE schedule_id=? ORDER BY sent_at DESC LIMIT 30",
            (sid,)
        ).fetchall()
    if not sched:
        flash("Agendamento não encontrado.", "danger")
        return redirect(url_for("index"))
    return render_template("log.html", sched=dict(sched), logs=logs, user=session.get("username"),
                           is_admin=(session.get("role") == "admin"))


@app.route("/api/status")
@login_required
def api_status():
    with get_conn() as conn:
        total  = conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]
        ativos = conn.execute("SELECT COUNT(*) FROM schedules WHERE active=1").fetchone()[0]
        hoje_n = conn.execute(
            "SELECT COUNT(*) FROM send_log WHERE sent_at LIKE ?",
            (hoje().isoformat() + "%",)
        ).fetchone()[0]
    return jsonify(total=total, ativos=ativos, enviados_hoje=hoje_n)


# ── Lógica de checagem e envio (chamada de fora via /cron/check-and-send) ────
def job_check_and_send():
    if not TOKEN:
        logger.warning("TELEGRAM_TOKEN não configurado — envio ignorado.")
        return {"verificados": 0, "enviados": 0, "erros": 0}

    today = hoje()
    agora  = datetime.now(TZ).time()
    logger.info("Verificando agendamentos para %s %s", today, agora.strftime("%H:%M"))
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM schedules WHERE active=1").fetchall()

    enviados, erros = 0, 0

    for r in rows:
        start = date.fromisoformat(r["start_date"])
        end   = date.fromisoformat(r["end_date"]) if r["end_date"] else None
        last  = r["last_sent"]

        if end and today > end:
            with get_conn() as conn:
                conn.execute("UPDATE schedules SET active=0 WHERE id=?", (r["id"],))
                conn.commit()
            logger.info("Agendamento #%d expirou e foi desativado.", r["id"])
            continue

        prox = next_occurrence(start, r["period_days"], last)
        horario_alvo = parse_time_str(r["send_time"] if "send_time" in r.keys() else None)

        # Só dispara se: já passou do dia (recuperando atraso, ex. app ficou
        # fora do ar) OU é hoje e o horário marcado já chegou.
        deve_enviar = prox < today or (prox == today and agora >= horario_alvo)

        if deve_enviar:
            ok, detail = enviar_telegram(r["chat_id"], r["message"])
            with get_conn() as conn:
                if ok:
                    conn.execute("UPDATE schedules SET last_sent=? WHERE id=?", (today.isoformat(), r["id"]))
                    conn.execute(
                        "INSERT INTO send_log (schedule_id, sent_at, status) VALUES (?,?,?)",
                        (r["id"], datetime.now(TZ).isoformat(), "ok")
                    )
                    enviados += 1
                    logger.info("✅ Enviado: agendamento #%d → chat %s", r["id"], r["chat_id"])
                else:
                    conn.execute(
                        "INSERT INTO send_log (schedule_id, sent_at, status, detail) VALUES (?,?,?,?)",
                        (r["id"], datetime.now(TZ).isoformat(), "erro", detail)
                    )
                    erros += 1
                    logger.error("❌ Falha no agendamento #%d: %s", r["id"], detail)
                    alertar_admin(
                        f"❌ Falha ao enviar agendamento #{r['id']} ({r['label'] or 'sem rótulo'})\n"
                        f"Chat: `{r['chat_id']}`\nErro: {detail[:200]}"
                    )
                conn.commit()

    return {"verificados": len(rows), "enviados": enviados, "erros": erros}


@app.route("/cron/check-and-send", methods=["GET", "POST"])
def cron_check_and_send():
    token = request.args.get("token", "") or request.headers.get("X-Cron-Token", "")
    if not CRON_SECRET or token != CRON_SECRET:
        return jsonify(error="unauthorized"), 401
    resultado = job_check_and_send()
    return jsonify(ok=True, **resultado)


# ── Webhook do Telegram ───────────────────────────────────────────────────────
@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    if WEBHOOK_SECRET:
        recebido = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if recebido != WEBHOOK_SECRET:
            return jsonify(error="unauthorized"), 401

    data = request.get_json(silent=True) or {}
    message = data.get("message") or data.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return jsonify(ok=True)

    comando = text.split()[0].split("@")[0]

    if comando == "/chatid":
        enviar_telegram(
            chat_id,
            f"🆔 Chat ID deste grupo: `{chat_id}`\n\n"
            "Cole este valor ao criar um agendamento, ou cadastre um nome "
            "amigável na tela de Contatos do painel."
        )
    elif comando == "/status":
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM schedules WHERE chat_id=? AND active=1 ORDER BY id",
                (str(chat_id),)
            ).fetchall()
        if not rows:
            enviar_telegram(chat_id, "📭 Nenhum agendamento ativo para este grupo.")
        else:
            linhas = [f"📋 *{len(rows)} agendamento(s) ativo(s)*\n"]
            for r in rows:
                prox = next_occurrence(
                    date.fromisoformat(r["start_date"]), r["period_days"], r["last_sent"]
                )
                linhas.append(
                    f"• *#{r['id']}* {r['label'] or ''} — a cada {r['period_days']}d\n"
                    f"  ⏭ Próximo: {prox.strftime('%d/%m/%Y')}"
                )
            enviar_telegram(chat_id, "\n".join(linhas))
    elif comando == "/start":
        enviar_telegram(chat_id, "👋 Bot de agendamentos ativo. Use /chatid para pegar o ID deste grupo.")

    return jsonify(ok=True)


# ── Execução local (não usado pelo PythonAnywhere) ───────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
