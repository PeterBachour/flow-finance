(()=>{
  const ID='financialVisualization';
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:0}).format((Number(c)||0)/100);
  const euro2=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const monthShort=value=>{const [y,m]=String(value||'').split('-');if(!y||!m)return value||'—';return new Intl.DateTimeFormat('fr-FR',{month:'short'}).format(new Date(Number(y),Number(m)-1,1)).replace('.','');};
  const dateShort=value=>{if(!value)return '—';const d=new Date(`${value}T12:00:00`);return new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short'}).format(d);};

  function lineChart(timeline,reserve){
    const rows=(timeline||[]).filter((_,i,arr)=>i===0||i===arr.length-1||i%3===0);
    if(rows.length<2)return '<p class="fv-empty">Trajectoire indisponible.</p>';
    const values=rows.map(r=>{
      const closing=Number(r.closing_balance_cents||0);
      const protectedStatic=Number(r.protected_static_cents||0);
      const plannedStatic=Math.max(0,protectedStatic-Number(reserve||0));
      const variable=Number(r.expected_variable_spend_cents||0);
      return closing-plannedStatic-variable;
    });
    const all=[...values,Number(reserve||0)];
    const min=Math.min(...all),max=Math.max(...all);
    const span=Math.max(1,max-min);
    const w=600,h=180,p=22;
    const points=values.map((v,i)=>`${p+i*(w-2*p)/(values.length-1)},${p+(max-v)*(h-2*p)/span}`).join(' ');
    const reserveY=p+(max-Number(reserve||0))*(h-2*p)/span;
    return `<div class="fv-line-wrap"><svg class="fv-line" viewBox="0 0 ${w} ${h}" role="img" aria-label="Trajectoire du solde projeté"><line x1="${p}" y1="${reserveY}" x2="${w-p}" y2="${reserveY}" class="fv-reserve-line"/><polyline points="${points}" class="fv-line-path"/>${values.map((v,i)=>{const x=p+i*(w-2*p)/(values.length-1),y=p+(max-v)*(h-2*p)/span;return `<circle cx="${x}" cy="${y}" r="4" class="fv-dot"><title>${dateShort(rows[i].date)} : ${euro2(v)}</title></circle>`}).join('')}</svg><div class="fv-axis"><span>${dateShort(rows[0].date)}</span><span>Réserve ${euro2(reserve)}</span><span>${dateShort(rows[rows.length-1].date)}</span></div></div>`;
  }

  function historyChart(months){
    const rows=(months||[]).slice(-6);
    const max=Math.max(1,...rows.map(r=>Number(r.variable_cents||0)));
    return `<div class="fv-bars">${rows.map(r=>{const value=Number(r.variable_cents||0);const height=Math.max(4,Math.round(value/max*100));return `<div class="fv-bar-col"><strong>${euro(value)}</strong><div class="fv-bar-track"><i style="height:${height}%"></i></div><span>${monthShort(r.month)}</span></div>`}).join('')}</div>`;
  }

  function categoryBars(categories){
    const rows=(categories||[]).slice(0,6);
    if(!rows.length)return '<p class="fv-empty">Pas assez de données catégorisées.</p>';
    return `<div class="fv-category-list">${rows.map(r=>`<div class="fv-category"><div><span>${r.category}</span><strong>${euro2(r.amount_cents)}</strong></div><div class="fv-category-track"><i style="width:${Math.max(2,Number(r.share_pct||0))}%"></i></div><small>${Number(r.share_pct||0).toFixed(1).replace('.',',')} % des dépenses variables sur 6 mois</small></div>`).join('')}</div>`;
  }

  function render(intel,visual){
    const forecast=intel.forecast||{};
    const trends=intel.trends||{};
    const windows=trends.windows||{};
    const safe=intel.safe_to_spend||{};
    const pos=intel.current_position||{};
    const projected=Number(forecast.projected_bank_balance_at_horizon_cents||0);
    const margin=Number(forecast.projected_margin_above_safety_cents||0);
    const reserve=Number(safe.safety_reserve_cents||0);
    const currentProjection=Number(pos.projected_full_month_cents||0);
    const baseline=Number(pos.baseline_variable_month_median_cents||0);
    const delta=baseline?Math.round((currentProjection-baseline)/baseline*100):null;
    return `<section class="fv-stack" id="${ID}">
      <section class="card fv-card">
        <div class="section-head"><div><p class="eyebrow">Trajectoire</p><h2>Jusqu’au prochain salaire</h2></div><span class="fv-kpi">${euro2(projected)} projetés</span></div>
        ${lineChart(forecast.timeline,reserve)}
        <div class="fv-caption"><span>Safe aujourd’hui <strong>${euro2(safe.safe_to_spend_cents)}</strong></span><span>Marge fin de cycle <strong>${euro2(margin)}</strong></span></div>
      </section>

      <section class="card fv-card">
        <div class="section-head"><div><p class="eyebrow">Tendance</p><h2>Dépenses variables</h2></div><span class="fv-kpi">6 mois</span></div>
        ${historyChart(visual.monthly_variable)}
        <div class="fv-window-grid">
          ${['3m','6m','12m'].map(key=>{const w=windows[key]||{};return `<div><span>${key.replace('m',' mois')}</span><strong>${euro2(w.variable_avg_cents)}</strong><small>moyenne mensuelle</small></div>`}).join('')}
        </div>
      </section>

      <section class="card fv-card">
        <div class="section-head"><div><p class="eyebrow">Répartition</p><h2>Où part le variable</h2></div><span class="fv-kpi">${euro2(visual.total_variable_cents)}</span></div>
        ${categoryBars(visual.categories)}
      </section>

      <section class="card fv-card fv-current">
        <div class="section-head"><div><p class="eyebrow">Mois estimé</p><h2>Position par rapport à ton historique</h2></div></div>
        <div class="fv-compare">
          <div><span>Projection du mois</span><strong>${euro2(currentProjection)}</strong></div>
          <div><span>Médiane historique</span><strong>${euro2(baseline)}</strong></div>
          <div><span>Écart estimé</span><strong>${delta==null?'—':`${delta>=0?'+':''}${delta} %`}</strong></div>
        </div>
        <p class="subtle">Cette comparaison reste estimative tant que le relevé du mois courant n’est pas consolidé. Elle ne transforme pas la variation de solde en catégories fictives.</p>
      </section>
    </section>`;
  }

  let busy=false;
  async function inject(){
    if(busy)return;
    const root=document.querySelector('[data-screen="home"]');
    if(!root||!root.classList.contains('active')||document.getElementById(ID))return;
    const anchor=document.getElementById('commitmentEngineCard')||document.getElementById('decisionBudgetCard')||document.getElementById('financialIntelligenceCard');
    if(!anchor)return;
    busy=true;
    try{
      const [ir,vr]=await Promise.all([
        fetch('/api/finance/intelligence?history_months=12',{cache:'no-store'}),
        fetch('/api/finance/visualization?months=6',{cache:'no-store'})
      ]);
      if(!ir.ok||!vr.ok)throw new Error('visualization unavailable');
      const intel=await ir.json(),visual=await vr.json();
      if(!document.getElementById(ID))anchor.insertAdjacentHTML('afterend',render(intel,visual));
    }catch(_){/* Visualization is secondary and must never block the cockpit. */}
    finally{busy=false;}
  }
  const observer=new MutationObserver(()=>queueMicrotask(inject));
  const start=()=>{const home=document.querySelector('[data-screen="home"]');if(home)observer.observe(home,{childList:true,subtree:false});document.querySelectorAll('[data-nav="home"]').forEach(btn=>btn.addEventListener('click',()=>setTimeout(inject,0)));inject();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
