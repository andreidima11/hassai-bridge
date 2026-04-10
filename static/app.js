// ── HASSAI Bridge v2 — Frontend ──

const API = '';
let allMemories = [];

// ── Endpoint display ──
function updateEndpointDisplay() {
  const base = `${window.location.protocol}//${window.location.host}`;
  document.getElementById('apiEndpoint').textContent = `${base}/v1`;
  document.getElementById('apiEndpointChat').textContent = `${base}/v1/chat/completions`;
  document.getElementById('apiEndpointModels').textContent = `${base}/v1/models`;
}
function copyEndpoint() {
  const url = document.getElementById('apiEndpoint').textContent;
  navigator.clipboard.writeText(url).then(() => toast('URL copiat!')).catch(() => {
    const ta = document.createElement('textarea'); ta.value = url;
    document.body.appendChild(ta); ta.select(); document.execCommand('copy');
    document.body.removeChild(ta); toast('URL copiat!');
  });
}

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
// SETTINGS
// ══════════════════════════════════════════════════

async function loadSettings() {
  try {
    const cfg = await api('GET', '/api/settings/');
    document.getElementById('lmUrl').value = cfg.lmstudio.base_url;
    document.getElementById('lmModel').value = cfg.lmstudio.model;
    document.getElementById('lmTimeout').value = cfg.lmstudio.timeout;
    document.getElementById('sxEnabled').checked = cfg.searxng.enabled;
    document.getElementById('knowledgeCutoff').value = cfg.knowledge_cutoff || '';
    document.getElementById('sxUrl').value = cfg.searxng.base_url;
    document.getElementById('sxMaxResults').value = cfg.searxng.max_results;
    document.getElementById('sxMaxChars').value = cfg.searxng.max_page_chars;
    document.getElementById('memEnabled').checked = cfg.memory.enabled;
    document.getElementById('memAutoExtract').checked = cfg.memory.auto_extract;
    document.getElementById('memMax').value = cfg.memory.max_memories_per_user;
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
      },
      searxng: {
        enabled: document.getElementById('sxEnabled').checked,
        base_url: document.getElementById('sxUrl').value,
        max_results: parseInt(document.getElementById('sxMaxResults').value),
        max_page_chars: parseInt(document.getElementById('sxMaxChars').value),
      },
      memory: {
        enabled: document.getElementById('memEnabled').checked,
        auto_extract: document.getElementById('memAutoExtract').checked,
        max_memories_per_user: parseInt(document.getElementById('memMax').value),
      },
      system_prompt: document.getElementById('systemPrompt').value,
      knowledge_cutoff: document.getElementById('knowledgeCutoff').value,
    });
    toast('Setări salvate!');
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
// MEMORY
// ══════════════════════════════════════════════════

const catLabels = {
  personal_info: '👤 Personal Info',
  preferences: '🎨 Preferences',
  home_setup: '🏠 Home Setup',
  facts: '📌 Facts',
  instructions: '📋 Instructions',
  context: '🔄 Context',
};

async function loadUsers() {
  try {
    const data = await api('GET', '/api/memory/users');
    const sel = document.getElementById('memUser');
    sel.innerHTML = '<option value="">-- selectează --</option>';
    for (const u of data.users) {
      sel.innerHTML += `<option value="${escapeHtml(u)}">${escapeHtml(u)}</option>`;
    }
  } catch (e) { /* no users yet */ }
}

async function loadMemoryPanel() {
  const userId = document.getElementById('memUser').value;
  if (!userId) { toast('Selectează un utilizator', true); return; }
  await Promise.all([loadStats(userId), loadMemories(userId)]);
}

async function loadStats(userId) {
  try {
    const stats = await api('GET', `/api/memory/stats/${encodeURIComponent(userId)}`);
    const grid = document.getElementById('statsGrid');
    let html = `<div class="stat-card"><div class="num">${stats.total}</div><div class="lbl">Total Memorii</div></div>`;
    for (const [cat, count] of Object.entries(stats.by_category || {})) {
      html += `<div class="stat-card"><div class="num">${count}</div><div class="lbl">${catLabels[cat] || cat}</div></div>`;
    }
    grid.innerHTML = html;
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

async function loadMemories(userId) {
  if (!userId) userId = document.getElementById('memUser').value;
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
            <span>📅 ${date}</span>
            <span>📊 ${accessed}</span>
            <span>🏷️ ${escapeHtml(m.keywords || '-')}</span>
            <span>📥 ${m.source}</span>
          </div>
        </div>
        <button class="btn btn-danger btn-sm" onclick="deleteMemory(${m.id})">🗑️</button>
      </div>`;
  }).join('');
}

function filterMemories(cat, btn) {
  document.querySelectorAll('.filter-btn').forEach(b => {
    b.classList.remove('active');
    b.style.background = '';
  });
  btn.classList.add('active');
  if (cat === 'all') {
    renderMemories(allMemories);
  } else {
    renderMemories(allMemories.filter(m => m.category === cat));
  }
}

async function addMemory() {
  const userId = document.getElementById('newMemUser').value || 'default';
  const content = document.getElementById('newMemContent').value;
  if (!content) { toast('Scrie conținutul', true); return; }
  try {
    await api('POST', '/api/memory/', {
      user_id: userId,
      content,
      category: document.getElementById('newMemCat').value,
      keywords: document.getElementById('newMemKeywords').value,
      importance: parseInt(document.getElementById('newMemImp').value),
    });
    document.getElementById('newMemContent').value = '';
    document.getElementById('newMemKeywords').value = '';
    toast('Memorie adăugată!');
    loadUsers();
    if (document.getElementById('memUser').value === userId) loadMemoryPanel();
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

async function deleteMemory(id) {
  try {
    await api('DELETE', `/api/memory/${id}`);
    toast('Memorie ștearsă');
    const userId = document.getElementById('memUser').value;
    if (userId) loadMemoryPanel();
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

async function clearUserMemories() {
  const userId = document.getElementById('memUser').value;
  if (!userId) return;
  if (!confirm(`Ștergi TOATE memoriile pentru "${userId}"?`)) return;
  try {
    await api('DELETE', `/api/memory/user/${encodeURIComponent(userId)}`);
    toast('Memorii șterse');
    loadMemoryPanel();
    loadUsers();
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

async function consolidateMemories() {
  const userId = document.getElementById('memUser').value;
  if (!userId) { toast('Selectează un utilizator', true); return; }
  toast('Se consolidează...');
  try {
    await api('POST', `/api/memory/consolidate/${encodeURIComponent(userId)}`);
    toast('Consolidare completă!');
    loadMemoryPanel();
  } catch (e) {
    toast('Eroare: ' + e.message, true);
  }
}

// ── Init ──
updateEndpointDisplay();
loadSettings();
checkHealth();
loadUsers();