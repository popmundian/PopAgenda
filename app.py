#!/usr/bin/env python3
"""
Agendador de Mensagens Telegram — Painel Web + Bot integrado
v3: múltiplos usuários com permissões (admin/user), canais com nomes
amigáveis para Chat IDs, e envio de teste com confirmação de senha.
"""

import os
import logging
import sqlite3
import secrets
import calendar as pycalendar
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL UNIQUE,
                color      TEXT NOT NULL DEFAULT '#229ED9',
                created_by TEXT,
                created_at TEXT NOT NULL
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
        if "category_id" not in cols:
            conn.execute("ALTER TABLE schedules ADD COLUMN category_id INTEGER")
            conn.commit()
            logger.info("Migração aplicada: coluna category_id adicionada.")
        if "emoji" not in cols:
            conn.execute("ALTER TABLE schedules ADD COLUMN emoji TEXT")
            conn.commit()
            logger.info("Migração aplicada: coluna emoji adicionada.")
        if "is_draft" not in cols:
            conn.execute("ALTER TABLE schedules ADD COLUMN is_draft INTEGER NOT NULL DEFAULT 0")
            conn.commit()
            logger.info("Migração aplicada: coluna is_draft adicionada.")

        user_cols = [c[1] for c in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "favorite_chat_id" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN favorite_chat_id TEXT")
            conn.commit()
            logger.info("Migração aplicada: coluna favorite_chat_id adicionada.")

        contact_cols = [c[1] for c in conn.execute("PRAGMA table_info(contacts)").fetchall()]
        if "is_principal" not in contact_cols:
            conn.execute("ALTER TABLE contacts ADD COLUMN is_principal INTEGER NOT NULL DEFAULT 0")
            conn.commit()
            logger.info("Migração aplicada: coluna is_principal adicionada.")

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


def occurrences_in_range(start: date, period: int, end, range_start: date, range_end: date):
    """Todas as datas em que um agendamento recorrente cai dentro de
    [range_start, range_end] — usado pelo calendário (que precisa de TODAS
    as ocorrências do mês, não só a próxima, que é o que next_occurrence faz)."""
    if period <= 0 or start > range_end:
        return []
    if end and end < range_start:
        return []

    limite = min(range_end, end) if end else range_end

    if start >= range_start:
        primeira = start
    else:
        ciclos_completos = (range_start - start).days // period
        primeira = start + timedelta(days=ciclos_completos * period)
        while primeira < range_start:
            primeira += timedelta(days=period)

    ocorrencias = []
    cur = primeira
    while cur <= limite:
        ocorrencias.append(cur)
        cur += timedelta(days=period)
    return ocorrencias


def parse_time_str(s) -> dtime:
    try:
        h, m = str(s).split(":")
        return dtime(int(h), int(m))
    except (ValueError, AttributeError):
        return dtime(8, 0)


def enrich(row, categories_map=None):
    d = dict(row)
    categories_map = categories_map or {}

    if d.get("is_draft"):
        # Rascunho: não tem data pra calcular nada, então nem tenta.
        d["next_date"]     = None
        d["next_display"]  = "—"
        d["overdue"]       = False
        d["end_display"]   = "—"
        d["start_display"] = "—"
        d["send_time"]      = d.get("send_time") or "08:00"
        cat = categories_map.get(d.get("category_id"))
        d["category_name"], d["category_color"] = (cat["name"], cat["color"]) if cat else (None, None)
        return d

    start = date.fromisoformat(d["start_date"])
    last  = date.fromisoformat(d["last_sent"]) if d["last_sent"] else None
    prox  = next_occurrence(start, d["period_days"], last)
    today = hoje()
    d["next_date"]    = prox.isoformat()
    d["next_display"] = prox.strftime("%d/%m/%Y")
    d["send_time"]     = d.get("send_time") or "08:00"
    agora = datetime.now(TZ).time()
    horario_alvo = parse_time_str(d["send_time"])
    pendente_hoje = prox == today and agora >= horario_alvo
    d["overdue"]       = (prox < today or pendente_hoje) and d["active"]
    d["end_display"]   = date.fromisoformat(d["end_date"]).strftime("%d/%m/%Y") if d["end_date"] else "—"
    d["start_display"] = start.strftime("%d/%m/%Y")
    cat = categories_map.get(d.get("category_id"))
    d["category_name"], d["category_color"] = (cat["name"], cat["color"]) if cat else (None, None)
    return d


def get_categories_map():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM categories").fetchall()
    return {r["id"]: {"name": r["name"], "color": r["color"]} for r in rows}


def emoji_em_uso(emoji, excluir_id=None):
    """Retorna a linha do agendamento que já usa esse emoji, ou None se está livre."""
    if not emoji:
        return None
    with get_conn() as conn:
        if excluir_id:
            return conn.execute(
                "SELECT id, label FROM schedules WHERE emoji=? AND id!=?", (emoji, excluir_id)
            ).fetchone()
        return conn.execute("SELECT id, label FROM schedules WHERE emoji=?", (emoji,)).fetchone()


def get_contacts_map():
    with get_conn() as conn:
        rows = conn.execute("SELECT chat_id, friendly_name FROM contacts").fetchall()
    return {r["chat_id"]: r["friendly_name"] for r in rows}


def canal_padrao_do_usuario(user_id) -> str | None:
    """Hierarquia de canal padrão: favorito pessoal do usuário primeiro;
    se ele não tiver um, cai pro canal 'principal' definido pelo admin;
    se nenhum dos dois existir, retorna None (formulário fica vazio)."""
    with get_conn() as conn:
        u = conn.execute("SELECT favorite_chat_id FROM users WHERE id=?", (user_id,)).fetchone()
        if u and u["favorite_chat_id"]:
            return u["favorite_chat_id"]
        principal = conn.execute("SELECT chat_id FROM contacts WHERE is_principal=1").fetchone()
        return principal["chat_id"] if principal else None


def cor_texto_contraste(hex_color: str) -> str:
    """Dado um fundo colorido, decide se o texto deve ser claro ou escuro
    pra continuar legível — evita texto branco sobre amarelo claro, etc."""
    try:
        h = (hex_color or "").lstrip("#")
        if len(h) != 6:
            return "#ffffff"
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        luminancia = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return "#1a2332" if luminancia > 0.6 else "#ffffff"
    except (ValueError, TypeError):
        return "#ffffff"


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
    """Grava uma linha no log de auditoria. Propositalmente NUNCA deixa uma
    falha aqui (ex.: banco ocupado por um instante) quebrar a ação real do
    usuário — na pior hipótese, perde-se um registro de log, não a ação."""
    actor = actor or session.get("username", "sistema")
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO audit_log (timestamp, actor, action, details) VALUES (?,?,?,?)",
                (datetime.now(TZ).isoformat(), actor, action, details)
            )
            conn.commit()
    except Exception as exc:
        logger.error("Falha ao gravar auditoria (%s/%s): %s", action, actor, exc)


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
        acao = request.form.get("acao", "senha")

        if acao == "favorito":
            novo_favorito = request.form.get("favorite_chat_id") or None
            with get_conn() as conn:
                conn.execute("UPDATE users SET favorite_chat_id=? WHERE id=?",
                             (novo_favorito, session["user_id"]))
                conn.commit()
            flash("Canal favorito atualizado! ✅", "success")
            return redirect(url_for("minha_conta"))

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

    with get_conn() as conn:
        u = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        canais = conn.execute("SELECT * FROM contacts ORDER BY friendly_name").fetchall()
    return render_template("conta.html", user=session.get("username"), canais=canais,
                           favorito_atual=u["favorite_chat_id"] if u else None,
                           is_admin=(session.get("role") == "admin"))


