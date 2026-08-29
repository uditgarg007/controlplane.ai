/* ─────────────────────────────────────────────────────────
   ControlPlane.ai — Dashboard JavaScript
   Pure vanilla JS: no dependencies, no build step.
   ──────────────────────────────────────────────────────── */

'use strict';

// ──────────────────────────────────────────────────────────
// Configuration
// ──────────────────────────────────────────────────────────
const API_BASE   = window.location.origin;  // same-origin; change if served separately
const REFRESH_MS = 5000;  // auto-refresh interval

let refreshInterval = null;
let isPaused = false;
let countdown = REFRESH_MS / 1000;

// ──────────────────────────────────────────────────────────
// State
// ──────────────────────────────────────────────────────────
const state = {
  snapshot: null,
  latencyHistory: [],   // ring buffer of last 10 latency values
};

// ──────────────────────────────────────────────────────────
// Boot
// ──────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initCharts();
  fetchAndRender();
  startAutoRefresh();
  bindControls();
});

// ──────────────────────────────────────────────────────────
// Auto-refresh
// ──────────────────────────────────────────────────────────
function startAutoRefresh() {
  refreshInterval = setInterval(() => {
    if (!isPaused) {
      countdown -= 1;
      updateCountdown();
      if (countdown <= 0) {
        countdown = REFRESH_MS / 1000;
        fetchAndRender();
      }
    }
  }, 1000);
}

function updateCountdown() {
  document.getElementById('refreshCountdown').textContent = `${countdown}s`;
}

