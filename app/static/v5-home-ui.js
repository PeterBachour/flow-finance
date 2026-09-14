(()=>{
  let busy=false;
  const shared=window.FlowV5HomeSnapshot=window.FlowV5HomeSnapshot||(()=>{
    let data=null;
    let promise=null;
    let fetchedAt=0;
    const maxAgeMs=15000;
    async function get(force=false){
      const now=Date.now();
      if(promise)return promise;
      if(data&&now-fetchedAt<maxAgeMs&&(!force||now-fetchedAt<1000))return data;
      promise=fetch('/api/v5/home-snapshot?months=6',{cache:'no-store'})
        .then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json();})
        .then(payload=>{data=payload;fetchedAt=Date.now();return payload;})
        .finally(()=>{promise=null;});
      return promise;
    }
    function invalidate(){
      data=null;
      fetchedAt=0;
      window.dispatchEvent(new Event('flow:v5-home-snapshot-invalidated'));
    }
    return {get,invalidate};
  })();
  const esc=value=>{const node=document.createElement('div');node.textContent=value??'';return node.innerHTML;};
  const euro=cents=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(cents)||0)/100);
  const fmtDate=value=>{
    if(!value)return '—';
    const d=new Date(`${String(value).slice(0,10)}T12:00:00`);
    return Number.isNaN(d.getTime())?String(value):new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short'}).format(d);
  };
  const confidenceLabel=value=>({high:'Confiance élevée',medium:'Confiance moyenne',low:'Confiance faible'})[value]||'Confiance à vérifier';
  const statusLabel=value=>({comfortable:'Confortable',prudent:'Prudent',watch:'À surveiller',critical:'Critique'})[value]||'À vérifier';

  async function refresh(force=false){
    if(busy)return;
    const home=document.querySelector('[data-screen="home"]');
    const hero=home?.querySelector('.card.hero');
    if(!home||!hero||!home.classList.contains('active'))return;
    if(!force&&home.dataset.v5Home==='true')return;
    busy=true;
    try{
      const snapshot=await shared.get(force);
      const data=snapshot.cockpit||{};
      const decision=data.decision||{};
      const protection=data.protection||{};
      const forecast=data.forecast||{};
      const confidence=data.confidence||{};
      const recommendation=decision.recommendation||{};
      const historical=data.historical_context||{};

      hero.innerHTML=`
        <div class="hero-top"><span class="status-pill" data-status="${esc(decision.status)}">${statusLabel(decision.status)}</span><span class="confidence-pill">${confidenceLabel(confidence.level)}</span></div>
        <p class="hero-label">Tu peux dépenser aujourd’hui</p>
        <div class="hero-amount">${euro(decision.daily_pace_cents)}</div>
        <p class="hero-copy">Rythme variable conseillé par le moteur V5. Les engagements connus, objectifs protégés et la réserve sont déjà pris en compte en amont.</p>
        <div class="hero-facts">
          <div class="hero-fact"><span>Safe jusqu’au revenu</span><strong>${euro(decision.safe_until_income_cents)}</strong><small>${decision.days_to_horizon||0} jour(s)</small></div>
          <div class="hero-fact"><span>Solde projeté</span><strong>${euro(forecast.projected_bank_balance_cents)}</strong><small>au ${fmtDate(forecast.horizon_end)}</small></div>
          <div class="hero-fact"><span>Solde réel</span><strong>${euro(decision.balance_cents)}</strong><small>au ${fmtDate(confidence.balance_as_of)}</small></div>
        </div>`;
      hero.dataset.v5Decision='true';

      const summary=home.querySelector('.home-summary');
      if(summary){
        summary.innerHTML=`
          <article class="card decision-card"><div class="section-head"><div><p class="eyebrow">Protection</p><h2>${euro(protection.protected_commitments_cents)}</h2></div></div><p class="subtle">Engagements confirmés protégés par le moteur canonique. Réserve de sécurité : <strong>${euro(protection.safety_reserve_cents)}</strong>.</p></article>
          <article class="card"><div class="section-head"><div><p class="eyebrow">Fin de cycle</p><h2>${euro(forecast.projected_margin_above_safety_cents)} de marge</h2></div></div><p class="subtle">Solde bancaire projeté : <strong>${euro(forecast.projected_bank_balance_cents)}</strong>. Variable projeté : <strong>${euro(forecast.projected_variable_to_horizon_cents)}</strong>.</p></article>`;
      }

      const decisionCard=[...home.querySelectorAll('.card')].find(card=>card.querySelector('.eyebrow')?.textContent?.trim()==='Décision');
      if(decisionCard){
        decisionCard.innerHTML=`<div class="section-head"><div><p class="eyebrow">Décision V5</p><h2>${esc(recommendation.title||'Maintenir le rythme')}</h2></div><span class="chip ${recommendation.severity==='critical'?'warning':'active'}">${esc(recommendation.severity||'info')}</span></div><p class="subtle">${esc(recommendation.detail||'Aucun ajustement prioritaire.')}</p>${recommendation.amount_cents!=null?`<div class="money">${euro(recommendation.amount_cents)}</div>`:''}`;
      }

      const metrics=home.querySelector('.metric-grid');
      if(metrics){
        metrics.innerHTML=`
          <article class="card metric metric-accent"><span>Safe disponible</span><strong>${euro(decision.safe_until_income_cents)}</strong><small>jusqu’au prochain revenu</small></article>
          <article class="card metric"><span>Réserve</span><strong>${euro(protection.safety_reserve_cents)}</strong><small>protégée</small></article>
          <article class="card metric"><span>Dernier mois clôturé</span><strong>${esc(historical.latest_closed_month||'—')}</strong><small>${euro(historical.latest_closed_variable_cents)} variable</small></article>
          <article class="card metric"><span>Décisions ouvertes</span><strong>${Number(data.open_financial_decisions)||0}</strong><small>${Number(data.quality_review_count)||0} revue(s) de données séparées</small></article>`;
      }

      home.dataset.v5Home='true';
    }catch(error){
      console.warn('Flow V5 home snapshot unavailable; keeping validated V4 home',error);
    }finally{busy=false;}
  }

  const observer=new MutationObserver(()=>queueMicrotask(()=>refresh(false)));
  const start=()=>{
    const home=document.querySelector('[data-screen="home"]');
    if(home)observer.observe(home,{childList:true,subtree:true});
    document.querySelectorAll('[data-nav="home"]').forEach(button=>button.addEventListener('click',()=>setTimeout(()=>refresh(true),0)));
    window.addEventListener('flow:v5-home-snapshot-invalidated',()=>setTimeout(()=>refresh(true),0));
    setTimeout(()=>refresh(false),0);
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
