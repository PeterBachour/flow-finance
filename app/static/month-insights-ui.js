(()=>{
  const CARD_ID='monthIncomeBreakdown';
  let lastMonth=null;
  let injecting=false;
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const pct=(cur,prev)=>{
    cur=Number(cur)||0;prev=Number(prev)||0;
    if(!prev)return null;
    return ((cur-prev)/Math.abs(prev))*100;
  };
  const deltaLabel=(cur,prev)=>{
    const d=(Number(cur)||0)-(Number(prev)||0);
    const p=pct(cur,prev);
    if(!prev)return `${d>=0?'+':''}${euro(d)} vs mois précédent`;
    return `${d>=0?'+':''}${euro(d)} · ${p>=0?'+':''}${p.toFixed(1).replace('.',',')} %`;
  };
  const detectMonth=()=>{
    const root=document.querySelector('[data-screen="month"]');
    const marker=root?.querySelector('.month-title small');
    const value=(marker?.textContent||'').trim();
    return /^\d{4}-\d{2}$/.test(value)?value:new Date().toISOString().slice(0,7);
  };
  const render=data=>{
    const c=data.current||{},p=data.previous||{},a3=data.average_3m||{};
    const method=c.salary_attribution_method==='payroll_period_plus_one_month'?'Fiche de paie réconciliée → mois budgétaire suivant':'Fallback bancaire';
    const coverage=Number(c.semantic_coverage_pct??0);
    return `<section class="card mi-card" id="${CARD_ID}">
      <div class="section-head"><div><p class="eyebrow">Lecture complète</p><h2>D’où vient l’écart du mois</h2></div><span class="mi-method">${method}</span></div>
      <div class="mi-grid">
        <article><span>Salaire affecté</span><strong>${euro(c.salary_cents)}</strong><small>${deltaLabel(c.salary_cents,p.salary_cents)}</small></article>
        <article><span>Autres revenus</span><strong>${euro(c.other_income_cents)}</strong><small>${deltaLabel(c.other_income_cents,p.other_income_cents)}</small></article>
        <article><span>Revenus totaux</span><strong>${euro(c.income_cents)}</strong><small>Moyenne 3 mois ${euro(a3.income_cents)}</small></article>
        <article><span>Solde consommation</span><strong>${euro(c.net_cents)}</strong><small>Revenus - consommation analysée</small></article>
      </div>
      <p class="mi-note">Le salaire est rattaché à sa période de paie afin d’éviter les faux mois à zéro ou deux salaires.</p>

      <div class="mi-divider"></div>
      <div class="section-head"><div><p class="eyebrow">Sorties du mois</p><h2>Où part réellement l’argent</h2></div><span class="mi-coverage">${coverage.toFixed(1).replace('.',',')} % catégorisé</span></div>
      <div class="mi-spend-summary">
        <div><span>Consommation</span><strong>${euro(c.consumption_cents)}</strong><small>Fixes + variables + exceptionnelles + inconnues</small></div>
        <div><span>Sorties cash</span><strong>${euro(c.cash_outflow_cents)}</strong><small>Inclut épargne et transferts</small></div>
      </div>
      <div class="mi-breakdown">
        <div><span>Fixes</span><strong>${euro(c.fixed_cents)}</strong><small>${deltaLabel(c.fixed_cents,p.fixed_cents)}</small></div>
        <div><span>Variables</span><strong>${euro(c.variable_cents)}</strong><small>${deltaLabel(c.variable_cents,p.variable_cents)}</small></div>
        <div><span>Épargne</span><strong>${euro(c.saving_cents)}</strong><small>Hors consommation</small></div>
        <div><span>Exceptionnelles</span><strong>${euro(c.exceptional_cents)}</strong><small>Voyage et achats atypiques</small></div>
        <div><span>Transferts</span><strong>${euro(c.transfers_cents)}</strong><small>Hors consommation</small></div>
        <div class="${Number(c.unknown_cents)>0?'mi-review':''}"><span>À qualifier</span><strong>${euro(c.unknown_cents)}</strong><small>${Number(c.unknown_cents)>0?'À revoir dans Mouvements':'Aucun montant inconnu'}</small></div>
      </div>
      ${Number(c.other_classified_cents)>0?`<p class="mi-note">Autres dépenses classées : <strong>${euro(c.other_classified_cents)}</strong>. Elles sont incluses dans la consommation mais restent isolées pour audit.</p>`:''}
      ${Number(c.excluded_cents)>0?`<p class="mi-note">Hors analyses : <strong>${euro(c.excluded_cents)}</strong> — visibles dans le cash, mais exclus de la consommation.</p>`:''}
    </section>`;
  };
  async function inject(){
    if(injecting)return;
    const root=document.querySelector('[data-screen="month"]');
    if(!root||!root.classList.contains('active'))return;
    const month=detectMonth();
    const existing=document.getElementById(CARD_ID);
    if(existing&&lastMonth===month)return;
    existing?.remove();
    const anchor=root.querySelector('.metric-grid');
    if(!anchor)return;
    injecting=true;
    try{
      const r=await fetch(`/api/v2.1/months/${month}`,{cache:'no-store'});
      if(!r.ok)throw new Error(`HTTP ${r.status}`);
      const data=await r.json();
      if(!root.classList.contains('active'))return;
      anchor.insertAdjacentHTML('afterend',render(data));
      lastMonth=month;
    }catch(e){
      anchor.insertAdjacentHTML('afterend',`<section class="card mi-card" id="${CARD_ID}"><p class="eyebrow">Lecture du mois</p><p class="subtle">Lecture mensuelle indisponible : ${String(e.message||e)}</p></section>`);
      lastMonth=month;
    }finally{injecting=false;}
  }
  const observer=new MutationObserver(()=>queueMicrotask(inject));
  const start=()=>{
    const root=document.querySelector('[data-screen="month"]');
    if(root)observer.observe(root,{childList:true,subtree:true});
    document.querySelectorAll('[data-nav="month"]').forEach(btn=>btn.addEventListener('click',()=>setTimeout(inject,0)));
    inject();
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