# ── Gerenciamento de usuários (admin) ────────────────────────────────────────
@app.route("/usuarios")
@admin_required
def usuarios():
    with get_conn() as conn:
        rows = conn.execute("SELECT id, username, role, favorite_chat_id, created_at FROM users ORDER BY id").fetchall()
        canais = conn.execute("SELECT * FROM contacts ORDER BY friendly_name").fetchall()
    return render_template("usuarios.html", usuarios=rows, canais=canais,
                           user=session.get("username"), is_admin=True)


@app.route("/usuarios/novo", methods=["POST"])
@admin_required
def usuarios_novo():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role     = request.form.get("role", "user")
    favorito = request.form.get("favorite_chat_id") or None
    if role not in ("admin", "user"):
        role = "user"
    if not username or len(password) < 6:
        flash("Informe um usuário e uma senha com pelo menos 6 caracteres.", "danger")
        return redirect(url_for("usuarios"))
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, favorite_chat_id, created_at) VALUES (?,?,?,?,?)",
                (username, generate_password_hash(password), role, favorito, datetime.now(TZ).isoformat())
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


# ── Calendário ────────────────────────────────────────────────────────────────
_NOMES_MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


@app.route("/calendario")
@login_required
def calendario():
    hoje_d = hoje()
    try:
        ano = int(request.args.get("ano", hoje_d.year))
        mes = int(request.args.get("mes", hoje_d.month))
    except ValueError:
        ano, mes = hoje_d.year, hoje_d.month
    if mes < 1:
        ano, mes = ano - 1, 12
    elif mes > 12:
        ano, mes = ano + 1, 1

    cal = pycalendar.Calendar(firstweekday=pycalendar.MONDAY)
    semanas = cal.monthdatescalendar(ano, mes)
    intervalo_inicio, intervalo_fim = semanas[0][0], semanas[-1][-1]

    is_admin = session.get("role") == "admin"
    meu_canal = None

    with get_conn() as conn:
        if is_admin:
            rows = conn.execute("SELECT * FROM schedules WHERE is_draft=0").fetchall()
        else:
            meu_canal = canal_padrao_do_usuario(session["user_id"])
            rows = conn.execute(
                "SELECT * FROM schedules WHERE is_draft=0 AND chat_id=?", (meu_canal,)
            ).fetchall() if meu_canal else []

    categories_map = get_categories_map()
    eventos_por_dia = {}
    for r in rows:
        start = date.fromisoformat(r["start_date"])
        end   = date.fromisoformat(r["end_date"]) if r["end_date"] else None
        cat = categories_map.get(r["category_id"])
        cor_fundo = cat["color"] if cat else "#229ED9"
        for d in occurrences_in_range(start, r["period_days"], end, intervalo_inicio, intervalo_fim):
            eventos_por_dia.setdefault(d, []).append({
                "id": r["id"],
                "label": r["label"] or f"Agendamento #{r['id']}",
                "emoji": r["emoji"] or "📌",
                "active": r["active"],
                "cor_fundo": cor_fundo,
                "cor_texto": cor_texto_contraste(cor_fundo),
            })

    prev_ano, prev_mes = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    next_ano, next_mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)

    return render_template(
        "calendario.html", semanas=semanas, ano=ano, mes=mes, nome_mes=_NOMES_MESES[mes],
        eventos_por_dia=eventos_por_dia, hoje=hoje_d,
        prev_ano=prev_ano, prev_mes=prev_mes, next_ano=next_ano, next_mes=next_mes,
        tem_canal=(is_admin or bool(meu_canal)),
        user=session.get("username"), is_admin=is_admin,
    )


