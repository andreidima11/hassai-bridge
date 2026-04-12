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

// ── Settings sub-tabs ──
document.querySelectorAll('.settings-tab').forEach(stab => {
  stab.addEventListener('click', () => {
    document.querySelectorAll('.settings-tab').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.settings-subpanel').forEach(p => p.classList.remove('active'));
    stab.classList.add('active');
    document.getElementById(stab.dataset.stab).classList.add('active');
  });
});

// ── Toast ──
function toast(msg, isError = false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show' + (isError ? ' error' : '');
  setTimeout(() => el.className = 'toast', 3000);
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
  if (d > 0) return `${d}d ${h}h ${m}m`;
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
  if (elementId === 'apiKeyDisplay' && !_apiKeyVisible && _apiKeyValue) {
    text = _apiKeyValue;
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(() => toast(t('toast.copied'))).catch(() => _copyFallback(text));
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
    toast(msg || t('toast.copied'));
  } catch (e) {
    toast(t('toast.copyFail'));
  }
  document.body.removeChild(ta);
}

async function loadSystemInfo() {
  try {
    const info = await api('GET', '/api/settings/info');

    // LMStudio / Provider
    const lm = info.services.lmstudio;
    const prov = info.services.provider || lm;
    const sx = info.services.searxng;
    const mem = info.services.memory;

    const lmCard = document.getElementById('svcLMStudio');
    const sxCard = document.getElementById('svcSearXNG');
    const memCard = document.getElementById('svcMemory');

    // Provider
    const lmOnline = (prov.status || lm.status) === 'connected';
    lmCard.className = 'service-card ' + (lmOnline ? 'online' : 'offline');
    lmCard.querySelector('.svc-status').className = 'svc-status ' + (lmOnline ? 'online' : 'offline');
    lmCard.querySelector('.svc-status').textContent = lmOnline ? t('status.connected') : t('status.unavailable');
    const provName = prov.name || lm.model || 'AI Provider';
    document.getElementById('svcProviderName').textContent = provName;
    document.getElementById('svcLMDetail').textContent = `${prov.url || lm.url} — ${prov.model || lm.model}`;

    // SearXNG
    const sxOnline = sx.status === 'connected';
    sxCard.className = 'service-card ' + (sx.enabled ? (sxOnline ? 'online' : 'offline') : '');
    const sxStatusEl = sxCard.querySelector('.svc-status');
    if (!sx.enabled) {
      sxStatusEl.className = 'svc-status disabled';
      sxStatusEl.textContent = t('status.disabled');
    } else {
      sxStatusEl.className = 'svc-status ' + (sxOnline ? 'online' : 'offline');
      sxStatusEl.textContent = sxOnline ? t('status.connected') : t('status.unavailable');
    }
    document.getElementById('svcSXDetail').textContent = sx.url;

    // Memory
    memCard.className = 'service-card ' + (mem.enabled ? 'online' : '');
    const memStatusEl = memCard.querySelector('.svc-status');
    if (mem.enabled) {
      memStatusEl.className = 'svc-status online';
      memStatusEl.textContent = mem.auto_extract ? t('status.activeAutoExtract') : t('status.active');
    } else {
      memStatusEl.className = 'svc-status disabled';
      memStatusEl.textContent = t('status.disabled');
    }
    document.getElementById('svcMemDetail').textContent = t('status.memoriesStored', { count: info.stats.total_memories });

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

    // Endpoints table (hidden by default, loaded for toggle)
    const table = document.getElementById('endpointsTable');
    table.innerHTML = info.endpoints.map(ep => `
      <div class="ep-row">
        <span class="ep-method ${ep.method.toLowerCase()}">${escapeHtml(ep.method)}</span>
        <span class="ep-path">${escapeHtml(ep.path)}</span>
        <span class="ep-desc">${escapeHtml(ep.description)}</span>
      </div>
    `).join('');

  } catch (e) {
    toast(t('toast.infoError', { msg: e.message }), true);
  }
}

function refreshInfo() {
  loadSystemInfo();
  toast(t('toast.infoRefreshed'));
}

function toggleEndpoints() {
  const table = document.getElementById('endpointsTable');
  const arrow = document.getElementById('epToggleArrow');
  if (table.style.display === 'none') {
    table.style.display = '';
    arrow.classList.add('open');
  } else {
    table.style.display = 'none';
    arrow.classList.remove('open');
  }
}

// ══════════════════════════════════════════════════
// STATISTICS TAB
// ══════════════════════════════════════════════════

const CHART_COLORS = [
  '#4f8cff', '#2ecc71', '#e74c3c', '#f1c40f', '#9b59b6',
  '#1abc9c', '#e67e22', '#3498db', '#e84393', '#00cec9',
  '#fd79a8', '#6c5ce7', '#00b894', '#fdcb6e',
];

