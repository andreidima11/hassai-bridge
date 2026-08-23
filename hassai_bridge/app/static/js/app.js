// ── HASSAI Bridge v2 — Frontend ──

const API = (typeof window.HASSAI_BASE === "string" ? window.HASSAI_BASE : "").replace(/\/$/, "");

/** API VERSION is already `v0.2.x`; avoid double `v` in the footer. */
function formatAppVersion(version) {
  const raw = String(version || "").trim();
  if (!raw) return "—";
  return /^v/i.test(raw) ? raw : `v${raw}`;
}

(function syncHaThemeFromParent() {
  const map = [
    ['--primary-background-color', '--bg'],
    ['--primary-background-color', '--bg2'],
    ['--card-background-color', '--card'],
    ['--primary-text-color', '--text'],
    ['--secondary-text-color', '--muted'],
    ['--divider-color', '--border'],
  ];
  try {
    const parentRoot = window.parent?.document?.documentElement;
    if (!parentRoot || parentRoot === document.documentElement) return;
    const ps = getComputedStyle(parentRoot);
    for (const [src, dst] of map) {
      const val = ps.getPropertyValue(src).trim();
      if (val) document.documentElement.style.setProperty(dst, val);
    }
  } catch {
    /* unavailable */
  }
})();

(function ensureFreshBuild() {
  const local = typeof window.HASSAI_BUILD === "string" ? window.HASSAI_BUILD : "";
  if (!local) return;
  fetch(API + "/api/build")
    .then((r) => r.json())
    .then((d) => {
      if (!d || !d.build || d.build === local) return;
      const u = new URL(location.href);
      if (u.searchParams.get("_b") === d.build) return;
      u.searchParams.set("_b", d.build);
      location.replace(u.href);
    })
    .catch(() => {});
})();

// ── Tabs ──
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.container > .panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    const panelId = tab.dataset.panel;
    document.getElementById(panelId).classList.add('active');
    if (panelId === 'statistics') loadUsageStats();
    if (panelId === 'logs') { loadLogs(); _startLogsAutoRefresh(); }
    if (panelId === 'skills') loadSkills();
    if (panelId === 'conversations') refreshConvUsers();
    if (panelId === 'memories') refreshMemTabUsers();
    if (panelId === 'users') loadUsersTab();
  });
});

function switchToTab(panelId) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.container > .panel').forEach(p => p.classList.remove('active'));
  const tab = document.querySelector(`.tab[data-panel="${panelId}"]`);
  if (tab) tab.classList.add('active');
  const panel = document.getElementById(panelId);
  if (panel) panel.classList.add('active');
  if (panelId === 'statistics') loadUsageStats();
  if (panelId === 'logs') { loadLogs(); _startLogsAutoRefresh(); }
  if (panelId === 'skills') loadSkills();
  if (panelId === 'conversations') refreshConvUsers();
  if (panelId === 'memories') refreshMemTabUsers();
  if (panelId === 'users') loadUsersTab();
}

// ── Settings sub-tabs (used in both Settings and Statistics) ──
document.querySelectorAll('.settings-tab').forEach(stab => {
  stab.addEventListener('click', () => {
    const parent = stab.closest('.panel') || stab.parentElement.parentElement;
    parent.querySelectorAll('.settings-tab').forEach(s => s.classList.remove('active'));
    parent.querySelectorAll('.settings-subpanel').forEach(p => p.classList.remove('active'));
    stab.classList.add('active');
    document.getElementById(stab.dataset.stab).classList.add('active');
    if (stab.dataset.stab === 'stab-stats-model' && _cachedUsageStats) {
      requestAnimationFrame(() => _renderUsageCharts(_cachedUsageStats));
    }
    if (stab.dataset.stab === 'stab-stats-server') {
      requestAnimationFrame(fitServerOverviewValues);
    }
  });
});

// ── Toast ──
function toast(msg, isError = false) {
  const el = document.getElementById('toast');
  if (!el) {
    console.error(msg);
    return;
  }
  el.textContent = msg;
  el.className = 'toast show' + (isError ? ' error' : '');
  setTimeout(() => el.className = 'toast', 3000);
}

function setText(id, value) {
  const el = typeof id === 'string' ? document.getElementById(id) : id;
  if (el) el.textContent = value;
}

