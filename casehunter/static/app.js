const state = { config: {}, cases: [], companies: [], playbooks: [] };
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const money = value => new Intl.NumberFormat('es-CL', {style:'currency', currency:'CLP', maximumFractionDigits:0}).format(Number(value || 0));

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
    dashboard:['Resumen','Contratos detectados, bloqueos y próximas acciones.'],
    cases:['Casos','De la señal pública al cierre administrativo.'],
    companies:['Empresas','Relaciona proveedores con los casos detectados.'],
    scan:['Descubrir','Convierte fuentes públicas en casos accionables.'],
    auto:['Auto','Prospección automática con aprobación humana antes del envío.'],
    detail:['Detalle del caso','Diagnóstico, documentos, acciones y línea de tiempo.'],
  };
  const t = titles[view] || titles.dashboard;
  $('page-title').textContent = t[0];
  $('page-subtitle').textContent = t[1];
}

const caseName = c => c.company_name || c.detected_company_name || 'Empresa por confirmar';

async function loadHealth() {
  try {
    const h = await api('/api/health');
    $('health').textContent = `Sistema operativo · v${h.version}`;
  } catch (_) {
    $('health').textContent = 'Sistema no disponible';
  }
}

async function loadDashboard() {
  const [d, cases] = await Promise.all([api('/api/dashboard'), api('/api/cases')]);
  $('metrics').innerHTML = [
    ['Casos activos', d.active_cases || 0], ['Resueltos', d.resolved_cases || 0],
    ['Acciones abiertas', d.open_actions || 0], ['Docs faltantes', d.missing_documents || 0],
    ['Mayor monto observado', money(d.largest_observed_amount_clp || 0)],
  ].map(([label,value]) => `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div></div>`).join('');
  $('priority-cases').innerHTML = cases.length ? cases.slice(0,7).map(c => `<div class="list-item clickable-case" data-case="${c.id}"><div class="list-title">${esc(caseName(c))}</div><div class="list-meta">${esc(c.contract_ref || c.external_id)} · prioridad ${c.financial_priority} · ${money(c.largest_amount_clp)}</div></div>`).join('') : '<div class="empty">Todavía no hay casos.</div>';
  $('blockers').innerHTML = d.blockers?.length ? d.blockers.map(b => `<div class="list-item"><div class="list-title">${esc(b.blocker || 'UNKNOWN')}</div><div class="list-meta">${b.count} caso(s)</div></div>`).join('') : '<div class="empty">Sin bloqueos activos.</div>';
  bindCaseLinks();
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
  const c = await api(`/api/cases/${id}`);
  setView('detail');
  $('detail-title').innerHTML = `<h2>${esc(caseName(c))}</h2><div class="list-meta">${esc(c.contract_ref || c.external_id)}</div>`;
  const companyOptions = [`<option value="">Sin vincular</option>`, ...state.companies.map(x => `<option value="${x.id}" ${x.id === c.company_id ? 'selected' : ''}>${esc(x.name)}</option>`)].join('');
  const statuses = ['DETECTED','VALIDATING','BLOCKER_IDENTIFIED','ACTION_REQUIRED','DOCUMENT_SENT','WAITING_AGENCY','FOLLOW_UP','RESOLVED','DISMISSED'];
  const statusOptions = statuses.map(s => `<option ${s === c.status ? 'selected' : ''}>${s}</option>`).join('');
  const blockerOptions = state.playbooks.map(p => `<option value="${esc(p.blocker)}" ${p.blocker === c.current_blocker ? 'selected' : ''}>${esc(p.title)}</option>`).join('');
  const pb = c.playbook || {};
  $('case-detail').innerHTML = `<div class="detail-grid"><div class="detail-column">
    <article class="card"><h2>Diagnóstico</h2><dl class="kv"><dt>Bloqueo</dt><dd>${esc(c.current_blocker || 'UNKNOWN')}</dd><dt>Organismo</dt><dd>${esc(c.agency || 'Por confirmar')}</dd><dt>Prioridad</dt><dd>${c.financial_priority}/100</dd></dl></article>
    <article class="card"><h2>Resolution Playbook</h2><p><strong>${esc(pb.title || '')}</strong></p><p class="muted">${esc(pb.goal || '')}</p>${pb.next_step ? `<div class="notice"><strong>Siguiente acción</strong><br>${esc(pb.next_step.title || '')}</div>` : ''}<button id="apply-playbook">Aplicar playbook</button></article>
    <article class="card"><h2>Acciones</h2>${(c.actions || []).map(a => `<div class="list-item"><strong>${esc(a.title)}</strong><div class="list-meta">${esc(a.status)}${a.due_date ? ` · ${esc(a.due_date)}` : ''}</div></div>`).join('') || '<div class="empty">Sin acciones.</div>'}<button id="add-action">Agregar acción</button></article>
  </div><div class="detail-column">
    <article class="card"><h2>Control</h2><div class="stack"><label>Estado<select id="detail-status">${statusOptions}</select></label><label>Bloqueo<select id="detail-blocker">${blockerOptions}</select></label><label>Empresa<select id="detail-company">${companyOptions}</select></label></div></article>
    <article class="card"><h2>Montos observados</h2><div class="amount-big">${money(c.financial?.largest_observed_amount_clp || 0)}</div><div class="warning">${esc(c.financial?.warning || '')}</div></article>
    <article class="card"><h2>Fuente pública</h2>${c.detail_url ? `<p><a href="${esc(c.detail_url)}" target="_blank" rel="noopener">Abrir antecedente original</a></p>` : ''}<div class="source-text">${esc(c.detail_text || c.raw_text || '')}</div></article>
  </div></div>`;
  $('detail-status').onchange = async e => { await api(`/api/cases/${c.id}/status`, {method:'PATCH', body:JSON.stringify({status:e.target.value})}); toast('Estado actualizado'); openCase(c.id); };
  $('detail-blocker').onchange = async e => { await api(`/api/cases/${c.id}/blocker`, {method:'PATCH', body:JSON.stringify({blocker:e.target.value, reason:null})}); toast('Bloqueo actualizado'); openCase(c.id); };
  $('detail-company').onchange = async e => { if (!e.target.value) return; await api(`/api/cases/${c.id}/company`, {method:'PATCH', body:JSON.stringify({company_id:Number(e.target.value)})}); toast('Empresa vinculada'); openCase(c.id); };
  $('apply-playbook').onclick = async () => { await api(`/api/cases/${c.id}/playbook/apply`, {method:'POST'}); toast('Playbook aplicado'); openCase(c.id); };
  $('add-action').onclick = async () => { const title = prompt('Nueva acción'); if (!title) return; await api(`/api/cases/${c.id}/actions`, {method:'POST', body:JSON.stringify({title})}); toast('Acción creada'); openCase(c.id); };
}

