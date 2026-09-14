(()=>{
  const ID='decisionBudgetCard';
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const fmtDate=value=>{
    if(!value)return '—';
    const d=new Date(`${value}T12:00:00`);
    return Number.isNaN(d.getTime())?value:new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short'}).format(d);
  };

  const render=data=>{
    const h=data.headline||{};
    const safe=data.safe_to_spend||{};
    const forecast=data.forecast||{};
    const quality=data.data_quality||{};
    const pos=data.current_position||{};
    const safeAmount=Number(safe.safe_to_spend_cents||0);
    const variable=Number(forecast.projected_variable_to_horizon_cents||0);
    const margin=Math.max(0,Number(forecast.projected_margin_above_safety_cents ?? forecast.expected_remaining_after_variable_spend_cents ?? 0));
    const projectedBank=Number(forecast.projected_bank_balance_at_horizon_cents||0);
    const commitments=Number(safe.planned_commitments_cents||0)+Number(safe.recurring_commitments_cents||0)+Number(safe.goal_contributions_cents||0);
    const estimated=quality.cycle_status==='estimated'||quality.decision_mode==='month_estimated';
    const consolidated=quality.cycle_status==='consolidated'||quality.decision_mode==='month_consolidated';
    const recommended=Number(h.recommended_daily_spend_cents??pos.recommended_daily_spend_cents??forecast.variable_daily_rate_cents??0);
    const confidence=forecast.variable_projection_confidence||quality.trend_confidence||'low';
    const confidenceLabel={high:'élevée',medium:'moyenne',low:'faible'}[confidence]||confidence;
    const modeLabel=estimated?'Mois estimé':(consolidated?'Mois consolidé':'Projection');

    return `<section class="card decision-budget" id="${ID}" aria-label="Budget de décision">
      <div class="decision-budget-head">
        <div><p class="eyebrow">Décision du jour</p><h2>Combien puis-je dépenser aujourd’hui ?</h2></div>
        <span class="decision-budget-confidence ${confidence}">${modeLabel} · confiance ${confidenceLabel}</span>
      </div>
      <div class="decision-budget-main">
        <span>Rythme conseillé aujourd’hui</span>
        <strong>${euro(recommended)}</strong>
        <small>${estimated?'Rythme journalier conseillé à partir du solde réel, des engagements protégés et de l’historique.':'Calculé à partir des données consolidées disponibles.'}</small>
      </div>
      <div class="decision-budget-equation" aria-label="Explication de la marge prévisionnelle">
        <div><span>Safe disponible</span><strong>${euro(safeAmount)}</strong></div>
        <b>−</b>
        <div><span>Variable projeté</span><strong>${euro(variable)}</strong></div>
        <b>=</b>
        <div class="result"><span>Marge fin de cycle</span><strong>${euro(margin)}</strong></div>
      </div>
      <div class="decision-budget-meta">
        <span>Solde projeté au ${fmtDate(forecast.horizon_end)} : <strong>${euro(projectedBank)}</strong></span>
        <span>Engagements protégés : <strong>${euro(commitments)}</strong></span>
        <span>Réserve de sécurité : <strong>${euro(safe.safety_reserve_cents)}</strong></span>
        <span>Rythme historique : <strong>${euro(forecast.variable_daily_rate_cents)}/j</strong></span>
      </div>
      ${estimated?`<div class="decision-budget-warning"><strong>Mode estimé pendant le mois.</strong> Le détail bancaire n’est consolidé qu’à la clôture. La marge de fin de cycle n’est pas un montant à dépenser immédiatement : la référence quotidienne reste le rythme conseillé ci-dessus.</div>`:''}
      <details class="decision-budget-details"><summary>Comment lire ces montants ?</summary><p><strong>Safe disponible</strong> = solde réel moins réserve de sécurité et engagements protégés. <strong>Variable projeté</strong> = dépenses variables attendues jusqu’au prochain salaire selon l’historique. <strong>Marge fin de cycle</strong> = ce qui resterait au-dessus de la réserve si ce rythme se poursuit. <strong>Solde projeté</strong> = réserve + marge après engagements et dépenses variables estimées.</p></details>
    </section>`;
  };

  async function inject(){
    const root=document.querySelector('[data-screen="home"]');
    if(!root||!root.classList.contains('active')||document.getElementById(ID))return;
    const anchor=document.getElementById('financialIntelligenceCard')||root.querySelector('.home-summary')||root.querySelector('.card.hero');
    if(!anchor)return;
    try{
      const r=await fetch('/api/finance/intelligence?history_months=12',{cache:'no-store'});
      if(!r.ok)return;
      const data=await r.json();
      if(document.getElementById(ID))return;
      anchor.insertAdjacentHTML('afterend',render(data));
    }catch(_){/* secondary decision layer must never break the cockpit */}
  }

  const observer=new MutationObserver(()=>queueMicrotask(inject));
  const start=()=>{const home=document.querySelector('[data-screen="home"]');if(home)observer.observe(home,{childList:true,subtree:false});document.querySelectorAll('[data-nav="home"]').forEach(btn=>btn.addEventListener('click',()=>setTimeout(inject,0)));inject();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
