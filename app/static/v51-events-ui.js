(()=>{
  let busy=false;
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML;};
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const fmtDate=value=>{if(!value)return '—';const d=new Date(`${String(value).slice(0,10)}T12:00:00`);return Number.isNaN(d.getTime())?String(value):new Intl.DateTimeFormat('fr-FR',{weekday:'short',day:'numeric',month:'short'}).format(d);};
  const statusLabel=v=>({safe:'Sûr',watch:'À surveiller',high:'Sous protection',critical:'Critique',income:'Revenu'})[v]||'Prévu';

  const eventHtml=e=>`<article class="v51-event" data-status="${esc(e.status)}">
    <div class="v51-event-date"><strong>${fmtDate(e.date)}</strong><small>${Number(e.days_away)===0?'Aujourd’hui':`J-${Number(e.days_away)||0}`}</small></div>
    <div class="v51-event-main"><strong>${esc(e.label||'Événement financier')}</strong><small>${statusLabel(e.status)} · solde après ${euro(e.balance_after_cents)}</small></div>
    <div class="money ${e.direction==='income'?'positive':'negative'}">${e.amount_cents>0?'+':''}${euro(e.amount_cents)}</div>
  </article>`;

  function html(data){
    const s=data.summary||{},events=data.events||[],nextOut=s.next_outflow,nextIn=s.next_income;
    return `<section id="v51UpcomingEvents" class="card v51-events-card">
      <div class="section-head"><div><p class="eyebrow">V5.1 RC · À venir</p><h2>Les prochains mouvements qui comptent</h2></div><span class="chip ${Number(s.sensitive_count)>0?'warning':'active'}">${Number(s.sensitive_count)||0} sensible(s)</span></div>
      <div class="v51-next-grid">
        <div><span>Prochaine sortie</span><strong>${nextOut?euro(Math.abs(nextOut.amount_cents)):'—'}</strong><small>${nextOut?`${fmtDate(nextOut.date)} · ${esc(nextOut.label)}`:'Aucune sortie connue'}</small></div>
        <div><span>Prochain revenu</span><strong>${nextIn?euro(nextIn.amount_cents):'—'}</strong><small>${nextIn?`${fmtDate(nextIn.date)} · ${esc(nextIn.label)}`:'Aucun revenu connu'}</small></div>
        <div><span>Flux nets connus</span><strong>${euro((Number(s.total_inflows_cents)||0)-(Number(s.total_outflows_cents)||0))}</strong><small>${Number(s.event_count)||0} événement(s) sur ${Number(data.days)||45} jours</small></div>
      </div>
      <details class="v51-events-details" ${Number(s.sensitive_count)>0?'open':''}><summary>Voir la timeline</summary><div class="v51-events-list">${events.map(eventHtml).join('')||'<div class="empty-state">Aucun événement connu sur cet horizon.</div>'}</div></details>
      <p class="subtle">${esc(data.principle||'')}</p>
    </section>`;
  }

  async function enhance(force=false){
    if(busy)return;
    const root=document.querySelector('[data-screen="home"]');
    if(!root||!root.classList.contains('active'))return;
    if(!force&&root.querySelector('#v51UpcomingEvents'))return;
    busy=true;
    try{
      const response=await fetch('/api/v5/upcoming-events?days=45',{cache:'no-store'});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const data=await response.json();
      root.querySelector('#v51UpcomingEvents')?.remove();
      const predictive=root.querySelector('#v5PredictivePilot');
      const hero=root.querySelector('.card.hero');
      const target=predictive||hero;
      if(target)target.insertAdjacentHTML('afterend',html(data));
    }catch(_){/* V5.0 cockpit remains usable */}finally{busy=false;}
  }

  const observer=new MutationObserver(()=>queueMicrotask(()=>enhance(false)));
  const start=()=>{
    const root=document.querySelector('[data-screen="home"]');if(root)observer.observe(root,{childList:true,subtree:true});
    document.querySelectorAll('[data-nav="home"]').forEach(b=>b.addEventListener('click',()=>setTimeout(()=>enhance(true),140)));
    setTimeout(()=>enhance(false),220);
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