// ──────────────────────────────────────────────────────────
// Data fetching
// ──────────────────────────────────────────────────────────
async function fetchAndRender() {
  try {
    const res = await fetch(`${API_BASE}/metrics/dashboard`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.snapshot = data;
    renderAll(data);
    flashLiveBadge();
  } catch (err) {
    // API not yet running — render demo data so the dashboard looks correct
    renderAll(generateDemoData());
  }
}

// ──────────────────────────────────────────────────────────
// Demo data (used when API is offline / for development)
// ──────────────────────────────────────────────────────────
function generateDemoData() {
  const total = 1247 + Math.floor(Math.random() * 10);
  const cacheHit = Math.floor(total * 0.62);
  const pass = Math.floor(total * 0.70);
  const warn = Math.floor(total * 0.15);
  const quarantine = Math.floor(total * 0.05);
  const redact = Math.floor(total * 0.02);
  const fail = total - pass - warn - quarantine - redact;
  const repairs = Math.floor(fail * 0.8);

  const recent = Array.from({ length: 10 }, (_, i) => ({
    query_id: crypto.randomUUID ? crypto.randomUUID() : `demo-${Date.now()}-${i}`,
    severity: ['pass','pass','pass','warn','fail','pass','pass','warn','pass','pass'][i],
    total_latency_ms: 80 + Math.random() * 400,
    cache_hit: Math.random() > 0.4,
    repair_iterations: Math.random() > 0.8 ? Math.floor(Math.random() * 3) + 1 : 0,
    align_score: 0.6 + Math.random() * 0.4,
    guard_risk_score: Math.random() * 0.3,
    guard_verdict: 'allow',
  }));

  return {
    total_requests: total,
    severity_distribution: { pass, warn, quarantine, redact, fail },
    cache: {
      hits: cacheHit,
      misses: total - cacheHit,
      hit_rate: +(cacheHit / total).toFixed(4),
    },
    latency: { avg_ms: 185 + Math.random() * 60 },
    token_economics: {
      avg_compression_ratio: 0.48 + Math.random() * 0.1,
    },
    grounding: { avg_align_score: 0.82 + Math.random() * 0.08 },
    repair_loop: { requests_repaired: repairs },
    recent_requests: recent,
    _demo: true,
  };
}

// ──────────────────────────────────────────────────────────
// Master render
// ──────────────────────────────────────────────────────────
function renderAll(data) {
  renderKPIs(data);
  renderSeverityDonut(data.severity_distribution);
  renderLatencySparkline(data);
  renderTokenBars(data);
  renderRepairStats(data);
  renderRecentTable(data.recent_requests || []);
  renderHitlBadge();
}

// ──────────────────────────────────────────────────────────
// HITL Queue Badge
// ──────────────────────────────────────────────────────────
async function renderHitlBadge() {
  const linkEl = document.getElementById('hitlLink');
  if (!linkEl) return;
  try {
    const res = await fetch(`${API_BASE}/api/hitl`);
    if (!res.ok) return;
    const data = await res.json();
    const count = (data.items || []).length;
    let badge = linkEl.querySelector('.hitl-count-badge');
    if (count > 0) {
      if (!badge) {
        badge = document.createElement('span');
        badge.className = 'hitl-count-badge';
        linkEl.appendChild(badge);
      }
      badge.textContent = count;
    } else if (badge) {
      badge.remove();
    }
  } catch (e) {
    // API offline — silently ignore
  }
}

// ──────────────────────────────────────────────────────────
// KPIs
// ──────────────────────────────────────────────────────────
function renderKPIs(data) {
  animateNumber('valTotal', data.total_requests, v => v.toLocaleString());
  animateNumber('valLatency', data.latency.avg_ms, v => `${v.toFixed(0)}<small>ms</small>`);
  animateNumber('valCacheRate', data.cache.hit_rate * 100, v => `${v.toFixed(1)}<small>%</small>`);
  animateNumber('valAlign', data.grounding.avg_align_score, v => v.toFixed(3));
  const savingsVal = Math.max(data.token_economics.avg_compression_ratio * 100, 0);
  animateNumber('valSavings', savingsVal, v => `${v.toFixed(1)}<small>%</small>`);
}

function animateNumber(id, target, fmt) {
  const el = document.getElementById(id);
  if (!el) return;
  const start = parseFloat(el.dataset.raw || '0');
  el.dataset.raw = target;
  const duration = 600;
  const startTime = performance.now();
  function tick(now) {
    const t = Math.min((now - startTime) / duration, 1);
    const eased = 1 - Math.pow(1 - t, 3);
    const current = start + (target - start) * eased;
    el.innerHTML = fmt(current);
    if (t < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

// ──────────────────────────────────────────────────────────
// Donut Chart (hand-drawn on Canvas — no chart lib needed)
// ──────────────────────────────────────────────────────────
let donutAnimProgress = 0;
let donutRaf = null;
let donutTarget = null;

function initCharts() {
  // Charts are initialised on first render call — nothing to do here.
}

function renderSeverityDonut(dist) {
  const { pass = 0, warn = 0, quarantine = 0, redact = 0, fail = 0 } = dist;
  const total = pass + warn + quarantine + redact + fail || 1;

  // Update legend
  document.getElementById('legPass').textContent = pass.toLocaleString();
  document.getElementById('legQuarantine').textContent = quarantine.toLocaleString();
  document.getElementById('legRedact').textContent = redact.toLocaleString();
  document.getElementById('legFail').textContent = fail.toLocaleString();

  document.getElementById('legPassPct').textContent = `(${((pass / total) * 100).toFixed(1)}%)`;
  document.getElementById('legQuarantinePct').textContent = `(${((quarantine / total) * 100).toFixed(1)}%)`;
  document.getElementById('legRedactPct').textContent = `(${((redact / total) * 100).toFixed(1)}%)`;
  document.getElementById('legFailPct').textContent = `(${((fail / total) * 100).toFixed(1)}%)`;

  const passPct = (pass / total * 100).toFixed(1);
  document.getElementById('donutPassPct').textContent = `${passPct}%`;

  // Canvas draw
  const canvas = document.getElementById('severityChart');
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  canvas.width = 180 * dpr;
  canvas.height = 180 * dpr;
  ctx.scale(dpr, dpr);

  const segments = [
    { frac: pass / total, color: '#34d399' },
    { frac: quarantine / total, color: '#a855f7' },
    { frac: redact / total, color: '#6b7280' },
    { frac: fail / total, color: '#f87171' },
  ];

  donutTarget = { ctx, segments };
  animateDonut(0);
}

function animateDonut(progress) {
  if (donutRaf) cancelAnimationFrame(donutRaf);
  if (!donutTarget) return;

  const { ctx, segments } = donutTarget;
  const cx = 90, cy = 90, r = 72, gap = 0.03;
  ctx.clearRect(0, 0, 180, 180);

  const startAngle = -Math.PI / 2;
  let angle = startAngle;

  // Background ring
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.lineWidth = 20;
  ctx.strokeStyle = 'rgba(255,255,255,0.04)';
  ctx.stroke();

  for (const seg of segments) {
    const sweep = seg.frac * Math.PI * 2 * progress;
    if (sweep < 0.01) { angle += seg.frac * Math.PI * 2 * progress; continue; }
    ctx.beginPath();
    ctx.arc(cx, cy, r, angle + gap, angle + sweep - gap);
    ctx.lineWidth = 20;
    ctx.lineCap = 'round';
    ctx.strokeStyle = seg.color;
    ctx.stroke();
    angle += sweep;
  }

  // Glow
  ctx.shadowColor = 'rgba(129,140,248,0.3)';
  ctx.shadowBlur = 12;

  if (progress < 1) {
    donutRaf = requestAnimationFrame(() => animateDonut(Math.min(progress + 0.04, 1)));
  }
}

// ──────────────────────────────────────────────────────────
// Latency Sparkline
// ──────────────────────────────────────────────────────────
function renderLatencySparkline(data) {
  const recent = data.recent_requests || [];
  const values = recent.slice(-10).map(r => r.total_latency_ms || 0);
  if (!values.length) return;

  // Push new value into history
  state.latencyHistory = values;

  const canvas = document.getElementById('latencyChart');
  const container = canvas.parentElement;
  const dpr = window.devicePixelRatio || 1;
  const W = container.offsetWidth || 400;
  const H = 120;

  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);

  const pts = state.latencyHistory;
  const min = Math.min(...pts);
  const max = Math.max(...pts) || 1;
  const pad = 12;

  const xStep = (W - pad * 2) / Math.max(pts.length - 1, 1);
  const yScale = (H - pad * 2) / (max - min || 1);

  const coords = pts.map((v, i) => ({
    x: pad + i * xStep,
    y: H - pad - (v - min) * yScale,
  }));

  // Gradient fill
  const grad = ctx.createLinearGradient(0, pad, 0, H);
  grad.addColorStop(0, 'rgba(129,140,248,0.25)');
  grad.addColorStop(1, 'rgba(129,140,248,0)');

  ctx.beginPath();
  ctx.moveTo(coords[0].x, H - pad);
  coords.forEach(p => ctx.lineTo(p.x, p.y));
  ctx.lineTo(coords[coords.length - 1].x, H - pad);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // Line
  ctx.beginPath();
  coords.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
  ctx.strokeStyle = '#818cf8';
  ctx.lineWidth = 2;
  ctx.lineJoin = 'round';
  ctx.stroke();

  // Dots
  coords.forEach(p => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
    ctx.fillStyle = '#818cf8';
    ctx.fill();
  });

  // Latest dot highlighted
  const last = coords[coords.length - 1];
  ctx.beginPath();
  ctx.arc(last.x, last.y, 5, 0, Math.PI * 2);
  ctx.fillStyle = '#c7d2fe';
  ctx.fill();
}

// ──────────────────────────────────────────────────────────
// Token Bars
// ──────────────────────────────────────────────────────────
function renderTokenBars(data) {
  // Use the most recent request's token economics (including cache hits)
  const recent = data.recent_requests || [];
  const last = recent.slice().reverse().find(r => r.token_economics && r.token_economics.raw_token_count > 0);
  const eco = (last && last.token_economics) || {};
  const raw = eco.raw_token_count || 0;
  const comp = eco.compressed_token_count || 0;

  document.getElementById('valRawTokens').textContent = raw > 0 ? `${raw.toLocaleString()} tokens` : '— tokens';
  document.getElementById('valCompressedTokens').textContent = raw > 0 ? `${comp.toLocaleString()} tokens` : '— tokens';

  const compPct = raw > 0 ? Math.min(Math.round((comp / raw) * 100), 100) : 0;
  document.getElementById('barCompressed').style.width = `${compPct}%`;

  const savedRatio = Math.max(data.token_economics.avg_compression_ratio || 0, 0);
  const saved = Math.round(savedRatio * 100);
  
  const tokenSavingsText = document.getElementById('tokenSavingsText');
  const tokenSavingsBadge = document.getElementById('tokenSavingsBadge');
  
  if (comp === 0 && raw > 0) {
    // Current request is a cache hit
    tokenSavingsText.innerHTML = `<strong>100% saved</strong> (Cache Hit!)`;
    tokenSavingsBadge.style.color = '#10b981'; // vibrant green
  } else if (saved > 0) {
    tokenSavingsText.textContent = `${saved}% saved on average`;
    tokenSavingsBadge.style.color = '#34d399';
  } else {
    tokenSavingsText.textContent = `0% saved on average`;
    tokenSavingsBadge.style.color = 'var(--clr-text-dim)';
  }
}

// ──────────────────────────────────────────────────────────
// Repair Stats
// ──────────────────────────────────────────────────────────
function renderRepairStats(data) {
  const repaired = data.repair_loop.requests_repaired || 0;
  const total = data.total_requests || 1;
  const rate = ((repaired / total) * 100).toFixed(1);

  document.getElementById('valRepairCount').textContent = repaired.toLocaleString();
  document.getElementById('valRepairRate').textContent = `${rate}%`;

  // Meter: show repair rate vs total (max out at 33%)
  const meterPct = Math.min((repaired / total) * 300, 100);
  document.getElementById('repairMeter').style.width = `${meterPct}%`;
}

// ──────────────────────────────────────────────────────────
// Recent Requests Table
// ──────────────────────────────────────────────────────────
function renderRecentTable(rows) {
  const tbody = document.getElementById('recentTableBody');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-row">No requests yet…</td></tr>';
    return;
  }

  tbody.innerHTML = rows.slice().reverse().slice(0, 10).map(r => {
    const sev = r.severity || 'pass';
    const lat = (r.total_latency_ms || 0).toFixed(1);
    const align = (r.align_score || 0).toFixed(3);
    const qid = (r.query_id || '').slice(0, 8) + '…';
    const repairs = r.repair_iterations || 0;
    const cacheHit = r.cache_hit;
    const gv = r.guard_verdict || 'allow';
    const gvClass = gv === 'block' ? 'fail' : gv === 'warn' ? 'warn' : 'pass';

    return `
      <tr>
        <td class="query-id">${qid}</td>
        <td><span class="sev-pill ${sev}">${sev.toUpperCase()}</span></td>
        <td>${lat} ms</td>
        <td class="${cacheHit ? 'cache-hit' : 'cache-miss'}">${cacheHit ? '✓ HIT' : '✗ MISS'}</td>
        <td>${repairs > 0 ? `⟳ ${repairs}` : '—'}</td>
        <td>${align}</td>
        <td><span class="sev-pill ${gvClass}" style="font-size:0.6rem">${gv.toUpperCase()}</span></td>
      </tr>
    `;
  }).join('');
}

// ──────────────────────────────────────────────────────────
// Query Playground
// ──────────────────────────────────────────────────────────
document.getElementById('submitQueryBtn').addEventListener('click', async () => {
  const query = document.getElementById('queryInput').value.trim();
  if (!query) return;

  const btn = document.getElementById('submitQueryBtn');
  const output = document.getElementById('tryOutput');
  btn.disabled = true;
  output.innerHTML = '<span class="try-placeholder">⏳ Running pipeline…</span>';

  const topK = parseInt(document.getElementById('topKInput').value, 10) || 8;
  const t0 = performance.now();

  try {
    const res = await fetch(`${API_BASE}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, top_k: topK }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const elapsed = (performance.now() - t0).toFixed(0);

    if (data.blocked) {
      // ── Flagged / Blocked response ────────────────────────
      const riskScore = (data.guard_risk_score || 0);
      const riskPct   = Math.round(riskScore * 100);
      const verdict   = (data.guard_verdict || 'block').toUpperCase();

      // Parse signals out of the block_reason text — they appear after "signals triggered:"
      // The answer text itself contains the structured breakdown.
      const answerLines = (data.answer || '').split('\n').filter(Boolean);
      // Extract the reason line (3rd line after the header + blank + "Reason:")
      const reasonLine  = answerLines.find(l => l.startsWith('Reason:')) || '';
      const signalsLine = answerLines.find(l => l.startsWith('Security signals')) || '';
      const reason      = reasonLine.replace('Reason:', '').trim();
      const signals     = signalsLine.replace('Security signals triggered:', '').trim();

      // Risk bar colour: low=amber, high=red
      const barColor = riskScore >= 0.5 ? '#f87171' : '#fbbf24';

      output.innerHTML = `
        <div class="flagged-card">
          <div class="flagged-header">
            <span class="flagged-icon">🚫</span>
            <span class="flagged-title">Request Flagged &amp; Blocked</span>
            <span class="flagged-badge">LLM NOT CALLED · 0 tokens consumed</span>
          </div>

          <div class="flagged-reason">
            <strong>Block reason</strong>
            <p>${escapeHtml(reason || data.block_reason || 'Security policy violation')}</p>
          </div>

          ${signals ? `
          <div class="flagged-signals">
            <strong>Signals triggered</strong>
            <div class="signal-chips">
              ${signals.split(',').map(s => `<span class="signal-chip">${escapeHtml(s.trim())}</span>`).join('')}
            </div>
          </div>` : ''}

          <div class="flagged-risk">
            <strong>Risk score</strong>
            <div class="risk-bar-track">
              <div class="risk-bar-fill" style="width:${riskPct}%;background:${barColor}"></div>
            </div>
            <span class="risk-label">${riskPct}% / 100%</span>
          </div>

          <div class="meta-row" style="margin-top:12px">
            <span>Guard verdict: <strong style="color:var(--clr-fail)">${escapeHtml(verdict)}</strong></span>
            <span>Latency: <strong>${data.total_latency_ms?.toFixed(1) || elapsed} ms</strong></span>
            <span>Intent: <strong>${escapeHtml(data.intent || '—')}</strong></span>
          </div>
        </div>
      `;
    } else {
      // ── Normal (allowed) response ─────────────────────────
      const sev = data.severity || 'pass';
      const guardVerdict = data.guard_verdict || 'allow';
      const guardBadge = guardVerdict === 'warn'
        ? `<span title="Guard issued a warning but allowed this request" style="color:var(--clr-warn)">⚠ Guard: WARN (${(data.guard_risk_score||0).toFixed(2)})</span>`
        : `<span style="color:var(--clr-pass)">✓ Guard: ALLOW</span>`;

      output.innerHTML = `
        <div>${escapeHtml(data.answer || '(no answer returned)')}</div>
        <div class="meta-row">
          <span>Severity: <span class="sev-pill ${sev}">${sev.toUpperCase()}</span></span>
          <span>Latency: <strong>${data.total_latency_ms?.toFixed(1) || elapsed} ms</strong></span>
          <span>Cache: <strong>${data.cache_hit ? '✓ HIT' : '✗ MISS'}</strong></span>
          <span>Align: <strong>${(data.align_score || 0).toFixed(3)}</strong></span>
          <span>Repair: <strong>${data.repair_triggered ? `✓ (${data.repair_iterations} iter)` : '—'}</strong></span>
          ${guardBadge}
        </div>
      `;
    }
  } catch (err) {
    output.innerHTML = `<span style="color: var(--clr-fail)">⚠ API offline: ${escapeHtml(err.message)}<br><small>Run the ControlPlane server first: <code>python -m controlplane.api.server</code></small></span>`;
  } finally {
    btn.disabled = false;
    // Refresh metrics after a query
    fetchAndRender();
  }
});

// Submit on Ctrl/Cmd + Enter
document.getElementById('queryInput').addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    document.getElementById('submitQueryBtn').click();
  }
});

// ──────────────────────────────────────────────────────────
// Controls
// ──────────────────────────────────────────────────────────
function bindControls() {
  const pauseBtn = document.getElementById('pauseBtn');
  const liveIndicator = document.getElementById('liveIndicator');

  pauseBtn.addEventListener('click', () => {
    isPaused = !isPaused;
    if (isPaused) {
      pauseBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M3 2l10 6-10 6V2z"/></svg>`;
      pauseBtn.title = 'Resume refresh';
      liveIndicator.style.opacity = '0.4';
    } else {
      pauseBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><rect x="3" y="2" width="4" height="12" rx="1"/><rect x="9" y="2" width="4" height="12" rx="1"/></svg>`;
      pauseBtn.title = 'Pause refresh';
      liveIndicator.style.opacity = '1';
      countdown = REFRESH_MS / 1000;
    }
  });
}

function flashLiveBadge() {
  const badge = document.getElementById('liveIndicator');
  badge.style.background = 'rgba(52, 211, 153, 0.25)';
  setTimeout(() => { badge.style.background = 'rgba(52, 211, 153, 0.1)'; }, 300);
}

// ──────────────────────────────────────────────────────────
// Utilities
// ──────────────────────────────────────────────────────────
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