// ── API helpers ──
async function api(method, path, body = null) {
  const opts = { method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(API + path, opts);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    const detail = err.detail || `HTTP ${resp.status}`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  if (resp.status === 204) return {};
  return resp.json();
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

function formatMemKeywords(keywords) {
  const raw = String(keywords || '').trim();
  if (!raw || raw === '-') return '';
  const parts = raw.split(',').map((part) => part.trim()).filter(Boolean);
  if (!parts.length) return '';
  const shown = parts.slice(0, 10);
  const extra = parts.length - shown.length;
  let html = shown.map((part) => `<span class="mem-kw">${escapeHtml(part)}</span>`).join('');
  if (extra > 0) html += `<span class="mem-kw mem-kw-more">+${extra}</span>`;
  return `<div class="mem-keywords" title="${escapeHtml(raw)}">${html}</div>`;
}

function renderMemoryItem(m, checkboxClass, deleteButtonHtml = '') {
  const stars = '★'.repeat(m.importance) + '☆'.repeat(5 - m.importance);
  const date = new Date(m.created_at * 1000).toLocaleDateString(currentLang === 'ro' ? 'ro-RO' : 'en-US');
  const accessed = m.access_count > 0 ? t('status.accessed', { count: m.access_count }) : t('status.notAccessed');
  return `
      <div class="mem-item" data-cat="${m.category}">
        <input type="checkbox" class="${checkboxClass}" value="${m.id}" onclick="${checkboxClass === 'mem-cb' ? 'updateMemBulkBar()' : 'updateMemTabBulkBar()'}" style="width:18px;height:18px;cursor:pointer;flex-shrink:0;margin-top:2px">
        <div class="mem-content">
          <div class="mem-head">
            <span class="mem-badge cat-${m.category}">${catLabel(m.category)}</span>
            <span class="importance-stars" title="${m.importance}/5">${stars}</span>
          </div>
          <div class="mem-body">${escapeHtml(m.content)}</div>
          ${formatMemKeywords(m.keywords)}
          <div class="mem-meta">
            <span>${date}</span>
            <span>${accessed}</span>
            <span class="mem-source">${escapeHtml(m.source || 'auto')}</span>
          </div>
        </div>
        ${deleteButtonHtml}
      </div>`;
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

function fitTextToOneLine(el, maxPx = 32, minPx = 12) {
  if (!el || el.clientWidth === 0) return;
  el.style.whiteSpace = 'nowrap';
  let size = maxPx;
  el.style.fontSize = `${size}px`;
  while (size > minPx && el.scrollWidth > el.clientWidth) {
    size -= 1;
    el.style.fontSize = `${size}px`;
  }
}

function fitServerOverviewValues() {
  fitTextToOneLine(document.getElementById('statsServerUptime'), 34, 12);
  fitTextToOneLine(document.getElementById('statsServerVersion'), 34, 11);
  fitTextToOneLine(document.getElementById('statsServerEndpoints'), 34, 12);
  fitTextToOneLine(document.getElementById('statsServerProviders'), 34, 12);
}

function updateEndpointDisplay(ip, port) {
  const base = ip && port ? `http://${ip}:${port}` : `${window.location.protocol}//${window.location.host}`;
  const htcUrl = document.getElementById('htcApiUrl');
  if (htcUrl) htcUrl.textContent = base;
}

let _apiKeyVisible = false;
let _apiKeyValue = '';

function toggleHtcKey() {
  _apiKeyVisible = !_apiKeyVisible;
  const el = document.getElementById('htcApiKey');
  if (!el) return;
  if (_apiKeyVisible && _apiKeyValue) {
    el.textContent = _apiKeyValue;
    el.classList.remove('api-key-blur');
  } else {
    el.textContent = '••••••••••••••••';
    el.classList.add('api-key-blur');
  }
}

function copyHtcText(btn) {
  const codeEl = btn.closest('.htc-code-box').querySelector('code');
  let text = codeEl.textContent;
  if (codeEl.id === 'htcApiKey' && !_apiKeyVisible && _apiKeyValue) {
    text = _apiKeyValue;
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(() => toast(t('toast.copied'))).catch(() => _copyFallback(text));
  } else {
    _copyFallback(text);
  }
}

function copyText(elementId) {
  const el = document.getElementById(elementId);
  let text = el.textContent;
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
    const services = info.services || {};
    const stats = info.stats || {};

    const lm = services.lmstudio || {};
    const prov = services.provider || lm;
    const sx = services.searxng || {};
    const mem = services.memory || {};

    const lmCard = document.getElementById('svcLMStudio');
    const sxCard = document.getElementById('svcSearXNG');
    const memCard = document.getElementById('svcMemory');

    const lmOnline = (prov.status || lm.status) === 'connected';
    if (lmCard) {
      lmCard.className = 'service-card ' + (lmOnline ? 'online' : 'offline');
      const st = lmCard.querySelector('.svc-status');
      if (st) {
        st.removeAttribute('data-i18n');
        st.className = 'svc-status ' + (lmOnline ? 'online' : 'offline');
        st.textContent = lmOnline ? t('status.connected') : t('status.unavailable');
      }
    }
    const provName = prov.name || lm.model || 'AI Provider';
    setText('svcProviderName', provName);
    setText('svcLMDetail', `${prov.url || lm.url || ''} — ${prov.model || lm.model || ''}`);

    const sxOnline = sx.status === 'connected';
    if (sxCard) {
      sxCard.className = 'service-card ' + (sx.enabled ? (sxOnline ? 'online' : 'offline') : '');
      const sxStatusEl = sxCard.querySelector('.svc-status');
      if (sxStatusEl) {
        sxStatusEl.removeAttribute('data-i18n');
        if (!sx.enabled) {
          sxStatusEl.className = 'svc-status disabled';
          sxStatusEl.textContent = t('status.disabled');
        } else {
          sxStatusEl.className = 'svc-status ' + (sxOnline ? 'online' : 'offline');
          sxStatusEl.textContent = sxOnline ? t('status.connected') : t('status.unavailable');
        }
      }
    }
    setText('svcSXDetail', sx.url || '');

    const fr = services.frigate || {};
    const frCard = document.getElementById('svcFrigate');
    const frOnline = fr.status === 'connected';
    const frDisabled = fr.enabled === false || fr.status === 'disabled';
    if (frCard) {
      frCard.className = 'service-card ' + (frDisabled ? '' : (frOnline ? 'online' : 'offline'));
      const frStatusEl = frCard.querySelector('.svc-status');
      if (frStatusEl) {
        frStatusEl.removeAttribute('data-i18n');
        if (frDisabled) {
          frStatusEl.className = 'svc-status disabled';
          frStatusEl.textContent = t('status.disabled');
        } else {
          frStatusEl.className = 'svc-status ' + (frOnline ? 'online' : 'offline');
          const label = frOnline ? t('status.connected') : t('status.unavailable');
          frStatusEl.textContent = fr.via === 'media' && frOnline
            ? `${label} (media)`
            : label;
        }
      }
    }
    setText('svcFrigateDetail', fr.url || '');

    if (memCard) {
      memCard.className = 'service-card ' + (mem.enabled ? 'online' : '');
      const memStatusEl = memCard.querySelector('.svc-status');
      if (memStatusEl) {
        memStatusEl.removeAttribute('data-i18n');
        if (mem.enabled) {
          memStatusEl.className = 'svc-status online';
          memStatusEl.textContent = mem.auto_extract ? t('status.activeAutoExtract') : t('status.active');
        } else {
          memStatusEl.className = 'svc-status disabled';
          memStatusEl.textContent = t('status.disabled');
        }
      }
    }
    setText('svcMemDetail', t('status.memoriesStored', { count: stats.total_memories || 0 }));

    setText('statUptime', formatUptime(info.uptime_seconds));
    setText('statUsers', stats.total_users);
    setText('statMemories', stats.total_memories);
    setText('statConversations', stats.total_conversations);
    setText('statActions24h', stats.actions_last_24h);

    if (info.version) setText('versionBadge', formatAppVersion(info.version));
    if (info.api_key) _apiKeyValue = info.api_key;
    updateEndpointDisplay(info.local_ip, info.port);

    const footerVer = document.getElementById('footerVersion');
    const footerHa = document.getElementById('footerHaStatus');
    if (footerVer) footerVer.textContent = formatAppVersion(info.version);
    if (footerHa) {
      const ha = info.home_assistant || {};
      footerHa.className = '';
      if (!ha.available) {
        footerHa.textContent = t('footer.haStandalone');
        footerHa.classList.add('footer-ha-standalone');
      } else if (ha.connected) {
        footerHa.textContent = t('footer.haConnected');
        footerHa.classList.add('footer-ha-connected');
      } else {
        footerHa.textContent = t('footer.haDisconnected');
        footerHa.classList.add('footer-ha-disconnected');
      }
    }

    const table = document.getElementById('endpointsTable');
    if (table && Array.isArray(info.endpoints)) {
      table.innerHTML = info.endpoints.map(ep => `
        <div class="ep-row">
          <span class="ep-method ${escapeHtml((ep.method || '').toLowerCase())}">${escapeHtml(ep.method)}</span>
          <span class="ep-path">${escapeHtml(ep.path)}</span>
          <span class="ep-desc">${escapeHtml(ep.description)}</span>
        </div>
      `).join('');
    }
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
  if (!table) return;
  if (table.style.display === 'none') {
    table.style.display = '';
    if (arrow) arrow.classList.add('open');
  } else {
    table.style.display = 'none';
    if (arrow) arrow.classList.remove('open');
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

function _chartParentWidth(canvas, fallback = 300) {
  const parent = canvas?.parentElement;
  if (!parent) return fallback;
  const w = parent.clientWidth;
  if (w > 0) return w;
  // Hidden subpanels report 0 width — fall back to canvas markup/default size.
  return canvas.width || fallback;
}

function _drawPieChart(canvas, data, colors) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const size = Math.max(120, Math.min(_chartParentWidth(canvas) - 40, 280));
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
  const cx = size / 2;
  const cy = size / 2;
  const r = Math.max(1, (size / 2) - 10);
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
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(200, _chartParentWidth(canvas, 800) - 44);
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

let _cachedUsageStats = null;

function _renderUsageCharts(stats) {
  const provData = stats.by_provider.map(p => ({ label: p.provider_name || p.provider_id, value: p.requests }));
  _drawPieChart(document.getElementById('chartProvider'), provData, CHART_COLORS);
  _buildLegend(document.getElementById('chartProviderLegend'), provData, CHART_COLORS);

  const modelData = stats.by_model.map(m => ({ label: m.model, value: m.requests }));
  _drawPieChart(document.getElementById('chartModel'), modelData, CHART_COLORS);
  _buildLegend(document.getElementById('chartModelLegend'), modelData, CHART_COLORS);

  const dailyLabels = stats.daily.map(d => d.day);
  const dailyValues = stats.daily.map(d => d.requests);
  _drawBarChart(document.getElementById('chartDaily'), dailyLabels, dailyValues, '#4f8cff');
}

async function loadUsageStats() {
  const days = parseInt(document.getElementById('statsPeriod').value) || 30;
  try {
    const stats = await api('GET', `/api/settings/stats?days=${days}`);

    // Overview
    document.getElementById('statsRequests').textContent = _formatNumber(stats.total_requests);
    document.getElementById('statsTokens').textContent = _formatNumber(stats.tokens.total);
    document.getElementById('statsSearches').textContent = _formatNumber(stats.search_requests);

    // Skills count
    try {
      const skillsList = await api('GET', '/api/skills/');
      const enabledSkills = skillsList.filter(s => !s.disabled).length;
      document.getElementById('statsSkills').textContent = `${enabledSkills} / ${skillsList.length}`;
    } catch {
      document.getElementById('statsSkills').textContent = '—';
    }

    // Eco Mode stats
    const eco = stats.eco_mode || {};
    document.getElementById('statsEcoRequests').textContent = _formatNumber(eco.requests || 0);
    document.getElementById('statsEcoSaved').textContent = _formatNumber(eco.saved_tokens || 0);
    document.getElementById('statsEcoAvg').textContent = _formatNumber(eco.avg_completion_eco || 0);
    document.getElementById('statsNormalAvg').textContent = _formatNumber(eco.avg_completion_normal || 0);

    // Secondary Provider stats
    const sec = stats.secondary || {};
    document.getElementById('statsSecondaryRequests').textContent = _formatNumber(sec.requests || 0);
    document.getElementById('statsSecondaryTokens').textContent = _formatNumber(sec.tokens || 0);

    // Prompt cache stats (aggregate)
    const kv = stats.kv_cache || {};
    document.getElementById('statsCacheHit').textContent = _formatNumber(kv.hit_tokens || 0);
    document.getElementById('statsCacheMiss').textContent = _formatNumber(kv.miss_tokens || 0);

    const modelsWithCache = (stats.by_model || []).filter(
      (m) => (m.cache_hit_tokens || 0) > 0 || (m.cache_miss_tokens || 0) > 0,
    );

    _cachedUsageStats = stats;
    _renderUsageCharts(stats);

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
      ? stats.by_model.map(m => {
        const cacheBits = [];
        if ((m.cache_hit_tokens || 0) > 0) cacheBits.push(`${t('stats.cacheHitShort')}: ${_formatNumber(m.cache_hit_tokens)}`);
        if ((m.cache_miss_tokens || 0) > 0) cacheBits.push(`${t('stats.cacheMissShort')}: ${_formatNumber(m.cache_miss_tokens)}`);
        const cacheMeta = cacheBits.length ? `<span class="stats-detail-meta">${cacheBits.join(' · ')}</span>` : '';
        return `
        <div class="stats-detail-row">
          <span class="stats-detail-name">${escapeHtml(m.model)} <span class="stats-detail-badge">${escapeHtml(m.provider_type)}</span></span>
          <span class="stats-detail-num">${m.requests} req</span>
          <span class="stats-detail-meta">${_formatNumber(m.tokens)} tok</span>
          <span class="stats-detail-meta">${_formatMs(m.avg_response_ms)} avg</span>
          ${cacheMeta}
        </div>`;
      }).join('')
      : `<p class="card-muted">${t('stats.noData')}</p>`;

    const cacheModelTable = document.getElementById('statsCacheModelTable');
    if (cacheModelTable) {
      cacheModelTable.innerHTML = modelsWithCache.length
        ? modelsWithCache.map(m => `
          <div class="stats-detail-row">
            <span class="stats-detail-name">${escapeHtml(m.model)}</span>
            <span class="stats-detail-meta">${t('stats.cacheHitShort')}: ${_formatNumber(m.cache_hit_tokens || 0)}</span>
            <span class="stats-detail-meta">${t('stats.cacheMissShort')}: ${_formatNumber(m.cache_miss_tokens || 0)}</span>
          </div>`).join('')
        : `<p class="card-muted">${t('stats.noCacheData')}</p>`;
    }

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
  // Load sub-tab data
  loadStatsMemory();
  loadStatsSkills();
  loadStatsServer();
}

// ══════════════════════════════════════════════════
// SETTINGS
// ══════════════════════════════════════════════════

let _haAgentPromptDefault = '';
let _haToolCategoryKeys = [];

async function loadHaToolCategories() {
  if (_haToolCategoryKeys.length) return _haToolCategoryKeys;
  try {
    const data = await api('GET', '/api/settings/ha-tool-categories');
    _haToolCategoryKeys = Object.keys(data.categories || {});
  } catch {
    _haToolCategoryKeys = [
      'entities', 'control', 'registry', 'automations', 'integrations',
      'dashboards', 'config_files', 'diagnostics', 'backups', 'addons',
      'updates', 'restart', 'network', 'upload', 'zigbee',
    ];
  }
  return _haToolCategoryKeys;
}

function renderHaToolAccess(cfg) {
  const list = document.getElementById('haToolAccessList');
  if (!list) return;
  const flags = cfg.ha_tools || {};
  const keys = _haToolCategoryKeys.length ? _haToolCategoryKeys : Object.keys(flags);
  if (!keys.length) return;
  list.innerHTML = keys.map((key) => {
    const label = t(`settings.haTools.${key}`) || key;
    const on = flags[key] !== false;
    return `<div class="toggle-row" style="margin-bottom:10px">
      <span>${label}</span>
      <label class="toggle"><input type="checkbox" data-ha-tool="${key}" ${on ? 'checked' : ''}><span class="slider"></span></label>
    </div>`;
  }).join('');
}

function collectHaTools() {
  const out = {};
  document.querySelectorAll('[data-ha-tool]').forEach((el) => {
    out[el.dataset.haTool] = el.checked;
  });
  return out;
}

let _bridgeToolGroupKeys = [];

async function loadBridgeToolGroups() {
  if (_bridgeToolGroupKeys.length) return _bridgeToolGroupKeys;
  try {
    const data = await api('GET', '/api/settings/bridge-tool-groups');
    _bridgeToolGroupKeys = Object.keys(data.groups || {});
  } catch {
    _bridgeToolGroupKeys = ['memory', 'status', 'control'];
  }
  return _bridgeToolGroupKeys;
}

function renderBridgeToolAccess(cfg) {
  const list = document.getElementById('bridgeToolAccessList');
  if (!list) return;
  const flags = cfg.bridge_tools || {};
  const keys = _bridgeToolGroupKeys.length ? _bridgeToolGroupKeys : Object.keys(flags);
  if (!keys.length) return;
  list.innerHTML = keys.map((key) => {
    const label = t(`settings.bridgeTools.${key}`) || key;
    const on = flags[key] !== false;
    return `<div class="toggle-row" style="margin-bottom:10px">
      <span>${label}</span>
      <label class="toggle"><input type="checkbox" data-bridge-tool="${key}" ${on ? 'checked' : ''}><span class="slider"></span></label>
    </div>`;
  }).join('');
}

function collectBridgeTools() {
  const out = {};
  document.querySelectorAll('[data-bridge-tool]').forEach((el) => {
    out[el.dataset.bridgeTool] = el.checked;
  });
  return out;
}

async function loadHaAgentPromptDefault() {
  if (_haAgentPromptDefault) return _haAgentPromptDefault;
  try {
    const data = await api('GET', '/api/settings/ha-agent-prompt-default');
    _haAgentPromptDefault = data.prompt || '';
  } catch {
    _haAgentPromptDefault = '';
  }
  return _haAgentPromptDefault;
}

async function resetHaAgentPrompt() {
  const def = await loadHaAgentPromptDefault();
  document.getElementById('haAgentPrompt').value = def;
}

async function loadSettings() {
  try {
    const cfg = await api('GET', '/api/settings/');

    // Apply saved language (also persist so the chat page can read it)
    const savedLang = cfg.language || 'en';
    setLanguage(savedLang, true);
    const langEl = document.getElementById('settingsLang');
    if (langEl) langEl.value = savedLang;
    const topLang = document.getElementById('langSelect');
    if (topLang) topLang.value = savedLang;
    const dynEl = document.getElementById('settingsDynamicGreetings');
    if (dynEl) dynEl.checked = cfg.dynamic_greetings !== false;

    // Providers
    _allProviders = cfg.providers || [];
    _activeProviderId = cfg.active_provider || '';
    _allSecondaryProviders = cfg.secondary_providers || [];
    await loadProviderPresets();
    renderProvidersList();
    renderSecondaryProvidersList();
    await loadRouting();

    // SearXNG
    document.getElementById('sxEnabled').checked = cfg.searxng.enabled;
    document.getElementById('knowledgeCutoff').value = cfg.knowledge_cutoff || '';
    document.getElementById('sxUrl').value = cfg.searxng.base_url;
    document.getElementById('sxMaxResults').value = cfg.searxng.max_results;
    document.getElementById('sxMaxChars').value = cfg.searxng.max_page_chars;
    document.getElementById('sxCacheTtl').value = cfg.searxng.cache_ttl || 300;

    // Frigate
    const fr = cfg.frigate || {};
    const frEn = document.getElementById('frigateEnabled');
    if (frEn) frEn.checked = fr.enabled !== false;
    const frUrl = document.getElementById('frigateUrl');
    if (frUrl) frUrl.value = fr.base_url || 'http://ccab4aaf-frigate:5000';
    const frTo = document.getElementById('frigateTimeout');
    if (frTo) frTo.value = fr.timeout ?? 12;

    // Voice
    const voice = cfg.voice || {};
    const vEn = document.getElementById('voiceEnabled');
    if (vEn) vEn.checked = voice.enabled === true;
    const vKey = document.getElementById('voiceKey');
    // Never echo the stored key back; blank means "keep it".
    if (vKey) vKey.placeholder = voice.google_api_key ? '•••••••• (saved)' : 'AIza…';
    const vLang = document.getElementById('voiceLanguage');
    if (vLang) vLang.value = voice.language || 'ro-RO';
    const vRate = document.getElementById('voiceRate');
    if (vRate) vRate.value = voice.speaking_rate ?? 1;
    const vMax = document.getElementById('voiceMaxChars');
    if (vMax) vMax.value = voice.max_reply_chars ?? 800;
    const vAuto = document.getElementById('voiceAutoplay');
    if (vAuto) vAuto.checked = voice.autoplay !== false;
    const vControls = document.getElementById('voiceControls');
    if (vControls) {
      const c = voice.controls || 'both';
      vControls.value = ['both', 'mic', 'conversation'].includes(c) ? c : 'both';
    }
    const localStt = voice.local_stt || {};
    const localTts = voice.local_tts || {};
    setVoiceEngineValue('voiceSttEngine', voice.stt_engine);
    setVoiceEngineValue('voiceTtsEngine', voice.tts_engine);
    const vSttUrl = document.getElementById('voiceLocalSttUrl');
    if (vSttUrl) vSttUrl.value = localStt.url || '';
    const vSttModel = document.getElementById('voiceLocalSttModel');
    if (vSttModel) vSttModel.value = localStt.model || '';
    const vTtsUrl = document.getElementById('voiceLocalTtsUrl');
    if (vTtsUrl) vTtsUrl.value = localTts.url || '';
    const vTtsVoice = document.getElementById('voiceLocalTtsVoice');
    if (vTtsVoice) vTtsVoice.value = localTts.voice || '';
    const vLocalTimeout = document.getElementById('voiceLocalTimeout');
    if (vLocalTimeout) vLocalTimeout.value = localStt.timeout ?? localTts.timeout ?? 60;
    bindVoiceEngineToggles();
    renderVoiceEngineSections();
    await loadVoiceVoices(voice.voice || 'Kore');
    renderVoiceMicStatus();
    if (vLang && !vLang.dataset.bound) {
      vLang.dataset.bound = '1';
      vLang.addEventListener('change', () => loadVoiceVoices(document.getElementById('voiceVoice')?.value));
    }

    // Memory
    document.getElementById('memEnabled').checked = cfg.memory.enabled;

    // Auto-consolidation
    const ac = cfg.memory.auto_consolidation || {};
    document.getElementById('acEnabled').checked = ac.enabled || false;
    document.getElementById('acSchedule').value = ac.schedule || 'daily';
    document.getElementById('acHour').value = ac.hour ?? 3;
    document.getElementById('memAutoExtract').checked = cfg.memory.auto_extract;
    document.getElementById('memMax').value = cfg.memory.max_memories_per_user;

    // Performance
    const perf = cfg.performance || {};
    document.getElementById('perfHistoryLimit').value = perf.history_limit || 10;
    document.getElementById('perfAgentRounds').value = perf.agent_max_rounds || 16;
    document.getElementById('perfParallelFetch').checked = perf.parallel_page_fetch !== false;

    // Security
    const sec = cfg.security || {};
    const _defaultEcoPrompt = 'Be concise. No filler words, no pleasantries, no sign-offs. Answer directly without restating the question. Skip explanations unless explicitly asked. Keep responses short and to the point.';
    document.getElementById('securityEcoPrompt').value = sec.eco_prompt || _defaultEcoPrompt;

    // System prompt
    document.getElementById('systemPrompt').value = cfg.system_prompt || '';
    const haDefault = await loadHaAgentPromptDefault();
    await loadHaToolCategories();
    renderHaToolAccess(cfg);
    await loadBridgeToolGroups();
    renderBridgeToolAccess(cfg);
    document.getElementById('haAgentPrompt').value = cfg.ha_agent_prompt || haDefault;
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
      frigate: {
        enabled: document.getElementById('frigateEnabled')?.checked !== false,
        base_url: (document.getElementById('frigateUrl')?.value || '').trim(),
        timeout: parseInt(document.getElementById('frigateTimeout')?.value) || 12,
      },
      memory: {
        enabled: document.getElementById('memEnabled').checked,
        auto_extract: document.getElementById('memAutoExtract').checked,
        max_memories_per_user: parseInt(document.getElementById('memMax').value),
        auto_consolidation: {
          enabled: document.getElementById('acEnabled').checked,
          schedule: document.getElementById('acSchedule').value,
          hour: parseInt(document.getElementById('acHour').value) || 3,
        },
      },
      performance: {
        history_limit: parseInt(document.getElementById('perfHistoryLimit').value),
        agent_max_rounds: parseInt(document.getElementById('perfAgentRounds').value) || 16,
        parallel_page_fetch: document.getElementById('perfParallelFetch').checked,
      },
      system_prompt: document.getElementById('systemPrompt').value,
      ha_agent_prompt: (() => {
        const raw = document.getElementById('haAgentPrompt').value;
        const def = _haAgentPromptDefault;
        if (def && raw.trim() === def.trim()) return '';
        return raw;
      })(),
      knowledge_cutoff: document.getElementById('knowledgeCutoff').value,
      language: document.getElementById('settingsLang').value,
      dynamic_greetings: document.getElementById('settingsDynamicGreetings')?.checked !== false,
      ha_tools: collectHaTools(),
      bridge_tools: collectBridgeTools(),
      voice: collectVoice(),
    });
    const vKeyInput = document.getElementById('voiceKey');
    if (vKeyInput && vKeyInput.value) {
      vKeyInput.value = '';
      vKeyInput.placeholder = '•••••••• (saved)';
    }
    toast(t('toast.settingsSaved'));
    persistLanguage(document.getElementById('settingsLang')?.value || currentLang);
    loadSystemInfo();
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function saveSecuritySettings() {
  try {
    await api('PUT', '/api/settings/', {
      security: {
        eco_prompt: document.getElementById('securityEcoPrompt').value,
      },
    });
    toast(t('toast.settingsSaved'));
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

async function testProvider(id) {
  try {
    const h = await api('GET', `/api/settings/providers/${encodeURIComponent(id)}/health`);
    const status = h.status || h.provider || 'unknown';
    const model = h.model || '';
    toast(`${status === 'connected' ? '✅' : '❌'} ${status}${model ? ' — ' + model : ''}`);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function testSecondaryProvider(id) {
  try {
    const h = await api('GET', `/api/settings/secondary-providers/${encodeURIComponent(id)}/health`);
    const status = h.status || 'unknown';
    const model = h.model || '';
    toast(`${status === 'connected' ? '✅' : '❌'} ${status}${model ? ' — ' + model : ''}`);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function testSearxng() {
  try {
    const h = await api('GET', '/api/settings/health');
    toast(`SearXNG: ${h.searxng === 'connected' ? '✅ ' + t('status.connected') : '❌ ' + t('status.unavailable')}`);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function testFrigate() {
  try {
    const h = await api('GET', '/api/settings/frigate/health');
    const ok = h.status === 'connected';
    const cams = Array.isArray(h.cameras) ? h.cameras.length : 0;
    const detail = ok
      ? `${t('status.connected')}${cams ? ` — ${cams} ${t('settings.frigateCameras')}` : ''}`
      : t('status.unavailable');
    toast(`Frigate: ${ok ? '✅' : '❌'} ${detail}${h.url ? ' (' + h.url + ')' : ''}`);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

// ══════════════════════════════════════════════════
// VOICE
// ══════════════════════════════════════════════════

// Chirp 3: HD speakers — used until the live list loads (needs a saved key).
const VOICE_FALLBACK_SPEAKERS = [
  'Achernar', 'Achird', 'Algenib', 'Algieba', 'Alnilam', 'Aoede', 'Autonoe',
  'Callirrhoe', 'Charon', 'Despina', 'Enceladus', 'Erinome', 'Fenrir', 'Gacrux',
  'Iapetus', 'Kore', 'Laomedeia', 'Leda', 'Orus', 'Pulcherrima', 'Puck',
  'Rasalgethi', 'Sadachbia', 'Sadaltager', 'Schedar', 'Sulafat',
];

let _voiceTestAudio = null;

function renderVoiceOptions(speakers, selected) {
  const sel = document.getElementById('voiceVoice');
  if (!sel) return;
  const list = speakers.length ? speakers : VOICE_FALLBACK_SPEAKERS.map((s) => ({ speaker: s }));
  sel.innerHTML = list.map((v) => {
    const name = v.speaker || v;
    const gender = v.gender ? ` (${v.gender.toLowerCase()})` : '';
    return `<option value="${name}"${name === selected ? ' selected' : ''}>${name}${gender}</option>`;
  }).join('');
  if (selected && !list.some((v) => (v.speaker || v) === selected)) {
    sel.insertAdjacentHTML('afterbegin', `<option value="${selected}" selected>${selected}</option>`);
  }
}

async function loadVoiceVoices(selected) {
  const lang = document.getElementById('voiceLanguage')?.value || 'ro-RO';
  renderVoiceOptions([], selected);
  try {
    const data = await api('GET', `/api/settings/voice/voices?language=${encodeURIComponent(lang)}`);
    if (Array.isArray(data.voices) && data.voices.length) {
      renderVoiceOptions(data.voices, selected);
    }
  } catch {
    // Keep the built-in speaker list; the key may not be saved yet.
  }
}

function renderVoiceMicStatus() {
  const el = document.getElementById('voiceMicStatus');
  if (!el) return;
  const secure = window.isSecureContext;
  const hasApi = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  if (secure && hasApi) {
    el.innerHTML = `✅ ${t('settings.voiceMicOk')}`;
  } else {
    el.innerHTML = `⚠️ ${t('settings.voiceMicBlocked', { origin: location.origin })}`;
  }
}

function setVoiceEngineValue(id, value) {
  const el = document.getElementById(id);
  if (el) el.value = value === 'local' ? 'local' : 'google';
}

// Only show the server boxes for engines that are actually selected.
function renderVoiceEngineSections() {
  const stt = document.getElementById('voiceSttEngine')?.value || 'google';
  const tts = document.getElementById('voiceTtsEngine')?.value || 'google';
  const show = (id, on) => {
    const el = document.getElementById(id);
    if (el) el.style.display = on ? '' : 'none';
  };
  show('voiceLocalCard', stt === 'local' || tts === 'local');
  show('voiceLocalSttBox', stt === 'local');
  show('voiceLocalTtsBox', tts === 'local');
  show('voiceGoogleCard', stt === 'google' || tts === 'google');
}

function bindVoiceEngineToggles() {
  for (const id of ['voiceSttEngine', 'voiceTtsEngine']) {
    const el = document.getElementById(id);
    if (!el || el.dataset.bound) continue;
    el.dataset.bound = '1';
    el.addEventListener('change', renderVoiceEngineSections);
  }
}

function collectVoice() {
  const rate = parseFloat(document.getElementById('voiceRate')?.value);
  const maxChars = parseInt(document.getElementById('voiceMaxChars')?.value, 10);
  const timeout = parseInt(document.getElementById('voiceLocalTimeout')?.value, 10);
  const localTimeout = Number.isFinite(timeout) ? timeout : 60;
  return {
    enabled: document.getElementById('voiceEnabled')?.checked || false,
    provider: 'google',
    stt_engine: document.getElementById('voiceSttEngine')?.value || 'google',
    tts_engine: document.getElementById('voiceTtsEngine')?.value || 'google',
    google_api_key: document.getElementById('voiceKey')?.value || '',
    language: document.getElementById('voiceLanguage')?.value || 'ro-RO',
    voice: document.getElementById('voiceVoice')?.value || 'Kore',
    speaking_rate: Number.isFinite(rate) ? rate : 1.0,
    max_reply_chars: Number.isFinite(maxChars) ? maxChars : 800,
    autoplay: document.getElementById('voiceAutoplay')?.checked !== false,
    controls: document.getElementById('voiceControls')?.value || 'both',
    local_stt: {
      url: document.getElementById('voiceLocalSttUrl')?.value?.trim() || '',
      model: document.getElementById('voiceLocalSttModel')?.value?.trim() || '',
      timeout: localTimeout,
    },
    local_tts: {
      url: document.getElementById('voiceLocalTtsUrl')?.value?.trim() || '',
      voice: document.getElementById('voiceLocalTtsVoice')?.value?.trim() || '',
      timeout: localTimeout,
    },
  };
}

async function checkLocalVoice(kind) {
  const isStt = kind === 'stt';
  const url = document.getElementById(isStt ? 'voiceLocalSttUrl' : 'voiceLocalTtsUrl')?.value?.trim() || '';
  const out = document.getElementById(isStt ? 'voiceLocalSttResult' : 'voiceLocalTtsResult');
  if (out) {
    out.style.display = '';
    out.textContent = '…';
  }
  try {
    const data = await api('POST', '/api/settings/voice/local/check', { kind, url });
    const names = isStt
      ? (data.models || [])
      : (data.voices || []).map((v) => v.id);
    const detail = names.length ? `${data.url} — ${names.slice(0, 8).join(', ')}` : data.url || '';
    if (out) out.textContent = `✅ ${detail}`;
    if (!isStt && names.length) fillLocalVoiceList(data.voices);
  } catch (e) {
    if (out) out.textContent = `❌ ${e.message}`;
  }
}

function fillLocalVoiceList(voices) {
  const list = document.getElementById('voiceLocalTtsVoiceList');
  if (!list) return;
  list.innerHTML = '';
  for (const v of voices || []) {
    const opt = document.createElement('option');
    opt.value = v.id;
    if (v.language) opt.label = `${v.id} (${v.language})`;
    list.appendChild(opt);
  }
}

async function loadLocalVoices() {
  const url = document.getElementById('voiceLocalTtsUrl')?.value?.trim() || '';
  try {
    const data = await api('GET', `/api/settings/voice/local/voices?url=${encodeURIComponent(url)}`);
    if (data.error) {
      toast(data.error, true);
      return;
    }
    fillLocalVoiceList(data.voices);
    toast(t('settings.voiceLocalVoicesFound', { count: (data.voices || []).length }));
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function testVoice() {
  const engine = document.getElementById('voiceTtsEngine')?.value || 'google';
  const payload = engine === 'local'
    ? {
        engine: 'local',
        url: document.getElementById('voiceLocalTtsUrl')?.value?.trim() || '',
        voice: document.getElementById('voiceLocalTtsVoice')?.value?.trim() || '',
        language: document.getElementById('voiceLanguage')?.value || 'ro-RO',
      }
    : {
        engine: 'google',
        google_api_key: document.getElementById('voiceKey')?.value || '',
        language: document.getElementById('voiceLanguage')?.value || 'ro-RO',
        voice: document.getElementById('voiceVoice')?.value || 'Kore',
      };
  try {
    const data = await api('POST', '/api/settings/voice/test', payload);
    if (_voiceTestAudio) _voiceTestAudio.pause();
    _voiceTestAudio = new Audio(data.audio);
    await _voiceTestAudio.play();
    toast(`🔊 ${data.voice}`);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

// ══════════════════════════════════════════════════
// PROVIDERS MANAGEMENT
// ══════════════════════════════════════════════════

let _allProviders = [];
let _providerPresets = {};
let _allSecondaryProviders = [];
let _activeProviderId = '';
let _editingProviderId = null; // null = adding new, string = editing existing
let _editingSecProviderId = null; // null = adding new, string = editing existing

// ── Auto mode (per-message provider selection) ──

const ROUTING_ROLES = ['fast', 'deep', 'vision'];
let _routingDerived = {};

function onRoutingModeChange() {
  const on = document.getElementById('routingAuto')?.checked;
  const box = document.getElementById('routingOptions');
  if (box) box.style.display = on ? '' : 'none';
}

function _routingRoleSelect(role) {
  return document.getElementById(`routingRole${role.charAt(0).toUpperCase()}${role.slice(1)}`);
}

function _fillRoutingRoleSelect(role, chosen) {
  const sel = _routingRoleSelect(role);
  if (!sel) return;
  const auto = _routingDerived[role];
  const autoName = auto ? (_allProviders.find(p => p.id === auto)?.name || auto) : t('settings.autoRoutingNone');
  sel.innerHTML = `<option value="">${t('settings.autoRoutingAutomatic', { name: autoName })}</option>`;
  for (const p of _allProviders) {
    sel.innerHTML += `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name || p.id)}</option>`;
  }
  sel.value = chosen || '';
}

async function loadRouting() {
  let data;
  try {
    data = await api('GET', '/api/settings/routing');
  } catch {
    return;
  }
  const conf = data.routing || {};
  _routingDerived = data.roles_derived || {};
  const autoEl = document.getElementById('routingAuto');
  if (autoEl) autoEl.checked = conf.mode === 'auto';
  const profileEl = document.getElementById('routingProfile');
  if (profileEl) profileEl.value = conf.profile || 'balanced';
  const stickyEl = document.getElementById('routingSticky');
  if (stickyEl) stickyEl.checked = conf.sticky_session !== false;
  for (const role of ROUTING_ROLES) _fillRoutingRoleSelect(role, (conf.roles || {})[role]);

  const note = document.getElementById('routingPricingNote');
  if (note) {
    const p = data.pricing || {};
    const onPeak = Object.entries(p.on_peak || {}).filter(([, v]) => v).map(([k]) => k);
    const parts = [t('settings.autoRoutingPrices', { date: p.updated_at || '—' })];
    if (p.stale) parts.push(t('settings.autoRoutingPricesStale'));
    if (onPeak.length) parts.push(t('settings.autoRoutingPeakNow', { list: onPeak.join(', ') }));
    note.textContent = parts.join(' ');
  }
  onRoutingModeChange();
}

async function saveRouting() {
  const roles = {};
  for (const role of ROUTING_ROLES) roles[role] = _routingRoleSelect(role)?.value || '';
  try {
    await api('PUT', '/api/settings/', {
      routing: {
        mode: document.getElementById('routingAuto')?.checked ? 'auto' : 'manual',
        profile: document.getElementById('routingProfile')?.value || 'balanced',
        sticky_session: document.getElementById('routingSticky')?.checked !== false,
        roles,
      },
    });
    toast(t('toast.settingsSaved'));
    await loadRouting();
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

function providerTypeCapabilities(ptype) {
  return _providerPresets[ptype]?.capabilities || {};
}

function updateProviderCapabilitySections(ptype) {
  const thinkingSection = document.getElementById('provThinkingSection');
  if (thinkingSection) {
    thinkingSection.style.display = providerTypeCapabilities(ptype).thinking ? '' : 'none';
  }
}

async function loadProviderPresets() {
  try {
    _providerPresets = await api('GET', '/api/settings/providers/presets');
  } catch {
    _providerPresets = {};
  }
}

const PROVIDER_TYPE_LABELS = {
  local: 'Local (LM Studio / Ollama)',
  openai: 'OpenAI',
  grok: 'Grok (xAI)',
  deepseek: 'DeepSeek',
  glm: 'GLM (Zhipu AI)',
  gemini: 'Gemini (Google)',
  qwen: 'Qwen (DashScope)',
};

const PROVIDER_TYPE_URLS = {
  local: 'http://localhost:1234',
  openai: 'https://api.openai.com/v1',
  grok: 'https://api.x.ai/v1',
  deepseek: 'https://api.deepseek.com/v1',
  glm: 'https://api.z.ai/api/paas/v4',
  gemini: 'https://generativelanguage.googleapis.com/v1beta/openai',
  qwen: 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
};

const LEGACY_PROVIDER_URLS = [
  'https://api.openai.com',
  'https://api.openai.com/v1/chat/completions',
  'https://api.x.ai',
  'https://api.x.ai/v1/chat/completions',
  'https://api.deepseek.com',
  'https://api.deepseek.com/chat/completions',
  'https://api.deepseek.com/v1/chat/completions',
  'https://generativelanguage.googleapis.com/v1beta/openai/',
  'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
  'https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions',
  'https://dashscope.aliyuncs.com/compatible-mode/v1',
  'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
];

function normalizeProviderUrl(url) {
  return String(url || '')
    .trim()
    .replace(/\/(chat\/completions|completions|responses|models|embeddings|images\/generations|images\/edits)$/i, '');
}

const PROVIDER_TYPE_NAMES = {
  local: 'LM Studio',
  openai: 'OpenAI',
  grok: 'Grok',
  deepseek: 'DeepSeek',
  glm: 'GLM',
  gemini: 'Gemini',
  qwen: 'Qwen',
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
    const secProv = p.secondary_provider ? _allSecondaryProviders.find(x => x.id === p.secondary_provider) : null;
    const secLabel = secProv ? `<span class="provider-secondary-badge">${t('settings.secondaryShort')}: ${escapeHtml(secProv.name)}</span>` : '';
    const visProv = p.vision_provider ? _allSecondaryProviders.find(x => x.id === p.vision_provider) : null;
    const visLabel = visProv ? `<span class="provider-secondary-badge">${t('settings.visionShort')}: ${escapeHtml(visProv.name)}</span>` : '';
    const imgProv = p.image_generation_provider ? _allSecondaryProviders.find(x => x.id === p.image_generation_provider) : null;
    const imgLabel = imgProv ? `<span class="provider-secondary-badge">${t('settings.imageGenShort')}: ${escapeHtml(imgProv.name)}</span>` : '';
    return `
      <div class="provider-item${activeClass}">
        <div class="provider-info">
          <div class="provider-name">
            ${isActive ? '✅ ' : ''}${escapeHtml(p.name)}
            <span class="provider-type-badge">${escapeHtml(typeLabel)}</span>
            ${secLabel}
            ${visLabel}
            ${imgLabel}
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

function _populateSecondarySelect(excludeId) {
  const sel = document.getElementById('provSecondary');
  sel.innerHTML = `<option value="">${t('settings.noSecondary')}</option>`;
  for (const p of _allSecondaryProviders) {
    sel.innerHTML += `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)} (${PROVIDER_TYPE_LABELS[p.type] || p.type})</option>`;
  }
}

function _populateVisionSelect() {
  const sel = document.getElementById('provVision');
  sel.innerHTML = `<option value="">${t('settings.noVision')}</option>`;
  for (const p of _allSecondaryProviders) {
    sel.innerHTML += `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)} (${PROVIDER_TYPE_LABELS[p.type] || p.type})</option>`;
  }
}

function _populateImageGenSelect() {
  const sel = document.getElementById('provImageGen');
  if (!sel) return;
  sel.innerHTML = `<option value="">${t('settings.noImageGen')}</option>`;
  for (const p of _allSecondaryProviders) {
    sel.innerHTML += `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)} (${PROVIDER_TYPE_LABELS[p.type] || p.type})</option>`;
  }
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
  document.getElementById('provEcoMode').checked = false;
  _populateSecondarySelect(null);
  document.getElementById('provSecondary').value = '';
  updateProviderCapabilitySections(document.getElementById('provType').value);
  _populateVisionSelect();
  document.getElementById('provVision').value = '';
  _populateImageGenSelect();
  document.getElementById('provImageGen').value = '';
  const provPicker = document.getElementById('provModelPicker');
  _resetModelPicker(document.getElementById('provModel'), 'provModelPicker');
  const dl = document.getElementById('provModelList'); if (dl) dl.remove();
  document.getElementById('provTestSection').style.display = 'none';
  document.getElementById('provTestResult').style.display = 'none';
  onProvTypeChange();
  document.getElementById('providersMain').style.display = 'none';
  document.getElementById('providerPage').style.display = '';
}

function editProvider(id) {
  const p = _allProviders.find(x => x.id === id);
  if (!p) return;
  _editingProviderId = id;
  document.getElementById('providerFormTitle').textContent = t('settings.editProvider');
  document.getElementById('provType').value = p.type || 'local';
  document.getElementById('provName').value = p.name || '';
  document.getElementById('provUrl').value = normalizeProviderUrl(p.base_url) || p.base_url || '';
  document.getElementById('provApiKey').value = p.api_key || '';
  document.getElementById('provModel').value = p.model || '';
  document.getElementById('provTimeout').value = p.timeout || 120;
  document.getElementById('provMaxTokens').value = p.max_tokens || 2048;
  document.getElementById('provTemperature').value = p.temperature ?? 0.7;
  document.getElementById('provSystemPrompt').value = p.system_prompt || '';
  document.getElementById('provEcoMode').checked = !!p.eco_mode;
  _populateSecondarySelect(id);
  document.getElementById('provSecondary').value = p.secondary_provider || '';
  const thinkingEl = document.getElementById('provThinkingMode');
  if (thinkingEl) thinkingEl.value = p.thinking_mode || 'auto';
  updateProviderCapabilitySections(p.type || 'local');
  _populateVisionSelect();
  document.getElementById('provVision').value = p.vision_provider || '';
  _populateImageGenSelect();
  document.getElementById('provImageGen').value = p.image_generation_provider || '';
  _resetModelPicker(document.getElementById('provModel'), 'provModelPicker');
  const dl2 = document.getElementById('provModelList'); if (dl2) dl2.remove();
  document.getElementById('provTestSection').style.display = '';
  document.getElementById('provTestResult').style.display = 'none';
  onProvTypeChange();
  document.getElementById('providersMain').style.display = 'none';
  document.getElementById('providerPage').style.display = '';
}

function cancelProviderForm() {
  document.getElementById('providerPage').style.display = 'none';
  document.getElementById('providersMain').style.display = '';
  _editingProviderId = null;
}

async function testProviderFromPage() {
  if (!_editingProviderId) return;
  const res = document.getElementById('provTestResult');
  res.style.display = '';
  res.textContent = '⏳ Testing...';
  res.style.color = 'var(--muted)';
  try {
    const h = await api('GET', `/api/settings/providers/${encodeURIComponent(_editingProviderId)}/health`);
    const status = h.status || h.provider || 'unknown';
    const model = h.model || '';
    res.textContent = `${status === 'connected' ? '✅' : '❌'} ${status}${model ? ' — ' + model : ''}`;
    res.style.color = status === 'connected' ? 'var(--success)' : 'var(--danger)';
  } catch (e) {
    res.textContent = '❌ ' + e.message;
    res.style.color = 'var(--danger)';
  }
}

function onProvTypeChange() {
  const ptype = document.getElementById('provType').value;
  // Pre-fill URL if empty or still a known default
  const urlField = document.getElementById('provUrl');
  const currentUrl = urlField.value.trim();
  const defaultUrls = [...Object.values(PROVIDER_TYPE_URLS), ...LEGACY_PROVIDER_URLS];
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
  updateProviderCapabilitySections(ptype);
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
    secondary_provider: document.getElementById('provSecondary').value || '',
    thinking_mode: document.getElementById('provThinkingMode')?.value || 'auto',
    vision_provider: document.getElementById('provVision').value || '',
    image_generation_provider: document.getElementById('provImageGen').value || '',
    eco_mode: document.getElementById('provEcoMode').checked,
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
    _allSecondaryProviders = cfg.secondary_providers || [];
    renderProvidersList();
    renderSecondaryProvidersList();
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
    _allSecondaryProviders = cfg.secondary_providers || [];
    renderProvidersList();
    renderSecondaryProvidersList();
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

function _modelEntryId(model) {
  return String(model?.id || model?.model || model?.name || '').trim();
}

function _resetModelPicker(modelInput, pickerId) {
  const picker = document.getElementById(pickerId);
  if (picker) {
    picker.innerHTML = '';
    picker.style.display = 'none';
  }
  if (modelInput) modelInput.style.display = '';
}

function _populateModelPicker(models, modelInput, pickerId) {
  const picker = document.getElementById(pickerId);
  if (!picker || !modelInput) return;
  const rows = (models || []).map((m) => {
    const id = _modelEntryId(m);
    if (!id) return '';
    const label = m.name && m.name !== id ? `${id} — ${m.name}` : id;
    return `<option value="${escapeHtml(id)}">${escapeHtml(label)}</option>`;
  }).filter(Boolean);
  picker.innerHTML = rows.join('');
  if (!rows.length) {
    picker.style.display = 'none';
    modelInput.style.display = '';
    toast(t('settings.noModelsFound'), true);
    return;
  }
  picker.style.display = 'block';
  modelInput.style.display = 'none';
  picker.onchange = () => {
    modelInput.value = picker.value;
  };
  const ids = (models || []).map(_modelEntryId).filter(Boolean);
  const current = modelInput.value.trim();
  if (current && ids.includes(current)) {
    picker.value = current;
  } else {
    modelInput.value = ids[0];
    picker.value = ids[0];
  }
  toast(t('toast.modelsReloaded', { count: ids.length }));
}

async function fetchProviderModels() {
  const baseUrl = document.getElementById('provUrl').value.trim();
  const apiKey = document.getElementById('provApiKey').value.trim();
  const modelInput = document.getElementById('provModel');
  const listId = 'provModelList';
  if (!baseUrl) { toast(t('settings.enterUrl'), true); return; }

  async function _applyModels(models) {
    let dl = document.getElementById(listId);
    if (!dl) {
      dl = document.createElement('datalist');
      dl.id = listId;
      modelInput.parentElement.appendChild(dl);
    }
    modelInput.setAttribute('list', listId);
    dl.innerHTML = models.map((m) => {
      const id = _modelEntryId(m);
      return id ? `<option value="${escapeHtml(id)}">` : '';
    }).join('');
    _populateModelPicker(models, modelInput, 'provModelPicker');
  }

  if (_editingProviderId) {
    try {
      const data = await api('GET', `/api/settings/providers/${encodeURIComponent(_editingProviderId)}/models`);
      _applyModels(data.models || []);
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
        _applyModels(data.models || []);
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
// SECONDARY PROVIDERS MANAGEMENT
// ══════════════════════════════════════════════════

function renderSecondaryProvidersList() {
  const container = document.getElementById('secondaryProvidersList');
  if (!_allSecondaryProviders.length) {
    container.innerHTML = `<p class="card-muted">${t('settings.noSecondaryProviders')}</p>`;
    return;
  }
  container.innerHTML = _allSecondaryProviders.map(p => {
    const typeLabel = PROVIDER_TYPE_LABELS[p.type] || p.type;
    return `
      <div class="provider-item">
        <div class="provider-info">
          <div class="provider-name">
            🔗 ${escapeHtml(p.name)}
            <span class="provider-type-badge">${escapeHtml(typeLabel)}</span>
          </div>
          <div class="provider-detail">${escapeHtml(p.base_url)} — model: ${escapeHtml(p.model || 'default')}</div>
        </div>
        <div class="provider-actions">
          <button class="btn btn-sm" onclick="editSecondaryProvider('${escapeHtml(p.id)}')">${t('settings.edit')}</button>
          <button class="btn btn-sm btn-danger" onclick="deleteSecondaryProvider('${escapeHtml(p.id)}')">${t('users.delete')}</button>
        </div>
      </div>`;
  }).join('');
}

function openAddSecondaryProvider() {
  _editingSecProviderId = null;
  document.getElementById('secProviderFormTitle').textContent = t('settings.addSecondaryProvider');
  document.getElementById('secProvType').value = 'local';
  document.getElementById('secProvName').value = '';
  document.getElementById('secProvUrl').value = 'http://localhost:1234';
  document.getElementById('secProvApiKey').value = '';
  document.getElementById('secProvModel').value = '';
  document.getElementById('secProvTimeout').value = 120;
  document.getElementById('secProvMaxTokens').value = 2048;
  document.getElementById('secProvTemperature').value = 0.7;
  document.getElementById('secProvTestSection').style.display = 'none';
  document.getElementById('secProvTestResult').style.display = 'none';
  _resetModelPicker(document.getElementById('secProvModel'), 'secProvModelPicker');
  onSecProvTypeChange();
  document.getElementById('providersMain').style.display = 'none';
  document.getElementById('secProviderPage').style.display = '';
}

function editSecondaryProvider(id) {
  const p = _allSecondaryProviders.find(x => x.id === id);
  if (!p) return;
  _editingSecProviderId = id;
  document.getElementById('secProviderFormTitle').textContent = t('settings.editSecondaryProvider');
  document.getElementById('secProvType').value = p.type || 'local';
  document.getElementById('secProvName').value = p.name || '';
  document.getElementById('secProvUrl').value = normalizeProviderUrl(p.base_url) || p.base_url || '';
  document.getElementById('secProvApiKey').value = p.api_key || '';
  document.getElementById('secProvModel').value = p.model || '';
  document.getElementById('secProvTimeout').value = p.timeout || 120;
  document.getElementById('secProvMaxTokens').value = p.max_tokens || 2048;
  document.getElementById('secProvTemperature').value = p.temperature ?? 0.7;
  document.getElementById('secProvTestSection').style.display = '';
  document.getElementById('secProvTestResult').style.display = 'none';
  _resetModelPicker(document.getElementById('secProvModel'), 'secProvModelPicker');
  onSecProvTypeChange();
  document.getElementById('providersMain').style.display = 'none';
  document.getElementById('secProviderPage').style.display = '';
}

function cancelSecProviderForm() {
  document.getElementById('secProviderPage').style.display = 'none';
  document.getElementById('providerPage').style.display = 'none';
  document.getElementById('providersMain').style.display = '';
  _editingSecProviderId = null;
}

async function testSecProviderFromPage() {
  if (!_editingSecProviderId) return;
  const res = document.getElementById('secProvTestResult');
  res.style.display = '';
  res.textContent = '⏳ Testing...';
  res.style.color = 'var(--muted)';
  try {
    const h = await api('GET', `/api/settings/secondary-providers/${encodeURIComponent(_editingSecProviderId)}/health`);
    const status = h.status || 'unknown';
    const model = h.model || '';
    res.textContent = `${status === 'connected' ? '✅' : '❌'} ${status}${model ? ' — ' + model : ''}`;
    res.style.color = status === 'connected' ? 'var(--success)' : 'var(--danger)';
  } catch (e) {
    res.textContent = '❌ ' + e.message;
    res.style.color = 'var(--danger)';
  }
}

function onSecProvTypeChange() {
  const ptype = document.getElementById('secProvType').value;
  const urlField = document.getElementById('secProvUrl');
  const currentUrl = urlField.value.trim();
  const defaultUrls = [...Object.values(PROVIDER_TYPE_URLS), ...LEGACY_PROVIDER_URLS];
  if (!currentUrl || defaultUrls.includes(currentUrl)) {
    urlField.value = PROVIDER_TYPE_URLS[ptype] || 'http://localhost:1234';
  }
  const nameField = document.getElementById('secProvName');
  const currentName = nameField.value.trim();
  const defaultNames = Object.values(PROVIDER_TYPE_NAMES);
  if (!currentName || defaultNames.includes(currentName)) {
    nameField.value = PROVIDER_TYPE_NAMES[ptype] || '';
  }
}

async function saveSecondaryProvider() {
  const data = {
    type: document.getElementById('secProvType').value,
    name: document.getElementById('secProvName').value.trim(),
    base_url: document.getElementById('secProvUrl').value.trim(),
    api_key: document.getElementById('secProvApiKey').value.trim(),
    model: document.getElementById('secProvModel').value.trim() || 'default',
    timeout: parseInt(document.getElementById('secProvTimeout').value) || 120,
    max_tokens: parseInt(document.getElementById('secProvMaxTokens').value) || 2048,
    temperature: parseFloat(document.getElementById('secProvTemperature').value) || 0.7,
  };
  if (!data.name) { toast(t('settings.providerNameRequired'), true); return; }
  try {
    if (_editingSecProviderId) {
      await api('PUT', `/api/settings/secondary-providers/${encodeURIComponent(_editingSecProviderId)}`, data);
      toast(t('settings.secProviderUpdated'));
    } else {
      await api('POST', '/api/settings/secondary-providers', data);
      toast(t('settings.secProviderAdded'));
    }
    cancelSecProviderForm();
    const secData = await api('GET', '/api/settings/secondary-providers');
    _allSecondaryProviders = secData.secondary_providers || [];
    renderSecondaryProvidersList();
    loadSystemInfo();
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function deleteSecondaryProvider(id) {
  const p = _allSecondaryProviders.find(x => x.id === id);
  if (!p) return;
  if (!confirm(t('settings.confirmDeleteSecProvider', { name: p.name }))) return;
  try {
    await api('DELETE', `/api/settings/secondary-providers/${encodeURIComponent(id)}`);
    toast(t('settings.secProviderDeleted'));
    const secData = await api('GET', '/api/settings/secondary-providers');
    _allSecondaryProviders = secData.secondary_providers || [];
    renderSecondaryProvidersList();
    // Reload primary providers too (cleared references)
    const cfg = await api('GET', '/api/settings/');
    _allProviders = cfg.providers || [];
    renderProvidersList();
    loadSystemInfo();
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function fetchSecProviderModels() {
  const baseUrl = document.getElementById('secProvUrl').value.trim();
  const apiKey = document.getElementById('secProvApiKey').value.trim();
  const modelInput = document.getElementById('secProvModel');
  const listId = 'secProvModelList';
  if (!baseUrl) { toast(t('settings.enterUrl'), true); return; }

  async function _applyModels(models) {
    let dl = document.getElementById(listId);
    if (!dl) {
      dl = document.createElement('datalist');
      dl.id = listId;
      modelInput.parentElement.appendChild(dl);
    }
    modelInput.setAttribute('list', listId);
    dl.innerHTML = models.map((m) => {
      const id = _modelEntryId(m);
      return id ? `<option value="${escapeHtml(id)}">` : '';
    }).join('');
    _populateModelPicker(models, modelInput, 'secProvModelPicker');
  }

  if (_editingSecProviderId) {
    try {
      const data = await api('GET', `/api/settings/secondary-providers/${encodeURIComponent(_editingSecProviderId)}/models`);
      _applyModels(data.models || []);
    } catch (e) {
      toast(t('toast.error', { msg: e.message }), true);
    }
  } else {
    // Create temp secondary provider, fetch models, delete it
    const tempData = {
      type: document.getElementById('secProvType').value,
      name: '_temp_sec_model_fetch',
      base_url: baseUrl,
      api_key: apiKey,
      model: 'default',
      timeout: 15,
      max_tokens: 2048,
      temperature: 0.7,
    };
    try {
      const result = await api('POST', '/api/settings/secondary-providers', tempData);
      const tempId = result.provider.id;
      try {
        const data = await api('GET', `/api/settings/secondary-providers/${encodeURIComponent(tempId)}/models`);
        _applyModels(data.models || []);
      } finally {
        await api('DELETE', `/api/settings/secondary-providers/${encodeURIComponent(tempId)}`);
        const secData = await api('GET', '/api/settings/secondary-providers');
        _allSecondaryProviders = secData.secondary_providers || [];
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
let _userKeysMap = {};  // username -> api key
let _userModalKeyVisible = false;

function catLabel(cat) {
  return t('cat.' + cat) || cat;
}

async function loadUsersTab() {
  try {
    const [cfg, memUsers, profiles] = await Promise.all([
      api('GET', '/api/settings/'),
      api('GET', '/api/memory/users'),
      api('GET', '/api/settings/users/profiles').catch(() => ({ users: [] })),
    ]);
    const users = cfg.users || {};
    const apiKeys = users.api_keys || {};
    document.getElementById('defaultUserInput').value = users.default_user || '';

    const userMap = {};
    _userKeysMap = {};
    const profileByName = {};
    for (const p of (profiles.users || [])) {
      profileByName[p.username] = p;
      if (p.api_key) _userKeysMap[p.username] = p.api_key;
    }
    for (const [key, name] of Object.entries(apiKeys)) {
      if (!userMap[name]) userMap[name] = { keys: [], hasMemories: false, profile: profileByName[name] };
      userMap[name].keys.push(key);
      _userKeysMap[name] = key;
    }
    for (const p of (profiles.users || [])) {
      if (!userMap[p.username]) userMap[p.username] = { keys: p.api_key ? [p.api_key] : [], hasMemories: false, profile: p };
    }
    for (const u of (memUsers.users || [])) {
      if (!userMap[u]) userMap[u] = { keys: [], hasMemories: true, profile: profileByName[u] };
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
      const prof = info.profile || {};
      const subtitle = prof.source === 'home_assistant'
        ? (prof.display_name && prof.display_name !== name ? `${prof.display_name} · HA` : 'Home Assistant')
        : (info.keys.length ? 'API key' : '');
      const actionsHtml = info.keys.length
        ? `<button class="btn btn-sm btn-danger" onclick="event.stopPropagation();deleteUser('${escapeHtml(name)}')">${t('users.delete')}</button>`
        : '';
      return `
        <div class="user-card ${isSelected ? 'selected' : ''}" onclick="selectUser('${escapeHtml(name)}')">
          <div class="user-card-main">
            <div class="user-avatar">${escapeHtml(name.substring(0,2).toUpperCase())}</div>
            <div class="user-info">
              <div class="user-name">${escapeHtml(name)}</div>
              ${subtitle ? `<div class="user-meta" style="font-size:.75rem;color:var(--muted)">${escapeHtml(subtitle)}</div>` : ''}
            </div>
          </div>
          <div class="user-actions">${actionsHtml}</div>
        </div>`;
    }).join('');
  } catch (e) {
    toast(t('toast.usersError', { msg: e.message }), true);
  }
}

async function syncHaUsers() {
  try {
    const result = await api('POST', '/api/settings/users/sync-ha');
    toast(t('users.synced', { count: result.synced || 0 }));
    await loadUsersTab();
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

function openAddUserPage() {
  document.getElementById('newUserName').value = '';
  document.getElementById('usersMain').style.display = 'none';
  document.getElementById('addUserPage').style.display = '';
  applyTranslations();
  setTimeout(() => document.getElementById('newUserName').focus(), 100);
}

function closeAddUserPage() {
  document.getElementById('addUserPage').style.display = 'none';
  document.getElementById('usersMain').style.display = '';
}

async function addUser() {
  const name = document.getElementById('newUserName').value.trim();
  if (!name) { toast(t('toast.enterUsername'), true); return; }
  try {
    const result = await api('POST', '/api/settings/users', { username: name });
    document.getElementById('newUserName').value = '';
    closeAddUserPage();
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
    if (_selectedUser === username) closeUserPage();
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
  _userModalKeyVisible = false;
  document.getElementById('selectedUserName').textContent = username;

  // API key section
  const keySection = document.getElementById('userModalKeySection');
  const keyEl = document.getElementById('userModalApiKey');
  const keyToggle = document.getElementById('btnToggleUserKey');
  if (_userKeysMap[username]) {
    keySection.style.display = '';
    keyEl.textContent = '••••••••';
    keyEl.classList.add('api-key-blur');
    keyToggle.textContent = t('info.show');
  } else {
    keySection.style.display = 'none';
  }

  document.getElementById('usersMain').style.display = 'none';
  document.getElementById('userDetailPage').style.display = '';
  document.querySelectorAll('.user-card').forEach(c => {
    c.classList.toggle('selected', c.querySelector('.user-name')?.textContent === username);
  });
  await loadStats(username);
}

function toggleUserModalKey() {
  _userModalKeyVisible = !_userModalKeyVisible;
  const el = document.getElementById('userModalApiKey');
  const btn = document.getElementById('btnToggleUserKey');
  const key = _userKeysMap[_selectedUser] || '';
  if (_userModalKeyVisible && key) {
    el.textContent = key;
    el.classList.remove('api-key-blur');
    btn.textContent = t('info.hide') || 'Hide';
  } else {
    el.textContent = '••••••••';
    el.classList.add('api-key-blur');
    btn.textContent = t('info.show');
  }
}

function copyUserModalKey() {
  const key = _userKeysMap[_selectedUser] || '';
  if (!key) return;
  navigator.clipboard.writeText(key).then(() => toast(t('toast.apiKeyCopied'))).catch(() => toast(t('toast.copyFail'), true));
}

function closeUserPage() {
  _selectedUser = null;
  document.getElementById('userDetailPage').style.display = 'none';
  document.getElementById('usersMain').style.display = '';
  document.querySelectorAll('.user-card').forEach(c => c.classList.remove('selected'));
}
const closeUserModal = closeUserPage;
const deselectUser = closeUserPage;

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    if (document.getElementById('addUserPage').style.display !== 'none') closeAddUserPage();
    else if (document.getElementById('userDetailPage').style.display !== 'none') closeUserPage();
    else if (document.getElementById('addMemoryPage').style.display !== 'none') closeAddMemoryPage();
    else if (document.getElementById('skillEditorPage').style.display !== 'none') closeSkillEditor();
    else if (document.getElementById('convDetailPage').style.display !== 'none') closeConvPage();
    else if (document.getElementById('secProviderPage').style.display !== 'none') cancelSecProviderForm();
    else if (document.getElementById('providerPage').style.display !== 'none') cancelProviderForm();
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
    updateMemBulkBar();
    return;
  }
  list.innerHTML = memories.map(m => renderMemoryItem(
    m,
    'mem-cb',
    `<button class="btn btn-danger btn-sm" onclick="deleteMemory(${m.id})">${t('users.delete')}</button>`,
  )).join('');
  updateMemBulkBar();
}

function updateMemBulkBar() {
  const checked = document.querySelectorAll('.mem-cb:checked');
  const delBtn = document.getElementById('memBulkDeleteBtn');
  const selBtn = document.getElementById('memSelectAllBtn');
  const countEl = document.getElementById('memSelectedCount');
  const hasMemories = document.querySelectorAll('.mem-cb').length > 0;
  if (hasMemories) {
    selBtn.style.display = '';
    if (checked.length > 0) {
      delBtn.style.display = '';
      countEl.style.display = '';
      countEl.textContent = `${checked.length} ${t('modal.selected')}`;
    } else {
      delBtn.style.display = 'none';
      countEl.style.display = 'none';
    }
  } else {
    delBtn.style.display = 'none';
    selBtn.style.display = 'none';
    countEl.style.display = 'none';
  }
}

function toggleMemSelectAll() {
  const cbs = document.querySelectorAll('.mem-cb');
  const allChecked = [...cbs].every(cb => cb.checked);
  cbs.forEach(cb => cb.checked = !allChecked);
  updateMemBulkBar();
}

async function bulkDeleteMemories() {
  const checked = document.querySelectorAll('.mem-cb:checked');
  if (!checked.length) return;
  if (!confirm(t('confirm.bulkDeleteMemories', { count: checked.length }))) return;
  const ids = [...checked].map(cb => parseInt(cb.value));
  try {
    await api('POST', '/api/memory/bulk-delete', { ids });
    toast(t('toast.memoriesBulkDeleted', { count: ids.length }));
    if (_selectedUser) await Promise.all([loadStats(_selectedUser), loadMemories(_selectedUser)]);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
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

// ══════════════════════════════════════════════════
// MEMORIES TAB
// ══════════════════════════════════════════════════

let _memTabUser = '';
let _memTabAll = [];
let _memTabFiltered = [];
let _memTabPage = 1;
const _memTabPerPage = 5;

async function refreshMemTabUsers() {
  const select = document.getElementById('memTabUserSelect');
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
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function loadMemoriesTab() {
  _memTabUser = document.getElementById('memTabUserSelect').value;
  const statsCard = document.getElementById('memTabStatsCard');
  const addBtn = document.getElementById('memTabAddBtn');
  const listCard = document.getElementById('memTabListCard');
  if (!_memTabUser) {
    statsCard.style.display = 'none';
    addBtn.style.display = 'none';
    listCard.style.display = 'none';
    return;
  }
  statsCard.style.display = '';
  addBtn.style.display = '';
  listCard.style.display = '';
  await Promise.all([loadMemTabStats(), loadMemTabItems()]);
}

async function loadMemTabStats() {
  if (!_memTabUser) return;
  try {
    const stats = await api('GET', `/api/memory/stats/${encodeURIComponent(_memTabUser)}`);
    const grid = document.getElementById('memTabStatsGrid');
    let html = `<div class="stat-card"><div class="num">${stats.total}</div><div class="lbl">${t('modal.total')}</div></div>`;
    for (const [cat, count] of Object.entries(stats.by_category || {})) {
      html += `<div class="stat-card"><div class="num">${count}</div><div class="lbl">${catLabel(cat)}</div></div>`;
    }
    grid.innerHTML = html;
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function loadMemTabItems() {
  if (!_memTabUser) return;
  try {
    const data = await api('GET', `/api/memory/${encodeURIComponent(_memTabUser)}?limit=200`);
    _memTabAll = data.memories || [];
    renderMemTabItems(_memTabAll);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

function renderMemTabItems(memories) {
  _memTabFiltered = memories;
  const list = document.getElementById('memTabList');
  const pagEl = document.getElementById('memTabPagination');
  if (!memories.length) {
    list.innerHTML = `<p style="color:var(--muted);font-size:.9rem">${t('status.noMemory')}</p>`;
    pagEl.innerHTML = '';
    updateMemTabBulkBar();
    return;
  }
  const totalPages = Math.ceil(memories.length / _memTabPerPage);
  if (_memTabPage > totalPages) _memTabPage = totalPages;
  if (_memTabPage < 1) _memTabPage = 1;
  const start = (_memTabPage - 1) * _memTabPerPage;
  const page = memories.slice(start, start + _memTabPerPage);
  list.innerHTML = page.map(m => renderMemoryItem(m, 'mem-tab-cb')).join('');
  // Pagination controls
  if (totalPages > 1) {
    let pag = `<button onclick="memTabGoPage(${_memTabPage - 1})" ${_memTabPage === 1 ? 'disabled' : ''}>&lsaquo;</button>`;
    for (let i = 1; i <= totalPages; i++) {
      pag += `<button onclick="memTabGoPage(${i})" class="${i === _memTabPage ? 'active' : ''}">${i}</button>`;
    }
    pag += `<button onclick="memTabGoPage(${_memTabPage + 1})" ${_memTabPage === totalPages ? 'disabled' : ''}>&rsaquo;</button>`;
    pagEl.innerHTML = pag;
  } else {
    pagEl.innerHTML = '';
  }
  updateMemTabBulkBar();
}

function memTabGoPage(page) {
  _memTabPage = page;
  renderMemTabItems(_memTabFiltered);
}

function updateMemTabBulkBar() {
  const checked = document.querySelectorAll('.mem-tab-cb:checked');
  const delBtn = document.getElementById('memTabBulkDeleteBtn');
  const selBtn = document.getElementById('memTabSelectAllBtn');
  const countEl = document.getElementById('memTabSelectedCount');
  const hasMemories = document.querySelectorAll('.mem-tab-cb').length > 0;
  if (hasMemories) {
    selBtn.style.display = '';
    if (checked.length > 0) {
      delBtn.style.display = '';
      countEl.style.display = '';
      countEl.textContent = `${checked.length} ${t('modal.selected')}`;
    } else {
      delBtn.style.display = 'none';
      countEl.style.display = 'none';
    }
  } else {
    delBtn.style.display = 'none';
    selBtn.style.display = 'none';
    countEl.style.display = 'none';
  }
}

function toggleMemTabSelectAll() {
  const cbs = document.querySelectorAll('.mem-tab-cb');
  const allChecked = [...cbs].every(cb => cb.checked);
  cbs.forEach(cb => cb.checked = !allChecked);
  updateMemTabBulkBar();
}

async function bulkDeleteMemoriesTab() {
  const checked = document.querySelectorAll('.mem-tab-cb:checked');
  if (!checked.length) return;
  if (!confirm(t('confirm.bulkDeleteMemories', { count: checked.length }))) return;
  const ids = [...checked].map(cb => parseInt(cb.value));
  try {
    await api('POST', '/api/memory/bulk-delete', { ids });
    toast(t('toast.memoriesBulkDeleted', { count: ids.length }));
    await Promise.all([loadMemTabStats(), loadMemTabItems()]);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

function filterMemoriesTab(cat, btn) {
  document.querySelectorAll('.mem-tab-filter').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  _memTabPage = 1;
  renderMemTabItems(cat === 'all' ? _memTabAll : _memTabAll.filter(m => m.category === cat));
}

async function addMemoryTab() {
  if (!_memTabUser) { toast(t('toast.selectUser'), true); return; }
  const content = document.getElementById('memTabNewContent').value;
  if (!content) { toast(t('toast.writeContent'), true); return; }
  try {
    await api('POST', '/api/memory/', {
      user_id: _memTabUser,
      content,
      category: document.getElementById('memTabNewCat').value,
      keywords: document.getElementById('memTabNewKeywords').value,
      importance: parseInt(document.getElementById('memTabNewImp').value),
    });
    document.getElementById('memTabNewContent').value = '';
    document.getElementById('memTabNewKeywords').value = '';
    closeAddMemoryPage();
    toast(t('toast.memoryAdded'));
    await Promise.all([loadMemTabStats(), loadMemTabItems()]);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

function openAddMemoryPage() {
  document.getElementById('memTabNewCat').value = 'facts';
  document.getElementById('memTabNewImp').value = 3;
  document.getElementById('memTabNewContent').value = '';
  document.getElementById('memTabNewKeywords').value = '';
  document.getElementById('memoriesMain').style.display = 'none';
  document.getElementById('addMemoryPage').style.display = '';
  applyTranslations();
}

function closeAddMemoryPage() {
  document.getElementById('addMemoryPage').style.display = 'none';
  document.getElementById('memoriesMain').style.display = '';
}

async function deleteMemoryTab(id) {
  try {
    await api('DELETE', `/api/memory/${id}`);
    toast(t('toast.memoryDeleted'));
    await Promise.all([loadMemTabStats(), loadMemTabItems()]);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function clearMemoriesTab() {
  if (!_memTabUser) return;
  if (!confirm(t('confirm.deleteAllMemories', { name: _memTabUser }))) return;
  try {
    await api('DELETE', `/api/memory/user/${encodeURIComponent(_memTabUser)}`);
    toast(t('toast.memoriesDeleted'));
    await Promise.all([loadMemTabStats(), loadMemTabItems()]);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function consolidateMemoriesTab() {
  if (!_memTabUser) { toast(t('toast.selectUser'), true); return; }
  toast(t('toast.consolidating'));
  try {
    await api('POST', `/api/memory/consolidate/${encodeURIComponent(_memTabUser)}`);
    toast(t('toast.consolidateComplete'));
    await Promise.all([loadMemTabStats(), loadMemTabItems()]);
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
// BACKUP / RESTORE (Ingress-safe: blob download + chunked upload)
// ══════════════════════════════════════════════════

const _IMPORT_CHUNK = 256 * 1024; // 256KB — stays under HA Ingress body limits

function setBackupStatus(msg) {
  const el = document.getElementById('backupImportStatus');
  if (!el) return;
  if (!msg) {
    el.style.display = 'none';
    el.textContent = '';
    return;
  }
  el.style.display = '';
  el.textContent = msg;
}

async function downloadViaBlob(path, filename) {
  const resp = await fetch(API + path, { credentials: 'same-origin', cache: 'no-store' });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }
  const blob = await resp.blob();
  // Companion WebView often navigates the Ingress iframe to the blob URL (kicks you
  // out of the add-on). Prefer the File System Access API, else only use <a download>
  // when the attribute is honored; never assign location.href to the blob.
  if (typeof window.showSaveFilePicker === 'function') {
    try {
      const handle = await window.showSaveFilePicker({
        suggestedName: filename,
        types: [{ description: 'ZIP', accept: { 'application/zip': ['.zip'] } }],
      });
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      return;
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      /* fall through */
    }
  }
  const companion = /Home Assistant/i.test(navigator.userAgent || '');
  if (companion) {
    throw new Error(t('toast.exportUseBrowser'));
  }
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.rel = 'noopener';
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }
}

async function refreshAfterImport() {
  // Do NOT location.reload / location.replace — that bounces HA Ingress out of the add-on.
  try {
    await loadSettings();
  } catch (e) {
    console.warn('refreshAfterImport loadSettings', e);
  }
  try {
    if (typeof loadUsersTab === 'function') await loadUsersTab();
  } catch (e) {
    /* optional */
  }
}

async function uploadChunked(file, kind) {
  const start = await api('POST', '/api/settings/import/start', {
    size: file.size,
    filename: file.name || '',
    kind,
  });
  const uploadId = start.id;
  let offset = 0;
  while (offset < file.size) {
    const end = Math.min(offset + _IMPORT_CHUNK, file.size);
    const blob = file.slice(offset, end);
    const form = new FormData();
    form.append('id', uploadId);
    form.append('offset', String(offset));
    form.append('chunk', blob, 'chunk.bin');
    const resp = await fetch(API + '/api/settings/import/chunk', {
      method: 'POST',
      credentials: 'same-origin',
      body: form,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      const detail = err.detail || `HTTP ${resp.status}`;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    offset = end;
    const pct = Math.min(100, Math.round((offset / file.size) * 100));
    setBackupStatus(t('toast.importProgress', { pct }));
  }
  return api('POST', '/api/settings/import/finish', { id: uploadId });
}

async function downloadFullExport() {
  try {
    setBackupStatus(t('toast.fullExportStarted'));
    await downloadViaBlob('/api/settings/export', 'hassai-export.zip');
    setBackupStatus('');
    toast(t('toast.backupDownloaded'));
  } catch (e) {
    setBackupStatus('');
    toast(t('toast.restoreError', { msg: e.message }), true);
  }
}

function _looksLikeZip(file) {
  const name = String(file?.name || '').toLowerCase();
  if (name.endsWith('.zip')) return true;
  const mime = String(file?.type || '').toLowerCase();
  if (mime.includes('zip') || mime === 'application/octet-stream') return true;
  return Boolean(file?.size) && !name;
}

function onImportZipPicked(event) {
  const input = event.target;
  const file = input.files && input.files[0];
  input.value = '';
  if (file) uploadFullImportFile(file);
}

function _fmtBytes(bytes) {
  const n = Number(bytes) || 0;
  if (n >= 1048576) return `${(n / 1048576).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

async function toggleShareImport() {
  const box = document.getElementById('shareImportList');
  if (!box) return;
  if (box.style.display !== 'none') {
    box.style.display = 'none';
    return;
  }
  box.style.display = '';
  box.innerHTML = `<p class="card-muted hint">${escapeHtml(t('toast.loading'))}</p>`;
  try {
    const data = await api('GET', '/api/settings/import/share');
    const files = data.files || [];
    if (!files.length) {
      box.innerHTML = `<p class="card-muted hint">${escapeHtml(t('settings.importFromShareEmpty'))}</p>`;
      return;
    }
    box.innerHTML = files
      .map(
        (f) =>
          `<div class="btn-row" style="align-items:center;gap:8px;margin-top:6px">
             <button type="button" class="btn btn-sm btn-success" onclick="importFromShare('${escapeHtml(f.name)}')">${escapeHtml(t('settings.importFull'))}</button>
             <span class="card-muted">${escapeHtml(f.name)} · ${escapeHtml(_fmtBytes(f.size))}</span>
           </div>`,
      )
      .join('');
  } catch (e) {
    box.innerHTML = `<p class="card-muted hint">${escapeHtml(e.message)}</p>`;
  }
}

async function importFromShare(name) {
  if (!confirm(t('confirm.fullImport'))) return;
  try {
    setBackupStatus(t('toast.importProgress', { pct: 0 }));
    await api('POST', '/api/settings/import/share', { name });
    setBackupStatus('');
    toast(t('toast.fullImportDone'));
    await refreshAfterImport();
  } catch (e) {
    setBackupStatus('');
    toast(t('toast.restoreError', { msg: e.message }), true);
  }
}

async function uploadFullImportFile(file) {
  if (!file) return;
  if (!_looksLikeZip(file)) {
    toast(t('toast.restoreError', { msg: 'ZIP required' }), true);
    return;
  }
  if (!confirm(t('confirm.fullImport'))) return;
  try {
    setBackupStatus(t('toast.importProgress', { pct: 0 }));
    await uploadChunked(file, 'zip');
    setBackupStatus('');
    toast(t('toast.fullImportDone'));
    await refreshAfterImport();
  } catch (e) {
    setBackupStatus('');
    toast(t('toast.restoreError', { msg: e.message }), true);
  }
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
        <div class="conv-session-item" style="display:flex;align-items:center;gap:10px">
          <input type="checkbox" class="conv-session-cb" value="${escapeHtml(s.session_id)}" onclick="event.stopPropagation();updateConvBulkBar()" style="width:18px;height:18px;cursor:pointer;flex-shrink:0">
          <div style="flex:1;cursor:pointer" onclick="openConvSession('${escapeHtml(userId)}','${escapeHtml(s.session_id)}')">
            <div class="conv-session-date">${dateStr} &nbsp; ${timeStr} — ${lastTimeStr}</div>
            <div class="conv-session-meta">
              <span>${s.message_count} ${t('conv.messages')}</span>
              <span>${durationStr}</span>
            </div>
          </div>
          <div class="conv-session-arrow" onclick="openConvSession('${escapeHtml(userId)}','${escapeHtml(s.session_id)}')" style="cursor:pointer">›</div>
        </div>`;
    }).join('');
    updateConvBulkBar();
  } catch (e) {
    toast(t('toast.convsError', { msg: e.message }), true);
  }
}

async function openConvSession(userId, sessionId) {
  _convUserId = userId;
  _convSessionId = sessionId;

  const body = document.getElementById('convPageMsgList');
  body.innerHTML = `<p class="card-muted" style="text-align:center;padding:40px 0">${t('conv.loadingMessages')}</p>`;

  document.getElementById('convMain').style.display = 'none';
  document.getElementById('convDetailPage').style.display = '';

  const locale = currentLang === 'ro' ? 'ro-RO' : 'en-US';
  try {
    const data = await api('GET', `/api/settings/conversations/${encodeURIComponent(userId)}/${encodeURIComponent(sessionId)}`);
    const messages = data.messages || [];

    if (messages.length) {
      const first = new Date(messages[0].created_at * 1000);
      const last = new Date(messages[messages.length - 1].created_at * 1000);
      document.getElementById('convPageTitle').textContent =
        first.toLocaleDateString(locale, { day: '2-digit', month: 'long', year: 'numeric' });
      document.getElementById('convPageSubtitle').textContent =
        `${messages.length} ${t('conv.messages')} · ${first.toLocaleTimeString(locale, {hour:'2-digit',minute:'2-digit'})} — ${last.toLocaleTimeString(locale, {hour:'2-digit',minute:'2-digit'})}`;
    } else {
      document.getElementById('convPageTitle').textContent = t('conv.conversation');
      document.getElementById('convPageSubtitle').textContent = t('conv.noMessages');
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

function updateConvBulkBar() {
  const checked = document.querySelectorAll('.conv-session-cb:checked');
  const bar = document.getElementById('convBulkBar');
  const count = document.getElementById('convSelectedCount');
  if (checked.length > 0) {
    bar.style.display = 'flex';
    count.textContent = `${checked.length} ${t('conv.selected')}`;
  } else {
    bar.style.display = 'none';
  }
}

function toggleConvSelectAll() {
  const cbs = document.querySelectorAll('.conv-session-cb');
  const allChecked = [...cbs].every(cb => cb.checked);
  cbs.forEach(cb => cb.checked = !allChecked);
  updateConvBulkBar();
}

async function bulkDeleteSessions() {
  const checked = document.querySelectorAll('.conv-session-cb:checked');
  if (!checked.length) return;
  const userId = document.getElementById('convUserSelect').value;
  if (!userId) return;
  if (!confirm(t('confirm.bulkDeleteSessions', { count: checked.length }))) return;
  const sessionIds = [...checked].map(cb => cb.value);
  try {
    await api('POST', `/api/settings/conversations/${encodeURIComponent(userId)}/bulk-delete`, { session_ids: sessionIds });
    toast(t('toast.sessionsDeleted', { count: sessionIds.length }));
    loadConversations();
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

function closeConvPage() {
  document.getElementById('convDetailPage').style.display = 'none';
  document.getElementById('convMain').style.display = '';
  _convUserId = '';
  _convSessionId = '';
}
const closeConvModal = closeConvPage;

async function deleteCurrentSession() {
  if (!_convUserId || !_convSessionId) return;
  if (!confirm(t('confirm.deleteSession'))) return;
  try {
    await api('DELETE', `/api/settings/conversations/${encodeURIComponent(_convUserId)}/${encodeURIComponent(_convSessionId)}`);
    toast(t('toast.sessionDeleted'));
    closeConvPage();
    loadConversations();
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

// ── Init ──
(function wireBackToChat() {
  const link = document.getElementById('backToChatLink');
  if (link) link.href = `${API || ''}/`;
})();
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
    if (tab.dataset.panel === 'conversations') {
      refreshConvUsers();
    }
    if (tab.dataset.panel === 'memories') {
      refreshMemTabUsers();
    }
  });
});


// ══════════════════════════════════════════════════
// SKILLS TAB
// ══════════════════════════════════════════════════

let _skillEditing = null; // null = creating, string = skill name being edited

// ── Code Editor helpers ──
function _syntaxHighlight(code) {
  const esc = code.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  return esc
    .replace(/(#.*?)$/gm, '<span class="syn-comment">$1</span>')
    .replace(/(&quot;{3}|'{3})([\s\S]*?)\1/g, '<span class="syn-str">$1$2$1</span>')
    .replace(/(["'])(?:(?!\1|\\).|\\.)*?\1/g, '<span class="syn-str">$&</span>')
    .replace(/\b(def|class|if|elif|else|for|while|return|import|from|as|try|except|finally|with|raise|yield|pass|break|continue|and|or|not|in|is|lambda|async|await|global|nonlocal)\b/g, '<span class="syn-kw">$1</span>')
    .replace(/\b(print|len|range|int|str|float|list|dict|set|tuple|bool|type|isinstance|getattr|setattr|hasattr|open|super|None|True|False)\b/g, '<span class="syn-builtin">$1</span>')
    .replace(/\b(self)\b/g, '<span class="syn-self">$1</span>')
    .replace(/@[\w.]+/g, '<span class="syn-decorator">$&</span>')
    .replace(/\b(\d+\.?\d*)\b/g, '<span class="syn-number">$1</span>')
    .replace(/\b([a-zA-Z_]\w*)\s*(?=\()/g, '<span class="syn-func">$1</span>');
}

function _updateCodeEditor() {
  const ta = document.getElementById('skillEditSource');
  const hl = document.getElementById('skillHighlight');
  const ln = document.getElementById('skillLineNumbers');
  if (!ta || !hl || !ln) return;

  // Highlight
  hl.innerHTML = _syntaxHighlight(ta.value) + '\n';

  // Line numbers
  const lines = ta.value.split('\n').length;
  let nums = '';
  for (let i = 1; i <= lines; i++) nums += `<span>${i}</span>`;
  ln.innerHTML = nums;

  // Resize textarea to fit content (no internal scroll)
  ta.style.height = 'auto';
  ta.style.height = Math.max(360, ta.scrollHeight) + 'px';
}

function _syncEditorScroll() {
  const container = document.getElementById('skillEditSource').parentElement;
  const hl = document.getElementById('skillHighlight');
  const ln = document.getElementById('skillLineNumbers');
  if (!container || !hl || !ln) return;
  ln.scrollTop = container.scrollTop;
}

function _initCodeEditor() {
  const ta = document.getElementById('skillEditSource');
  if (!ta || ta._editorInit) return;
  ta._editorInit = true;
  ta.addEventListener('input', _updateCodeEditor);
  // Scroll sync on the container, not textarea
  ta.parentElement.addEventListener('scroll', _syncEditorScroll);
  ta.addEventListener('keydown', function(e) {
    if (e.key === 'Tab') {
      e.preventDefault();
      const start = this.selectionStart;
      const end = this.selectionEnd;
      this.value = this.value.substring(0, start) + '    ' + this.value.substring(end);
      this.selectionStart = this.selectionEnd = start + 4;
      _updateCodeEditor();
    }
  });
  _updateCodeEditor();
}

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
  document.getElementById('skillEditorTitle').textContent = t('skills.createSkill') || 'Create Skill';
  document.getElementById('skillEditorSubtitle').textContent = t('skills.createDesc') || 'Create a new custom skill';
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
  document.getElementById('skillsMain').style.display = 'none';
  document.getElementById('skillEditorPage').style.display = '';
  _initCodeEditor();
  _updateCodeEditor();
}

async function editSkill(name) {
  _skillEditing = name;
  document.getElementById('skillEditorTitle').textContent = t('skills.editSkill') || 'Edit Skill';
  document.getElementById('skillEditorSubtitle').textContent = name;
  document.getElementById('skillNameSection').style.display = 'none';
  document.getElementById('skillTestOutput').style.display = 'none';

  try {
    const data = await api('GET', `/api/skills/${encodeURIComponent(name)}`);
    document.getElementById('skillEditSource').value = data.source || '';
  } catch (e) {
    toast('Error: ' + e.message, true);
    return;
  }
  document.getElementById('skillsMain').style.display = 'none';
  document.getElementById('skillEditorPage').style.display = '';
  _initCodeEditor();
  _updateCodeEditor();
}

function closeSkillEditor() {
  document.getElementById('skillEditorPage').style.display = 'none';
  document.getElementById('skillsMain').style.display = '';
  _skillEditing = null;
}
const closeSkillModal = closeSkillEditor;

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
    closeSkillEditor();
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

// ══════════════════════════════════════════════════
// HOW TO CONNECT — SLIDER
// ══════════════════════════════════════════════════

let _htcIndex = 0;
const _htcTotal = 4;

function _htcUpdate() {
  document.querySelectorAll('.htc-slide').forEach((s, i) => s.classList.toggle('active', i === _htcIndex));
  document.querySelectorAll('.htc-dot').forEach((d, i) => d.classList.toggle('active', i === _htcIndex));
  document.querySelector('.htc-prev').disabled = _htcIndex === 0;
  const nextBtn = document.querySelector('.htc-next');
  nextBtn.textContent = _htcIndex === _htcTotal - 1 ? '✓' : t('htc.next');
  nextBtn.disabled = _htcIndex === _htcTotal - 1;
}

function htcNext() { if (_htcIndex < _htcTotal - 1) { _htcIndex++; _htcUpdate(); } }
function htcPrev() { if (_htcIndex > 0) { _htcIndex--; _htcUpdate(); } }
function htcGo(i) { _htcIndex = i; _htcUpdate(); }

// ══════════════════════════════════════════════════
// STATISTICS SUB-TABS DATA
// ══════════════════════════════════════════════════

let _cachedInfo = null;

async function loadStatsMemory() {
  try {
    const memUsers = await api('GET', '/api/memory/users');
    const users = memUsers.users || [];
    document.getElementById('statsMemUsers').textContent = users.length;

    // Load per-user stats
    let totalMem = 0;
    const userStats = [];
    const catAgg = {};
    for (const u of users) {
      try {
        const s = await api('GET', `/api/memory/stats/${encodeURIComponent(u)}`);
        userStats.push({ name: u, total: s.total, categories: s.by_category || {} });
        totalMem += s.total;
        for (const [cat, count] of Object.entries(s.by_category || {})) {
          catAgg[cat] = (catAgg[cat] || 0) + count;
        }
      } catch { /* skip */ }
    }

    document.getElementById('statsMemTotal').textContent = totalMem;
    // Auto-extract status
    try {
      const cfg = await api('GET', '/api/settings/');
      document.getElementById('statsMemAutoExtract').textContent = cfg.memory.auto_extract ? t('status.active') : t('status.disabled');
    } catch {
      document.getElementById('statsMemAutoExtract').textContent = '—';
    }

    // User table
    document.getElementById('statsMemoryUserTable').innerHTML = userStats.length
      ? userStats.map(u => `
        <div class="stats-detail-row">
          <span class="stats-detail-name">${escapeHtml(u.name)}</span>
          <span class="stats-detail-num">${u.total} memories</span>
        </div>`).join('')
      : `<p class="card-muted">${t('stats.noData')}</p>`;

    // Category table
    const catEntries = Object.entries(catAgg).sort((a, b) => b[1] - a[1]);
    document.getElementById('statsMemoryCatTable').innerHTML = catEntries.length
      ? catEntries.map(([cat, count]) => `
        <div class="stats-detail-row">
          <span class="stats-detail-name">${t('cat.' + cat) || cat}</span>
          <span class="stats-detail-num">${count}</span>
        </div>`).join('')
      : `<p class="card-muted">${t('stats.noData')}</p>`;
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function loadStatsSkills() {
  try {
    const list = await api('GET', '/api/skills/');
    const total = list.length;
    const enabled = list.filter(s => !s.disabled).length;
    const builtin = list.filter(s => !s.generated).length;
    const generated = list.filter(s => s.generated).length;
    const totalUsage = list.reduce((sum, s) => sum + (s.usage_count || 0), 0);

    document.getElementById('statsSkillsTotal').textContent = total;
    document.getElementById('statsSkillsEnabled').textContent = enabled;
    document.getElementById('statsSkillsBuiltin').textContent = builtin;
    document.getElementById('statsSkillsGenerated').textContent = generated;
    document.getElementById('statsSkillsTotalUsage').textContent = totalUsage;

    document.getElementById('statsSkillsTable').innerHTML = list.length
      ? list.map(s => `
        <div class="stats-detail-row">
          <span class="stats-detail-name">${escapeHtml(s.name)} ${s.generated ? '<span class="stats-detail-badge">user</span>' : '<span class="stats-detail-badge">built-in</span>'}</span>
          <span class="stats-detail-meta">${s.disabled ? '⏸ disabled' : '✅ active'} · ${t('stats.used')} ${s.usage_count || 0}x</span>
        </div>`).join('')
      : `<p class="card-muted">${t('stats.noData')}</p>`;
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

async function loadStatsServer() {
  try {
    const info = await api('GET', '/api/settings/info');
    _cachedInfo = info;

    document.getElementById('statsServerUptime').textContent = formatUptime(info.uptime_seconds);
    document.getElementById('statsServerVersion').textContent = formatAppVersion(info.version);
    document.getElementById('statsServerEndpoints').textContent = info.endpoints.length;
    document.getElementById('statsServerProviders').textContent = (info.providers || []).length;

    // Server details
    const details = [
      { label: t('stats.localIp'), value: info.local_ip || '—' },
      { label: t('stats.port'), value: info.port || '8899' },
      { label: t('stats.activeProvider'), value: info.active_provider || '—' },
      { label: t('info.uptime'), value: formatUptime(info.uptime_seconds) },
      { label: t('stats.totalUsers'), value: info.stats.total_users },
      { label: t('info.totalMemories'), value: info.stats.total_memories },
      { label: t('info.messages'), value: info.stats.total_conversations },
      { label: t('info.actions24h'), value: info.stats.actions_last_24h },
    ];
    document.getElementById('statsServerDetails').innerHTML = details.map(d => `
      <div class="stats-detail-row">
        <span class="stats-detail-name">${escapeHtml(d.label)}</span>
        <span class="stats-detail-num">${escapeHtml(String(d.value))}</span>
      </div>`).join('');

    // Service status
    const lm = info.services.lmstudio;
    const prov = info.services.provider || lm;
    const sx = info.services.searxng;
    const mem = info.services.memory;
    const services = [
      { name: prov.name || 'AI Provider', status: (prov.status || lm.status) === 'connected' ? '✅ ' + t('status.connected') : '❌ ' + t('status.unavailable'), detail: `${prov.url || lm.url} — ${prov.model || lm.model}` },
      { name: 'SearXNG', status: !sx.enabled ? '⏸ ' + t('status.disabled') : (sx.status === 'connected' ? '✅ ' + t('status.connected') : '❌ ' + t('status.unavailable')), detail: sx.url },
      { name: t('info.memoryAi'), status: mem.enabled ? '✅ ' + (mem.auto_extract ? t('status.activeAutoExtract') : t('status.active')) : '⏸ ' + t('status.disabled'), detail: t('status.memoriesStored', { count: info.stats.total_memories }) },
    ];
    document.getElementById('statsServiceDetails').innerHTML = services.map(s => `
      <div class="stats-detail-row">
        <span class="stats-detail-name">${escapeHtml(s.name)}</span>
        <span class="stats-detail-num" style="white-space:nowrap">${s.status}</span>
        <span class="stats-detail-meta">${escapeHtml(s.detail)}</span>
      </div>`).join('');
    requestAnimationFrame(fitServerOverviewValues);
  } catch (e) {
    toast(t('toast.error', { msg: e.message }), true);
  }
}

window.addEventListener('resize', () => {
  requestAnimationFrame(fitServerOverviewValues);
});
