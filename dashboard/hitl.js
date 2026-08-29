const API_BASE = window.location.origin;

async function fetchQueue() {
  try {
    const res = await fetch(`${API_BASE}/api/hitl`);
    if (!res.ok) throw new Error('Network response was not ok');
    const data = await res.json();
    renderQueue(data.items);
  } catch (e) {
    document.getElementById('queueContainer').innerHTML = `<div class="empty-queue">Failed to load queue. Make sure API is running.</div>`;
  }
}

function renderQueue(items) {
  const container = document.getElementById('queueContainer');
  if (!items || items.length === 0) {
    container.innerHTML = `<div class="empty-queue">🎉 Queue is empty! No pending reviews.</div>`;
    return;
  }

  container.innerHTML = items.map(item => `
    <div class="hitl-card" id="card-${item.query_id}">
      <div class="hitl-header">
        <span style="font-family: var(--font-mono); font-size: 0.8rem; color: var(--clr-text-dim);">Query ID: ${item.query_id}</span>
        <span class="sev-pill quarantine">${(item.severity || 'QUARANTINE').toUpperCase()}</span>
      </div>
      <div class="hitl-field">
        <div class="hitl-label">Original User Query</div>
        <div class="hitl-content">${escapeHtml(item.original_query || '')}</div>
      </div>
      <div class="hitl-field">
        <div class="hitl-label">Generated Response (Pending)</div>
        <div class="hitl-content" contenteditable="true" id="output-${item.query_id}" style="border: 1px dashed var(--clr-border); outline: none;">${escapeHtml(item.raw_output || '')}</div>
        <div style="font-size: 0.7rem; color: var(--clr-text-dim); margin-top: 4px;">* You can edit the text above before approving or redacting.</div>
      </div>
      <div class="hitl-actions">
        <button class="btn btn-approve" onclick="resolveItem('${item.query_id}', 'approve')">✓ Approve (Pass)</button>
        <button class="btn btn-redact" onclick="resolveItem('${item.query_id}', 'redact')">✎ Redact (Edit)</button>
        <button class="btn btn-block" onclick="resolveItem('${item.query_id}', 'block')">🚫 Block (Fail)</button>
      </div>
    </div>
  `).join('');
}

async function resolveItem(queryId, action) {
  // In a real app we would also submit the edited text if we chose to 'redact'.
  // For this UI we will just mark the decision state.
  try {
    const res = await fetch(`${API_BASE}/api/hitl/${queryId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, reviewed_by: 'admin' })
    });
    
    if (res.ok) {
      document.getElementById(`card-${queryId}`).style.opacity = '0.5';
      document.getElementById(`card-${queryId}`).style.pointerEvents = 'none';
      setTimeout(() => fetchQueue(), 1000);
    }
  } catch(e) {
    alert("Error resolving item");
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

document.addEventListener('DOMContentLoaded', () => {
  fetchQueue();
  setInterval(fetchQueue, 5000);
});
