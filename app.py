#!/usr/bin/env python3
"""
Agendador de Mensagens Telegram — Painel Web + Bot integrado
Versão adaptada para hospedagem gratuita (PythonAnywhere) + GitHub Actions.

Diferenças em relação à versão Docker/VPS:
- O bot usa WEBHOOK em vez de polling (PythonAnywhere free não permite
  processos contínuos em segundo plano, mas isso não é necessário aqui: o
  Telegram simplesmente chama nossa URL quando alguém manda uma mensagem).
- A verificação diária de envio não roda mais sozinha dentro do processo
  (não há "segundo plano" persistente no free tier). Em vez disso, existe
  uma rota protegida por senha (/cron/check-and-send) que faz a checagem.
  Um workflow do GitHub Actions chama essa rota todo dia, de graça.
- Envio ao Telegram usa a biblioteca "requests" (síncrona, simples), em vez
  de asyncio — mais adequado ao modelo de hospedagem WSGI tradicional.
"""

import os
import logging
import sqlite3
import secrets
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from functools import wraps

import requests
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify
)
from dotenv import load_dotenv

load_dotenv()

# ── Configurações ────────────────────────────────────────────────────────────
TOKEN           = os.getenv("TELEGRAM_TOKEN", "")
TIMEZONE        = os.getenv("TIMEZONE", "America/Sao_Paulo")
DB_PATH         = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedules.db"))
WEB_USER        = os.getenv("WEB_USER", "admin")
WEB_PASS        = os.getenv("WEB_PASS", "senha123")
SECRET_KEY      = os.getenv("SECRET_KEY", secrets.token_hex(32))
CRON_SECRET     = os.getenv("CRON_SECRET", "")       # protege /cron/check-and-send
WEBHOOK_SECRET  = os.getenv("WEBHOOK_SECRET", "")    # protege /telegram/webhook

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
        conn.commit()


# Roda sempre que o módulo é importado — inclusive quando o PythonAnywhere
# importa "app" a partir do arquivo WSGI (que nunca executa o bloco
# "if __name__ == '__main__'" lá embaixo). Por isso fica aqui fora.
init_db()


# ── Helpers de data ──────────────────────────────────────────────────────────
def hoje() -> date:
    """'Hoje' sempre no fuso configurado (TIMEZONE), não no fuso do servidor."""
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


def enrich(row):
    d = dict(row)
    start = date.fromisoformat(d["start_date"])
    last  = date.fromisoformat(d["last_sent"]) if d["last_sent"] else None
    prox  = next_occurrence(start, d["period_days"], last)
    today = hoje()
    d["next_date"]    = prox.isoformat()
    d["next_display"] = prox.strftime("%d/%m/%Y")
    d["overdue"]       = prox <= today and d["active"]
    d["end_display"]   = date.fromisoformat(d["end_date"]).strftime("%d/%m/%Y") if d["end_date"] else "—"
    d["start_display"] = start.strftime("%d/%m/%Y")
    return d


# ── Telegram: envio simples via HTTP (sem asyncio, sem SDK pesado) ──────────
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


# ── Auth do painel web ───────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if u == WEB_USER and p == WEB_PASS:
            session["logged_in"] = True
            session["username"]  = u
            return redirect(url_for("index"))
        flash("Usuário ou senha incorretos.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── Rotas do painel (idênticas à versão anterior) ────────────────────────────
@app.route("/")
@login_required
def index():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM schedules ORDER BY active DESC, id DESC"
        ).fetchall()
    schedules = [enrich(r) for r in rows]
    return render_template("index.html", schedules=schedules, user=session.get("username"))


