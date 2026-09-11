const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const money = value => new Intl.NumberFormat('es-CL', {style:'currency', currency:'CLP', maximumFractionDigits:0}).format(Number(value || 0));

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: {'Content-Type':'application/json', ...(options.headers || {})},
    ...options,
  });
  let body = null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('json')) body = await response.json();
  else body = await response.text();
  if (!response.ok) {
    const error = new Error(body?.detail || body || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return body;
}

function safeUrl(value) {
  try {
    const url = new URL(String(value || ''), window.location.origin);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
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

function showLogin(message = '') {
  $('portfolio-view').classList.add('hidden');
  $('session-tools').classList.add('hidden');
  $('login-view').classList.remove('hidden');
  if (message) {
    $('login-error').textContent = message;
    $('login-error').classList.remove('hidden');
  } else {
    $('login-error').classList.add('hidden');
  }
}

function showPortfolio() {
  $('login-view').classList.add('hidden');
  $('portfolio-view').classList.remove('hidden');
  $('session-tools').classList.remove('hidden');
}

function renderCounts(target, items, key) {
  $(target).innerHTML = items?.length ? items.map(item => `<div class="count-row"><span>${esc(item[key] || 'Sin clasificar')}</span><strong>${Number(item.case_count || 0)}</strong></div>`).join('') : '<div class="empty">Sin datos suficientes.</div>';
}

function renderCases(cases) {
  $('cases').innerHTML = cases?.length ? `<div class="table-wrap"><table>
    <thead><tr><th>Organismo</th><th>Referencia</th><th>Estado</th><th>Bloqueo</th><th>Monto</th><th>Última señal</th></tr></thead>
    <tbody>${cases.map(item => {
      const source = safeUrl(item.source_url);
      const signal = item.latest_signal;
      return `<tr>
        <td><strong>${esc(item.agency || 'Por confirmar')}</strong></td>
        <td>${source ? `<a href="${esc(source)}" target="_blank" rel="noopener">${esc(item.contract_ref || `Caso #${item.case_id}`)}</a>` : esc(item.contract_ref || `Caso #${item.case_id}`)}</td>
        <td><span class="status ${item.status === 'RESOLVED' ? 'resolved' : ''}">${esc(statusLabel(item.status))}</span></td>
        <td>${esc(item.current_blocker || 'Sin bloqueo confirmado')}</td>
        <td>${money(item.amount_clp || 0)}</td>
        <td>${signal ? `<strong>${esc(signal.event_date || '')}</strong><br><span class="muted">${esc(signal.title || '')}</span>` : '<span class="muted">Sin señal registrada</span>'}</td>
      </tr>`;
    }).join('')}</tbody></table></div>` : '<div class="empty">Esta cartera todavía no tiene casos vinculados.</div>';
}

function recommendationCard(item) {
  const result = item.recommendation;
  const open = item.open_actions || [];
  if (!result || result.status !== 'READY' || !result.recommendation) {
    return `<article class="rec-card neutral">
      <div class="rec-head"><div><strong>${esc(item.agency || item.contract_ref || `Caso #${item.case_id}`)}</strong><div class="muted">${esc(statusLabel(item.status))}</div></div><span class="status">Sin recomendación</span></div>
      <p class="muted">Todavía no hay precedentes resueltos comparables suficientes para recomendar un movimiento con confianza.</p>
      ${open[0] ? `<div class="current-action"><span>Acción abierta actual</span><strong>${esc(open[0].title)}</strong></div>` : ''}
    </article>`;
  }
  const rec = result.recommendation;
  const evidence = (rec.evidence || []).slice(0,3).map(ev => {
    const source = safeUrl(ev.source_url);
    return `<div class="evidence"><span>${esc(ev.basis || 'evidencia pública')}</span><strong>${esc(ev.evidence || 'Antecedente comparable')}</strong>${source ? `<a href="${esc(source)}" target="_blank" rel="noopener">Ver fuente</a>` : ''}</div>`;
  }).join('');
  return `<article class="rec-card">
    <div class="rec-head"><div><strong>${esc(item.agency || item.contract_ref || `Caso #${item.case_id}`)}</strong><div class="muted">${esc(item.contract_ref || '')}</div></div><span class="confidence">${Number(rec.confidence || 0)}%</span></div>
    <h3>${esc(rec.title)}</h3>
    <p class="muted">${esc(rec.rationale || '')}</p>
    <div class="confidence-track"><div style="width:${Math.max(0, Math.min(100, Number(rec.confidence || 0)))}%"></div></div>
    <div class="evidence-grid">${evidence || '<span class="muted">Sin evidencia enlazada.</span>'}</div>
    ${result.causality_notice ? `<div class="notice">${esc(result.causality_notice)}</div>` : ''}
  </article>`;
}

function renderPortfolio(data) {
  showPortfolio();
  const company = data.company || {};
  const metrics = data.metrics || {};
  $('company-name').textContent = company.name || 'Empresa';
  $('company-meta').textContent = company.rut ? `RUT ${company.rut}` : 'Cartera pública consolidada';
  $('metrics').innerHTML = [
    ['Monto público observado', money(metrics.observed_amount_clp || 0)],
    ['Casos abiertos', Number(metrics.open_case_count || 0)],
    ['Casos resueltos', Number(metrics.resolved_case_count || 0)],
    ['Acciones abiertas', Number(metrics.open_actions || 0)],
    ['Cambios públicos', Number(metrics.public_changes || 0)],
  ].map(([label,value]) => `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div></div>`).join('');
  renderCases(data.cases || []);
  renderCounts('agencies', data.agencies || [], 'name');
  renderCounts('blockers', data.blockers || [], 'type');
  const open = (data.cases || []).filter(item => !['RESOLVED','DISMISSED'].includes(item.status));
  $('recommendations').innerHTML = open.length ? open.map(recommendationCard).join('') : '<div class="empty">No hay casos abiertos que requieran un próximo movimiento.</div>';
}

async function loadSessionAndPortfolio() {
  try {
    const me = await api('/api/client/me');
    $('session-email').textContent = `${me.user.email} · ${me.company.name}`;
    const portfolio = await api('/api/client/portfolio');
    renderPortfolio(portfolio);
  } catch (error) {
    if (error.status === 401) {
      showLogin();
      return;
    }
    $('fatal-error').textContent = error.message || String(error);
    $('fatal-error').classList.remove('hidden');
  }
}

$('login-form').onsubmit = async event => {
  event.preventDefault();
  const button = $('login-button');
  button.disabled = true;
  button.textContent = 'Entrando…';
  try {
    const result = await api('/api/client/login', {
      method:'POST',
      body:JSON.stringify({email:$('login-email').value, password:$('login-password').value}),
    });
    $('session-email').textContent = `${result.user.email} · ${result.company.name}`;
    $('login-password').value = '';
    const portfolio = await api('/api/client/portfolio');
    renderPortfolio(portfolio);
  } catch (error) {
    showLogin(error.status === 401 ? 'Correo o contraseña incorrectos.' : (error.message || String(error)));
  } finally {
    button.disabled = false;
    button.textContent = 'Entrar';
  }
};

$('logout').onclick = async () => {
  try { await api('/api/client/logout', {method:'POST'}); } catch (_) {}
  $('login-email').value = '';
  $('login-password').value = '';
  showLogin();
};

$('refresh').onclick = async () => {
  const button = $('refresh');
  button.disabled = true;
  try {
    const portfolio = await api('/api/client/portfolio');
    renderPortfolio(portfolio);
  } catch (error) {
    if (error.status === 401) showLogin('Tu sesión expiró. Inicia sesión nuevamente.');
    else $('fatal-error').textContent = error.message || String(error);
  } finally {
    button.disabled = false;
  }
};

loadSessionAndPortfolio();
