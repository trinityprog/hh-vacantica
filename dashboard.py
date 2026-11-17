import hashlib
import hmac
import os
import subprocess
import threading

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
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🤖</text></svg>">
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
  .card[style*="cursor:pointer"]:hover { border-color: #3b82f6; }
  .card-label { color: #64748b; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 8px; }
  .card-value { font-size: 32px; font-weight: 700; color: #fff; }
  .card-value.green { color: #22c55e; }
  .card-value.blue  { color: #60a5fa; }
  .card-value.amber { color: #fbbf24; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; align-items: start; }
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
  .panel-toolbar { padding: 10px 18px; border-bottom: 1px solid #2d3148; }
  .panel-search { width: 100%; background: #0d1117; border: 1px solid #2d3148; border-radius: 8px; color: #e2e8f0; padding: 7px 10px; font-size: 12.5px; outline: none; }
  .panel-search:focus { border-color: #3b82f6; }
  .panel-search::placeholder { color: #475569; }
  .pager { display: flex; align-items: center; justify-content: space-between; padding: 8px 18px; border-top: 1px solid #1e2235; font-size: 12px; color: #64748b; }
  .pager button { background: #1e2235; border: 1px solid #2d3148; color: #cbd5e1; border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; }
  .pager button:disabled { opacity: .4; cursor: default; }
  .pager button:not(:disabled):hover { background: #2d3148; }
  td button { background: #1e2235; border: 1px solid #2d3148; color: #cbd5e1; border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; white-space: nowrap; }
  td button:hover { background: #2d3148; }
  .toolbar-btn { background: #1e2235; border: 1px solid #2d3148; color: #cbd5e1; border-radius: 8px; padding: 7px 12px; font-size: 12.5px; cursor: pointer; white-space: nowrap; }
  .toolbar-btn:hover { background: #2d3148; }
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
      <div class="panel-header">Отклики</div>
      <div class="panel-toolbar"><input class="panel-search" id="responses-search" placeholder="Поиск по вакансии/компании…"></div>
      <div id="responses-table"></div>
      <div class="pager" id="responses-pager"></div>
    </div>
    <div>
      <div class="panel" id="publishes-panel" style="display:none">
        <div class="panel-header">Поднятия резюме</div>
        <div class="panel-toolbar"><input class="panel-search" id="publishes-search" placeholder="Поиск по сообщению…"></div>
        <div id="publishes-table"></div>
        <div class="pager" id="publishes-pager"></div>
      </div>
      <div class="panel" id="unread-chats-panel">
        <div class="panel-header">Ждут вашего ответа в чате</div>
        <div id="unread-chats-table"></div>
      </div>
    </div>
  </div>
  <div class="panel" style="margin-bottom:16px">
    <div class="panel-header">На ручную обработку</div>
    <div class="panel-toolbar" style="display:flex;gap:8px;align-items:center">
      <input class="panel-search" id="manual-search" placeholder="Поиск по вакансии/компании/причине…" style="flex:1">
      <button class="toolbar-btn" onclick="openManualFive()">Открыть 5</button>
      <button class="toolbar-btn" onclick="handleManualFive()">Отправить в обработано</button>
    </div>
    <div id="manual-review-table"></div>
    <div class="pager" id="manual-pager"></div>
  </div>
  <div class="log-panel">
    <div class="panel-header">Лог</div>
    <div class="log-body" id="log"></div>
  </div>
</div>

<script>
let countdown = 30;

const SIDE_PANELS = ['publishes-panel', 'unread-chats-panel'];
function showSidePanel(id) {
  SIDE_PANELS.forEach(pid => {
    document.getElementById(pid).style.display = pid === id ? '' : 'none';
  });
}

function classForLevel(line) {
  if (line.includes(' ERROR ')) return 'log-ERROR';
  if (line.includes(' WARNING ') || line.includes(' WARN ')) return 'log-WARN';
  if (line.includes(' DEBUG ')) return 'log-DEBUG';
  return 'log-INFO';
}

function toLocalDate(dt) {
  return new Date(dt.replace(' ', 'T') + 'Z');
}

function timeAgo(dt) {
  const d = toLocalDate(dt);
  const s = Math.floor((Date.now() - d) / 1000);
  if (s < 60) return s + 'с назад';
  if (s < 3600) return Math.floor(s/60) + 'м назад';
  if (s < 86400) return Math.floor(s/3600) + 'ч назад';
  return Math.floor(s/86400) + 'д назад';
}

function formatLocal(dt) {
  const d = toLocalDate(dt);
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getDate())}.${pad(d.getMonth()+1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// --- Списки с поиском и пагинацией ---
const panels = {
  responses: { page: 1, q: '', endpoint: '/api/responses' },
  publishes: { page: 1, q: '', endpoint: '/api/publishes' },
  manual:    { page: 1, q: '', endpoint: '/api/manual_review' },
};
const tableIds = { responses: 'responses-table', publishes: 'publishes-table', manual: 'manual-review-table' };
const pagerIds = { responses: 'responses-pager', publishes: 'publishes-pager', manual: 'manual-pager' };

let manualRows = [];
let manualOpenedIds = new Set();
let manualLastOpened = [];

function statusBadge(status) {
  const map = {
    'Собеседование': '#22c55e',
    'Отказ': '#f87171',
    'Просмотрен': '#60a5fa',
    'Не просмотрен': '#64748b',
  };
  const color = map[status] || '#475569';
  const label = status && status !== 'sent' ? status : 'Отправлен';
  return `<span style="color:${color};font-size:12px">${label}</span>`;
}

function renderResponses(rows) {
  if (rows.length === 0) return '<div class="empty">Ничего не найдено</div>';
  const trs = rows.map(r => `
    <tr style="${r.unread ? 'background:#f472b608' : ''}">
      <td>${r.unread ? '<span title="Ждёт вашего ответа в чате" style="color:#f472b6">●</span> ' : ''}<a href="${r.vacancy_url}" target="_blank">${r.vacancy_title}</a><br><span class="time">${r.company_name}</span></td>
      <td><span class="salary">${r.salary_text || '—'}</span><br><span class="time">${timeAgo(r.responded_at)}</span></td>
      <td>${statusBadge(r.status)}</td>
    </tr>`).join('');
  return `<table><thead><tr><th>Вакансия</th><th>Зарплата</th><th>Статус</th></tr></thead><tbody>${trs}</tbody></table>`;
}

function renderPublishes(rows) {
  if (rows.length === 0) return '<div class="empty">Ничего не найдено</div>';
  const trs = rows.map(p => `
    <tr>
      <td class="${p.success ? 'ok' : 'err'}">${p.success ? '✅' : '❌'}</td>
      <td style="font-size:12px">${p.message}</td>
      <td><span class="time">${timeAgo(p.published_at)}</span></td>
    </tr>`).join('');
  return `<table><thead><tr><th></th><th>Сообщение</th><th>Время</th></tr></thead><tbody>${trs}</tbody></table>`;
}

function renderManual(rows) {
  if (rows.length === 0) return '<div class="empty">Ничего не найдено</div>';
  const trs = rows.map(m => `
    <tr style="${manualOpenedIds.has(m.vacancy_id) ? 'background:#3b82f608' : ''}">
      <td><a href="${m.vacancy_url}" target="_blank">${m.vacancy_title}</a><br><span class="time">${m.company_name}</span></td>
      <td style="font-size:12px">${m.reason}</td>
      <td><span class="time">${timeAgo(m.created_at)}</span></td>
      <td><button onclick="markHandled('${m.vacancy_id}')">Обработал</button></td>
    </tr>`).join('');
  return `<table><thead><tr><th>Вакансия</th><th>Причина</th><th>Время</th><th></th></tr></thead><tbody>${trs}</tbody></table>`;
}

async function markHandled(vacancyId) {
  await fetch(`/api/manual_review/${encodeURIComponent(vacancyId)}/handle`, { method: 'POST' });
  manualOpenedIds.delete(vacancyId);
  manualLastOpened = manualLastOpened.filter(id => id !== vacancyId);
  await loadPanel('manual');
}

function openManualFive() {
  const targets = manualRows.slice(0, 5);
  if (targets.length === 0) return;
  targets.forEach(m => {
    window.open(m.vacancy_url, '_blank');
    manualOpenedIds.add(m.vacancy_id);
  });
  manualLastOpened = targets.map(m => m.vacancy_id);
  document.getElementById(tableIds.manual).innerHTML = renderManual(manualRows);
}

async function handleManualFive() {
  const ids = manualLastOpened.length > 0 ? manualLastOpened : manualRows.slice(0, 5).map(m => m.vacancy_id);
  if (ids.length === 0) return;
  await Promise.all(ids.map(id => fetch(`/api/manual_review/${encodeURIComponent(id)}/handle`, { method: 'POST' })));
  ids.forEach(id => manualOpenedIds.delete(id));
  manualLastOpened = [];
  await loadPanel('manual');
}

const renderers = { responses: renderResponses, publishes: renderPublishes, manual: renderManual };

async function loadPanel(name) {
  const st = panels[name];
  const url = `${st.endpoint}?q=${encodeURIComponent(st.q)}&page=${st.page}`;
  const data = await fetch(url).then(r => r.json());
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));
  if (st.page > pages) { st.page = pages; return loadPanel(name); }
  if (name === 'manual') manualRows = data.rows;
  document.getElementById(tableIds[name]).innerHTML = renderers[name](data.rows);
  document.getElementById(pagerIds[name]).innerHTML = `
    <span>${data.total} записей · стр. ${st.page}/${pages}</span>
    <div>
      <button ${st.page <= 1 ? 'disabled' : ''} onclick="panelPage('${name}', -1)">← Назад</button>
      <button ${st.page >= pages ? 'disabled' : ''} onclick="panelPage('${name}', 1)">Вперёд →</button>
    </div>`;
}

function panelPage(name, delta) {
  panels[name].page += delta;
  loadPanel(name);
}

const searchTimers = {};
function wireSearch(name, inputId) {
  document.getElementById(inputId).addEventListener('input', (e) => {
    clearTimeout(searchTimers[name]);
    searchTimers[name] = setTimeout(() => {
      panels[name].q = e.target.value;
      panels[name].page = 1;
      loadPanel(name);
    }, 300);
  });
}
wireSearch('responses', 'responses-search');
wireSearch('publishes', 'publishes-search');
wireSearch('manual', 'manual-search');

async function load() {
  const data = await fetch('/api/data').then(r => r.json());

  // Cards
  document.getElementById('cards').innerHTML = `
    <div class="card"><div class="card-label">Всего откликов</div><div class="card-value blue">${data.stats.total_responses}</div></div>
    <div class="card"><div class="card-label">Сегодня откликов</div><div class="card-value green">${data.stats.today_responses}</div></div>
    <div class="card" style="cursor:pointer" onclick="showSidePanel('publishes-panel')"><div class="card-label">Поднятий резюме</div><div class="card-value amber">${data.stats.total_publishes}</div></div>
    <div class="card"><div class="card-label">На ручную обработку</div><div class="card-value" style="color:#f472b6">${data.stats.manual_review_count}</div></div>
    <div class="card" style="cursor:pointer" onclick="window.open('https://hh.ru/applicant/negotiations?filter=all&state=INTERVIEW', '_blank')"><div class="card-label">Собеседований</div><div class="card-value green">${data.stats.interview_count}</div></div>
    <div class="card" style="cursor:pointer" onclick="showSidePanel('unread-chats-panel')"><div class="card-label">Ждут ответа в чате</div><div class="card-value" style="color:#f472b6">${data.stats.unread_count}</div></div>
    <div class="card"><div class="card-label">Последний отклик</div><div class="card-value" style="font-size:16px;padding-top:6px">${data.last_response ? formatLocal(data.last_response) : '—'}</div></div>
  `;

  // Unread chats
  if (data.unread_chats.length === 0) {
    document.getElementById('unread-chats-table').innerHTML = '<div class="empty">Нет чатов, ждущих ответа</div>';
  } else {
    const trs = data.unread_chats.map(c => `
      <tr>
        <td>${c.vacancy_title}<br><span class="time">${c.company_name}</span></td>
        <td style="font-size:12px;max-width:400px;white-space:pre-wrap">${(c.last_message || '').slice(0, 200)}</td>
        <td><a href="${c.chat_url}" target="_blank">Открыть чат →</a></td>
      </tr>`).join('');
    document.getElementById('unread-chats-table').innerHTML = `<table><thead><tr><th>Вакансия</th><th>Сообщение</th><th></th></tr></thead><tbody>${trs}</tbody></table>`;
  }

  // Log
  const logEl = document.getElementById('log');
  logEl.innerHTML = data.log.map(l => `<div class="log-line ${classForLevel(l)}">${l}</div>`).join('');
  logEl.scrollTop = logEl.scrollHeight;

  await Promise.all([loadPanel('responses'), loadPanel('publishes'), loadPanel('manual')]);
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

    # responded_at хранится в SQLite как UTC (CURRENT_TIMESTAMP) — форматируем
    # в локальное время на фронтенде (см. timeAgo/formatLocal в JS), а не тут
    last_rows, _ = database.get_responses(page=1, page_size=1)
    last_response = last_rows[0]["responded_at"] if last_rows else None

    log_lines = []
    try:
        with open(LOG_PATH, encoding="utf-8") as f:
            log_lines = f.readlines()[-80:]
        log_lines = [l.rstrip() for l in log_lines if l.strip()]
    except Exception:
        pass

    return jsonify({
        "stats": stats,
        "log": log_lines,
        "last_response": last_response,
        "unread_chats": database.get_unread_chats(),
    })


PAGE_SIZE = 15


@app.route("/api/responses")
def api_responses():
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    rows, total = database.get_responses(q, page, PAGE_SIZE)
    return jsonify({"rows": rows, "total": total, "page": page, "page_size": PAGE_SIZE})


@app.route("/api/publishes")
def api_publishes():
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    rows, total = database.get_publishes(q, page, PAGE_SIZE)
    return jsonify({"rows": rows, "total": total, "page": page, "page_size": PAGE_SIZE})


@app.route("/api/manual_review")
def api_manual_review():
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    rows, total = database.get_manual_review(q, page, PAGE_SIZE)
    return jsonify({"rows": rows, "total": total, "page": page, "page_size": PAGE_SIZE})


@app.route("/api/manual_review/<vacancy_id>/handle", methods=["POST"])
def api_manual_review_handle(vacancy_id):
    database.mark_manual_review_handled(vacancy_id)
    return jsonify({"status": "ok"})


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
