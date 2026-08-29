async function fetchPolicies() {
    const res = await fetch('/api/policy');
    const data = await res.json();
    renderPolicies(data.policies);
}

function renderPolicies(policies) {
    const container = document.getElementById('policyContainer');
    container.innerHTML = '';
    
    policies.forEach(p => {
        const card = document.createElement('div');
        card.className = 'policy-card';
        
        card.innerHTML = `
            <div class="policy-header">${p.name.replace('_', ' ')}</div>
            <div class="form-group">
                <label>AlignScore Threshold (0 to 1)</label>
                <input type="number" step="0.01" min="0" max="1" id="${p.name}_align" value="${p.align_score_threshold}">
            </div>
            <div class="form-group">
                <label>Guard Block Composite Threshold (0 to 1)</label>
                <input type="number" step="0.01" min="0" max="1" id="${p.name}_comp" value="${p.guard_block_composite_threshold}">
            </div>
            <div class="form-group">
                <label>Guard Block Signal Threshold (0 to 1)</label>
                <input type="number" step="0.01" min="0" max="1" id="${p.name}_sig" value="${p.guard_block_signal_threshold}">
            </div>
            <div class="form-group">
                <label>
                    <input type="checkbox" id="${p.name}_pii" ${p.pii_masking_enabled ? 'checked' : ''}>
                    Enable PII Masking
                </label>
            </div>
            <div class="form-group">
                <label>
                    <input type="checkbox" id="${p.name}_quarantine" ${p.quarantine_on_warn ? 'checked' : ''}>
                    Quarantine on WARN
                </label>
            </div>
            <button class="btn-save" onclick="savePolicy('${p.name}')">Save Changes</button>
        `;
        container.appendChild(card);
    });
}

async function savePolicy(name) {
    const payload = {
        align_score_threshold: parseFloat(document.getElementById(`${name}_align`).value),
        guard_block_composite_threshold: parseFloat(document.getElementById(`${name}_comp`).value),
        guard_block_signal_threshold: parseFloat(document.getElementById(`${name}_sig`).value),
        pii_masking_enabled: document.getElementById(`${name}_pii`).checked,
        quarantine_on_warn: document.getElementById(`${name}_quarantine`).checked
    };
    
    const res = await fetch(`/api/policy/${name}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });
    
    if (res.ok) {
        const toast = document.getElementById('toast');
        toast.style.opacity = 1;
        setTimeout(() => toast.style.opacity = 0, 3000);
    }
}

document.addEventListener('DOMContentLoaded', fetchPolicies);
