import hashlib
import hmac
import os
import sqlite3
import subprocess
import threading
from datetime import datetime

from flask import Flask, jsonify, request, abort

import config
import database

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

app = Flask(__name__)

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "app.log")

HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HH Vacantica</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f1117; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
  .header { background: #1a1d27; border-bottom: 1px solid #2d3148; padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; }
  .header h1 { font-size: 18px; font-weight: 600; color: #fff; }
  .badge { background: #22c55e22; color: #22c55e; border: 1px solid #22c55e44; padding: 4px 10px; border-radius: 20px; font-size: 12px; }
  .refresh { color: #64748b; font-size: 12px; }
  .container { padding: 24px; max-width: 1200px; margin: 0 auto; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card { background: #1a1d27; border: 1px solid #2d3148; border-radius: 12px; padding: 20px; }
  .card-label { color: #64748b; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 8px; }
  .card-value { font-size: 32px; font-weight: 700; color: #fff; }
  .card-value.green { color: #22c55e; }
  .card-value.blue  { color: #60a5fa; }
  .card-value.amber { color: #fbbf24; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
  @media(max-width:768px){ .grid2 { grid-template-columns: 1fr; } }
  .panel { background: #1a1d27; border: 1px solid #2d3148; border-radius: 12px; overflow: hidden; }
  .panel-header { padding: 14px 18px; border-bottom: 1px solid #2d3148; font-size: 13px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: .05em; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { padding: 10px 16px; text-align: left; color: #475569; font-weight: 500; border-bottom: 1px solid #1e2235; }
  td { padding: 10px 16px; border-bottom: 1px solid #1e2235; color: #cbd5e1; vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #ffffff08; }
  .ok  { color: #22c55e; }
  .err { color: #f87171; }
  a { color: #60a5fa; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .log-panel { background: #1a1d27; border: 1px solid #2d3148; border-radius: 12px; overflow: hidden; margin-bottom: 16px; }
  .log-body { background: #0d1117; padding: 14px 18px; font-family: 'JetBrains Mono', monospace; font-size: 11.5px; max-height: 340px; overflow-y: auto; }
  .log-line { padding: 2px 0; border-bottom: 1px solid #ffffff06; white-space: pre-wrap; word-break: break-all; }
  .log-INFO  { color: #94a3b8; }
  .log-ERROR { color: #f87171; }
  .log-WARN  { color: #fbbf24; }
  .log-DEBUG { color: #475569; }
  .salary { color: #22c55e; font-size: 12px; }
  .time   { color: #475569; font-size: 11px; }
  .empty  { padding: 24px; text-align: center; color: #475569; font-size: 13px; }
</style>
</head>
<body>
<div class="header">
  <h1>🤖 HH Vacantica</h1>
  <div style="display:flex;gap:12px;align-items:center">
    <span class="badge" id="status-badge">● Активен</span>
    <span class="refresh" id="countdown">обновление через 30с</span>
  </div>
</div>
<div class="container">
  <div class="cards" id="cards"></div>
  <div class="grid2">
    <div class="panel">
      <div class="panel-header">Последние отклики</div>
      <div id="responses-table"></div>
    </div>
    <div class="panel">
      <div class="panel-header">Поднятия резюме</div>
      <div id="publishes-table"></div>
    </div>
  </div>
  <div class="log-panel">
    <div class="panel-header">Лог</div>
    <div class="log-body" id="log"></div>
  </div>
</div>

<script>
let countdown = 30;

function classForLevel(line) {
  if (line.includes(' ERROR ')) return 'log-ERROR';
  if (line.includes(' WARNING ') || line.includes(' WARN ')) return 'log-WARN';
  if (line.includes(' DEBUG ')) return 'log-DEBUG';
  return 'log-INFO';
}

function timeAgo(dt) {
  const d = new Date(dt.replace(' ', 'T') + 'Z');
  const s = Math.floor((Date.now() - d) / 1000);
  if (s < 60) return s + 'с назад';
  if (s < 3600) return Math.floor(s/60) + 'м назад';
  if (s < 86400) return Math.floor(s/3600) + 'ч назад';
  return Math.floor(s/86400) + 'д назад';
}

async function load() {
  const data = await fetch('/api/data').then(r => r.json());

  // Cards
  document.getElementById('cards').innerHTML = `
    <div class="card"><div class="card-label">Всего откликов</div><div class="card-value blue">${data.stats.total_responses}</div></div>
    <div class="card"><div class="card-label">Сегодня откликов</div><div class="card-value green">${data.stats.today_responses}</div></div>
    <div class="card"><div class="card-label">Поднятий резюме</div><div class="card-value amber">${data.stats.total_publishes}</div></div>
    <div class="card"><div class="card-label">Последний отклик</div><div class="card-value" style="font-size:16px;padding-top:6px">${data.last_response || '—'}</div></div>
  `;

  // Responses
  if (data.responses.length === 0) {
    document.getElementById('responses-table').innerHTML = '<div class="empty">Откликов ещё нет</div>';
  } else {
    let rows = data.responses.map(r => `
      <tr>
        <td><a href="${r.vacancy_url}" target="_blank">${r.vacancy_title}</a><br><span class="time">${r.company_name}</span></td>
        <td><span class="salary">${r.salary_text || '—'}</span><br><span class="time">${timeAgo(r.responded_at)}</span></td>
      </tr>`).join('');
    document.getElementById('responses-table').innerHTML = `<table><thead><tr><th>Вакансия</th><th>Зарплата</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  // Publishes
  if (data.publishes.length === 0) {
    document.getElementById('publishes-table').innerHTML = '<div class="empty">Поднятий ещё нет</div>';
  } else {
    let rows = data.publishes.map(p => `
      <tr>
        <td class="${p.success ? 'ok' : 'err'}">${p.success ? '✅' : '❌'}</td>
        <td style="font-size:12px">${p.message}</td>
        <td><span class="time">${timeAgo(p.published_at)}</span></td>
      </tr>`).join('');
    document.getElementById('publishes-table').innerHTML = `<table><thead><tr><th></th><th>Сообщение</th><th>Время</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  // Log
  const logEl = document.getElementById('log');
  logEl.innerHTML = data.log.map(l => `<div class="log-line ${classForLevel(l)}">${l}</div>`).join('');
  logEl.scrollTop = logEl.scrollHeight;
}

async function tick() {
  countdown--;
  document.getElementById('countdown').textContent = `обновление через ${countdown}с`;
  if (countdown <= 0) {
    countdown = 30;
    await load();
  }
}

load();
setInterval(tick, 1000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return HTML


@app.route("/api/data")
def api_data():
    stats = database.get_stats()

    with sqlite3.connect(database.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        responses = [dict(r) for r in conn.execute(
            "SELECT vacancy_title, company_name, vacancy_url, salary_text, responded_at "
            "FROM responses ORDER BY responded_at DESC LIMIT 20"
        ).fetchall()]

        publishes = [dict(r) for r in conn.execute(
            "SELECT success, message, published_at "
            "FROM resume_publishes ORDER BY published_at DESC LIMIT 20"
        ).fetchall()]

    last_response = None
    if responses:
        ts = responses[0]["responded_at"]
        try:
            dt = datetime.fromisoformat(ts)
            last_response = dt.strftime("%d.%m %H:%M")
        except Exception:
            last_response = ts

    log_lines = []
    try:
        with open(LOG_PATH, encoding="utf-8") as f:
            log_lines = f.readlines()[-80:]
        log_lines = [l.rstrip() for l in log_lines if l.strip()]
    except Exception:
        pass

    return jsonify({
        "stats": stats,
        "responses": responses,
        "publishes": publishes,
        "log": log_lines,
        "last_response": last_response,
    })


@app.route("/webhook", methods=["POST"])
def webhook():
    if not WEBHOOK_SECRET:
        abort(503, "WEBHOOK_SECRET не задан")

    sig = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), request.data, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        abort(403)

    event = request.headers.get("X-GitHub-Event", "")
    if event != "push":
        return jsonify({"status": "ignored"})

    payload = request.json or {}
    ref = payload.get("ref", "")
    if ref != "refs/heads/master":
        return jsonify({"status": "ignored", "ref": ref})

    def deploy():
        base = os.path.dirname(os.path.abspath(__file__))
        subprocess.run(
            ["git", "pull", "origin", "master"],
            cwd=base,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=no"},
        )
        venv_pip = os.path.join(base, "venv", "bin", "pip")
        if os.path.exists(venv_pip):
            subprocess.run([venv_pip, "install", "-r", "requirements.txt", "-q"], cwd=base)
        subprocess.run(["systemctl", "restart", "hh-vacantica"])

    threading.Thread(target=deploy, daemon=True).start()
    return jsonify({"status": "deploying"})


def start_dashboard(port: int = 8080):
    t = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
        daemon=True,
        name="dashboard",
    )
    t.start()