# ── Canais de comunicação (nomes amigáveis para Chat IDs) ────────────────────
@app.route("/canais")
@login_required
def canais():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM contacts ORDER BY is_principal DESC, friendly_name").fetchall()
    return render_template("canais.html", canais=rows, user=session.get("username"),
                           is_admin=(session.get("role") == "admin"))


@app.route("/canais/novo", methods=["POST"])
@login_required
def canais_novo():
    chat_id = request.form.get("chat_id", "").strip()
    nome    = request.form.get("friendly_name", "").strip()
    if not chat_id or not nome:
        flash("Preencha o Chat ID e o nome do canal.", "danger")
        return redirect(url_for("canais"))
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO contacts (chat_id, friendly_name, created_by, created_at) VALUES (?,?,?,?)",
                (chat_id, nome, session.get("username"), datetime.now(TZ).isoformat())
            )
            conn.commit()
        flash(f"Canal '{nome}' cadastrado! ✅", "success")
    except sqlite3.IntegrityError:
        flash("Esse Chat ID já está cadastrado como canal.", "danger")
    return redirect(url_for("canais"))


@app.route("/canais/remover/<int:cid>", methods=["POST"])
@admin_required
def canais_remover(cid):
    with get_conn() as conn:
        row = conn.execute("SELECT friendly_name FROM contacts WHERE id=?", (cid,)).fetchone()
        conn.execute("DELETE FROM contacts WHERE id=?", (cid,))
        conn.commit()
    registrar_auditoria("remover_canal", row["friendly_name"] if row else f"id={cid}")
    flash("Canal removido.", "warning")
    return redirect(url_for("canais"))


