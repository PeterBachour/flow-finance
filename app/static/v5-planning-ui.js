(()=>{
  let busyMonth=false,busyWealth=false;
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML;};
  const api=async(url,options={})=>{const r=await fetch(url,{cache:'no-store',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});if(!r.ok)throw new Error((await r.text())||`HTTP ${r.status}`);return r.json();};
  const monthLabel=value=>{const d=new Date(`${value}-15T12:00:00`);return new Intl.DateTimeFormat('fr-FR',{month:'short',year:'2-digit'}).format(d);};

  function planChart(months){
    if(!months?.length)return '<p class="subtle">Projection indisponible.</p>';
    const values=months.map(m=>Number(m.closing_balance_cents||0));
    const low=Math.min(...values),high=Math.max(...values),span=Math.max(1,high-low),w=640,h=130,p=14;
    const pts=values.map((v,i)=>`${p+i*(w-2*p)/Math.max(1,values.length-1)},${p+(high-v)*(h-2*p)/span}`).join(' ');
    return `<div class="v5-plan-chart"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Projection de trésorerie incluant les dépenses variables estimées"><polyline points="${pts}"/></svg><div class="v5-plan-labels">${months.map(m=>`<span>${monthLabel(m.month)}</span>`).join('')}</div></div>`;
  }

  function planHtml(data){
    const p=data.projection||{},months=p.months||[],estimate=p.variable_estimate||{};
    return `<section id="v5Planning" class="card v5-planning-card">
      <div class="section-head"><div><p class="eyebrow">V5 · Projection multi-mois</p><h2>${data.horizon_months} mois de visibilité</h2></div><span class="chip active">Estimé</span></div>
      <div class="v5-plan-kpis"><div><span>Solde projeté estimé</span><strong>${euro(p.closing_balance_cents)}</strong></div><div><span>Marge minimale estimée</span><strong>${euro(p.minimum_safe_margin_cents)}</strong></div><div><span>Protection</span><strong>${euro(p.protected_cents)}</strong></div></div>
      ${planChart(months)}
      <div class="v5-plan-estimate"><strong>${euro(p.estimated_variable_spend_cents)} de dépenses variables estimées</strong><span>Rythme utilisé : ${euro(p.variable_daily_rate_cents)}/jour · source ${esc(estimate.source||'canonique')}</span><small>Solde connu sans estimation variable : ${euro(p.known_closing_balance_cents)}</small></div>
      <details class="v5-scenario"><summary>Simuler un changement</summary><form id="v5ScenarioForm" class="v5-scenario-grid">
        <label>Dépense ponctuelle €<input name="one_time" inputmode="decimal" placeholder="0"></label>
        <label>Dépenses mensuelles + €<input name="monthly_spend" inputmode="decimal" placeholder="0"></label>
        <label>Revenu mensuel + €<input name="monthly_income" inputmode="decimal" placeholder="0"></label>
        <button class="btn secondary">Simuler</button>
      </form><div id="v5ScenarioResult"></div></details>
      <p class="subtle">${esc(data.principle||'')}</p>
    </section>`;
  }

  async function enhanceMonth(){
    if(busyMonth)return;
    const root=document.querySelector('[data-screen="month"]');
    if(!root||!root.classList.contains('active')||root.querySelector('#v5Planning'))return;
    busyMonth=true;
    try{
      const data=await api('/api/v5/plan?months=6');
      const head=root.querySelector('.page-head');if(!head)return;
      head.insertAdjacentHTML('afterend',planHtml(data));
      const form=root.querySelector('#v5ScenarioForm');
      form?.addEventListener('submit',async e=>{
        e.preventDefault();const f=e.currentTarget.elements,result=root.querySelector('#v5ScenarioResult');
        result.innerHTML='<div class="skeleton"></div>';
        const cents=v=>Math.max(0,Math.round((Number(String(v||'').replace(',','.'))||0)*100));
        try{
          const sim=await api('/api/v5/scenario',{method:'POST',body:JSON.stringify({months:6,one_time_expense_cents:cents(f.one_time.value),monthly_spend_delta_cents:cents(f.monthly_spend.value),monthly_income_delta_cents:cents(f.monthly_income.value)})});
          const cls=sim.verdict==='compatible'?'positive':sim.verdict==='caution'?'warning':'danger';
          result.innerHTML=`<div class="v5-scenario-result ${cls}"><strong>${esc(sim.verdict_label)}</strong><span>Solde final estimé ${euro(sim.simulated?.closing_balance_cents)} · impact ${euro(sim.impact?.closing_balance_delta_cents)}</span><span>Marge minimale estimée ${euro(sim.simulated?.minimum_safe_margin_cents)}</span><small>${esc(sim.principle)}</small></div>`;
        }catch(err){result.innerHTML=`<div class="notice">Simulation indisponible : ${esc(err.message)}</div>`;}
      });
    }catch(_){/* V4 month remains available */}finally{busyMonth=false;}
  }

  function goalsHtml(data){
    const arb=data.goal_arbitration||{},goals=arb.goals||[];
    return `<section id="v5GoalArbitration" class="card v5-goal-arbitration">
      <div class="section-head"><div><p class="eyebrow">V5 · Arbitrage</p><h2>Ordre conseillé des objectifs</h2></div><span class="chip">${euro(arb.monthly_capacity_cents)}/mois</span></div>
      <div class="v5-goal-list">${goals.map((g,i)=>`<article><span class="v5-rank">${i+1}</span><div><strong>${esc(g.name)}</strong><small>${esc(g.reason)}</small><div class="v5-goal-meta"><span>Requis ${g.required_monthly_cents==null?'—':euro(g.required_monthly_cents)+'/mois'}</span><span>Conseillé ${euro(g.recommended_monthly_cents)}/mois</span>${g.funding_gap_cents>0?`<span class="danger">Écart ${euro(g.funding_gap_cents)}</span>`:''}</div></div></article>`).join('')||'<div class="empty-state">Aucun objectif actif.</div>'}</div>
      <p class="subtle">${esc(arb.method||'')}</p>
    </section>`;
  }

  async function enhanceWealth(){
    if(busyWealth)return;
    const root=document.querySelector('[data-screen="wealth"]');
    if(!root||!root.classList.contains('active')||root.querySelector('#v5GoalArbitration'))return;
    busyWealth=true;
    try{
      const data=await api('/api/v5/plan?months=6');
      const target=root.querySelector('#wealthDecisionView,#wealthQualityView')||root.querySelector('.page-head');
      if(target)target.insertAdjacentHTML('afterend',goalsHtml(data));
    }catch(_){/* existing wealth remains available */}finally{busyWealth=false;}
  }

  const observer=new MutationObserver(()=>queueMicrotask(()=>{enhanceMonth();enhanceWealth();}));
  const start=()=>{
    const app=document.getElementById('app');if(app)observer.observe(app,{childList:true,subtree:true});
    document.querySelectorAll('[data-nav="month"]').forEach(b=>b.addEventListener('click',()=>setTimeout(enhanceMonth,60)));
    document.querySelectorAll('[data-nav="wealth"]').forEach(b=>b.addEventListener('click',()=>setTimeout(enhanceWealth,60)));
    enhanceMonth();enhanceWealth();
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
