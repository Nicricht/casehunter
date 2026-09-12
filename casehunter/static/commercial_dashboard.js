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
    NEW: { label: 'Trabajar investigación', action: 'open-case' },
    RESEARCHED: { label: 'Trabajar investigación', action: 'open-case' },
    CONTACT_READY: { label: 'Revisar borrador', action: 'open-auto' },
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
      <button class="secondary commercial-open" data-case="${Number(item.id)}">Abrir caso</button>
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

  async function openAutoWorkspace() {
    setView('auto');
    await loadAuto();
    $('outreach-queue')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
    document.querySelectorAll('.commercial-open').forEach(button => {
      button.onclick = event => {
        event.stopPropagation();
        openCase(Number(button.dataset.case));
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
