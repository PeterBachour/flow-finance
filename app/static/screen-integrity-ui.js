(()=>{
  const MONTH_ID='canonicalCurrentMonth';
  const MOVEMENT_ID='canonicalMovementNotice';
  let cache=null;
  let cacheAt=0;

  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const fmtDate=value=>{
    if(!value)return '—';
    const d=new Date(`${value}T12:00:00`);
    return Number.isNaN(d.getTime())?value:new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short'}).format(d);
  };
  const localMonth=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;};
  const currentMonthLabel=()=>new Intl.DateTimeFormat('fr-FR',{month:'long',year:'numeric'}).format(new Date());

  async function intel(){
    if(cache&&Date.now()-cacheAt<15000)return cache;
    const r=await fetch('/api/finance/intelligence?history_months=12',{cache:'no-store'});
    if(!r.ok)throw new Error(`HTTP ${r.status}`);
    cache=await r.json();
    cacheAt=Date.now();
    return cache;
  }

  function restoreMonth(root){
    document.getElementById(MONTH_ID)?.remove();
    root.querySelectorAll('[data-canonical-suppressed="1"]').forEach(el=>{el.hidden=false;delete el.dataset.canonicalSuppressed;});
  }

  async function enhanceMonth(){
    const root=document.querySelector('[data-screen="month"]');
    if(!root||!root.classList.contains('active'))return;
    const toolbar=root.querySelector('.month-toolbar');
    const displayed=toolbar?.querySelector('.month-title small')?.textContent?.trim();
    if(!toolbar||displayed!==localMonth()){restoreMonth(root);return;}
    try{
      const data=await intel();
      const q=data.data_quality||{};
      if(q.decision_mode!=='month_estimated')return;
      const safe=data.safe_to_spend||{};
      const forecast=data.forecast||{};
      const h=data.headline||{};
      const p=data.current_position||{};
      const commitments=Number(safe.planned_commitments_cents||0)+Number(safe.recurring_commitments_cents||0)+Number(safe.goal_contributions_cents||0);
      const projectedBank=Number(forecast.projected_bank_balance_at_horizon_cents||0);
      const margin=Number(forecast.projected_margin_above_safety_cents||0);
      const variable=Number(forecast.projected_variable_to_horizon_cents||0);
      const daily=Number(h.recommended_daily_spend_cents??p.recommended_daily_spend_cents??forecast.variable_daily_rate_cents??0);

      if(!document.getElementById(MONTH_ID)){
        toolbar.insertAdjacentHTML('afterend',`<section id="${MONTH_ID}" class="canonical-month-stack">
          <section class="card canonical-month-banner">
            <div class="section-head"><div><p class="eyebrow">Mois en cours · estimé</p><h2>Pilotage de ${currentMonthLabel()}</h2></div><span class="chip active">Solde réel</span></div>
            <p class="subtle">Le relevé détaillé du mois n’est disponible qu’à la clôture. Flow n’affiche donc pas de faux revenus ou dépenses à 0 € : le pilotage courant s’appuie sur le solde réel et les projections validées.</p>
          </section>
          <section class="metric-grid canonical-month-metrics">
            <article class="card metric metric-accent"><span>Solde réel</span><strong>${euro(safe.balance_cents)}</strong><small>au ${fmtDate(q.balance_as_of)}</small></article>
            <article class="card metric"><span>Safe disponible</span><strong>${euro(safe.safe_to_spend_cents)}</strong><small>jusqu’au salaire</small></article>
            <article class="card metric"><span>Solde projeté</span><strong>${euro(projectedBank)}</strong><small>au ${fmtDate(forecast.horizon_end)}</small></article>
            <article class="card metric"><span>Marge fin de cycle</span><strong>${euro(margin)}</strong><small>au-dessus de la réserve</small></article>
          </section>
          <section class="card canonical-month-details">
            <div class="section-head"><div><p class="eyebrow">Projection</p><h2>Ce qui reste à absorber</h2></div></div>
            <div class="fi-metrics">
              <div><span>Variable projeté</span><strong>${euro(variable)}</strong></div>
              <div><span>Engagements protégés</span><strong>${euro(commitments)}</strong></div>
              <div><span>Réserve de sécurité</span><strong>${euro(safe.safety_reserve_cents)}</strong></div>
              <div><span>Rythme conseillé</span><strong>${euro(daily)}/j</strong></div>
            </div>
            <p class="fi-note"><strong>Dernier mois consolidé :</strong> relevé arrêté au ${fmtDate(q.statement_coverage_end)}. Les catégories du mois courant seront disponibles après import du relevé de clôture.</p>
          </section>
        </section>`);
      }

      Array.from(root.children).forEach(el=>{
        if(el===toolbar||el.id===MONTH_ID||el.classList.contains('page-head'))return;
        if(!el.hidden){el.hidden=true;el.dataset.canonicalSuppressed='1';}
      });
    }catch(_){/* Keep legacy month screen if canonical intelligence is unavailable. */}
  }

  async function enhanceMovements(){
    const root=document.querySelector('[data-screen="movements"]');
    if(!root||!root.classList.contains('active'))return;
    const listCard=root.querySelector('.movement-list')?.closest('.card');
    const displayedLabel=listCard?.querySelector('.eyebrow')?.textContent?.trim()?.toLocaleLowerCase('fr-FR');
    const isCurrent=displayedLabel===currentMonthLabel().toLocaleLowerCase('fr-FR');
    if(!isCurrent){document.getElementById(MOVEMENT_ID)?.remove();return;}
    try{
      const data=await intel();
      const q=data.data_quality||{};
      const p=data.current_position||{};
      if(q.decision_mode!=='month_estimated')return;
      if(!document.getElementById(MOVEMENT_ID)){
        const toolbar=root.querySelector('.toolbar');
        toolbar?.insertAdjacentHTML('afterend',`<section id="${MOVEMENT_ID}" class="card canonical-movement-notice">
          <div class="section-head"><div><p class="eyebrow">Relevé mensuel en attente</p><h2>Le détail de ${currentMonthLabel()} n’est pas encore consolidé</h2></div></div>
          <p class="subtle">Un écran vide ici ne signifie pas 0 € dépensé. Le dernier relevé consolidé s’arrête au ${fmtDate(q.statement_coverage_end)}. Depuis cette date, le solde réel a évolué de <strong>${euro(p.net_balance_change_cents)}</strong>, sans que Flow invente la nature des mouvements.</p>
        </section>`);
      }
      const empty=listCard?.querySelector('.empty-state');
      const emptyText=`Aucun mouvement consolidé pour ${currentMonthLabel()} : le relevé de fin de mois est encore en attente.`;
      if(empty&&empty.textContent!==emptyText)empty.textContent=emptyText;
      const pageCopy=root.querySelector('.page-head .subtle');
      const copy='Historique consolidé des opérations. Le mois courant reste estimé jusqu’au relevé de clôture.';
      if(pageCopy&&pageCopy.textContent!==copy)pageCopy.textContent=copy;
    }catch(_){/* Non-blocking display clarification. */}
  }

  function enhance(){enhanceMonth();enhanceMovements();}
  const observer=new MutationObserver(()=>queueMicrotask(enhance));
  const start=()=>{document.querySelectorAll('.screen').forEach(screen=>observer.observe(screen,{childList:true,subtree:true}));document.querySelectorAll('[data-nav]').forEach(btn=>btn.addEventListener('click',()=>setTimeout(enhance,0)));enhance();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