@app.route("/novo", methods=["GET", "POST"])
@login_required
def novo():
    if request.method == "POST":
        label       = request.form.get("label", "").strip()
        chat_id     = request.form.get("chat_id", "").strip()
        period_str  = request.form.get("period_days", "").strip()
        start_str   = request.form.get("start_date", "").strip()
        end_str     = request.form.get("end_date", "").strip()
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
            return render_template("form.html", action="novo",
                                   data=request.form, user=session.get("username"))

        with get_conn() as conn:
            conn.execute("""
                INSERT INTO schedules
                  (chat_id, label, message, period_days, start_date, end_date, created_by, created_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                chat_id, label, message, int(period_str),
                start.isoformat(),
                end.isoformat() if end else None,
                session.get("username"),
                datetime.now(TZ).isoformat(),
            ))
            conn.commit()
        flash("Agendamento criado com sucesso! ✅", "success")
        return redirect(url_for("index"))

    return render_template("form.html", action="novo", data={}, user=session.get("username"))


@app.route("/editar/<int:sid>", methods=["GET", "POST"])
@login_required
def editar(sid):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM schedules WHERE id=?", (sid,)).fetchone()
    if not row:
        flash("Agendamento não encontrado.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        label      = request.form.get("label", "").strip()
        period_str = request.form.get("period_days", "").strip()
        start_str  = request.form.get("start_date", "").strip()
        end_str    = request.form.get("end_date", "").strip()
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
            return render_template("form.html", action="editar", sid=sid,
                                   data=request.form, user=session.get("username"))

        with get_conn() as conn:
            conn.execute("""
                UPDATE schedules SET label=?, message=?, period_days=?,
                  start_date=?, end_date=? WHERE id=?
            """, (label, message, int(period_str),
                  start.isoformat(), end.isoformat() if end else None, sid))
            conn.commit()
        flash("Agendamento atualizado! ✅", "success")
        return redirect(url_for("index"))

    data = dict(row)
    return render_template("form.html", action="editar", sid=sid,
                           data=data, user=session.get("username"))


@app.route("/toggle/<int:sid>")
@login_required
def toggle(sid):
    with get_conn() as conn:
        row = conn.execute("SELECT active FROM schedules WHERE id=?", (sid,)).fetchone()
        if row:
            novo = 0 if row["active"] else 1
            conn.execute("UPDATE schedules SET active=? WHERE id=?", (novo, sid))
            conn.commit()
            flash(f"Agendamento #{ sid } {'ativado ✅' if novo else 'pausado ⏸'}.", "info")
    return redirect(url_for("index"))


@app.route("/remover/<int:sid>", methods=["POST"])
@login_required
def remover(sid):
    with get_conn() as conn:
        conn.execute("DELETE FROM schedules WHERE id=?", (sid,))
        conn.execute("DELETE FROM send_log WHERE schedule_id=?", (sid,))
        conn.commit()
    flash(f"Agendamento #{sid} removido.", "warning")
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
    return render_template("log.html", sched=dict(sched), logs=logs, user=session.get("username"))


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


# ── Lógica de checagem e envio (agora chamada de fora, não em segundo plano) ─
def job_check_and_send():
    if not TOKEN:
        logger.warning("TELEGRAM_TOKEN não configurado — envio ignorado.")
        return {"verificados": 0, "enviados": 0, "erros": 0}

    today = hoje()
    logger.info("Verificando agendamentos para %s", today)
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

        if prox <= today:
            ok, detail = enviar_telegram(r["chat_id"], r["message"])
            with get_conn() as conn:
                if ok:
                    conn.execute(
                        "UPDATE schedules SET last_sent=? WHERE id=?",
                        (today.isoformat(), r["id"])
                    )
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
                conn.commit()

    return {"verificados": len(rows), "enviados": enviados, "erros": erros}


@app.route("/cron/check-and-send", methods=["GET", "POST"])
def cron_check_and_send():
    """Chamada pelo GitHub Actions uma vez por dia (ou mais, por segurança).
    Protegida por um token secreto — sem o token certo, não faz nada."""
    token = request.args.get("token", "") or request.headers.get("X-Cron-Token", "")
    if not CRON_SECRET or token != CRON_SECRET:
        return jsonify(error="unauthorized"), 401
    resultado = job_check_and_send()
    return jsonify(ok=True, **resultado)


# ── Webhook do Telegram (substitui o polling contínuo) ───────────────────────
@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    # Verifica o cabeçalho secreto que o Telegram devolve em toda chamada,
    # configurado no momento em que registramos o webhook (ver README).
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
        return jsonify(ok=True)  # nada a fazer (foto, sticker, etc.)

    comando = text.split()[0].split("@")[0]  # ignora "@nomedobot" e argumentos

    if comando == "/chatid":
        enviar_telegram(
            chat_id,
            f"🆔 Chat ID deste grupo: `{chat_id}`\n\n"
            "Cole este valor ao criar um agendamento no painel web."
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


# ── Execução local (não usado pelo PythonAnywhere, só para testar no seu PC) ─
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
