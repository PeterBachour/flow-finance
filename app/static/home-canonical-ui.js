(()=>{
  const euro=cents=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(cents)||0)/100);
  const fmtDate=value=>{
    if(!value)return '—';
    const d=new Date(`${value}T12:00:00`);
    return Number.isNaN(d.getTime())?value:new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short'}).format(d);
  };
  const confidenceLabel=value=>({high:'Confiance élevée',medium:'Confiance moyenne',low:'Confiance faible'})[value]||'Confiance à vérifier';
  const modeLabel=value=>value==='month_estimated'?'Mois estimé':value==='month_consolidated'?'Mois consolidé':'Pilotage financier';
  let busy=false;

  async function refresh(){
    if(busy)return;
    const home=document.querySelector('[data-screen="home"]');
    const hero=home?.querySelector('.card.hero');
    if(!home||!hero||!home.classList.contains('active')||hero.dataset.canonicalFinance==='true')return;
    busy=true;
    try{
      const [intelResponse,commitmentResponse]=await Promise.all([
        fetch('/api/finance/intelligence?history_months=12',{cache:'no-store'}),
        fetch('/api/finance/commitments',{cache:'no-store'})
      ]);
      if(!intelResponse.ok)throw new Error(`HTTP ${intelResponse.status}`);
      const data=await intelResponse.json();
      const commitments=commitmentResponse.ok?await commitmentResponse.json():null;
      const headline=data.headline||{};
      const safe=data.safe_to_spend||{};
      const forecast=data.forecast||{};
      const position=data.current_position||{};
      const quality=data.data_quality||{};
      const daily=Number(headline.recommended_daily_spend_cents ?? position.recommended_daily_spend_cents ?? headline.variable_daily_rate_cents ?? 0);
      const safeAmount=Number(headline.safe_to_spend_cents ?? safe.safe_to_spend_cents ?? 0);
      const balance=Number(safe.balance_cents ?? position.current_balance_cents ?? 0);
      const days=Number(safe.horizon_days ?? position.days_to_horizon ?? 0);
      const projectedBank=Number(forecast.projected_bank_balance_at_horizon_cents ?? 0);
      const projectedMargin=Number(forecast.projected_margin_above_safety_cents ?? headline.expected_remaining_at_horizon_cents ?? 0);
      const variableProjected=Number(forecast.projected_variable_to_horizon_cents||0);
      const protected=Number(commitments?.summary?.protected_confirmed_cents ?? (Number(safe.planned_commitments_cents||0)+Number(safe.recurring_commitments_cents||0)+Number(safe.goal_contributions_cents||0)));
      const reserve=Number(safe.safety_reserve_cents||0);
      const mode=headline.decision_mode||quality.decision_mode;
      const confidence=headline.trend_confidence||quality.trend_confidence;

      hero.innerHTML=`
        <div class="hero-top"><span class="status-pill" data-status="comfortable">${modeLabel(mode)}</span><span class="confidence-pill">${confidenceLabel(confidence)}</span></div>
        <p class="hero-label">Rythme conseillé aujourd’hui</p>
        <div class="hero-amount">${euro(daily)}</div>
        <p class="hero-copy">Rythme de dépense variable conseillé jusqu’au prochain salaire. Les engagements connus et la réserve de sécurité sont déjà protégés.</p>
        <div class="hero-facts">
          <div class="hero-fact"><span>Safe jusqu’au revenu</span><strong>${euro(safeAmount)}</strong><small>${days} jour(s)</small></div>
          <div class="hero-fact"><span>Solde projeté fin de cycle</span><strong>${euro(projectedBank)}</strong><small>dont ${euro(projectedMargin)} de marge</small></div>
          <div class="hero-fact"><span>Solde réel</span><strong>${euro(balance)}</strong><small>au ${fmtDate(quality.balance_as_of)}</small></div>
        </div>`;
      hero.dataset.canonicalFinance='true';

      const summary=home.querySelector('.home-summary');
      if(summary){
        summary.innerHTML=`
          <article class="card decision-card"><div class="section-head"><div><p class="eyebrow">Protection</p><h2>${euro(protected)} d’engagements</h2></div></div><p class="subtle">Sommes déjà réservées avant le prochain salaire. Elles ne font pas partie du Safe disponible.</p></article>
          <article class="card"><div class="section-head"><div><p class="eyebrow">Fin de cycle</p><h2>${euro(projectedBank)} projetés</h2></div></div><p class="subtle">Après ${euro(variableProjected)} de dépenses variables projetées. Marge au-dessus de la réserve : <strong>${euro(projectedMargin)}</strong>.</p></article>`;
      }

      const baseMetrics=home.querySelector('.metric-grid');
      if(baseMetrics){
        baseMetrics.innerHTML=`
          <article class="card metric metric-accent"><span>Safe disponible</span><strong>${euro(safeAmount)}</strong><small>jusqu’au salaire</small></article>
          <article class="card metric"><span>Engagements</span><strong>${euro(protected)}</strong><small>déjà protégés</small></article>
          <article class="card metric"><span>Réserve</span><strong>${euro(reserve)}</strong><small>minimum conservé</small></article>
          <article class="card metric"><span>Variable projeté</span><strong>${euro(variableProjected)}</strong><small>jusqu’au ${fmtDate(forecast.horizon_end)}</small></article>`;
      }
    }catch(_){
      // Keep the base cockpit if canonical finance is temporarily unavailable.
    }finally{busy=false;}
  }

  const observer=new MutationObserver(()=>queueMicrotask(refresh));
  const start=()=>{const home=document.querySelector('[data-screen="home"]');if(home)observer.observe(home,{childList:true,subtree:true});document.querySelectorAll('[data-nav="home"]').forEach(btn=>btn.addEventListener('click',()=>setTimeout(refresh,0)));refresh();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
