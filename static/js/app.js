// ── HASSAI Bridge v2 — Frontend ──

const API = '';

// ── Tabs ──
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.panel).classList.add('active');
  });
});

// ── Toast ──
function toast(msg, isError = false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show' + (isError ? ' error' : '');
  setTimeout(() => t.className = 'toast', 3000);
}

// ── API helpers ──
async function api(method, path, body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(API + path, opts);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

// ══════════════════════════════════════════════════
// INFO TAB
// ══════════════════════════════════════════════════

function formatUptime(seconds) {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}z ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function updateEndpointDisplay(ip, port) {
  const base = ip && port ? `http://${ip}:${port}` : `${window.location.protocol}//${window.location.host}`;
  document.getElementById('apiEndpoint').textContent = base;
  document.getElementById('apiEndpointChat').textContent = `${base}/v1/chat/completions`;
  document.getElementById('apiEndpointModels').textContent = `${base}/v1/models`;
}

let _apiKeyVisible = false;
let _apiKeyValue = '';

function toggleApiKey() {
  _apiKeyVisible = !_apiKeyVisible;
  const el = document.getElementById('apiKeyDisplay');
  if (_apiKeyVisible && _apiKeyValue) {
    el.textContent = _apiKeyValue;
    el.classList.remove('api-key-blur');
  } else {
    el.textContent = '••••••••••••••••';
    el.classList.add('api-key-blur');
  }
}

function copyText(elementId) {
  const el = document.getElementById(elementId);
  let text = el.textContent;
  // If it's the API key and hidden, copy the real value
  if (elementId === 'apiKeyDisplay' && !_apiKeyVisible && _apiKeyValue) {
    text = _apiKeyValue;
  }
  // navigator.clipboard requires secure context (HTTPS or localhost).
  // On LAN IPs (http://192.168.x.x) we must use the textarea fallback.
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(() => toast('Copiat!')).catch(() => _copyFallback(text));
  } else {
    _copyFallback(text);
  }
}

function _copyFallback(text, msg) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try {
    document.execCommand('copy');
    toast(msg || 'Copiat!');
  } catch (e) {
    toast('Nu s-a putut copia');
  }
  document.body.removeChild(ta);
}

