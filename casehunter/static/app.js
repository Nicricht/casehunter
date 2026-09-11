const state = { config: {}, cases: [], companies: [], playbooks: [] };
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const money = value => new Intl.NumberFormat('es-CL', {style:'currency', currency:'CLP', maximumFractionDigits:0}).format(Number(value || 0));
const pct = value => `${Math.round(Number(value || 0) * 100)}%`;
const caseName = c => c.company_name || c.detected_company_name || 'Empresa por confirmar';

function safeUrl(value) {
  try {
    const parsed = new URL(String(value || ''), window.location.origin);
    return ['http:', 'https:'].includes(parsed.protocol) ? esc(parsed.href) : '#';
  } catch (_) {
    return '#';
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {headers:{'Content-Type':'application/json', ...(options.headers || {})}, ...options});
  const body = response.headers.get('content-type')?.includes('json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(body?.detail || body || `HTTP ${response.status}`);
  return body;
}

function toast(message) {
  const node = $('toast');
  node.textContent = message;
  node.classList.remove('hidden');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.add('hidden'), 3500);
}

function setView(view) {
  document.querySelectorAll('.view').forEach(n => n.classList.remove('active'));
  document.querySelectorAll('#nav button').forEach(n => n.classList.remove('active'));
  $(`view-${view}`)?.classList.add('active');
  document.querySelector(`#nav button[data-view="${view}"]`)?.classList.add('active');
  const titles = {
    dashboard:['Pilot Command Center','Cartera, señales públicas y próximas acciones en una sola vista.'],
    cases:['Casos','De la señal pública al cierre administrativo.'],
    companies:['Empresas','Relaciona proveedores con los casos detectados.'],
    scan:['Descubrir','Convierte fuentes públicas en casos accionables.'],
    auto:['Auto','Detección, contacto, respuesta y seguimiento en un solo ciclo.'],
    detail:['Detalle del caso','Diagnóstico, evidencia, acciones y recomendación por precedentes.'],
  };
  const t = titles[view] || titles.dashboard;
  $('page-title').textContent = t[0];
  $('page-subtitle').textContent = t[1];
}

async function loadHealth() {
  try {
    const h = await api('/api/health');
    $('health').textContent = `Sistema operativo · v${h.version}`;
  } catch (_) {
    $('health').textContent = 'Sistema no disponible';
  }
}

function pilotBadge(stage) {
  const cls = stage === 'RESOLVED' ? 'resolved' : stage === 'ACTIVE_PILOT' ? 'follow' : stage === 'PROBLEM_CONFIRMED' ? 'medium' : '';
  return `<span class="badge ${cls}">${esc(stage || 'SIN ETAPA')}</span>`;
}

function recommendationHtml(result, caseId, compact = false) {
  if (!result || result.status !== 'READY' || !result.recommendation) {
    const message = result?.causality_notice || 'Todavía no existen suficientes precedentes resueltos comparables.';
    return `<div class="rec-card empty-rec"><div class="eyebrow">PRÓXIMA ACCIÓN RECOMENDADA</div><div class="rec-title">Esperando más evidencia</div><p class="muted">${esc(message)}</p><div class="rec-actions"><button class="secondary recommendation-case" data-case="${caseId}">Ver caso</button></div></div>`;
  }
  const r = result.recommendation;
  const evidence = (r.evidence || []).slice(0, compact ? 2 : 5).map(item => {
    const link = safeUrl(item.source_url);
    const source = link === '#' ? '' : `<a href="${link}" target="_blank" rel="noopener">Fuente</a>`;
    return `<div class="evidence-item"><strong>Caso #${esc(item.case_id)}</strong> · ${esc(item.basis || 'evidencia')}<br>${esc(item.evidence || '')}${source ? `<br>${source}` : ''}</div>`;
  }).join('');
  return `<div class="rec-card"><div class="eyebrow">PRÓXIMA ACCIÓN RECOMENDADA</div><div class="rec-title">${esc(r.title)}</div><p class="muted">${esc(r.rationale || '')}</p><div class="rec-confidence"><strong>${Number(r.confidence || 0)}%</strong><div class="confidence-bar"><div class="confidence-fill" style="width:${Math.max(0, Math.min(100, Number(r.confidence || 0)))}%"></div></div><span class="muted">${Number(r.precedent_count || 0)} precedente(s)</span></div>${evidence ? `<div class="evidence-list">${evidence}</div>` : ''}<div class="causality-note">${esc(result.causality_notice || '')}</div><div class="rec-actions"><button class="recommendation-apply" data-case="${caseId}">Aplicar acción</button><button class="secondary recommendation-case" data-case="${caseId}">Ver caso</button></div></div>`;
}

