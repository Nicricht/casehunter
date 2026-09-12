(() => {
  const STAGE_LABELS = {
    NEW: 'Nuevo',
    RESEARCHED: 'Investigado',
    CONTACT_READY: 'Contacto listo',
    CONTACTED: 'Contactado',
    REPLIED: 'Respondió',
    QUALIFIED: 'Calificado',
    WATCHING: 'En seguimiento',
    CASE_RESOLVED: 'Resuelto',
    CLOSED: 'Cerrado',
  };

  const STAGE_ACTIONS = {
    NEW: { label: 'Preparar prospecto', action: 'prepare-prospect' },
    RESEARCHED: { label: 'Preparar prospecto', action: 'prepare-prospect' },
    CONTACT_READY: { label: 'Revisar dossier', action: 'show-prospect' },
    CONTACTED: { label: 'Sincronizar respuestas', action: 'sync-mail' },
    REPLIED: { label: 'Revisar respuesta', action: 'open-auto' },
    QUALIFIED: { label: 'Aplicar recomendación', action: 'apply-recommendation' },
    WATCHING: { label: 'Actualizar seguimiento', action: 'sync-mail' },
  };

  function stageLabel(stage) {
    return STAGE_LABELS[stage] || String(stage || 'Sin etapa');
  }

  function scoreBadge(score) {
    const value = Math.max(0, Math.min(100, Number(score || 0)));
    const cls = value >= 80 ? 'resolved' : value >= 60 ? 'follow' : value >= 40 ? 'medium' : '';
    return `<span class="badge ${cls}">${value}/100</span>`;
  }

  function actionHtml(item) {
    const spec = STAGE_ACTIONS[item.commercial_stage];
    if (!spec) return '';
    return `<div class="rec-actions" style="margin-top:10px">
      <button class="commercial-next" data-case="${Number(item.id)}" data-action="${esc(spec.action)}">${esc(spec.label)}</button>
      <button class="secondary commercial-dossier" data-case="${Number(item.id)}">Ver dossier</button>
    </div>`;
  }

  function opportunityHtml(item) {
    const reasons = (item.opportunity_reasons || []).slice(0, 3).join(' · ');
    const company = item.detected_company_name || 'Empresa por confirmar';
    const context = [item.contract_ref, item.agency].filter(Boolean).join(' · ');
    return `<div class="list-item clickable-case" data-case="${Number(item.id)}">
      <div class="pilot-hero-head">
        <div>
          <div class="list-title">${esc(company)}</div>
          <div class="list-meta">${esc(context || 'Caso público en evaluación')}</div>
        </div>
        <div>${scoreBadge(item.opportunity_score)} <span class="badge">${esc(stageLabel(item.commercial_stage))}</span></div>
      </div>
      ${reasons ? `<div class="list-meta">${esc(reasons)}</div>` : ''}
      <div class="notice"><strong>Siguiente movimiento</strong><br>${esc(item.next_commercial_move || 'Revisar el caso y definir la siguiente acción.')}</div>
      ${actionHtml(item)}
    </div>`;
  }

  function factValue(value) {
    if (Array.isArray(value)) return value.map(item => esc(item)).join(' · ');
    if (typeof value === 'number') return money(value);
    return esc(value ?? '');
  }

  function prospectDossierHtml(dossier) {
    const facts = (dossier.confirmed_facts || []).map(item => `
      <div class="pilot-fact"><span>${esc(item.label)}</span><strong>${factValue(item.value)}</strong></div>`).join('');
    const pending = (dossier.pending_validation || []).map(item => `<div class="evidence-item">${esc(item)}</div>`).join('');
    const sources = (dossier.evidence_sources || []).map(item => {
      const link = safeUrl(item.url);
      return `<div class="evidence-item"><strong>${esc(item.title || 'Fuente pública')}</strong>${item.event_date ? ` · ${esc(item.event_date)}` : ''}<br>${link === '#' ? esc(item.url || '') : `<a href="${link}" target="_blank" rel="noopener">Abrir fuente pública</a>`}</div>`;
    }).join('');
    const contact = dossier.best_contact;
    const contactHtml = contact
      ? `<div class="notice"><strong>Contacto mejor respaldado</strong><br>${esc(contact.email || '')} · confianza ${Number(contact.trust_score || 0)}/100 · ${esc(contact.trust_decision || 'REVIEW')}<br><span class="muted">${esc(contact.source_url || '')}</span></div>`
      : '<div class="notice">Todavía no existe un contacto corporativo suficientemente respaldado.</div>';
    const message = dossier.recommended_message || {};
    const messageHtml = `<div class="rec-card">
      <div class="eyebrow">BORRADOR RECOMENDADO</div>
      <div class="rec-title">${esc(message.subject || 'Sin asunto')}</div>
      <div class="list-meta">Estado ${esc(message.status || 'NOT_PREPARED')}${message.recipient_email ? ` · ${esc(message.recipient_email)}` : ''}</div>
      <div class="notice" style="white-space:pre-wrap;margin-top:10px">${esc(message.body || '')}</div>
      <div class="causality-note">Este dossier nunca aprueba ni envía el correo. La aprobación humana sigue siendo obligatoria.</div>
      <div class="rec-actions"><button class="secondary prospect-open-auto">Ir a cola de prospección</button></div>
    </div>`;
    return `<article id="prospect-dossier" class="card" style="margin-bottom:18px">
      <div class="card-head"><div><div class="eyebrow">DOSSIER COMERCIAL · 1 PÁGINA</div><h2>${esc(dossier.company || 'Empresa por confirmar')}</h2><p class="muted">${esc([dossier.contract_ref, dossier.agency].filter(Boolean).join(' · '))}</p></div><span class="badge ${dossier.ready_for_review ? 'resolved' : 'medium'}">${dossier.ready_for_review ? 'LISTO PARA REVISAR' : 'REQUIERE VALIDACIÓN'}</span></div>
      <div class="notice"><strong>Regla de evidencia</strong><br>${esc(dossier.evidence_notice || '')}</div>
      <div class="pilot-facts" style="margin-top:12px">${facts || '<div class="empty">Sin hechos estructurados todavía.</div>'}</div>
      <div class="grid two" style="margin-top:14px">
        <div><div class="eyebrow">POR VALIDAR</div>${pending || '<div class="empty">Sin pendientes registrados.</div>'}</div>
        <div><div class="eyebrow">FUENTES PÚBLICAS</div>${sources || '<div class="empty">Sin fuentes enlazadas.</div>'}</div>
      </div>
      <div style="margin-top:14px">${contactHtml}</div>
      <div style="margin-top:14px">${messageHtml}</div>
    </article>`;
  }

  async function openAutoWorkspace() {
    setView('auto');
    await loadAuto();
    $('outreach-queue')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function showProspectDossier(caseId, prepare = false) {
    const payload = prepare
      ? await api(`/api/cases/${caseId}/prospect/prepare`, { method: 'POST' })
      : await api(`/api/cases/${caseId}/prospect`);
    const dossier = payload.dossier || payload;
    await openCase(caseId);
    $('prospect-dossier')?.remove();
    $('case-detail').insertAdjacentHTML('afterbegin', prospectDossierHtml(dossier));
    document.querySelector('.prospect-open-auto')?.addEventListener('click', openAutoWorkspace);
    $('prospect-dossier')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (prepare) {
      const status = dossier.recommended_message?.status || 'NOT_PREPARED';
      toast(status === 'READY_FOR_APPROVAL'
        ? 'Prospecto preparado · contacto validado y borrador listo para revisión'
        : 'Dossier preparado · todavía falta validar un contacto antes de aprobar');
    }
  }

  async function runCommercialAction(button) {
    const caseId = Number(button.dataset.case);
    const action = button.dataset.action;
    button.disabled = true;
    try {
      if (action === 'open-case') {
        await openCase(caseId);
        return;
      }
      if (action === 'prepare-prospect') {
        await showProspectDossier(caseId, true);
        return;
      }
      if (action === 'show-prospect') {
        await showProspectDossier(caseId, false);
        return;
      }
      if (action === 'open-auto') {
        await openAutoWorkspace();
        return;
      }
      if (action === 'sync-mail') {
        const result = await api('/api/mail/sync', { method: 'POST' });
        const created = Number(result?.created || 0);
        const checked = Number(result?.checked || 0);
        const watchChanges = Number(result?.public_watch?.changes || 0);
        toast(`Sincronización lista · ${created} respuesta(s) nueva(s) · ${checked} revisada(s) · ${watchChanges} cambio(s) público(s)`);
        await renderCommercialFocus();
        return;
      }
      if (action === 'apply-recommendation') {
        const result = await api(`/api/cases/${caseId}/recommendation/apply`, { method: 'POST' });
        if (result.materialized) toast('Recomendación convertida en acción interna');
        else if (result.materialization_reason === 'equivalent_action_already_open') toast('La acción recomendada ya estaba abierta');
        else if (result.materialization_reason === 'confidence_below_threshold') toast('La evidencia aún no alcanza el umbral para materializar la acción');
        else toast('No había una recomendación aplicable todavía');
        await renderCommercialFocus();
      }
    } catch (error) {
      toast(error.message || 'No fue posible ejecutar la acción');
    } finally {
      button.disabled = false;
    }
  }

  function bindCommercialActions() {
    document.querySelectorAll('.commercial-next').forEach(button => {
      button.onclick = event => {
        event.stopPropagation();
        runCommercialAction(button);
      };
    });
    document.querySelectorAll('.commercial-dossier').forEach(button => {
      button.onclick = event => {
        event.stopPropagation();
        showProspectDossier(Number(button.dataset.case), false).catch(error => toast(error.message));
      };
    });
  }

  async function renderCommercialFocus() {
    const node = $('priority-cases');
    if (!node) return;
    try {
      const ops = await api('/api/operations?top_limit=7');
      const opportunities = ops.top_opportunities || [];
      const card = node.closest('.card');
      const title = card?.querySelector('.card-head h2');
      if (title) title.textContent = 'Oportunidades para atacar hoy';
      node.innerHTML = opportunities.length
        ? opportunities.map(opportunityHtml).join('')
        : '<div class="empty">No hay oportunidades comerciales activas en este momento.</div>';
      bindCaseLinks();
      bindCommercialActions();
    } catch (error) {
      node.innerHTML = `<div class="empty">No fue posible cargar el ranking comercial: ${esc(error.message)}</div>`;
    }
  }

  const baseLoadDashboard = loadDashboard;
  loadDashboard = async function commercialLoadDashboard() {
    await baseLoadDashboard();
    await renderCommercialFocus();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', renderCommercialFocus, { once: true });
  } else {
    renderCommercialFocus();
  }
})();