async function loadSystemInfo() {
  try {
    const info = await api('GET', '/api/settings/info');

    // Services status
    const lm = info.services.lmstudio;
    const sx = info.services.searxng;
    const mem = info.services.memory;

    const lmCard = document.getElementById('svcLMStudio');
    const sxCard = document.getElementById('svcSearXNG');
    const memCard = document.getElementById('svcMemory');

    // LMStudio
    const lmOnline = lm.status === 'connected';
    lmCard.className = 'service-card ' + (lmOnline ? 'online' : 'offline');
    lmCard.querySelector('.svc-status').className = 'svc-status ' + (lmOnline ? 'online' : 'offline');
    lmCard.querySelector('.svc-status').textContent = lmOnline ? 'Conectat' : 'Indisponibil';
    document.getElementById('svcLMDetail').textContent = `${lm.url} — ${lm.model}`;

    // SearXNG
    const sxOnline = sx.status === 'connected';
    sxCard.className = 'service-card ' + (sx.enabled ? (sxOnline ? 'online' : 'offline') : '');
    const sxStatusEl = sxCard.querySelector('.svc-status');
    if (!sx.enabled) {
      sxStatusEl.className = 'svc-status disabled';
      sxStatusEl.textContent = 'Dezactivat';
    } else {
      sxStatusEl.className = 'svc-status ' + (sxOnline ? 'online' : 'offline');
      sxStatusEl.textContent = sxOnline ? 'Conectat' : 'Indisponibil';
    }
    document.getElementById('svcSXDetail').textContent = sx.url;

    // Memory
    memCard.className = 'service-card ' + (mem.enabled ? 'online' : '');
    const memStatusEl = memCard.querySelector('.svc-status');
    if (mem.enabled) {
      memStatusEl.className = 'svc-status online';
      memStatusEl.textContent = mem.auto_extract ? 'Activ + Auto-extracție' : 'Activ';
    } else {
      memStatusEl.className = 'svc-status disabled';
      memStatusEl.textContent = 'Dezactivat';
    }
    document.getElementById('svcMemDetail').textContent = `${info.stats.total_memories} memorii stocate`;

    // Header badges
    document.getElementById('statusLM').className = 'status ' + (lmOnline ? 'ok' : 'err');
    document.getElementById('statusSX').className = 'status ' + (sx.enabled && sxOnline ? 'ok' : 'err');

    // Stats
    document.getElementById('statUptime').textContent = formatUptime(info.uptime_seconds);
    document.getElementById('statUsers').textContent = info.stats.total_users;
    document.getElementById('statMemories').textContent = info.stats.total_memories;
    document.getElementById('statConversations').textContent = info.stats.total_conversations;
    document.getElementById('statActions24h').textContent = info.stats.actions_last_24h;

    // Version badge
    if (info.version) {
      document.getElementById('versionBadge').textContent = info.version;
    }

    // API Key
    if (info.api_key) {
      _apiKeyValue = info.api_key;
    }

    // Update endpoints with real LAN IP
    updateEndpointDisplay(info.local_ip, info.port);

    // Endpoints table
    const table = document.getElementById('endpointsTable');
    table.innerHTML = info.endpoints.map(ep => `
      <div class="ep-row">
        <span class="ep-method ${ep.method.toLowerCase()}">${escapeHtml(ep.method)}</span>
        <span class="ep-path">${escapeHtml(ep.path)}</span>
        <span class="ep-desc">${escapeHtml(ep.description)}</span>
      </div>
    `).join('');

  } catch (e) {
    toast('Eroare la încărcarea info: ' + e.message, true);
  }
}

function refreshInfo() {
  loadSystemInfo();
  toast('Info reîmprospătat!');
}

// ══════════════════════════════════════════════════
// SETTINGS
// ══════════════════════════════════════════════════

async function refreshModelList(selectedModel) {
  const select = document.getElementById('lmModel');
  const currentVal = selectedModel || select.value;
  try {
    const data = await api('GET', '/v1/models');
    const models = data.data || [];
    select.innerHTML = '';
    if (models.length === 0) {
      select.innerHTML = '<option value="default">default (niciun model detectat)</option>';
    } else {
      models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.id;
        select.appendChild(opt);
      });
    }
    // Set saved value (add it if not in list)
    if (currentVal && currentVal !== 'default') {
      const exists = Array.from(select.options).some(o => o.value === currentVal);
      if (!exists) {
        const opt = document.createElement('option');
        opt.value = currentVal;
        opt.textContent = currentVal + ' (salvat)';
        select.appendChild(opt);
      }
      select.value = currentVal;
    }
    if (!selectedModel) toast('Modele reîncărcate!');
  } catch (e) {
    select.innerHTML = '<option value="default">default (LMStudio indisponibil)</option>';
    if (currentVal && currentVal !== 'default') {
      const opt = document.createElement('option');
      opt.value = currentVal;
      opt.textContent = currentVal + ' (salvat)';
      select.appendChild(opt);
      select.value = currentVal;
    }
    if (!selectedModel) toast('Nu s-au putut încărca modelele: ' + e.message, true);
  }
}

