/* CyberSec Pro Academy — Shared Lab JavaScript
   Each lab page calls: initLab({ id, totalSteps, systemPrompt, quickPrompts, welcomeMsg })
*/

let _cfg = {};
let _apiKey = localStorage.getItem('cspa_api_key') || '';
const _history = [];

function initLab(cfg) {
  _cfg = cfg;

  // Restore progress
  const saved = JSON.parse(localStorage.getItem('lab_' + cfg.id + '_progress') || '{}');
  for (let i = 0; i < cfg.totalSteps; i++) {
    if (saved[i]) { const el = document.getElementById('step-' + i); if (el) el.classList.add('done'); }
  }
  _updateProgress();

  // API key state
  if (_apiKey) {
    const b = document.getElementById('apiBanner'); if (b) b.style.display = 'none';
    const s = document.getElementById('aiStatus'); if (s) s.textContent = 'Online — ' + (cfg.modeLabel || 'AI Active');
  }

  // Welcome message
  if (cfg.welcomeMsg) _addMsg('ai', cfg.welcomeMsg);

  // Modal click-outside
  const m = document.getElementById('apiModal');
  if (m) m.addEventListener('click', e => { if (e.target === m) _closeModal(); });
}

function toggleStep(n) {
  const el = document.getElementById('step-' + n);
  if (!el) return;
  el.classList.toggle('open');
  if (el.classList.contains('open') && !el.classList.contains('done')) {
    el.classList.add('done');
    _saveProgress();
    _updateProgress();
  }
}

function _saveProgress() {
  const d = {};
  for (let i = 0; i < _cfg.totalSteps; i++) {
    const el = document.getElementById('step-' + i);
    if (el) d[i] = el.classList.contains('done');
  }
  localStorage.setItem('lab_' + _cfg.id + '_progress', JSON.stringify(d));
}

function _updateProgress() {
  let c = 0;
  for (let i = 0; i < _cfg.totalSteps; i++) {
    const el = document.getElementById('step-' + i);
    if (el && el.classList.contains('done')) c++;
  }
  const p = _cfg.totalSteps ? Math.round((c / _cfg.totalSteps) * 100) : 0;
  const f = document.getElementById('lpFill'); if (f) f.style.width = p + '%';
  const pct = document.getElementById('lpPct'); if (pct) pct.textContent = p + '%';
  const st = document.getElementById('lpSteps'); if (st) st.textContent = c + ' / ' + _cfg.totalSteps + ' steps';
}

function _addMsg(role, text) {
  const chat = document.getElementById('aiChat');
  if (!chat) return;
  const div = document.createElement('div');
  div.className = 'msg msg-' + role;
  div.innerHTML = `<div class="msg-label">${role === 'ai' ? 'AI Analyst' : 'You'}</div><div class="bubble">${_fmt(text)}</div>`;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function _fmt(t) {
  return t
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\n/g,'<br>');
}

function _showTyping() {
  const chat = document.getElementById('aiChat');
  if (!chat) return;
  const div = document.createElement('div');
  div.id = 'typing'; div.className = 'msg msg-ai';
  div.innerHTML = '<div class="msg-label">AI Analyst</div><div class="bubble typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div>';
  chat.appendChild(div); chat.scrollTop = chat.scrollHeight;
}
function _removeTyping() { const t = document.getElementById('typing'); if (t) t.remove(); }

async function sendMessage() {
  const input = document.getElementById('aiInput');
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  if (!_apiKey) { openApiModal(); return; }
  _addMsg('user', text);
  _history.push({ role: 'user', content: text });
  _showTyping();
  const btn = document.getElementById('sendBtn'); if (btn) btn.disabled = true;
  try {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'x-api-key': _apiKey, 'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
        'anthropic-dangerous-direct-browser-access': 'true'
      },
      body: JSON.stringify({ model: 'claude-opus-4-6', max_tokens: 1500, system: _cfg.systemPrompt, messages: _history.slice(-10) })
    });
    const data = await res.json();
    _removeTyping();
    if (data.error) { _addMsg('ai', 'Error: ' + data.error.message); }
    else { const r = data.content[0].text; _history.push({ role: 'assistant', content: r }); _addMsg('ai', r); }
  } catch (err) { _removeTyping(); _addMsg('ai', 'Connection error: ' + err.message); }
  if (btn) btn.disabled = false;
}

function qp(key) {
  const p = _cfg.quickPrompts && _cfg.quickPrompts[key];
  if (!p) return;
  const input = document.getElementById('aiInput');
  if (input) { input.value = p; input.focus(); }
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

function openApiModal() { const m = document.getElementById('apiModal'); if (m) m.classList.add('open'); }
function _closeModal() { const m = document.getElementById('apiModal'); if (m) m.classList.remove('open'); }
window.closeApiModal = _closeModal;

function saveKey() {
  const val = (document.getElementById('apiKeyInput') || {}).value || '';
  if (!val.trim().startsWith('sk-')) { alert('Invalid key — must start with sk-'); return; }
  _apiKey = val.trim();
  localStorage.setItem('cspa_api_key', _apiKey);
  const b = document.getElementById('apiBanner'); if (b) b.style.display = 'none';
  const s = document.getElementById('aiStatus'); if (s) s.textContent = 'Online — ' + (_cfg.modeLabel || 'AI Active');
  _closeModal();
  _addMsg('ai', 'API key connected. Paste your tool output below and I\'ll start analyzing.');
}

function copyCmd(btn) {
  const block = btn.nextElementSibling;
  if (!block) return;
  navigator.clipboard.writeText(block.innerText).then(() => {
    btn.textContent = 'Copied!'; btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 1800);
  });
}

// Expose globals
window.toggleStep = toggleStep;
window.sendMessage = sendMessage;
window.handleKey = handleKey;
window.qp = qp;
window.openApiModal = openApiModal;
window.saveKey = saveKey;
window.copyCmd = copyCmd;