async function loadAuto() {
  const [status, queue, runs] = await Promise.all([api('/api/auto/status'), api('/api/outreach'), api('/api/auto/runs')]);
  const counts = status.queue_counts || {};
  $('auto-metrics').innerHTML = [['Por aprobar',counts.READY_FOR_APPROVAL||0],['Sin contacto',counts.NEEDS_CONTACT||0],['Aprobados',counts.APPROVED||0],['Enviados',counts.SENT||0]].map(([label,value]) => `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div></div>`).join('');
  const last = status.last_run;
  $('auto-status').innerHTML = last ? `Último ciclo: <strong>${esc(last.status)}</strong> · ${last.cases_created} caso(s) nuevo(s) · ${last.drafts_created} borrador(es) · ${last.contacts_found} contacto(s).` : 'Todavía no se ha ejecutado Case Hunter Auto.';
  $('auto-runs').innerHTML = runs.length ? runs.slice(0,8).map(r => `<div class="list-item"><div class="list-title">${esc(r.status)}</div><div class="list-meta">${esc(r.started_at)} · ${r.cases_created} nuevos · ${r.drafts_created} borradores${r.error ? ` · ${esc(r.error)}` : ''}</div></div>`).join('') : '<div class="empty">Sin ciclos.</div>';
  $('outreach-queue').innerHTML = queue.length ? `<table><thead><tr><th>Empresa</th><th>Prioridad</th><th>Destinatario</th><th>Estado</th><th>Acción</th></tr></thead><tbody>${queue.map(m => `<tr><td><strong>${esc(m.detected_company_name || 'Empresa por confirmar')}</strong><div class="list-meta">${esc(m.contract_ref || '')}</div><details><summary>Ver correo</summary><div class="source-text">${esc(m.body)}</div></details></td><td>${m.financial_priority}</td><td>${esc(m.recipient_email || 'No encontrado')}</td><td>${esc(m.status)}</td><td>${outreachActions(m)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">La cola está vacía.</div>';
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
  document.querySelectorAll('.outreach-approve-send').forEach(btn => btn.onclick = async () => { try { await api(`/api/outreach/${btn.dataset.id}/approve`, {method:'POST', body:JSON.stringify({recipient_email:null})}); if (state.config.smtp_configured) { await api(`/api/outreach/${btn.dataset.id}/send`, {method:'POST'}); toast('Aprobado y enviado'); } else toast('Aprobado. Configura SMTP para enviar.'); loadAuto(); } catch(e) { toast(e.message); } });
  document.querySelectorAll('.outreach-send').forEach(btn => btn.onclick = async () => { try { await api(`/api/outreach/${btn.dataset.id}/send`, {method:'POST'}); toast('Correo enviado'); loadAuto(); } catch(e) { toast(e.message); } });
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
  $('case-status').onchange = loadCases;
  $('case-search').onkeydown = e => { if (e.key === 'Enter') loadCases(); };
  $('company-form').onsubmit = async e => { e.preventDefault(); try { await api('/api/companies', {method:'POST', body:JSON.stringify({name:$('company-name').value, rut:$('company-rut').value || null})}); e.target.reset(); toast('Empresa guardada'); await loadCompanies(); } catch(err) { toast(err.message); } };
  $('auto-run').onclick = async () => { const b=$('auto-run'); b.disabled=true; b.textContent='Ejecutando…'; try { const r=await api('/api/auto/run',{method:'POST',body:JSON.stringify({})}); toast(`Auto: ${r.cases_created} casos nuevos, ${r.drafts_created} borradores.`); await Promise.all([loadAuto(),loadDashboard()]); } catch(e) { toast(e.message); } finally { b.disabled=false; b.textContent='Ejecutar ahora'; } };
  $('auto-refresh').onclick = loadAuto;
  $('scan-form').onsubmit = async e => { e.preventDefault(); const b=$('scan-button'); b.disabled=true; b.textContent='Escaneando…'; try { const r=await api('/api/scans/ley-lobby',{method:'POST',body:JSON.stringify({url:$('scan-url').value,max_pages:Number($('scan-pages').value),enrich:true,enrich_limit:Number($('scan-enrich').value)})}); $('scan-result').classList.remove('hidden'); $('scan-result').textContent=`Listo. ${r.scan.pages_scanned} página(s), ${r.scan.candidate_count} candidato(s), ${r.import.created} caso(s) nuevo(s).`; await Promise.all([loadScans(),loadDashboard()]); } catch(err) { toast(err.message); } finally { b.disabled=false; b.textContent='Iniciar escaneo'; } };
}

boot().catch(err => toast(err.message));