async function loadSettings() {
  try {
    const cfg = await api('GET', '/api/settings/');
    document.getElementById('lmUrl').value = cfg.lmstudio.base_url;
    // Load model list then set saved value
    await refreshModelList(cfg.lmstudio.model);
    document.getElementById('lmTimeout').value = cfg.lmstudio.timeout;
    document.getElementById('lmMaxTokens').value = cfg.lmstudio.max_tokens || 2048;
    document.getElementById('lmTemperature').value = cfg.lmstudio.temperature ?? 0.7;
    document.getElementById('sxEnabled').checked = cfg.searxng.enabled;
    document.getElementById('knowledgeCutoff').value = cfg.knowledge_cutoff || '';
    document.getElementById('sxUrl').value = cfg.searxng.base_url;
    document.getElementById('sxMaxResults').value = cfg.searxng.max_results;
    document.getElementById('sxMaxChars').value = cfg.searxng.max_page_chars;
    document.getElementById('sxCacheTtl').value = cfg.searxng.cache_ttl || 300;
    document.getElementById('memEnabled').checked = cfg.memory.enabled;
    document.getElementById('memAutoExtract').checked = cfg.memory.auto_extract;
    document.getElementById('memMax').value = cfg.memory.max_memories_per_user;
    const perf = cfg.performance || {};
    document.getElementById('perfHistoryLimit').value = perf.history_limit || 10;
    document.getElementById('perfParallelFetch').checked = perf.parallel_page_fetch !== false;
    document.getElementById('systemPrompt').value = cfg.system_prompt || '';
  } catch (e) {
    toast('Eroare la încărcarea setărilor: ' + e.message, true);
  }
}