function _drawPieChart(canvas, data, colors) {
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const size = Math.min(canvas.parentElement.clientWidth - 40, 280);
  canvas.width = size * dpr;
  canvas.height = size * dpr;
  canvas.style.width = size + 'px';
  canvas.style.height = size + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const total = data.reduce((s, d) => s + d.value, 0);
  if (total === 0) {
    ctx.fillStyle = '#7a7e92';
    ctx.font = '14px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(t('stats.noData'), size / 2, size / 2);
    return;
  }
  const cx = size / 2, cy = size / 2, r = (size / 2) - 10;
  let startAngle = -Math.PI / 2;

  data.forEach((d, i) => {
    const sliceAngle = (d.value / total) * 2 * Math.PI;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, startAngle, startAngle + sliceAngle);
    ctx.closePath();
    ctx.fillStyle = colors[i % colors.length];
    ctx.fill();

    // Percentage label
    if (d.value / total > 0.05) {
      const midAngle = startAngle + sliceAngle / 2;
      const lx = cx + (r * 0.65) * Math.cos(midAngle);
      const ly = cy + (r * 0.65) * Math.sin(midAngle);
      ctx.fillStyle = '#fff';
      ctx.font = 'bold 12px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(Math.round(d.value / total * 100) + '%', lx, ly);
    }
    startAngle += sliceAngle;
  });

  // Donut hole
  ctx.beginPath();
  ctx.arc(cx, cy, r * 0.45, 0, Math.PI * 2);
  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--card').trim() || '#181b25';
  ctx.fill();
}

function _drawBarChart(canvas, labels, values, color) {
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.parentElement.clientWidth - 44;
  const h = 180;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = w + 'px';
  canvas.style.height = h + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  if (!values.length) {
    ctx.fillStyle = '#7a7e92';
    ctx.font = '14px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(t('stats.noData'), w / 2, h / 2);
    return;
  }

  const maxVal = Math.max(...values, 1);
  const barW = Math.max(4, Math.min(30, (w - 40) / values.length - 2));
  const gap = Math.max(1, ((w - 40) - barW * values.length) / Math.max(values.length - 1, 1));
  const chartH = h - 34;
  const startX = 30;

  // Grid lines
  ctx.strokeStyle = 'rgba(122,126,146,.15)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = 4 + (chartH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(startX, y);
    ctx.lineTo(w, y);
    ctx.stroke();
    ctx.fillStyle = '#7a7e92';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(Math.round(maxVal - (maxVal / 4) * i), startX - 4, y + 3);
  }

  // Bars
  values.forEach((v, i) => {
    const barH = (v / maxVal) * chartH;
    const x = startX + i * (barW + gap);
    const y = 4 + chartH - barH;
    ctx.fillStyle = color || '#4f8cff';
    ctx.beginPath();
    const radius = Math.min(3, barW / 2);
    ctx.moveTo(x, y + radius);
    ctx.arcTo(x, y, x + barW, y, radius);
    ctx.arcTo(x + barW, y, x + barW, y + barH, radius);
    ctx.lineTo(x + barW, 4 + chartH);
    ctx.lineTo(x, 4 + chartH);
    ctx.closePath();
    ctx.fill();

    // Label every Nth bar
    if (labels.length <= 14 || i % Math.ceil(labels.length / 14) === 0) {
      ctx.save();
      ctx.translate(x + barW / 2, h - 2);
      ctx.rotate(-Math.PI / 4);
      ctx.fillStyle = '#7a7e92';
      ctx.font = '9px sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(labels[i].slice(5), 0, 0); // show MM-DD
      ctx.restore();
    }
  });
}

function _buildLegend(container, data, colors) {
  container.innerHTML = data.map((d, i) =>
    `<span class="chart-legend-item"><span class="chart-legend-dot" style="background:${colors[i % colors.length]}"></span>${escapeHtml(d.label)} (${d.value})</span>`
  ).join('');
}

function _formatNumber(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return String(n);
}

function _formatMs(ms) {
  if (ms >= 60000) return (ms / 60000).toFixed(1) + 'm';
  if (ms >= 1000) return (ms / 1000).toFixed(1) + 's';
  return ms + 'ms';
}

