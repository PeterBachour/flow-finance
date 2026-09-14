(()=>{
  const ID='commitmentEngineCard';
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Math.abs(Number(c)||0))/100);
  const fmtDate=value=>{
    if(!value)return 'Ce mois';
    const d=new Date(`${value}T12:00:00`);
    return Number.isNaN(d.getTime())?value:new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short'}).format(d);
  };
  const labels={confirmed:'Confirmé',probable:'À valider',stale:'Ancien',rejected:'Rejeté'};
  const types={cycle_reserve:'Réserve de cycle',planned_transaction:'Échéance planifiée',recurring:'Récurrent'};

  async function load(){
    const r=await fetch('/api/finance/commitments',{cache:'no-store'});
    if(!r.ok)throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  function row(item){
    const actionable=item.item_type==='recurring'&&(item.status==='probable'||item.status==='stale');
    const overlap=Boolean(item.planned_overlap||item.cycle_overlap);
    return `<article class="ce-row">
      <div class="ce-row-main">
        <div><strong>${item.label}</strong><small>${fmtDate(item.next_expected_date)} · ${types[item.item_type]||'Engagement'}${item.category?` · ${item.category}`:''}</small></div>
        <div class="ce-amount"><strong>${euro(item.amount_cents)}</strong><span class="ce-status ${item.status}">${labels[item.status]||item.status}</span></div>
      </div>
      <p>${overlap?'Déjà couvert par un engagement équivalent : aucun double comptage.':item.status_reason}</p>
      ${actionable?`<div class="ce-actions"><button data-ce-decision="accept" data-id="${item.id}">Valider</button><button class="secondary" data-ce-decision="reject" data-id="${item.id}">Rejeter</button></div>`:''}
    </article>`;
  }

  function render(data){
    const s=data.summary||{};
    const items=(data.items||[]).filter(i=>i.status!=='rejected'&&(i.within_horizon||i.status!=='confirmed')).slice(0,12);
    return `<section class="card ce-card" id="${ID}" aria-label="Engagements à venir">
      <div class="section-head"><div><p class="eyebrow">Engagements</p><h2>À protéger avant le salaire</h2></div><span class="ce-pill">${Number(s.review_needed||0)} à revoir</span></div>
      <div class="ce-summary">
        <div><span>Total protégé</span><strong>${euro(s.protected_confirmed_cents)}</strong></div>
        <div><span>Réserves de cycle</span><strong>${euro(s.cycle_reserve_cents)}</strong></div>
        <div><span>Récurrents protégés</span><strong>${euro(s.protected_recurring_cents)}</strong></div>
      </div>
      <div class="ce-list">${items.length?items.map(row).join(''):'<p class="subtle">Aucun engagement à afficher sur cet horizon.</p>'}</div>
      <details><summary>Règle de calcul</summary><p>Le total protégé regroupe les réserves de cycle confirmées, les échéances planifiées actives et les récurrents validés. Les récurrents probables ou anciens restent visibles sans réduire le disponible. Tout engagement équivalent est neutralisé pour éviter un double comptage.</p></details>
    </section>`;
  }

  async function decide(id,decision,button){
    button.disabled=true;
    try{
      const r=await fetch(`/api/finance/commitments/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision})});
      if(!r.ok)throw new Error(await r.text());
      document.getElementById(ID)?.remove();
      await inject();
    }catch(err){
      button.disabled=false;
      alert(`Impossible de mettre à jour cet engagement : ${err.message}`);
    }
  }

  function bind(card){
    card.querySelectorAll('[data-ce-decision]').forEach(btn=>btn.addEventListener('click',()=>decide(btn.dataset.id,btn.dataset.ceDecision,btn)));
  }

  async function inject(){
    const root=document.querySelector('[data-screen="home"]');
    if(!root||!root.classList.contains('active')||document.getElementById(ID))return;
    const anchor=document.getElementById('decisionBudgetCard')||document.getElementById('financialIntelligenceCard')||root.querySelector('.card.hero');
    if(!anchor)return;
    try{
      const data=await load();
      if(document.getElementById(ID))return;
      anchor.insertAdjacentHTML('afterend',render(data));
      bind(document.getElementById(ID));
    }catch(_){/* commitment review must never break the cockpit */}
  }

  const observer=new MutationObserver(()=>queueMicrotask(inject));
  const start=()=>{
    const home=document.querySelector('[data-screen="home"]');
    if(home)observer.observe(home,{childList:true,subtree:false});
    document.querySelectorAll('[data-nav="home"]').forEach(btn=>btn.addEventListener('click',()=>setTimeout(inject,0)));
    inject();
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
