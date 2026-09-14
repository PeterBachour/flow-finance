(()=>{
  let busy=false;
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML;};
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const levelLabel=v=>({low:'Faible',watch:'À surveiller',high:'Élevé',critical:'Critique'})[v]||'À vérifier';
  const monthLabel=v=>{if(!v)return '—';const d=new Date(`${v}-15T12:00:00`);return new Intl.DateTimeFormat('fr-FR',{month:'short',year:'2-digit'}).format(d);};

  function html(data){
    const risk=data.risk||{},trajectory=data.trajectory||{},events=data.critical_events||[],checks=trajectory.checkpoints||[];
    const primary=data.recommendations?.primary;
    return `<section id="v5PredictivePilot" class="card v5-predictive-card">
      <div class="section-head"><div><p class="eyebrow">V5 · Pilotage prédictif</p><h2>Risque ${levelLabel(risk.level)} · ${Number(risk.score)||0}/100</h2></div><span class="chip ${risk.level==='critical'||risk.level==='high'?'warning':'active'}">6 mois</span></div>
      <div class="v5-risk-meter" role="img" aria-label="Score de risque ${Number(risk.score)||0} sur 100"><span style="width:${Math.max(0,Math.min(100,Number(risk.score)||0))}%"></span></div>
      <div class="v5-checkpoints">${checks.map(c=>`<div><span>${c.horizon_months} mois · ${monthLabel(c.month)}</span><strong>${euro(c.closing_balance_cents)}</strong><small>Marge ${euro(c.safe_margin_cents)}</small></div>`).join('')||'<div class="empty-state">Trajectoire indisponible.</div>'}</div>
      ${primary?`<div class="v5-predictive-action"><span>Priorité</span><strong>${esc(primary.title||'À surveiller')}</strong><small>${esc(primary.suggested_action||primary.explanation||'')}</small></div>`:''}
      <details class="v5-critical-events"><summary>${events.length} événement(s) futur(s) sensible(s)</summary>${events.length?`<div class="v5-event-list">${events.map(e=>`<article><div><strong>${esc(e.label||'Événement')}</strong><small>${esc(e.date||'')} · ${esc(e.severity)}</small></div><div class="money">${euro(e.amount_cents)}</div><small>Solde après : ${euro(e.balance_after_cents)} · écart protection : ${euro(e.distance_to_protection_cents)}</small></article>`).join('')}</div>`:'<p class="subtle">Aucun événement critique détecté sur l’horizon.</p>'}</details>
      <details class="v5-risk-details"><summary>Comment le score est calculé</summary><div class="v5-risk-components">${Object.entries(risk.components||{}).map(([key,c])=>`<div><span>${esc(key)}</span><strong>${Number(c.score)||0}/100</strong><small>Poids ${Number(c.weight_pct)||0}%</small></div>`).join('')}</div><p class="subtle">${esc(risk.method||'')}</p></details>
    </section>`;
  }

  async function enhance(force=false){
    if(busy)return;
    const root=document.querySelector('[data-screen="home"]');
    if(!root||!root.classList.contains('active'))return;
    if(!force&&root.querySelector('#v5PredictivePilot'))return;
    busy=true;
    try{
      const snapshot=await window.FlowV5HomeSnapshot.get(force);
      const data=snapshot.predictive||{};
      root.querySelector('#v5PredictivePilot')?.remove();
      const hero=root.querySelector('.card.hero');
      const decision=[...root.querySelectorAll('.card')].find(card=>card.querySelector('.eyebrow')?.textContent?.includes('Décision'));
      const target=decision||hero;
      if(target)target.insertAdjacentHTML('afterend',html(data));
    }catch(_){/* validated V5 home remains usable */}finally{busy=false;}
  }

  const observer=new MutationObserver(()=>queueMicrotask(()=>enhance(false)));
  const start=()=>{
    const root=document.querySelector('[data-screen="home"]');if(root)observer.observe(root,{childList:true,subtree:true});
    document.querySelectorAll('[data-nav="home"]').forEach(b=>b.addEventListener('click',()=>setTimeout(()=>enhance(true),100)));
    window.addEventListener('flow:v5-home-snapshot-invalidated',()=>setTimeout(()=>enhance(true),40));
    setTimeout(()=>enhance(false),150);
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