@app.route("/canais/principal/<int:cid>", methods=["POST"])
@admin_required
def canais_principal(cid):
    with get_conn() as conn:
        atual = conn.execute("SELECT is_principal, friendly_name FROM contacts WHERE id=?", (cid,)).fetchone()
        if not atual:
            flash("Canal não encontrado.", "danger")
            return redirect(url_for("canais"))
        if atual["is_principal"]:
            conn.execute("UPDATE contacts SET is_principal=0 WHERE id=?", (cid,))
        else:
            conn.execute("UPDATE contacts SET is_principal=0")  # só um principal por vez
            conn.execute("UPDATE contacts SET is_principal=1 WHERE id=?", (cid,))
        conn.commit()

    # registrar_auditoria abre sua própria conexão — só chamar DEPOIS do
    # commit acima, senão as duas conexões disputam o lock do arquivo.
    if atual["is_principal"]:
        registrar_auditoria("desmarcar_canal_principal", atual["friendly_name"])
        flash(f"'{atual['friendly_name']}' não é mais o canal principal.", "info")
    else:
        registrar_auditoria("marcar_canal_principal", atual["friendly_name"])
        flash(f"'{atual['friendly_name']}' agora é o canal principal. ⭐", "success")
    return redirect(url_for("canais"))


# ── Categorias ────────────────────────────────────────────────────────────────
@app.route("/categorias")
@login_required
def categorias():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    return render_template("categorias.html", categorias=rows, user=session.get("username"),
                           is_admin=(session.get("role") == "admin"))


@app.route("/categorias/novo", methods=["POST"])
@login_required
def categorias_novo():
    nome = request.form.get("name", "").strip()
    cor  = request.form.get("color", "#229ED9").strip() or "#229ED9"
    if not nome:
        flash("Informe um nome para a categoria.", "danger")
        return redirect(url_for("categorias"))
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO categories (name, color, created_by, created_at) VALUES (?,?,?,?)",
                (nome, cor, session.get("username"), datetime.now(TZ).isoformat())
            )
            conn.commit()
        registrar_auditoria("criar_categoria", nome)
        flash(f"Categoria '{nome}' criada! ✅", "success")
    except sqlite3.IntegrityError:
        flash("Já existe uma categoria com esse nome.", "danger")
    return redirect(url_for("categorias"))


