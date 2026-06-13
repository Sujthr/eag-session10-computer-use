/* Desktop Agent Dashboard — app.js */

'use strict';

let _autoScroll  = true;
let _taskRunning = false;
let _statusPoll  = null;
let _sse         = null;

// ── Boot ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  connectSSE();
  refreshStatus();
  loadProviders();
  loadRecordings();
  _statusPoll = setInterval(refreshStatus, 3000);
});

// ── SSE — live log stream ──────────────────────────────────────────────────────

function connectSSE() {
  if (_sse) { _sse.close(); }
  _sse = new EventSource('/api/logs/stream');

  _sse.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      appendLog(msg);
    } catch {}
  };

  _sse.onerror = () => {
    // reconnect after 2s
    setTimeout(connectSSE, 2000);
  };
}

// ── Log terminal ───────────────────────────────────────────────────────────────

function appendLog(msg) {
  const term = document.getElementById('log-terminal');
  if (!term) return;

  const line  = document.createElement('div');
  line.className = 'log-line';

  const lvlClass = `lvl-${msg.level || 'INFO'}`;
  const lvlIcon  = {
    DEBUG: '·', INFO: '›', SUCCESS: '✓', WARNING: '!', ERROR: '✗'
  }[msg.level] || '›';

  line.innerHTML =
    `<span class="log-ts">${esc(msg.time || '')}</span>` +
    `<span class="log-lvl ${lvlClass}">${lvlIcon} ${esc(msg.level || '')}</span>` +
    `<span class="log-msg">${esc(msg.message || '')}</span>`;

  term.appendChild(line);

  // Keep at most 500 lines
  while (term.children.length > 500) {
    term.removeChild(term.firstChild);
  }

  if (_autoScroll) {
    term.scrollTop = term.scrollHeight;
  }
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function clearLog() {
  const term = document.getElementById('log-terminal');
  if (term) term.innerHTML = '';
}

function toggleAutoScroll() {
  _autoScroll = !_autoScroll;
  const btn = document.getElementById('autoscroll-btn');
  if (btn) btn.textContent = `Auto-scroll ${_autoScroll ? '✓' : '✗'}`;
}

// ── Status polling ─────────────────────────────────────────────────────────────

async function refreshStatus() {
  try {
    const r = await fetch('/api/status');
    const s = await r.json();
    updateStatusPill(s.task);
    updateDaemon(s.daemon);

    if (s.task.running && !_taskRunning) {
      // Server has a running task we didn't start (e.g. page reload mid-task)
      _taskRunning = true;
      setCardsEnabled(false);
    } else if (!s.task.running && _taskRunning) {
      _taskRunning = false;
      setCardsEnabled(true);
      if (s.task.result) {
        showResult(s.task.task, s.task.result);
        loadRecordings();
      }
    } else if (!s.task.running && !_taskRunning) {
      // Ensure buttons are always enabled when idle
      setCardsEnabled(true);
    }
  } catch {}
}

function updateStatusPill(task) {
  const pill = document.getElementById('task-status-pill');
  const dot  = document.getElementById('task-status-dot');
  const text = document.getElementById('task-status-text');
  if (!pill) return;

  const classes = {
    idle:    'pill-idle',
    running: 'pill-running',
    done:    'pill-done',
    error:   'pill-error',
  };
  const icons = {
    idle: '⊙', running: '◉', done: '✓', error: '✗',
  };
  const labels = {
    idle: 'Idle',
    running: `Running: ${task.task || ''}`,
    done: `Done: ${task.task || ''}`,
    error: `Error: ${task.task || ''}`,
  };

  const st = task.status || 'idle';
  pill.className = `status-pill ${classes[st] || 'pill-idle'}`;
  if (st === 'running') dot.classList.add('pulse'); else dot.classList.remove('pulse');
  dot.textContent  = icons[st]  || '⊙';
  text.textContent = labels[st] || 'Idle';
}

function updateDaemon(ok) {
  const dot = document.getElementById('daemon-dot');
  const tag = document.getElementById('daemon-tag');
  if (!dot) return;
  dot.className = `provider-dot ${ok ? 'dot-active' : 'dot-off'}`;
  if (tag) tag.textContent = ok ? 'running' : 'not found';
}

// ── Provider list ──────────────────────────────────────────────────────────────

async function loadProviders() {
  try {
    const r  = await fetch('/api/providers');
    const ps = await r.json();
    const el = document.getElementById('provider-list');
    if (!el) return;

    el.innerHTML = ps.map(p => {
      const dotClass = p.active ? (p.paid ? 'dot-paid' : 'dot-active') : 'dot-off';
      const tag      = p.paid   ? '<span style="color:#ffb300;font-size:10px">paid</span>' :
                       p.active ? '<span style="color:#39ff14;font-size:10px">free</span>' :
                                  '<span style="color:#444;font-size:10px">off</span>';
      return `
        <div class="provider-row">
          <span class="provider-dot ${dotClass}"></span>
          <span class="provider-name">${p.label}</span>
          ${tag}
        </div>`;
    }).join('');
  } catch {}
}

// ── Run tasks ──────────────────────────────────────────────────────────────────

async function runTask(name) {
  if (_taskRunning) {
    showToast('A task is already running', 'warning');
    return;
  }

  _taskRunning = true;
  setCardsEnabled(false);

  let url  = `/api/run/${name}`;
  let body = {};

  if (name === 'calculator') {
    const expr = document.getElementById('calc-expr');
    body.expression = expr ? expr.value.trim() : '127 * 43 - 58';
  }
  if (name === 'browser_game') {
    const movesEl = document.getElementById('game-moves');
    body.moves = movesEl ? parseInt(movesEl.value) || 5 : 5;
  }

  // Update result box
  const rb = document.getElementById('result-box');
  if (rb) { rb.textContent = `Running ${name}…`; rb.style.color = 'var(--cyan)'; }

  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (data.error) {
      showToast(data.error, 'error');
      _taskRunning = false;
      setCardsEnabled(true);
    } else {
      showToast(`Task "${name}" started`, 'info');
    }
  } catch (e) {
    showToast('Failed to start task: ' + e, 'error');
    _taskRunning = false;
    setCardsEnabled(true);
  }
}