function bindRecommendationActions() {
  document.querySelectorAll('.recommendation-case').forEach(btn => btn.onclick = () => openCase(Number(btn.dataset.case)));
  document.querySelectorAll('.recommendation-apply').forEach(btn => btn.onclick = async () => {
    const caseId = Number(btn.dataset.case);
    btn.disabled = true;
    try {
      const result = await api(`/api/cases/${caseId}/recommendation/apply`, {method:'POST'});
      if (result.materialized) toast('Recomendación convertida en acción');
      else if (result.materialization_reason === 'equivalent_action_already_open') toast('La acción equivalente ya está abierta');
      else if (result.materialization_reason === 'confidence_below_threshold') toast('Confianza insuficiente para aplicar automáticamente');
      else toast('No había una recomendación aplicable');
      await loadDashboard();
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
    }
  });
}

function renderPilotFunnel(funnel) {
  const counts = funnel?.counts || {};
  const stages = [
    ['DETECTED','Detectados'],['CONTACTED','Contactados'],['ENGAGED','Respondieron'],
    ['PROBLEM_CONFIRMED','Problema confirmado'],['ACTIVE_PILOT','Piloto activo'],['RESOLVED','Resueltos'],
  ];
  const max = Math.max(1, ...stages.map(([key]) => Number(counts[key] || 0)));
  return stages.map(([key,label]) => `<div class="funnel-row"><div><div class="list-title">${label}</div><div class="funnel-track"><div class="funnel-fill" style="width:${Math.max(3, Math.round((Number(counts[key] || 0) / max) * 100))}%"></div></div></div><strong>${Number(counts[key] || 0)}</strong></div>`).join('');
}

function renderPortfolios(portfolios) {
  if (!portfolios?.length) return '<div class="empty">Todavía no hay carteras agrupadas.</div>';
  return portfolios.slice(0, 6).map(p => {
    const priority = p.priority_case || {};
    const next = priority.next_action?.title || 'Sin acción abierta';
    return `<div class="portfolio-row"><div class="portfolio-title"><div><div class="list-title">${esc(p.company_name)}</div><div class="list-meta">${esc(priority.agency || 'Organismo por confirmar')}</div></div><strong>${money(p.confirmed_public_amount_clp || 0)}</strong></div><div class="portfolio-stats"><span class="stat-pill">${Number(p.open_case_count || 0)} abiertos</span><span class="stat-pill">${Number(p.resolved_case_count || 0)} resueltos</span><span class="stat-pill">prioridad ${Number(p.highest_priority || 0)}</span></div><div class="list-meta">Siguiente: ${esc(next)}</div>${priority.case_id ? `<button class="link-button clickable-case" data-case="${priority.case_id}">Abrir caso prioritario</button>` : ''}</div>`;
  }).join('');
}

