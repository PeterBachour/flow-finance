(()=>{
  const ROOT_ID='advancedAnalysisView';
  let busy=false;
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML;};
  const signed=v=>{const n=Number(v);if(!Number.isFinite(n))return '—';return `${n>0?'+':''}${n.toFixed(1).replace('.',',')} %`;};
  const periodLabel=key=>({"3m":'3 mois',"6m":'6 mois',"12m":'12 mois'})[key]||key;

  function render(data){
    const windows=data.windows||{};
    const latest=Number(data.latest_closed_variable_cents||0);
    const ref=Number(data.prior_reference_median_cents||0);
    const delta=data.latest_vs_reference_pct;
    const trends=(data.category_trends||[]).slice(0,5);
    const signals=(data.signals||[]).slice(0,5);
    const deltaClass=delta==null?'':Number(delta)>0?'up':'down';
    return `<section id="${ROOT_ID}" class="card aa-card aa-stack">
      <div class="aa-head"><div><p class="eyebrow">Analyse historique</p><h2>Ce qui change vraiment</h2></div><span class="aa-badge">jusqu’à ${esc(data.latest_closed_month||'—')}</span></div>
      <div class="aa-kpis">${['3m','6m','12m'].map(key=>{const w=windows[key]||{};return `<div class="aa-kpi"><span>${periodLabel(key)}</span><strong>${euro(w.average_monthly_cents)}</strong><small>moyenne variable/mois</small></div>`;}).join('')}</div>
      <div class="aa-summary"><div><span>Dernier mois clôturé</span><strong>${euro(latest)}</strong><small>Référence médiane : ${euro(ref)}</small></div><div class="aa-delta ${deltaClass}">${delta==null?'Référence insuffisante':signed(delta)}</div></div>
      <details class="aa-details"><summary>Voir tendances et écarts inhabituels</summary><div class="aa-body">
        <div>${signals.length?signals.map(s=>`<div class="aa-signal"><div><strong>${esc(s.title)}</strong><small>${esc(s.detail)}</small></div><span class="aa-severity ${esc(s.severity||'watch')}">${s.severity==='high'?'Important':s.severity==='positive'?'Favorable':'À surveiller'}</span></div>`).join(''):'<p class="subtle">Aucun écart inhabituel détecté sur les données disponibles.</p>'}</div>
        <div class="aa-trends">${trends.length?trends.map(t=>`<div class="aa-trend"><div><span>${esc(t.category)}</span><small>${euro(t.previous_3m_average_cents)} → ${euro(t.recent_3m_average_cents)} / mois</small></div><strong>${t.delta_pct==null?'n/a':signed(t.delta_pct)}</strong></div>`).join(''):'<p class="subtle">Pas assez d’historique par catégorie.</p>'}</div>
        <p class="aa-method">${esc(data.method||'')}</p>
      </div></details>
    </section>`;
  }

  async function enhance(){
    if(busy)return;
    const root=document.querySelector('[data-screen="month"]');
    if(!root||!root.classList.contains('active'))return;
    const anchor=root.querySelector('.month-balance')||root.querySelector('.metric-grid');
    if(!anchor)return;
    busy=true;
    try{
      const r=await fetch('/api/v4.7/analysis',{cache:'no-store'});if(!r.ok)throw new Error();const data=await r.json();
      document.getElementById(ROOT_ID)?.remove();
      anchor.insertAdjacentHTML('afterend',render(data));
    }catch(_){/* keep base month screen */}
    finally{busy=false;}
  }

  const observer=new MutationObserver(()=>queueMicrotask(enhance));
  const start=()=>{const root=document.querySelector('[data-screen="month"]');if(root)observer.observe(root,{childList:true,subtree:false});document.querySelectorAll('[data-nav="month"]').forEach(b=>b.addEventListener('click',()=>setTimeout(enhance,0)));enhance();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