@app.route("/categorias/remover/<int:cid>", methods=["POST"])
@admin_required
def categorias_remover(cid):
    with get_conn() as conn:
        conn.execute("UPDATE schedules SET category_id=NULL WHERE category_id=?", (cid,))
        conn.execute("DELETE FROM categories WHERE id=?", (cid,))
        conn.commit()
    registrar_auditoria("remover_categoria", f"id={cid}")
    flash("Categoria removida. Agendamentos que usavam ela ficaram sem categoria.", "warning")
    return redirect(url_for("categorias"))


# ── Rotas do painel (agendamentos) ───────────────────────────────────────────
@app.route("/")
@login_required
def index():
    sort = request.args.get("sort", "next")

    view = request.args.get("view")
    if view in ("cards", "inline", "details"):
        session["view_mode"] = view
    else:
        view = session.get("view_mode", "cards")

    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM schedules ORDER BY active DESC, id DESC").fetchall()
        categories = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    contacts_map   = get_contacts_map()
    categories_map = get_categories_map()
    schedules = []
    for r in rows:
        s = enrich(r, categories_map)
        s["friendly_name"] = contacts_map.get(s["chat_id"])
        schedules.append(s)

    # Rascunhos sempre por último dentro de cada critério de ordenação —
    # não tem data pra comparar, então não faz sentido competir por posição.
    if sort == "categoria":
        schedules.sort(key=lambda s: (s["is_draft"], (s["category_name"] or "zzz_sem_categoria").lower()))
    elif sort == "alfabetica":
        schedules.sort(key=lambda s: (s["is_draft"], (s["label"] or "").lower()))
    elif sort == "periodo":
        schedules.sort(key=lambda s: (s["is_draft"], s["period_days"]))
    else:
        schedules.sort(key=lambda s: (s["is_draft"], s["next_date"] or "9999-99-99"))

    return render_template("index.html", schedules=schedules, categories=categories,
                           sort=sort, view=view, user=session.get("username"),
                           is_admin=(session.get("role") == "admin"))


@app.route("/novo", methods=["GET", "POST"])
@login_required
def novo():
    with get_conn() as conn:
        contacts   = conn.execute("SELECT * FROM contacts ORDER BY is_principal DESC, friendly_name").fetchall()
        categories = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    meu_canal_padrao = canal_padrao_do_usuario(session["user_id"])

    if request.method == "POST":
        label       = request.form.get("label", "").strip()
        chat_id     = request.form.get("chat_id", "").strip()
        is_draft    = request.form.get("is_draft") == "on"
        period_str  = request.form.get("period_days", "").strip()
        start_str   = request.form.get("start_date", "").strip()
        end_str     = request.form.get("end_date", "").strip()
        send_time   = request.form.get("send_time", "").strip() or "08:00"
        category_id = request.form.get("category_id") or None
        emoji       = request.form.get("emoji", "").strip() or None
        message     = request.form.get("message", "").strip()

        errors = []
        if not chat_id:
            errors.append("Informe o Chat ID do grupo.")
        if not message:
            errors.append("A mensagem não pode ser vazia.")

        start, end = None, None
        if is_draft:
            # Rascunho: sem data ainda, então nem valida período/datas.
            period_int = 0
        else:
            if not period_str.isdigit() or int(period_str) < 1:
                errors.append("Período deve ser um número inteiro positivo.")
            start = parse_date(start_str)
            if not start:
                errors.append("Data de início inválida.")
            end = parse_date(end_str) if end_str else None
            if end and start and end <= start:
                errors.append("Data final deve ser posterior à inicial.")
            period_int = int(period_str) if period_str.isdigit() else 0

        conflito = emoji_em_uso(emoji)
        if conflito:
            errors.append(f"O emoji {emoji} já está em uso por '{conflito['label'] or ('#' + str(conflito['id']))}'.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("form.html", action="novo", data=request.form,
                                   contacts=contacts, categories=categories,
                                   user=session.get("username"), is_admin=(session.get("role") == "admin"))

        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO schedules
                  (chat_id, label, message, period_days, start_date, end_date, send_time,
                   category_id, emoji, is_draft, created_by, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                chat_id, label, message, period_int,
                start.isoformat() if start else "",
                end.isoformat() if end else None,
                send_time, category_id, emoji, 1 if is_draft else 0,
                session.get("username"),
                datetime.now(TZ).isoformat(),
            ))
            conn.commit()
        registrar_auditoria("criar_agendamento", f"#{cur.lastrowid} - {label or 'sem rótulo'}"
                             + (" (rascunho)" if is_draft else ""))
        flash("Rascunho salvo! ✅" if is_draft else "Agendamento criado com sucesso! ✅", "success")
        return redirect(url_for("index"))

    return render_template("form.html", action="novo", data={"chat_id": meu_canal_padrao or ""},
                           contacts=contacts, categories=categories,
                           user=session.get("username"), is_admin=(session.get("role") == "admin"))