async function loadDashboard() {
  const [d, cases, ops, portfolios] = await Promise.all([
    api('/api/dashboard'),
    api('/api/cases'),
    api('/api/operations'),
    api('/api/portfolios?min_cases=1&active_only=false'),
  ]);
  const k = ops.kpis || {};
  const funnel = ops.pilot_funnel || {counts:{}, rows:[]};
  $('metrics').innerHTML = [
    ['Pilotos activos', k.pilots_active || 0],
    ['CLP bajo seguimiento', money(funnel.tracked_amount_clp_active_pilots || 0)],
    ['Cambios públicos', funnel.public_changes_active_pilots || 0],
    ['Pilotos resueltos', k.pilot_resolved || 0],
    ['Tasa de respuesta', pct(k.reply_rate || 0)],
    ['Acciones abiertas', k.open_actions || 0],
  ].map(([label,value]) => `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div></div>`).join('');

  const rows = funnel.rows || [];
  const activePilots = rows.filter(row => row.stage === 'ACTIVE_PILOT');
  const primary = activePilots[0] || rows.find(row => row.stage === 'PROBLEM_CONFIRMED') || null;
  if (primary) {
    let detail = null;
    let recommendation = null;
    try {
      [detail, recommendation] = await Promise.all([
        api(`/api/cases/${primary.case_id}`),
        api(`/api/cases/${primary.case_id}/recommendation`).catch(() => null),
      ]);
    } catch (_) {
      detail = null;
    }
    const latest = detail?.timeline?.find(e => ['PUBLIC_WATCH_CHANGE','COMPANY_REPLY','PILOT_STARTED','RESOLUTION_RECOMMENDATION'].includes(e.event_type)) || detail?.timeline?.[0];
    $('pilot-command').innerHTML = `<div class="command-layout"><div class="pilot-hero"><div class="pilot-hero-head"><div><div class="pilot-name">${esc(primary.company_name || caseName(detail || {}))}</div><div class="list-meta">Caso #${primary.case_id} · ${esc(detail?.agency || 'Organismo por confirmar')}</div></div>${pilotBadge(primary.stage)}</div><div class="pilot-amount">${money(primary.tracked_amount_clp || 0)}</div><div class="pilot-amount-label">monto público bajo seguimiento en este caso</div><div class="pilot-facts"><div class="pilot-fact"><span>Bloqueo</span><strong>${esc(primary.current_blocker || detail?.current_blocker || 'Por confirmar')}</strong></div><div class="pilot-fact"><span>Días en piloto</span><strong>${Number(primary.pilot_days_active || 0)}</strong></div><div class="pilot-fact"><span>Última señal</span><strong>${esc(latest?.event_date || 'Sin novedad')}</strong></div></div>${latest ? `<div class="notice"><strong>${esc(latest.title || 'Última novedad')}</strong><br><span>${esc((latest.details || '').slice(0,420))}</span></div>` : '<div class="notice">Todavía no hay una señal nueva registrada después del inicio del seguimiento.</div>'}</div>${recommendationHtml(recommendation, primary.case_id, true)}</div>`;
  } else {
    $('pilot-command').innerHTML = '<div class="empty">No hay un piloto activo todavía. El Command Center se activará cuando una empresa confirme seguimiento.</div>';
  }

  $('portfolio-command').innerHTML = renderPortfolios(portfolios);
  $('pilot-funnel').innerHTML = renderPilotFunnel(funnel);
  $('priority-cases').innerHTML = cases.length ? cases.slice(0,7).map(c => `<div class="list-item clickable-case" data-case="${c.id}"><div class="list-title">${esc(caseName(c))}</div><div class="list-meta">${esc(c.contract_ref || c.external_id)} · prioridad ${c.financial_priority} · ${money(c.largest_amount_clp)}</div></div>`).join('') : '<div class="empty">Todavía no hay casos.</div>';
  $('blockers').innerHTML = d.blockers?.length ? d.blockers.map(b => `<div class="list-item"><div class="list-title">${esc(b.blocker || 'UNKNOWN')}</div><div class="list-meta">${b.count} caso(s)</div></div>`).join('') : '<div class="empty">Sin bloqueos activos.</div>';
  bindCaseLinks();
  bindRecommendationActions();
}

