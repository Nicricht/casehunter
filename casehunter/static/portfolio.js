const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const money = value => new Intl.NumberFormat('es-CL', {style:'currency', currency:'CLP', maximumFractionDigits:0}).format(Number(value || 0));

async function api(path) {
  const response = await fetch(path, {headers:{'Content-Type':'application/json'}});
  const body = response.headers.get('content-type')?.includes('json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(body?.detail || body || `HTTP ${response.status}`);
  return body;
}

function safeUrl(value) {
  try {
    const parsed = new URL(String(value || ''), window.location.origin);
    return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : null;
  } catch (_) {
    return null;
  }
}

function statusLabel(status) {
  const labels = {
    DETECTED:'Detectado', VALIDATING:'Validando', BLOCKER_IDENTIFIED:'Bloqueo identificado',
    ACTION_REQUIRED:'Acción requerida', DOCUMENT_SENT:'Documento enviado', WAITING_AGENCY:'Esperando organismo',
    FOLLOW_UP:'Seguimiento', RESOLVED:'Resuelto', DISMISSED:'Descartado',
  };
  return labels[status] || status || 'Sin estado';
}

function latestSignal(caseDetail) {
  const preferred = (caseDetail.timeline || []).find(item => [
    'PUBLIC_WATCH_CHANGE','COMPANY_REPLY','RESOLUTION_RECOMMENDATION','STATUS_CHANGED','PILOT_STARTED'
  ].includes(item.event_type));
  return preferred || (caseDetail.timeline || [])[0] || null;
}

function openActions(caseDetail) {
  return (caseDetail.actions || []).filter(action => action.status === 'TODO');
}

function renderPicker(portfolios) {
  $('portfolio-picker').classList.remove('hidden');
  $('portfolio-detail').classList.add('hidden');
  $('portfolio-list').innerHTML = portfolios.length ? portfolios.map(portfolio => {
    const url = `/static/portfolios.html?company=${encodeURIComponent(portfolio.identity_key)}`;
    return `<a class="client-portfolio-card" href="${url}">
      <div class="client-card-head"><strong>${esc(portfolio.company_name)}</strong><span>${money(portfolio.confirmed_public_amount_clp || 0)}</span></div>
      <div class="client-card-meta">${Number(portfolio.open_case_count || 0)} abiertos · ${Number(portfolio.resolved_case_count || 0)} resueltos · prioridad ${Number(portfolio.highest_priority || 0)}</div>
      <div class="client-card-agency">${esc(portfolio.priority_case?.agency || 'Organismo por confirmar')}</div>
      <div class="client-card-action">Abrir cartera →</div>
    </a>`;
  }).join('') : '<div class="empty">Todavía no hay carteras agrupadas.</div>';
}

function renderCaseRows(rows) {
  $('client-cases').innerHTML = rows.length ? `<div class="client-table-wrap"><table class="client-table">
    <thead><tr><th>Organismo</th><th>Referencia</th><th>Estado</th><th>Bloqueo</th><th>Monto</th><th>Última señal</th></tr></thead>
    <tbody>${rows.map(({detail}) => {
      const signal = latestSignal(detail);
      const source = safeUrl(detail.detail_url || detail.source_url);
      const amount = (detail.amounts_clp || []).reduce((sum, value) => sum + Number(value || 0), 0);
      return `<tr>
        <td><strong>${esc(detail.agency || 'Por confirmar')}</strong></td>
        <td>${source ? `<a href="${esc(source)}" target="_blank" rel="noopener">${esc(detail.contract_ref || detail.external_id)}</a>` : esc(detail.contract_ref || detail.external_id)}</td>
        <td><span class="client-status ${detail.status === 'RESOLVED' ? 'resolved' : ''}">${esc(statusLabel(detail.status))}</span></td>
        <td>${esc(detail.current_blocker || 'Sin bloqueo confirmado')}</td>
        <td>${money(amount)}</td>
        <td>${signal ? `<strong>${esc(signal.event_date || '')}</strong><br><span class="muted">${esc(signal.title || '')}</span>` : '<span class="muted">Sin señal registrada</span>'}</td>
      </tr>`;
    }).join('')}</tbody></table></div>` : '<div class="empty">Esta cartera todavía no tiene casos.</div>';
}

function renderCountList(targetId, items, keyName) {
  $(targetId).innerHTML = items?.length ? items.map(item => `<div class="client-count-row"><span>${esc(item[keyName] || 'Sin clasificar')}</span><strong>${Number(item.case_count || 0)}</strong></div>`).join('') : '<div class="empty">Sin datos suficientes.</div>';
}

function recommendationCard(row) {
  const result = row.recommendation;
  const detail = row.detail;
  const open = openActions(detail);
  if (!result || result.status !== 'READY' || !result.recommendation) {
    return `<div class="client-rec-card neutral">
      <div class="client-rec-top"><div><strong>${esc(detail.agency || detail.contract_ref || `Caso #${detail.id}`)}</strong><div class="list-meta">${esc(statusLabel(detail.status))}</div></div><span class="client-status">Sin recomendación</span></div>
      <p class="muted">Todavía no hay suficientes precedentes resueltos comparables para recomendar un movimiento con confianza.</p>
      ${open[0] ? `<div class="client-current-action"><span>Acción abierta actual</span><strong>${esc(open[0].title)}</strong></div>` : ''}
    </div>`;
  }
  const rec = result.recommendation;
  const evidence = (rec.evidence || []).slice(0,3).map(item => {
    const source = safeUrl(item.source_url);
    return `<div class="client-evidence"><span>Caso #${esc(item.case_id)}</span><strong>${esc(item.evidence || item.basis || 'Antecedente comparable')}</strong>${source ? `<a href="${esc(source)}" target="_blank" rel="noopener">Ver fuente</a>` : ''}</div>`;
  }).join('');
  return `<div class="client-rec-card">
    <div class="client-rec-top"><div><strong>${esc(detail.agency || detail.contract_ref || `Caso #${detail.id}`)}</strong><div class="list-meta">${esc(detail.contract_ref || detail.external_id)}</div></div><span class="client-confidence">${Number(rec.confidence || 0)}%</span></div>
    <h3>${esc(rec.title)}</h3>
    <p class="muted">${esc(rec.rationale || '')}</p>
    <div class="client-confidence-bar"><div style="width:${Math.max(0, Math.min(100, Number(rec.confidence || 0)))}%"></div></div>
    <div class="client-evidence-grid">${evidence || '<span class="muted">Sin evidencia enlazada.</span>'}</div>
  </div>`;
}

async function renderDetail(portfolio) {
  $('portfolio-picker').classList.add('hidden');
  $('portfolio-detail').classList.remove('hidden');
  $('client-company').textContent = portfolio.company_name;
  $('client-summary').textContent = `${portfolio.case_count} caso(s) públicos agrupados en ${portfolio.agencies?.length || 0} organismo(s).`;

  const caseRows = await Promise.all((portfolio.case_ids || []).map(async caseId => {
    const detail = await api(`/api/cases/${caseId}`);
    let recommendation = null;
    try { recommendation = await api(`/api/cases/${caseId}/recommendation`); } catch (_) { recommendation = null; }
    return {detail, recommendation};
  }));

  const openCases = caseRows.filter(row => row.detail.status !== 'RESOLVED' && row.detail.status !== 'DISMISSED');
  const resolvedCases = caseRows.filter(row => row.detail.status === 'RESOLVED');
  const amount = caseRows.reduce((sum, row) => sum + (row.detail.amounts_clp || []).reduce((s, value) => s + Number(value || 0), 0), 0);
  const openActionCount = caseRows.reduce((sum, row) => sum + openActions(row.detail).length, 0);
  const signals = caseRows.reduce((sum, row) => sum + (row.detail.timeline || []).filter(item => item.event_type === 'PUBLIC_WATCH_CHANGE').length, 0);

  $('client-metrics').innerHTML = [
    ['Monto público observado', money(amount)],
    ['Casos abiertos', openCases.length],
    ['Casos resueltos', resolvedCases.length],
    ['Acciones abiertas', openActionCount],
    ['Cambios públicos', signals],
  ].map(([label,value]) => `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div></div>`).join('');

  renderCaseRows(caseRows);
  renderCountList('client-agencies', portfolio.agencies || [], 'name');
  renderCountList('client-blockers', portfolio.blockers || [], 'type');
  $('client-recommendations').innerHTML = openCases.length ? openCases.map(recommendationCard).join('') : '<div class="empty">No hay casos abiertos que requieran una recomendación.</div>';
}

async function boot() {
  try {
    const portfolios = await api('/api/portfolios?min_cases=1&active_only=false');
    const requested = new URLSearchParams(window.location.search).get('company');
    if (!requested) {
      renderPicker(portfolios);
      return;
    }
    const portfolio = portfolios.find(item => item.identity_key === requested);
    if (!portfolio) throw new Error('No se encontró esa cartera. Puede que todavía no tenga casos vinculados.');
    await renderDetail(portfolio);
  } catch (error) {
    $('client-error').textContent = error.message || String(error);
    $('client-error').classList.remove('hidden');
  }
}

boot();