async function loadUsageStats() {
  const days = parseInt(document.getElementById('statsPeriod').value) || 30;
  try {
    const stats = await api('GET', `/api/settings/stats?days=${days}`);

    // Overview
    document.getElementById('statsRequests').textContent = _formatNumber(stats.total_requests);
    document.getElementById('statsTokens').textContent = _formatNumber(stats.tokens.total);
    document.getElementById('statsSearches').textContent = _formatNumber(stats.search_requests);
    document.getElementById('statsStream').textContent = `${_formatNumber(stats.stream_requests)} / ${_formatNumber(stats.non_stream_requests)}`;

    // Pie chart - by provider
    const provData = stats.by_provider.map(p => ({ label: p.provider_name || p.provider_id, value: p.requests }));
    _drawPieChart(document.getElementById('chartProvider'), provData, CHART_COLORS);
    _buildLegend(document.getElementById('chartProviderLegend'), provData, CHART_COLORS);

    // Pie chart - by model
    const modelData = stats.by_model.map(m => ({ label: m.model, value: m.requests }));
    _drawPieChart(document.getElementById('chartModel'), modelData, CHART_COLORS);
    _buildLegend(document.getElementById('chartModelLegend'), modelData, CHART_COLORS);

    // Daily bar chart
    const dailyLabels = stats.daily.map(d => d.day);
    const dailyValues = stats.daily.map(d => d.requests);
    _drawBarChart(document.getElementById('chartDaily'), dailyLabels, dailyValues, '#4f8cff');

    // Provider detail table
    document.getElementById('statsProviderTable').innerHTML = stats.by_provider.length
      ? stats.by_provider.map(p => `
        <div class="stats-detail-row">
          <span class="stats-detail-name">${escapeHtml(p.provider_name || p.provider_id)} <span class="stats-detail-badge">${escapeHtml(p.provider_type)}</span></span>
          <span class="stats-detail-num">${p.requests} req</span>
          <span class="stats-detail-meta">${_formatNumber(p.tokens)} tok</span>
          <span class="stats-detail-meta">${_formatMs(p.avg_response_ms)} avg</span>
        </div>`).join('')
      : `<p class="card-muted">${t('stats.noData')}</p>`;

    // Model detail table
    document.getElementById('statsModelTable').innerHTML = stats.by_model.length
      ? stats.by_model.map(m => `
        <div class="stats-detail-row">
          <span class="stats-detail-name">${escapeHtml(m.model)} <span class="stats-detail-badge">${escapeHtml(m.provider_type)}</span></span>
          <span class="stats-detail-num">${m.requests} req</span>
          <span class="stats-detail-meta">${_formatNumber(m.tokens)} tok</span>
          <span class="stats-detail-meta">${_formatMs(m.avg_response_ms)} avg</span>
        </div>`).join('')
      : `<p class="card-muted">${t('stats.noData')}</p>`;

    // User detail table
    document.getElementById('statsUserTable').innerHTML = stats.by_user.length
      ? stats.by_user.map(u => `
        <div class="stats-detail-row">
          <span class="stats-detail-name">${escapeHtml(u.user_id)}</span>
          <span class="stats-detail-num">${u.requests} req</span>
          <span class="stats-detail-meta">${_formatNumber(u.tokens)} tok</span>
        </div>`).join('')
      : `<p class="card-muted">${t('stats.noData')}</p>`;

  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

// ══════════════════════════════════════════════════
// SETTINGS
// ══════════════════════════════════════════════════

async function loadSettings() {
  try {
    const cfg = await api('GET', '/api/settings/');

    // Apply saved language
    const savedLang = cfg.language || 'en';
    if (savedLang !== currentLang) {
      setLanguage(savedLang, true);
    }
    document.getElementById('settingsLang').value = savedLang;
    document.getElementById('langSelect').value = savedLang;

    // Providers
    _allProviders = cfg.providers || [];
    _activeProviderId = cfg.active_provider || '';
    renderProvidersList();

    // SearXNG
    document.getElementById('sxEnabled').checked = cfg.searxng.enabled;
    document.getElementById('knowledgeCutoff').value = cfg.knowledge_cutoff || '';
    document.getElementById('sxUrl').value = cfg.searxng.base_url;
    document.getElementById('sxMaxResults').value = cfg.searxng.max_results;
    document.getElementById('sxMaxChars').value = cfg.searxng.max_page_chars;
    document.getElementById('sxCacheTtl').value = cfg.searxng.cache_ttl || 300;

    // Memory
    document.getElementById('memEnabled').checked = cfg.memory.enabled;
    document.getElementById('memAutoExtract').checked = cfg.memory.auto_extract;
    document.getElementById('memMax').value = cfg.memory.max_memories_per_user;

    // Performance
    const perf = cfg.performance || {};
    document.getElementById('perfHistoryLimit').value = perf.history_limit || 10;
    document.getElementById('perfParallelFetch').checked = perf.parallel_page_fetch !== false;

    // System prompt
    document.getElementById('systemPrompt').value = cfg.system_prompt || '';
  } catch (e) {
    toast(t('toast.settingsError', { msg: e.message }), true);
  }
}

async function saveSettings() {
  try {
    await api('PUT', '/api/settings/', {
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
      language: document.getElementById('settingsLang').value,
    });
    toast(t('toast.settingsSaved'));
    loadSystemInfo();
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function checkHealth() {
  try {
    const h = await api('GET', '/api/settings/health');
    const provOk = (h.provider || h.lmstudio) === 'connected';
    const provLabel = h.provider_name || 'AI';
    toast(`${provLabel}: ${h.provider || h.lmstudio} | SearXNG: ${h.searxng}`);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

// ══════════════════════════════════════════════════
// PROVIDERS MANAGEMENT
// ══════════════════════════════════════════════════

let _allProviders = [];
let _activeProviderId = '';
let _editingProviderId = null; // null = adding new, string = editing existing

const PROVIDER_TYPE_LABELS = {
  local: 'Local (LM Studio / Ollama)',
  openai: 'OpenAI',
  grok: 'Grok (xAI)',
  deepseek: 'DeepSeek',
  glm: 'GLM (Zhipu AI)',
};

const PROVIDER_TYPE_URLS = {
  local: 'http://localhost:1234',
  openai: 'https://api.openai.com',
  grok: 'https://api.x.ai/v1/chat/completions',
  deepseek: 'https://api.deepseek.com/chat/completions',
  glm: 'https://api.z.ai/api/paas/v4',
};

const PROVIDER_TYPE_NAMES = {
  local: 'LM Studio',
  openai: 'OpenAI',
  grok: 'Grok',
  deepseek: 'DeepSeek',
  glm: 'GLM',
};

function renderProvidersList() {
  const container = document.getElementById('providersList');
  if (!_allProviders.length) {
    container.innerHTML = `<p class="card-muted">${t('settings.noProviders')}</p>`;
    return;
  }
  container.innerHTML = _allProviders.map(p => {
    const isActive = p.id === _activeProviderId;
    const typeLabel = PROVIDER_TYPE_LABELS[p.type] || p.type;
    const activeClass = isActive ? ' provider-active' : '';
    return `
      <div class="provider-item${activeClass}">
        <div class="provider-info">
          <div class="provider-name">
            ${isActive ? '✅ ' : ''}${escapeHtml(p.name)}
            <span class="provider-type-badge">${escapeHtml(typeLabel)}</span>
          </div>
          <div class="provider-detail">${escapeHtml(p.base_url)} — model: ${escapeHtml(p.model || 'default')}</div>
        </div>
        <div class="provider-actions">
          ${!isActive ? `<button class="btn btn-sm btn-success" onclick="activateProvider('${escapeHtml(p.id)}')">${t('settings.activate')}</button>` : ''}
          <button class="btn btn-sm" onclick="editProvider('${escapeHtml(p.id)}')">${t('settings.edit')}</button>
          <button class="btn btn-sm btn-danger" onclick="deleteProvider('${escapeHtml(p.id)}')">${t('users.delete')}</button>
        </div>
      </div>`;
  }).join('');
}

function openAddProvider() {
  _editingProviderId = null;
  document.getElementById('providerFormTitle').textContent = t('settings.addProvider');
  document.getElementById('provType').value = 'local';
  document.getElementById('provName').value = '';
  document.getElementById('provUrl').value = 'http://localhost:1234';
  document.getElementById('provApiKey').value = '';
  document.getElementById('provModel').value = '';
  document.getElementById('provTimeout').value = 120;
  document.getElementById('provMaxTokens').value = 2048;
  document.getElementById('provTemperature').value = 0.7;
  document.getElementById('provSystemPrompt').value = '';
  const dl = document.getElementById('provModelList'); if (dl) dl.remove();
  onProvTypeChange();
  document.getElementById('providerModal').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function editProvider(id) {
  const p = _allProviders.find(x => x.id === id);
  if (!p) return;
  _editingProviderId = id;
  document.getElementById('providerFormTitle').textContent = t('settings.editProvider');
  document.getElementById('provType').value = p.type || 'local';
  document.getElementById('provName').value = p.name || '';
  document.getElementById('provUrl').value = p.base_url || '';
  document.getElementById('provApiKey').value = p.api_key || '';
  document.getElementById('provModel').value = p.model || '';
  document.getElementById('provTimeout').value = p.timeout || 120;
  document.getElementById('provMaxTokens').value = p.max_tokens || 2048;
  document.getElementById('provTemperature').value = p.temperature ?? 0.7;
  document.getElementById('provSystemPrompt').value = p.system_prompt || '';
  const dl2 = document.getElementById('provModelList'); if (dl2) dl2.remove();
  onProvTypeChange();
  document.getElementById('providerModal').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function cancelProviderForm() {
  document.getElementById('providerModal').classList.remove('open');
  document.body.style.overflow = '';
  _editingProviderId = null;
}

function onProvTypeChange() {
  const ptype = document.getElementById('provType').value;
  // Pre-fill URL if empty or still a known default
  const urlField = document.getElementById('provUrl');
  const currentUrl = urlField.value.trim();
  const defaultUrls = Object.values(PROVIDER_TYPE_URLS);
  if (!currentUrl || defaultUrls.includes(currentUrl)) {
    urlField.value = PROVIDER_TYPE_URLS[ptype] || 'http://localhost:1234';
  }
  // Pre-fill name if empty or still a known default
  const nameField = document.getElementById('provName');
  const currentName = nameField.value.trim();
  const defaultNames = Object.values(PROVIDER_TYPE_NAMES);
  if (!currentName || defaultNames.includes(currentName)) {
    nameField.value = PROVIDER_TYPE_NAMES[ptype] || '';
  }
}

async function saveProvider() {
  const data = {
    type: document.getElementById('provType').value,
    name: document.getElementById('provName').value.trim(),
    base_url: document.getElementById('provUrl').value.trim(),
    api_key: document.getElementById('provApiKey').value.trim(),
    model: document.getElementById('provModel').value.trim() || 'default',
    timeout: parseInt(document.getElementById('provTimeout').value) || 120,
    max_tokens: parseInt(document.getElementById('provMaxTokens').value) || 2048,
    temperature: parseFloat(document.getElementById('provTemperature').value) || 0.7,
    system_prompt: document.getElementById('provSystemPrompt').value.trim(),
  };
  if (!data.name) { toast(t('settings.providerNameRequired'), true); return; }
  try {
    if (_editingProviderId) {
      await api('PUT', `/api/settings/providers/${encodeURIComponent(_editingProviderId)}`, data);
      toast(t('settings.providerUpdated'));
    } else {
      await api('POST', '/api/settings/providers', data);
      toast(t('settings.providerAdded'));
    }
    cancelProviderForm();
    // Reload providers from server
    const cfg = await api('GET', '/api/settings/');
    _allProviders = cfg.providers || [];
    _activeProviderId = cfg.active_provider || '';
    renderProvidersList();
    loadSystemInfo();
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function deleteProvider(id) {
  const p = _allProviders.find(x => x.id === id);
  if (!p) return;
  if (!confirm(t('settings.confirmDeleteProvider', { name: p.name }))) return;
  try {
    await api('DELETE', `/api/settings/providers/${encodeURIComponent(id)}`);
    toast(t('settings.providerDeleted'));
    const cfg = await api('GET', '/api/settings/');
    _allProviders = cfg.providers || [];
    _activeProviderId = cfg.active_provider || '';
    renderProvidersList();
    loadSystemInfo();
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function activateProvider(id) {
  try {
    await api('PUT', `/api/settings/providers/${encodeURIComponent(id)}/activate`);
    _activeProviderId = id;
    renderProvidersList();
    toast(t('settings.providerActivated'));
    loadSystemInfo();
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function fetchProviderModels() {
  const baseUrl = document.getElementById('provUrl').value.trim();
  const apiKey = document.getElementById('provApiKey').value.trim();
  const modelInput = document.getElementById('provModel');
  const listId = 'provModelList';
  if (!baseUrl) { toast(t('settings.enterUrl'), true); return; }

  async function _populateDatalist(models) {
    let dl = document.getElementById(listId);
    if (!dl) {
      dl = document.createElement('datalist');
      dl.id = listId;
      modelInput.parentElement.appendChild(dl);
    }
    modelInput.setAttribute('list', listId);
    dl.innerHTML = models.map(m => `<option value="${escapeHtml(m.id)}">`).join('');
    if (models.length) {
      if (!modelInput.value || modelInput.value === 'default') modelInput.value = models[0].id;
      toast(t('toast.modelsReloaded'));
    } else {
      toast(t('settings.noModelsFound'), true);
    }
  }

  if (_editingProviderId) {
    try {
      const data = await api('GET', `/api/settings/providers/${encodeURIComponent(_editingProviderId)}/models`);
      _populateDatalist(data.models || []);
    } catch (e) {
      toast(t('toast.error', { msg: e.message }), true);
    }
  } else {
    const tempData = {
      type: document.getElementById('provType').value,
      name: '_temp_model_fetch',
      base_url: baseUrl,
      api_key: apiKey,
      model: 'default',
      timeout: 15,
      max_tokens: 2048,
      temperature: 0.7,
    };
    try {
      const result = await api('POST', '/api/settings/providers', tempData);
      const tempId = result.provider.id;
      try {
        const data = await api('GET', `/api/settings/providers/${encodeURIComponent(tempId)}/models`);
        _populateDatalist(data.models || []);
      } finally {
        await api('DELETE', `/api/settings/providers/${encodeURIComponent(tempId)}`);
        const cfg = await api('GET', '/api/settings/');
        _allProviders = cfg.providers || [];
        _activeProviderId = cfg.active_provider || '';
      }
    } catch (e) {
      toast(t('toast.error', { msg: e.message }), true);
    }
  }
}

// ══════════════════════════════════════════════════
// USERS + MEMORY
// ══════════════════════════════════════════════════

let _selectedUser = null;
let allMemories = [];

function catLabel(cat) {
  return t('cat.' + cat) || cat;
}

async function loadUsersTab() {
  try {
    const [cfg, memUsers] = await Promise.all([
      api('GET', '/api/settings/'),
      api('GET', '/api/memory/users'),
    ]);
    const users = cfg.users || {};
    const apiKeys = users.api_keys || {};
    document.getElementById('defaultUserInput').value = users.default_user || '';

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
      container.innerHTML = `<div class="card"><p class="card-muted">${t('users.noUsers')}</p></div>`;
      return;
    }

    container.innerHTML = names.map(name => {
      const info = userMap[name];
      const isSelected = _selectedUser === name;
      const keyHtml = info.keys.length
        ? '<code>' + escapeHtml(info.keys[0]) + '</code>'
        : `<span class="no-key">${t('users.noKey')}</span>`;
      const actionsHtml = info.keys.length
        ? `<button class="btn btn-sm" onclick="event.stopPropagation();copyUserKey('${escapeHtml(info.keys[0])}')">${t('users.copy')}</button>
           <button class="btn btn-sm btn-danger" onclick="event.stopPropagation();deleteUser('${escapeHtml(name)}')">${t('users.delete')}</button>`
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
    toast(t('toast.usersError', { msg: e.message }), true);
  }
}

async function addUser() {
  const name = document.getElementById('newUserName').value.trim();
  if (!name) { toast(t('toast.enterUsername'), true); return; }
  try {
    const result = await api('POST', '/api/settings/users', { username: name });
    document.getElementById('newUserName').value = '';
    toast(t('toast.userCreated', { name: result.username }));
    loadUsersTab();
  } catch (e) {
    if (e.message.includes('409')) toast(t('toast.userExists'), true);
    else toast(t('toast.error', { msg: e.message }), true);
  }
}

async function deleteUser(username) {
  if (!confirm(t('confirm.deleteUser', { name: username }))) return;
  try {
    try { await api('DELETE', `/api/memory/user/${encodeURIComponent(username)}`); } catch(e) { /* no memories */ }
    await api('DELETE', `/api/settings/users/${encodeURIComponent(username)}`);
    toast(t('toast.userDeleted', { name: username }));
    if (_selectedUser === username) closeUserModal();
    loadUsersTab();
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
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
    toast(t('toast.defaultUserSaved'));
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

function copyUserKey(key) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(key).then(() => toast(t('toast.apiKeyCopied'))).catch(() => _copyFallback(key, t('toast.apiKeyCopied')));
  } else {
    _copyFallback(key, t('toast.apiKeyCopied'));
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

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    if (document.getElementById('providerModal').classList.contains('open')) {
      cancelProviderForm();
    } else if (document.getElementById('userModal').classList.contains('open')) {
      closeUserModal();
    }
  }
});

// ── Memory functions ──

async function loadStats(userId) {
  try {
    const stats = await api('GET', `/api/memory/stats/${encodeURIComponent(userId)}`);
    const grid = document.getElementById('statsGrid');
    let html = `<div class="stat-card"><div class="num">${stats.total}</div><div class="lbl">${t('modal.total')}</div></div>`;
    for (const [cat, count] of Object.entries(stats.by_category || {})) {
      html += `<div class="stat-card"><div class="num">${count}</div><div class="lbl">${catLabel(cat)}</div></div>`;
    }
    grid.innerHTML = html;
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
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
    toast(t('toast.error', { msg: e.message }), true);
  }
}

function renderMemories(memories) {
  const list = document.getElementById('memList');
  if (!memories.length) {
    list.innerHTML = `<p style="color:var(--muted);font-size:.9rem">${t('status.noMemory')}</p>`;
    return;
  }
  list.innerHTML = memories.map(m => {
    const stars = '★'.repeat(m.importance) + '☆'.repeat(5 - m.importance);
    const date = new Date(m.created_at * 1000).toLocaleDateString(currentLang === 'ro' ? 'ro-RO' : 'en-US');
    const accessed = m.access_count > 0 ? t('status.accessed', { count: m.access_count }) : t('status.notAccessed');
    return `
      <div class="mem-item" data-cat="${m.category}">
        <div class="mem-content">
          <span class="mem-badge cat-${m.category}">${catLabel(m.category)}</span>
          <span class="importance-stars" title="${m.importance}/5">${stars}</span>
          <div style="margin-top:6px">${escapeHtml(m.content)}</div>
          <div class="mem-meta">
            <span>${date}</span>
            <span>${accessed}</span>
            <span>${escapeHtml(m.keywords || '-')}</span>
            <span>${m.source}</span>
          </div>
        </div>
        <button class="btn btn-danger btn-sm" onclick="deleteMemory(${m.id})">${t('users.delete')}</button>
      </div>`;
  }).join('');
}

function filterMemories(cat, btn) {
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderMemories(cat === 'all' ? allMemories : allMemories.filter(m => m.category === cat));
}

async function addMemory() {
  if (!_selectedUser) { toast(t('toast.selectUser'), true); return; }
  const content = document.getElementById('newMemContent').value;
  if (!content) { toast(t('toast.writeContent'), true); return; }
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
    toast(t('toast.memoryAdded'));
    await Promise.all([loadStats(_selectedUser), loadMemories(_selectedUser)]);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function deleteMemory(id) {
  try {
    await api('DELETE', `/api/memory/${id}`);
    toast(t('toast.memoryDeleted'));
    if (_selectedUser) await Promise.all([loadStats(_selectedUser), loadMemories(_selectedUser)]);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function clearUserMemories() {
  if (!_selectedUser) return;
  if (!confirm(t('confirm.deleteAllMemories', { name: _selectedUser }))) return;
  try {
    await api('DELETE', `/api/memory/user/${encodeURIComponent(_selectedUser)}`);
    toast(t('toast.memoriesDeleted'));
    await Promise.all([loadStats(_selectedUser), loadMemories(_selectedUser)]);
    loadUsersTab();
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function consolidateMemories() {
  if (!_selectedUser) { toast(t('toast.selectUser'), true); return; }
  toast(t('toast.consolidating'));
  try {
    await api('POST', `/api/memory/consolidate/${encodeURIComponent(_selectedUser)}`);
    toast(t('toast.consolidateComplete'));
    await Promise.all([loadStats(_selectedUser), loadMemories(_selectedUser)]);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function restartServer() {
  if (!confirm(t('confirm.restart'))) return;
  try {
    await api('POST', '/api/settings/restart');
    toast(t('toast.serverRestarting'));
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
    toast(t('toast.restartError', { msg: e.message }), true);
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
  toast(t('toast.backupDownloaded'));
}

async function uploadRestore(input) {
  const file = input.files[0];
  if (!file) return;
  if (!confirm(t('confirm.restore'))) {
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
    toast(t('toast.dbRestored'));
    setTimeout(() => location.reload(), 1500);
  } catch (e) {
    toast(t('toast.restoreError', { msg: e.message }), true);
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

    select.innerHTML = `<option value="">${t('conv.choose')}</option>`;
    for (const name of [...userSet].sort()) {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    }
    if (prev && userSet.has(prev)) select.value = prev;
    toast(t('toast.usersReloaded'));
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function loadConversations() {
  const userId = document.getElementById('convUserSelect').value;
  const sessCard = document.getElementById('convSessionsCard');

  if (!userId) {
    sessCard.style.display = 'none';
    return;
  }

  const locale = currentLang === 'ro' ? 'ro-RO' : 'en-US';
  try {
    const data = await api('GET', `/api/settings/conversations/${encodeURIComponent(userId)}`);
    const sessions = data.sessions || [];
    sessCard.style.display = '';

    const list = document.getElementById('convSessionsList');
    if (!sessions.length) {
      list.innerHTML = `<p class="card-muted">${t('conv.noConversations')}</p>`;
      return;
    }

    list.innerHTML = sessions.map(s => {
      const started = new Date(s.started_at * 1000);
      const last = new Date(s.last_at * 1000);
      const dateStr = started.toLocaleDateString(locale, { day: '2-digit', month: 'short', year: 'numeric' });
      const timeStr = started.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
      const lastTimeStr = last.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
      const duration = Math.round((s.last_at - s.started_at) / 60);
      const durationStr = duration < 1 ? '<1 min' : duration < 60 ? `${duration} min` : `${Math.floor(duration/60)}h ${duration%60}m`;
      return `
        <div class="conv-session-item" onclick="openConvSession('${escapeHtml(userId)}','${escapeHtml(s.session_id)}')">
          <div class="conv-session-info">
            <div class="conv-session-date">${dateStr} &nbsp; ${timeStr} — ${lastTimeStr}</div>
            <div class="conv-session-meta">
              <span>${s.message_count} ${t('conv.messages')}</span>
              <span>${durationStr}</span>
            </div>
          </div>
          <div class="conv-session-arrow">›</div>
        </div>`;
    }).join('');
  } catch (e) {
    toast(t('toast.convsError', { msg: e.message }), true);
  }
}

async function openConvSession(userId, sessionId) {
  _convUserId = userId;
  _convSessionId = sessionId;

  const modal = document.getElementById('convModal');
  const body = document.getElementById('convModalMessages');
  body.innerHTML = `<p class="card-muted" style="text-align:center;padding:40px 0">${t('conv.loadingMessages')}</p>`;

  modal.classList.add('open');
  document.body.style.overflow = 'hidden';

  const locale = currentLang === 'ro' ? 'ro-RO' : 'en-US';
  try {
    const data = await api('GET', `/api/settings/conversations/${encodeURIComponent(userId)}/${encodeURIComponent(sessionId)}`);
    const messages = data.messages || [];

    if (messages.length) {
      const first = new Date(messages[0].created_at * 1000);
      const last = new Date(messages[messages.length - 1].created_at * 1000);
      document.getElementById('convModalTitle').textContent =
        first.toLocaleDateString(locale, { day: '2-digit', month: 'long', year: 'numeric' });
      document.getElementById('convModalSubtitle').textContent =
        `${messages.length} ${t('conv.messages')} · ${first.toLocaleTimeString(locale, {hour:'2-digit',minute:'2-digit'})} — ${last.toLocaleTimeString(locale, {hour:'2-digit',minute:'2-digit'})}`;
    } else {
      document.getElementById('convModalTitle').textContent = t('conv.conversation');
      document.getElementById('convModalSubtitle').textContent = t('conv.noMessages');
    }

    if (!messages.length) {
      body.innerHTML = `<p class="card-muted" style="text-align:center;padding:40px 0">${t('conv.noMessages')}</p>`;
      return;
    }

    body.innerHTML = messages.map(m => {
      const time = new Date(m.created_at * 1000).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const roleLabel = m.role === 'user' ? t('status.userRole') : m.role === 'assistant' ? t('status.assistantRole') : m.role;
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
    body.innerHTML = `<p class="card-muted" style="text-align:center;padding:40px 0;color:var(--danger)">${t('toast.error', { msg: escapeHtml(e.message) })}</p>`;
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
  if (!confirm(t('confirm.deleteSession'))) return;
  try {
    await api('DELETE', `/api/settings/conversations/${encodeURIComponent(_convUserId)}/${encodeURIComponent(_convSessionId)}`);
    toast(t('toast.sessionDeleted'));
    closeConvModal();
    loadConversations();
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

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

// ══════════════════════════════════════════════════
// LOGS TAB
// ══════════════════════════════════════════════════

let _logsAutoTimer = null;

async function loadLogs() {
  const level = document.getElementById('logLevel').value;
  const search = document.getElementById('logSearch').value.trim();
  const pre = document.getElementById('logsOutput');
  try {
    const params = new URLSearchParams({ limit: 500, level });
    if (search) params.set('search', search);
    const resp = await fetch(`${API}/api/logs?${params}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const logs = await resp.json();
    if (!logs.length) {
      pre.innerHTML = `<span class="log-muted">${t('logs.noLogs')}</span>`;
      return;
    }
    pre.innerHTML = logs.map(e => {
      const lvl = escapeHtml(e.level);
      const name = escapeHtml(e.name);
      const msg = escapeHtml(e.msg);
      return `<span class="log-line"><span class="log-ts">${escapeHtml(e.ts)}</span> <span class="log-level-${lvl}">${lvl.padEnd(8)}</span> <span class="log-name">[${name}]</span> ${msg}</span>`;
    }).join('\n');
    // Auto-scroll to bottom
    pre.scrollTop = pre.scrollHeight;
  } catch (e) {
    pre.innerHTML = `<span class="log-level-ERROR">${t('logs.loadError', { msg: e.message })}</span>`;
  }
}

function clearLogsView() {
  document.getElementById('logsOutput').innerHTML = `<span class="log-muted">${t('logs.cleared')}</span>`;
}

function _startLogsAutoRefresh() {
  _stopLogsAutoRefresh();
  if (document.getElementById('logAutoRefresh')?.checked) {
    _logsAutoTimer = setInterval(loadLogs, 3000);
  }
}

function _stopLogsAutoRefresh() {
  if (_logsAutoTimer) { clearInterval(_logsAutoTimer); _logsAutoTimer = null; }
}

// Auto-refresh control
document.getElementById('logAutoRefresh')?.addEventListener('change', () => {
  if (document.getElementById('logAutoRefresh').checked) _startLogsAutoRefresh();
  else _stopLogsAutoRefresh();
});

// Search on Enter
document.getElementById('logSearch')?.addEventListener('keydown', e => {
  if (e.key === 'Enter') loadLogs();
});

// Start/stop auto-refresh when switching tabs
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    if (tab.dataset.panel === 'logs') {
      loadLogs();
      _startLogsAutoRefresh();
    } else {
      _stopLogsAutoRefresh();
    }
    if (tab.dataset.panel === 'statistics') {
      loadUsageStats();
    }
    if (tab.dataset.panel === 'skills') {
      loadSkills();
    }
  });
});


// ══════════════════════════════════════════════════
// SKILLS TAB
// ══════════════════════════════════════════════════

let _skillEditing = null; // null = creating, string = skill name being edited

async function loadSkills() {
  const el = document.getElementById('skillsList');
  if (!el) return;
  try {
    const list = await api('GET', '/api/skills/');
    if (!list.length) {
      el.innerHTML = '<div class="card"><p class="card-muted" data-i18n="skills.noSkills">No skills installed. Click "+ New Skill" to create one.</p></div>';
      applyTranslations();
      return;
    }
    el.innerHTML = list.map(s => `
      <div class="card skill-card" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;padding:14px 18px">
        <div style="flex:1;min-width:200px">
          <div style="display:flex;align-items:center;gap:8px">
            <strong>${escapeHtml(s.name)}</strong>
            ${s.generated ? '<span class="badge badge-sm" style="background:#00b894;color:#fff">generated</span>' : '<span class="badge badge-sm" style="background:#6c5ce7;color:#fff">built-in</span>'}
            ${s.disabled ? '<span class="badge badge-sm" style="background:#d63031;color:#fff">disabled</span>' : ''}
          </div>
          <div style="font-size:.82rem;color:var(--muted);margin-top:2px">${escapeHtml(s.description)}</div>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0">
          <button class="btn btn-sm btn-primary" onclick="editSkill('${escapeHtml(s.name)}')" data-i18n="skills.edit">Edit</button>
          <button class="btn btn-sm" onclick="toggleSkill('${escapeHtml(s.name)}')">${s.disabled ? '▶ Enable' : '⏸ Disable'}</button>
          ${s.generated ? `<button class="btn btn-sm btn-danger" onclick="deleteSkill('${escapeHtml(s.name)}')" data-i18n="skills.delete">Delete</button>` : ''}
        </div>
      </div>
    `).join('');
    applyTranslations();
  } catch (e) {
    el.innerHTML = `<div class="card"><p style="color:var(--danger)">Error loading skills: ${escapeHtml(e.message)}</p></div>`;
  }
}

async function openCreateSkill() {
  _skillEditing = null;
  document.getElementById('skillModalTitle').textContent = t('skills.createSkill') || 'Create Skill';
  document.getElementById('skillModalSubtitle').textContent = t('skills.createDesc') || 'Create a new custom skill';
  document.getElementById('skillNameSection').style.display = '';
  document.getElementById('skillEditName').value = '';
  document.getElementById('skillTestOutput').style.display = 'none';

  // Load template
  try {
    const tpl = await api('GET', '/api/skills/template');
    document.getElementById('skillEditSource').value = tpl.source || '';
  } catch {
    document.getElementById('skillEditSource').value = '';
  }
  document.getElementById('skillModal').classList.add('open');
}

async function editSkill(name) {
  _skillEditing = name;
  document.getElementById('skillModalTitle').textContent = t('skills.editSkill') || 'Edit Skill';
  document.getElementById('skillModalSubtitle').textContent = name;
  document.getElementById('skillNameSection').style.display = 'none';
  document.getElementById('skillTestOutput').style.display = 'none';

  try {
    const data = await api('GET', `/api/skills/${encodeURIComponent(name)}`);
    document.getElementById('skillEditSource').value = data.source || '';
  } catch (e) {
    toast('Error: ' + e.message, true);
    return;
  }
  document.getElementById('skillModal').classList.add('open');
}

function closeSkillModal() {
  document.getElementById('skillModal').classList.remove('open');
  _skillEditing = null;
}

async function saveSkillEdit() {
  const source = document.getElementById('skillEditSource').value;
  try {
    if (_skillEditing) {
      await api('PATCH', `/api/skills/${encodeURIComponent(_skillEditing)}`, { source });
      toast(t('skills.updated') || 'Skill updated');
    } else {
      const name = document.getElementById('skillEditName').value.trim();
      if (!name) { toast('Enter a skill name', true); return; }
      await api('POST', '/api/skills/', { name, source });
      toast(t('skills.created') || 'Skill created');
    }
    closeSkillModal();
    loadSkills();
  } catch (e) {
    toast('Error: ' + e.message, true);
  }
}

async function toggleSkill(name) {
  try {
    await api('POST', `/api/skills/${encodeURIComponent(name)}/toggle`);
    loadSkills();
  } catch (e) {
    toast('Error: ' + e.message, true);
  }
}

async function deleteSkill(name) {
  if (!confirm(`Delete skill "${name}"?`)) return;
  try {
    await api('DELETE', `/api/skills/${encodeURIComponent(name)}`);
    toast(t('skills.deleted') || 'Skill deleted');
    loadSkills();
  } catch (e) {
    toast('Error: ' + e.message, true);
  }
}

async function reloadSkills() {
  try {
    const res = await api('POST', '/api/skills/reload');
    toast(`${res.count} skills loaded`);
    loadSkills();
  } catch (e) {
    toast('Error: ' + e.message, true);
  }
}

async function testSkill() {
  const name = _skillEditing;
  if (!name) { toast('Save the skill first before testing', true); return; }
  const outputEl = document.getElementById('skillTestOutput');
  let inputData = {};
  try {
    const raw = document.getElementById('skillTestInput').value.trim();
    if (raw) inputData = JSON.parse(raw);
  } catch {
    toast('Invalid JSON in test input', true);
    return;
  }
  outputEl.style.display = 'block';
  outputEl.textContent = 'Running...';
  try {
    const result = await api('POST', `/api/skills/${encodeURIComponent(name)}/test`, { input_data: inputData });
    outputEl.textContent = JSON.stringify(result, null, 2);
    outputEl.style.color = result.success ? 'var(--success)' : 'var(--danger)';
  } catch (e) {
    outputEl.textContent = 'Error: ' + e.message;
    outputEl.style.color = 'var(--danger)';
  }
}