async function loadCases() {
  const params = new URLSearchParams();
  if ($('case-status').value) params.set('status', $('case-status').value);
  if ($('case-search').value.trim()) params.set('search', $('case-search').value.trim());
  state.cases = await api('/api/cases' + (params.size ? `?${params}` : ''));
  $('cases-table').innerHTML = state.cases.length ? `<table><thead><tr><th>Empresa</th><th>Contrato</th><th>Bloqueo</th><th>Estado</th><th>Prioridad</th><th>Monto</th></tr></thead><tbody>${state.cases.map(c => `<tr class="clickable clickable-case" data-case="${c.id}"><td><strong>${esc(caseName(c))}</strong></td><td>${esc(c.contract_ref || c.external_id)}</td><td>${esc(c.current_blocker || '')}</td><td>${esc(c.status)}</td><td>${c.financial_priority}</td><td>${money(c.largest_amount_clp)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">No hay casos con esos filtros.</div>';
  bindCaseLinks();
}

function bindCaseLinks() {
  document.querySelectorAll('.clickable-case').forEach(node => node.onclick = () => openCase(Number(node.dataset.case)));
}

async function loadCompanies() {
  state.companies = await api('/api/companies');
  $('companies-list').innerHTML = state.companies.length ? state.companies.map(c => `<div class="list-item"><div class="list-title">${esc(c.name)}</div><div class="list-meta">${esc(c.rut || 'RUT no registrado')} · ${c.case_count} caso(s)</div></div>`).join('') : '<div class="empty">Aún no hay empresas registradas.</div>';
}

async function loadScans() {
  const scans = await api('/api/scans');
  $('scan-history').innerHTML = scans.length ? scans.map(s => `<div class="list-item"><div class="list-title">${s.error ? 'Escaneo con error' : `${s.candidate_count} candidato(s)`}</div><div class="list-meta">${esc(s.started_at)} · ${s.pages_scanned} página(s)${s.error ? ` · ${esc(s.error)}` : ''}</div></div>`).join('') : '<div class="empty">Todavía no se han ejecutado escaneos.</div>';
}

async function openCase(id) {
  const [c, recommendation] = await Promise.all([
    api(`/api/cases/${id}`),
    api(`/api/cases/${id}/recommendation`).catch(() => null),
  ]);
  setView('detail');
  $('detail-title').innerHTML = `<h2>${esc(caseName(c))}</h2><div class="list-meta">${esc(c.contract_ref || c.external_id)}</div>`;
  const companyOptions = [`<option value="">Sin vincular</option>`, ...state.companies.map(x => `<option value="${x.id}" ${x.id === c.company_id ? 'selected' : ''}>${esc(x.name)}</option>`)].join('');
  const statuses = ['DETECTED','VALIDATING','BLOCKER_IDENTIFIED','ACTION_REQUIRED','DOCUMENT_SENT','WAITING_AGENCY','FOLLOW_UP','RESOLVED','DISMISSED'];
  const statusOptions = statuses.map(s => `<option ${s === c.status ? 'selected' : ''}>${s}</option>`).join('');
  const blockerOptions = state.playbooks.map(p => `<option value="${esc(p.blocker)}" ${p.blocker === c.current_blocker ? 'selected' : ''}>${esc(p.title)}</option>`).join('');
  const pb = c.playbook || {};
  $('case-detail').innerHTML = `<div class="detail-grid"><div class="detail-column">
    <article class="card"><h2>Diagnóstico</h2><dl class="kv"><dt>Bloqueo</dt><dd>${esc(c.current_blocker || 'UNKNOWN')}</dd><dt>Organismo</dt><dd>${esc(c.agency || 'Por confirmar')}</dd><dt>Prioridad</dt><dd>${c.financial_priority}/100</dd></dl></article>
    <article class="card case-recommendation"><h2>Resolution Learning</h2>${recommendationHtml(recommendation, c.id)}</article>
    <article class="card"><h2>Resolution Playbook</h2><p><strong>${esc(pb.title || '')}</strong></p><p class="muted">${esc(pb.goal || '')}</p>${pb.next_step ? `<div class="notice"><strong>Siguiente acción operativa</strong><br>${esc(pb.next_step.title || '')}</div>` : ''}<button id="apply-playbook">Aplicar playbook</button></article>
    <article class="card"><h2>Acciones</h2>${(c.actions || []).map(a => `<div class="list-item"><strong>${esc(a.title)}</strong><div class="list-meta">${esc(a.status)}${a.due_date ? ` · ${esc(a.due_date)}` : ''}</div></div>`).join('') || '<div class="empty">Sin acciones.</div>'}<button id="add-action">Agregar acción</button></article>
  </div><div class="detail-column">
    <article class="card"><h2>Control</h2><div class="stack"><label>Estado<select id="detail-status">${statusOptions}</select></label><label>Bloqueo<select id="detail-blocker">${blockerOptions}</select></label><label>Empresa<select id="detail-company">${companyOptions}</select></label></div></article>
    <article class="card"><h2>Montos observados</h2><div class="amount-big">${money(c.financial?.largest_observed_amount_clp || 0)}</div><div class="warning">${esc(c.financial?.warning || '')}</div></article>
    <article class="card"><h2>Fuente pública</h2>${c.detail_url && safeUrl(c.detail_url) !== '#' ? `<p><a href="${safeUrl(c.detail_url)}" target="_blank" rel="noopener">Abrir antecedente original</a></p>` : ''}<div class="source-text">${esc(c.detail_text || c.raw_text || '')}</div></article>
  </div></div>`;
  $('detail-status').onchange = async e => { await api(`/api/cases/${c.id}/status`, {method:'PATCH', body:JSON.stringify({status:e.target.value})}); toast('Estado actualizado'); openCase(c.id); };
  $('detail-blocker').onchange = async e => { await api(`/api/cases/${c.id}/blocker`, {method:'PATCH', body:JSON.stringify({blocker:e.target.value, reason:null})}); toast('Bloqueo actualizado'); openCase(c.id); };
  $('detail-company').onchange = async e => { if (!e.target.value) return; await api(`/api/cases/${c.id}/company`, {method:'PATCH', body:JSON.stringify({company_id:Number(e.target.value)})}); toast('Empresa vinculada'); openCase(c.id); };
  $('apply-playbook').onclick = async () => { await api(`/api/cases/${c.id}/playbook/apply`, {method:'POST'}); toast('Playbook aplicado'); openCase(c.id); };
  $('add-action').onclick = async () => { const title = prompt('Nueva acción'); if (!title) return; await api(`/api/cases/${c.id}/actions`, {method:'POST', body:JSON.stringify({title})}); toast('Acción creada'); openCase(c.id); };
  bindRecommendationActions();
}

async function loadAuto() {
  const [status, queue, runs, replies, followups] = await Promise.all([
    api('/api/auto/status'), api('/api/outreach'), api('/api/auto/runs'), api('/api/replies?limit=20'), api('/api/followups?limit=20')
  ]);
  const counts = status.queue_counts || {};
  $('auto-metrics').innerHTML = [
    ['Por aprobar',counts.READY_FOR_APPROVAL||0],['Sin contacto',counts.NEEDS_CONTACT||0],
    ['Enviados',counts.SENT||0],['Respondidos',counts.REPLIED||0],
    ['Respuestas',status.reply_count||0],['Follow-ups pendientes',status.followups_due||0]
  ].map(([label,value]) => `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div></div>`).join('');
  const last = status.last_run;
  const mailState = status.gmail_monitoring_configured ? 'Gmail conectado' : 'Gmail sin credenciales';
  const sendState = status.smtp_configured ? 'envío habilitado' : 'envío deshabilitado';
  $('auto-status').innerHTML = last ? `Último ciclo: <strong>${esc(last.status)}</strong> · ${last.cases_created} caso(s) nuevo(s) · ${last.drafts_created} borrador(es) · ${last.contacts_found} contacto(s).<br>${mailState} · ${sendState}.` : `Todavía no se ha ejecutado Case Hunter Auto.<br>${mailState} · ${sendState}.`;
  $('auto-runs').innerHTML = runs.length ? runs.slice(0,8).map(r => `<div class="list-item"><div class="list-title">${esc(r.status)}</div><div class="list-meta">${esc(r.started_at)} · ${r.cases_created} nuevos · ${r.drafts_created} borradores${r.error ? ` · ${esc(r.error)}` : ''}</div></div>`).join('') : '<div class="empty">Sin ciclos.</div>';
  $('outreach-queue').innerHTML = queue.length ? `<table><thead><tr><th>Empresa</th><th>Prioridad</th><th>Destinatario</th><th>Estado</th><th>Acción</th></tr></thead><tbody>${queue.map(m => `<tr><td><strong>${esc(m.detected_company_name || 'Empresa por confirmar')}</strong><div class="list-meta">${esc(m.contract_ref || '')}</div><details><summary>Ver correo</summary><div class="source-text">${esc(m.body)}</div></details></td><td>${m.financial_priority}</td><td>${esc(m.recipient_email || 'No encontrado')}</td><td>${esc(m.status)}</td><td>${outreachActions(m)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">La cola está vacía.</div>';
  $('reply-list').innerHTML = replies.length ? replies.map(r => `<div class="list-item"><div class="list-title">${esc(r.classification)}</div><div class="list-meta">${esc(r.sender_email || '')} · caso #${r.case_id}</div><div class="source-text">${esc((r.body || '').slice(0,600))}</div></div>`).join('') : '<div class="empty">Sin respuestas clasificadas.</div>';
  $('followup-list').innerHTML = followups.length ? followups.map(f => `<div class="list-item"><div class="list-title">${esc(f.detected_company_name || 'Empresa')}</div><div class="list-meta">${esc(f.status)} · ${esc(f.due_at)} · ${esc(f.recipient_email || '')}</div></div>`).join('') : '<div class="empty">Sin seguimientos programados.</div>';
  bindOutreachActions();
}

function outreachActions(m) {
  if (m.status === 'NEEDS_CONTACT') return `<button class="secondary outreach-recipient" data-id="${m.id}">Agregar correo</button>`;
  if (m.status === 'READY_FOR_APPROVAL') return `<button class="outreach-approve-send" data-id="${m.id}">Aprobar${state.config.smtp_configured ? ' y enviar' : ''}</button><button class="secondary outreach-reject" data-id="${m.id}">Descartar</button>`;
  if (m.status === 'APPROVED' || m.status === 'FAILED') return `<button class="outreach-send" data-id="${m.id}">${m.status === 'FAILED' ? 'Reintentar' : 'Enviar'}</button>`;
  return '';
}

function bindOutreachActions() {
  document.querySelectorAll('.outreach-recipient').forEach(btn => btn.onclick = async () => { const email = prompt('Correo corporativo verificado'); if (!email) return; try { await api(`/api/outreach/${btn.dataset.id}/recipient`, {method:'PATCH', body:JSON.stringify({recipient_email:email})}); toast('Destinatario agregado'); loadAuto(); } catch(e) { toast(e.message); } });
  document.querySelectorAll('.outreach-approve-send').forEach(btn => btn.onclick = async () => { try { await api(`/api/outreach/${btn.dataset.id}/approve`, {method:'POST', body:JSON.stringify({recipient_email:null})}); if (state.config.smtp_configured) { const sent = await api(`/api/outreach/${btn.dataset.id}/send`, {method:'POST'}); toast(sent.status === 'SENT' ? 'Aprobado y enviado' : `No enviado: ${sent.status}`); } else toast('Aprobado. El ciclo cloud lo enviará cuando Gmail esté configurado.'); loadAuto(); } catch(e) { toast(e.message); } });
  document.querySelectorAll('.outreach-send').forEach(btn => btn.onclick = async () => { try { const sent = await api(`/api/outreach/${btn.dataset.id}/send`, {method:'POST'}); toast(sent.status === 'SENT' ? 'Correo enviado' : `No enviado: ${sent.status}`); loadAuto(); } catch(e) { toast(e.message); } });
  document.querySelectorAll('.outreach-reject').forEach(btn => btn.onclick = async () => { try { await api(`/api/outreach/${btn.dataset.id}/reject`, {method:'POST'}); toast('Prospecto descartado'); loadAuto(); } catch(e) { toast(e.message); } });
}

async function boot() {
  await loadHealth();
  state.config = await api('/api/config');
  state.playbooks = await api('/api/playbooks');
  await Promise.all([loadCompanies(), loadDashboard()]);
  $('scan-url').value = state.config.default_ley_lobby_url;
  document.querySelectorAll('#nav button').forEach(btn => btn.onclick = async () => { const view = btn.dataset.view; setView(view); if (view === 'dashboard') await loadDashboard(); if (view === 'cases') await loadCases(); if (view === 'companies') await loadCompanies(); if (view === 'scan') await loadScans(); if (view === 'auto') await loadAuto(); });
  document.querySelectorAll('[data-view-link]').forEach(btn => btn.onclick = async () => { setView(btn.dataset.viewLink); await loadCases(); });
  $('back-cases').onclick = async () => { setView('cases'); await loadCases(); };
  $('refresh-cases').onclick = loadCases;
  $('command-refresh').onclick = async () => { const b=$('command-refresh'); b.disabled=true; b.textContent='Actualizando…'; try { await api('/api/mail/sync',{method:'POST'}); toast('Inteligencia del piloto actualizada'); await loadDashboard(); } catch(e) { toast(e.message); } finally { b.disabled=false; b.textContent='Actualizar inteligencia'; } };
  $('case-status').onchange = loadCases;
  $('case-search').onkeydown = e => { if (e.key === 'Enter') loadCases(); };
  $('company-form').onsubmit = async e => { e.preventDefault(); try { await api('/api/companies', {method:'POST', body:JSON.stringify({name:$('company-name').value, rut:$('company-rut').value || null})}); e.target.reset(); toast('Empresa guardada'); await loadCompanies(); } catch(err) { toast(err.message); } };
  $('auto-run').onclick = async () => { const b=$('auto-run'); b.disabled=true; b.textContent='Ejecutando…'; try { const r=await api('/api/auto/run',{method:'POST',body:JSON.stringify({})}); toast(`Auto: ${r.cases_created} casos nuevos, ${r.drafts_created} borradores, ${r.reply_sync?.created || 0} respuestas.`); await Promise.all([loadAuto(),loadDashboard()]); } catch(e) { toast(e.message); } finally { b.disabled=false; b.textContent='Ejecutar ahora'; } };
  $('auto-refresh').onclick = loadAuto;
  $('mail-sync').onclick = async () => { try { const r=await api('/api/mail/sync',{method:'POST'}); toast(r.configured ? `${r.created} respuesta(s) nueva(s)` : 'Gmail aún no está configurado'); await Promise.all([loadAuto(),loadDashboard()]); } catch(e) { toast(e.message); } };
  $('followups-process').onclick = async () => { try { const r=await api('/api/followups/process?send=true',{method:'POST'}); toast(`${r.due} seguimiento(s) vencido(s), ${r.sent} enviado(s)`); await loadAuto(); } catch(e) { toast(e.message); } };
  $('scan-form').onsubmit = async e => { e.preventDefault(); const b=$('scan-button'); b.disabled=true; b.textContent='Escaneando…'; try { const r=await api('/api/scans/ley-lobby',{method:'POST',body:JSON.stringify({url:$('scan-url').value,max_pages:Number($('scan-pages').value),enrich:true,enrich_limit:Number($('scan-enrich').value)})}); $('scan-result').classList.remove('hidden'); $('scan-result').textContent=`Listo. ${r.scan.pages_scanned} página(s), ${r.scan.candidate_count} candidato(s), ${r.import.created} caso(s) nuevo(s).`; await Promise.all([loadScans(),loadDashboard()]); } catch(err) { toast(err.message); } finally { b.disabled=false; b.textContent='Iniciar escaneo'; } };
}

boot().catch(err => toast(err.message));