@app.route("/editar/<int:sid>", methods=["GET", "POST"])
@login_required
def editar(sid):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM schedules WHERE id=?", (sid,)).fetchone()
        contacts   = conn.execute("SELECT * FROM contacts ORDER BY friendly_name").fetchall()
        categories = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    if not row:
        flash("Agendamento não encontrado.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        label       = request.form.get("label", "").strip()
        is_draft    = request.form.get("is_draft") == "on"
        period_str  = request.form.get("period_days", "").strip()
        start_str   = request.form.get("start_date", "").strip()
        end_str     = request.form.get("end_date", "").strip()
        send_time   = request.form.get("send_time", "").strip() or "08:00"
        category_id = request.form.get("category_id") or None
        emoji       = request.form.get("emoji", "").strip() or None
        message     = request.form.get("message", "").strip()

        errors = []
        if not message:
            errors.append("A mensagem não pode ser vazia.")

        start, end = None, None
        if is_draft:
            period_int = 0
        else:
            if not period_str.isdigit() or int(period_str) < 1:
                errors.append("Período inválido.")
            start = parse_date(start_str)
            if not start:
                errors.append("Data de início inválida (obrigatória para ativar o rascunho).")
            end = parse_date(end_str) if end_str else None
            if end and start and end <= start:
                errors.append("Data final deve ser posterior à inicial.")
            period_int = int(period_str) if period_str.isdigit() else 0

        conflito = emoji_em_uso(emoji, excluir_id=sid)
        if conflito:
            errors.append(f"O emoji {emoji} já está em uso por '{conflito['label'] or ('#' + str(conflito['id']))}'.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("form.html", action="editar", sid=sid, data=request.form,
                                   contacts=contacts, categories=categories, user=session.get("username"),
                                   is_admin=(session.get("role") == "admin"))

        with get_conn() as conn:
            conn.execute("""
                UPDATE schedules SET label=?, message=?, period_days=?, start_date=?, end_date=?,
                  send_time=?, category_id=?, emoji=?, is_draft=? WHERE id=?
            """, (label, message, period_int, start.isoformat() if start else "",
                  end.isoformat() if end else None, send_time, category_id, emoji,
                  1 if is_draft else 0, sid))
            conn.commit()
        registrar_auditoria("editar_agendamento", f"#{sid}" + (" (virou rascunho)" if is_draft
                             else " (ativado)" if row["is_draft"] else ""))
        flash("Rascunho atualizado! ✅" if is_draft else "Agendamento atualizado! ✅", "success")
        return redirect(url_for("index"))

    data = dict(row)
    return render_template("form.html", action="editar", sid=sid, data=data, contacts=contacts,
                           categories=categories, user=session.get("username"),
                           is_admin=(session.get("role") == "admin"))


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
        if r["is_draft"]:
            continue  # rascunho sem data — nunca é considerado pro envio

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
            "amigável na tela de Canais do painel."
        )
    elif comando == "/status":
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM schedules WHERE chat_id=? AND active=1 AND is_draft=0 ORDER BY id",
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