async function saveSettings() {
  try {
    await api('PUT', '/api/settings/', {
      lmstudio: {
        base_url: document.getElementById('lmUrl').value,
        model: document.getElementById('lmModel').value,
        timeout: parseInt(document.getElementById('lmTimeout').value),
        max_tokens: parseInt(document.getElementById('lmMaxTokens').value),
        temperature: parseFloat(document.getElementById('lmTemperature').value),
      },
      searxng: {
        enabled: document.getElementById('sxEnabled').checked,
        base_url: document.getElementById('sxUrl').value,
        max_results: parseInt(document.getElementById('sxMaxResults').value),
        max_page_chars: parseInt(document.getElementById('sxMaxChars').value),
        cache_ttl: parseInt(document.getElementById('sxCacheTtl').value),
      },
      memory: {
        enabled: document.getElementById('memEnabled').checked,
        auto_extract: document.getElementById('memAutoExtract').checked,
        max_memories_per_user: parseInt(document.getElementById('memMax').value),
      },
      performance: {
        history_limit: parseInt(document.getElementById('perfHistoryLimit').value),
        parallel_page_fetch: document.getElementById('perfParallelFetch').checked,
      },
      system_prompt: document.getElementById('systemPrompt').value,
      knowledge_cutoff: document.getElementById('knowledgeCutoff').value,
    });
    toast('Setări salvate!');
    loadSystemInfo(); // refresh info panel
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

async function checkHealth() {
  try {
    const h = await api('GET', '/api/settings/health');
    document.getElementById('statusLM').className = 'status ' + (h.lmstudio === 'connected' ? 'ok' : 'err');
    document.getElementById('statusSX').className = 'status ' + (h.searxng === 'connected' ? 'ok' : 'err');
    toast(`LMStudio: ${h.lmstudio} | SearXNG: ${h.searxng}`);
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

// ══════════════════════════════════════════════════
// USERS + MEMORY
// ══════════════════════════════════════════════════

let _selectedUser = null;
let allMemories = [];

const catLabels = {
  personal_info: 'Personal Info',
  preferences: 'Preferences',
  home_setup: 'Home Setup',
  facts: 'Facts',
  instructions: 'Instructions',
  context: 'Context',
};

async function loadUsersTab() {
  try {
    const [cfg, memUsers] = await Promise.all([
      api('GET', '/api/settings/'),
      api('GET', '/api/memory/users'),
    ]);
    const users = cfg.users || {};
    const apiKeys = users.api_keys || {};
    document.getElementById('defaultUserInput').value = users.default_user || '';

    // Merge configured users + users with memories
    const userMap = {};
    for (const [key, name] of Object.entries(apiKeys)) {
      if (!userMap[name]) userMap[name] = { keys: [], hasMemories: false };
      userMap[name].keys.push(key);
    }
    for (const u of (memUsers.users || [])) {
      if (!userMap[u]) userMap[u] = { keys: [], hasMemories: true };
      else userMap[u].hasMemories = true;
    }

    const container = document.getElementById('userCardsList');
    const names = Object.keys(userMap);
    if (names.length === 0) {
      container.innerHTML = '<div class="card"><p class="card-muted">Niciun utilizator configurat. Adaugă unul mai sus.</p></div>';
      return;
    }

    container.innerHTML = names.map(name => {
      const info = userMap[name];
      const isSelected = _selectedUser === name;
      const keyHtml = info.keys.length
        ? '<code>' + escapeHtml(info.keys[0]) + '</code>'
        : '<span class="no-key">fără API key</span>';
      const actionsHtml = info.keys.length
        ? `<button class="btn btn-sm" onclick="event.stopPropagation();copyUserKey('${escapeHtml(info.keys[0])}')" title="Copiază API Key">Copiază</button>
           <button class="btn btn-sm btn-danger" onclick="event.stopPropagation();deleteUser('${escapeHtml(name)}')" title="Șterge">Șterge</button>`
        : '';
      return `
        <div class="user-card ${isSelected ? 'selected' : ''}" onclick="selectUser('${escapeHtml(name)}')">
          <div class="user-card-main">
            <div class="user-avatar">${escapeHtml(name.substring(0,2).toUpperCase())}</div>
            <div class="user-info">
              <div class="user-name">${escapeHtml(name)}</div>
              <div class="user-key">${keyHtml}</div>
            </div>
          </div>
          <div class="user-actions">${actionsHtml}</div>
        </div>`;
    }).join('');
  } catch (e) {
    toast('Eroare la încărcarea utilizatorilor: ' + e.message, true);
  }
}

async function addUser() {
  const name = document.getElementById('newUserName').value.trim();
  if (!name) { toast('Introdu un nume de utilizator', true); return; }
  try {
    const result = await api('POST', '/api/settings/users', { username: name });
    document.getElementById('newUserName').value = '';
    toast(`Utilizator "${result.username}" creat!`);
    loadUsersTab();
  } catch (e) {
    if (e.message.includes('409')) toast('Utilizatorul există deja', true);
    else toast('Eroare: ' + e.message, true);
  }
}

async function deleteUser(username) {
  if (!confirm(`Ștergi utilizatorul "${username}", API key-ul și TOATE memoriile asociate?\n\nAceastă acțiune este ireversibilă!`)) return;
  try {
    // Delete all memories first, then the user
    try { await api('DELETE', `/api/memory/user/${encodeURIComponent(username)}`); } catch(e) { /* no memories */ }
    await api('DELETE', `/api/settings/users/${encodeURIComponent(username)}`);
    toast(`Utilizator "${username}" șters complet`);
    if (_selectedUser === username) closeUserModal();
    loadUsersTab();
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

async function deleteUserFull() {
  if (!_selectedUser) return;
  deleteUser(_selectedUser);
}

async function saveDefaultUser() {
  const name = document.getElementById('defaultUserInput').value.trim();
  try {
    await api('PUT', '/api/settings/users/default', { username: name });
    toast('Utilizator implicit salvat!');
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

function copyUserKey(key) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(key).then(() => toast('API Key copiat!')).catch(() => _copyFallback(key, 'API Key copiat!'));
  } else {
    _copyFallback(key, 'API Key copiat!');
  }
}

async function selectUser(username) {
  _selectedUser = username;
  document.getElementById('selectedUserName').textContent = username;
  const overlay = document.getElementById('userModal');
  overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
  document.querySelectorAll('.user-card').forEach(c => {
    c.classList.toggle('selected', c.querySelector('.user-name')?.textContent === username);
  });
  await Promise.all([loadStats(username), loadMemories(username)]);
}

function closeUserModal() {
  _selectedUser = null;
  const overlay = document.getElementById('userModal');
  overlay.classList.remove('open');
  document.body.style.overflow = '';
  document.querySelectorAll('.user-card').forEach(c => c.classList.remove('selected'));
}
const deselectUser = closeUserModal;

// Close modal on Escape
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.getElementById('userModal').classList.contains('open')) {
    closeUserModal();
  }
});

// ── Memory functions ──

async function loadStats(userId) {
  try {
    const stats = await api('GET', `/api/memory/stats/${encodeURIComponent(userId)}`);
    const grid = document.getElementById('statsGrid');
    let html = `<div class="stat-card"><div class="num">${stats.total}</div><div class="lbl">Total</div></div>`;
    for (const [cat, count] of Object.entries(stats.by_category || {})) {
      html += `<div class="stat-card"><div class="num">${count}</div><div class="lbl">${catLabels[cat] || cat}</div></div>`;
    }
    grid.innerHTML = html;
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

async function loadMemories(userId) {
  if (!userId) userId = _selectedUser;
  if (!userId) return;
  try {
    const data = await api('GET', `/api/memory/${encodeURIComponent(userId)}?limit=200`);
    allMemories = data.memories || [];
    renderMemories(allMemories);
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

function renderMemories(memories) {
  const list = document.getElementById('memList');
  if (!memories.length) {
    list.innerHTML = '<p style="color:var(--muted);font-size:.9rem">Nicio memorie.</p>';
    return;
  }
  list.innerHTML = memories.map(m => {
    const stars = '★'.repeat(m.importance) + '☆'.repeat(5 - m.importance);
    const date = new Date(m.created_at * 1000).toLocaleDateString('ro-RO');
    const accessed = m.access_count > 0 ? `accesată de ${m.access_count}x` : 'neaccesată';
    return `
      <div class="mem-item" data-cat="${m.category}">
        <div class="mem-content">
          <span class="mem-badge cat-${m.category}">${catLabels[m.category] || m.category}</span>
          <span class="importance-stars" title="Importanță: ${m.importance}/5">${stars}</span>
          <div style="margin-top:6px">${escapeHtml(m.content)}</div>
          <div class="mem-meta">
            <span>${date}</span>
            <span>Accesat: ${accessed}</span>
            <span>${escapeHtml(m.keywords || '-')}</span>
            <span>${m.source}</span>
          </div>
        </div>
        <button class="btn btn-danger btn-sm" onclick="deleteMemory(${m.id})">Șterge</button>
      </div>`;
  }).join('');
}

function filterMemories(cat, btn) {
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderMemories(cat === 'all' ? allMemories : allMemories.filter(m => m.category === cat));
}

async function addMemory() {
  if (!_selectedUser) { toast('Selectează un utilizator', true); return; }
  const content = document.getElementById('newMemContent').value;
  if (!content) { toast('Scrie conținutul', true); return; }
  try {
    await api('POST', '/api/memory/', {
      user_id: _selectedUser,
      content,
      category: document.getElementById('newMemCat').value,
      keywords: document.getElementById('newMemKeywords').value,
      importance: parseInt(document.getElementById('newMemImp').value),
    });
    document.getElementById('newMemContent').value = '';
    document.getElementById('newMemKeywords').value = '';
    toast('Memorie adăugată!');
    await Promise.all([loadStats(_selectedUser), loadMemories(_selectedUser)]);
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

async function deleteMemory(id) {
  try {
    await api('DELETE', `/api/memory/${id}`);
    toast('Memorie ștearsă');
    if (_selectedUser) await Promise.all([loadStats(_selectedUser), loadMemories(_selectedUser)]);
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

async function clearUserMemories() {
  if (!_selectedUser) return;
  if (!confirm(`Ștergi TOATE memoriile pentru "${_selectedUser}"?`)) return;
  try {
    await api('DELETE', `/api/memory/user/${encodeURIComponent(_selectedUser)}`);
    toast('Memorii șterse');
    await Promise.all([loadStats(_selectedUser), loadMemories(_selectedUser)]);
    loadUsersTab();
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

async function consolidateMemories() {
  if (!_selectedUser) { toast('Selectează un utilizator', true); return; }
  toast('Se consolidează...');
  try {
    await api('POST', `/api/memory/consolidate/${encodeURIComponent(_selectedUser)}`);
    toast('Consolidare completă!');
    await Promise.all([loadStats(_selectedUser), loadMemories(_selectedUser)]);
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

async function restartServer() {
  if (!confirm('Ești sigur că vrei să restartezi serverul HASSAI Bridge?')) return;
  try {
    await api('POST', '/api/settings/restart');
    toast('Serverul se restartează...');
    setTimeout(() => {
      const check = setInterval(async () => {
        try {
          await fetch('/api/settings/health');
          clearInterval(check);
          location.reload();
        } catch(e) { /* still restarting */ }
      }, 1500);
    }, 2000);
  } catch (e) {
    toast('Eroare la restart: ' + e.message, true);
  }
}

// ══════════════════════════════════════════════════
// BACKUP / RESTORE
// ══════════════════════════════════════════════════

function downloadBackup() {
  const a = document.createElement('a');
  a.href = API + '/api/settings/backup';
  a.download = 'hassai_backup.db';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  toast('Backup descărcat!');
}

async function uploadRestore(input) {
  const file = input.files[0];
  if (!file) return;
  if (!confirm('Restaurarea înlocuiește TOATE datele existente!\n\nEști sigur?')) {
    input.value = '';
    return;
  }
  const formData = new FormData();
  formData.append('file', file);
  try {
    const resp = await fetch(API + '/api/settings/restore/upload', {
      method: 'POST',
      body: formData,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    toast('Baza de date restaurată! Se reîncarcă...');
    setTimeout(() => location.reload(), 1500);
  } catch (e) {
    toast('Eroare la restaurare: ' + e.message, true);
  }
  input.value = '';
}

// ══════════════════════════════════════════════════
// CONVERSATIONS TAB
// ══════════════════════════════════════════════════

let _convUserId = '';
let _convSessionId = '';

async function refreshConvUsers() {
  const select = document.getElementById('convUserSelect');
  const prev = select.value;
  try {
    const [cfg, memData] = await Promise.all([
      api('GET', '/api/settings/'),
      api('GET', '/api/memory/users'),
    ]);
    const userSet = new Set();
    const apiKeys = (cfg.users || {}).api_keys || {};
    for (const name of Object.values(apiKeys)) userSet.add(name);
    for (const u of (memData.users || [])) userSet.add(u);

    select.innerHTML = '<option value="">— Alege —</option>';
    for (const name of [...userSet].sort()) {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    }
    if (prev && userSet.has(prev)) select.value = prev;
    toast('Utilizatori reîncărcați!');
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

async function loadConversations() {
  const userId = document.getElementById('convUserSelect').value;
  const sessCard = document.getElementById('convSessionsCard');

  if (!userId) {
    sessCard.style.display = 'none';
    return;
  }

  try {
    const data = await api('GET', `/api/settings/conversations/${encodeURIComponent(userId)}`);
    const sessions = data.sessions || [];
    sessCard.style.display = '';

    const list = document.getElementById('convSessionsList');
    if (!sessions.length) {
      list.innerHTML = '<p class="card-muted">Nicio conversație găsită pentru acest utilizator.</p>';
      return;
    }

    list.innerHTML = sessions.map(s => {
      const started = new Date(s.started_at * 1000);
      const last = new Date(s.last_at * 1000);
      const dateStr = started.toLocaleDateString('ro-RO', { day: '2-digit', month: 'short', year: 'numeric' });
      const timeStr = started.toLocaleTimeString('ro-RO', { hour: '2-digit', minute: '2-digit' });
      const lastTimeStr = last.toLocaleTimeString('ro-RO', { hour: '2-digit', minute: '2-digit' });
      const duration = Math.round((s.last_at - s.started_at) / 60);
      const durationStr = duration < 1 ? '<1 min' : duration < 60 ? `${duration} min` : `${Math.floor(duration/60)}h ${duration%60}m`;
      return `
        <div class="conv-session-item" onclick="openConvSession('${escapeHtml(userId)}','${escapeHtml(s.session_id)}')">
          <div class="conv-session-info">
            <div class="conv-session-date">${dateStr} &nbsp; ${timeStr} — ${lastTimeStr}</div>
            <div class="conv-session-meta">
              <span>${s.message_count} mesaje</span>
              <span>${durationStr}</span>
            </div>
          </div>
          <div class="conv-session-arrow">›</div>
        </div>`;
    }).join('');
  } catch (e) {
    toast('Eroare la încărcarea conversațiilor: ' + e.message, true);
  }
}

async function openConvSession(userId, sessionId) {
  _convUserId = userId;
  _convSessionId = sessionId;

  const modal = document.getElementById('convModal');
  const body = document.getElementById('convModalMessages');
  body.innerHTML = '<p class="card-muted" style="text-align:center;padding:40px 0">Se încarcă...</p>';

  // Open modal
  modal.classList.add('open');
  document.body.style.overflow = 'hidden';

  try {
    const data = await api('GET', `/api/settings/conversations/${encodeURIComponent(userId)}/${encodeURIComponent(sessionId)}`);
    const messages = data.messages || [];

    // Set header info
    if (messages.length) {
      const first = new Date(messages[0].created_at * 1000);
      const last = new Date(messages[messages.length - 1].created_at * 1000);
      document.getElementById('convModalTitle').textContent =
        first.toLocaleDateString('ro-RO', { day: '2-digit', month: 'long', year: 'numeric' });
      document.getElementById('convModalSubtitle').textContent =
        `${messages.length} mesaje · ${first.toLocaleTimeString('ro-RO', {hour:'2-digit',minute:'2-digit'})} — ${last.toLocaleTimeString('ro-RO', {hour:'2-digit',minute:'2-digit'})}`;
    } else {
      document.getElementById('convModalTitle').textContent = 'Conversație';
      document.getElementById('convModalSubtitle').textContent = 'Niciun mesaj';
    }

    if (!messages.length) {
      body.innerHTML = '<p class="card-muted" style="text-align:center;padding:40px 0">Niciun mesaj în această sesiune.</p>';
      return;
    }

    body.innerHTML = messages.map(m => {
      const time = new Date(m.created_at * 1000).toLocaleTimeString('ro-RO', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const roleLabel = m.role === 'user' ? 'Utilizator' : m.role === 'assistant' ? 'Asistent' : m.role;
      const content = escapeHtml(m.content).replace(/\n/g, '<br>');
      return `
        <div class="conv-msg conv-msg-${m.role}">
          <div class="conv-msg-header">
            <span class="conv-msg-role">${roleLabel}</span>
            <span class="conv-msg-time">${time}</span>
          </div>
          <div class="conv-msg-content">${content}</div>
        </div>`;
    }).join('');
  } catch (e) {
    body.innerHTML = `<p class="card-muted" style="text-align:center;padding:40px 0;color:var(--danger)">Eroare: ${escapeHtml(e.message)}</p>`;
  }
}

function closeConvModal() {
  document.getElementById('convModal').classList.remove('open');
  document.body.style.overflow = '';
  _convUserId = '';
  _convSessionId = '';
}

async function deleteCurrentSession() {
  if (!_convUserId || !_convSessionId) return;
  if (!confirm('Ești sigur că vrei să ștergi această conversație?\n\nAceastă acțiune este ireversibilă!')) return;
  try {
    await api('DELETE', `/api/settings/conversations/${encodeURIComponent(_convUserId)}/${encodeURIComponent(_convSessionId)}`);
    toast('Conversație ștearsă!');
    closeConvModal();
    loadConversations();
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

// Close conv modal on Escape
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.getElementById('convModal').classList.contains('open')) {
    closeConvModal();
  }
});

// ── Init ──
loadSystemInfo();
loadSettings();
refreshConvUsers();
loadUsersTab();