function setCardsEnabled(enabled) {
  ['card-calc', 'card-vscode', 'card-game', 'card-notepad', 'card-email', 'card-multiapp'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    if (enabled) el.classList.remove('disabled');
    else         el.classList.add('disabled');
  });
  document.querySelectorAll('.btn-run, .task-btn-side').forEach(b => {
    b.disabled = !enabled;
  });
}

// ── Result display ─────────────────────────────────────────────────────────────

function showResult(task, result) {
  const rb   = document.getElementById('result-box');
  const badge = document.getElementById('result-task-badge');

  if (rb) {
    const isErr = result && result.error;
    rb.style.color = isErr ? 'var(--red)' : 'var(--green)';
    rb.textContent  = JSON.stringify(result, null, 2);
  }
  if (badge) {
    badge.textContent = task || '';
  }
}

// ── Recordings ─────────────────────────────────────────────────────────────────

async function loadRecordings() {
  try {
    const r    = await fetch('/api/recordings');
    const recs = await r.json();
    const tbody = document.getElementById('recordings-tbody');
    if (!tbody) return;

    if (!recs.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-dim);padding:20px 14px">No recordings yet.</td></tr>';
      return;
    }

    tbody.innerHTML = recs.slice(0, 20).map(rec => {
      const ok     = rec.status === 'ok';
      const sc     = ok ? 'status-ok' : 'status-error';
      const icon   = ok ? '✓' : '✗';
      const actions = (rec.actions || []).length;
      const result  = rec.result ? esc(String(rec.result).slice(0, 40)) : '—';
      const ts      = rec.start_ts || '—';
      const layer   = (rec.actions && rec.actions[0]) ? esc(rec.actions[0].action) : '—';

      return `
        <tr>
          <td><strong>${esc(rec.task || '')}</strong></td>
          <td style="font-family:'JetBrains Mono',monospace;font-size:11px">${layer}</td>
          <td class="${sc}">${icon} ${esc(rec.status || '')}</td>
          <td style="color:var(--text-dim)">${esc(ts)}</td>
          <td style="color:var(--text-dim)">${actions}</td>
          <td style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--cyan)">${result}</td>
        </tr>`;
    }).join('');
  } catch {}
}

// ── Toast notifications ────────────────────────────────────────────────────────

function showToast(msg, type = 'info') {
  const colors = { info: 'var(--cyan)', warning: 'var(--amber)', error: 'var(--red)', success: 'var(--green)' };
  const div = document.createElement('div');
  div.style.cssText = `
    position:fixed; bottom:24px; right:24px;
    background:rgba(10,14,24,.95);
    border:1px solid ${colors[type] || colors.info};
    color:${colors[type] || colors.info};
    padding:12px 18px; border-radius:10px;
    font-size:13px; z-index:9999;
    backdrop-filter:blur(20px);
    box-shadow:0 4px 24px rgba(0,0,0,.5);
    max-width:320px;
  `;
  div.textContent = msg;
  document.body.appendChild(div);
  setTimeout(() => { if (div.parentNode) div.parentNode.removeChild(div); }, 3500);
}
