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

  function stageLabel(stage) {
    return STAGE_LABELS[stage] || String(stage || 'Sin etapa');
  }

  function scoreBadge(score) {
    const value = Math.max(0, Math.min(100, Number(score || 0)));
    const cls = value >= 80 ? 'resolved' : value >= 60 ? 'follow' : value >= 40 ? 'medium' : '';
    return `<span class="badge ${cls}">${value}/100</span>`;
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
    </div>`;
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
