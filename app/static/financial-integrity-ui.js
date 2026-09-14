(()=>{
  const CARD_ID='financialIntegrityCard';
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const shortMonth=value=>{if(!value)return '—';const [y,m]=value.split('-');return new Intl.DateTimeFormat('fr-FR',{month:'short'}).format(new Date(Number(y),Number(m)-1,1)).replace('.','');};
  const labelIssue=key=>({missing_statement_balance:'Solde de relevé manquant',statement_arithmetic_mismatch:'Équation du relevé incohérente',ledger_mismatch:'Ledger différent du relevé',missing_balance_snapshot:'Snapshot de clôture manquant',import_quality_not_verified:'Qualité d’import à confirmer',rows_need_review:'Lignes signalées à revoir'})[key]||key;
  async function fetchIntegrity(){const r=await fetch('/api/finance/integrity?months=24',{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json();}

  function render(data){
    const safe=data.safe_to_spend_breakdown||{};
    const summary=(data.statement_audit||{}).summary||{};
    const months=((data.monthly_audit||{}).months||[]).slice(-6);
    const maxConsumption=Math.max(1,...months.map(m=>Number(m.consumption_cents||0)));
    const hard=Number(data.hard_issue_count||0);
    const reviews=Number(data.review_issue_count||0);
    const warningStatements=((data.statement_audit||{}).statements||[]).filter(s=>s.integrity_status==='warning').slice(-4).reverse();
    const reviewStatements=((data.statement_audit||{}).statements||[]).filter(s=>s.integrity_status==='reconciled_with_review').slice(-4).reverse();
    const components=(safe.components||[]).map(item=>`<div class="integrity-line"><span>${item.operator==='-'?'− ':''}${item.label}</span><strong>${item.operator==='-'?'− ':''}${euro(item.amount_cents)}</strong></div>`).join('');
    const badge=hard>0?`${hard} anomalie(s) bloquante(s)`:reviews>0?`Comptabilité OK · ${reviews} revue(s) documentaire(s)`:'Données cohérentes';
    const badgeClass=hard>0?'review':'ok';

    return `<section class="card integrity-card" id="${CARD_ID}" aria-label="Intégrité financière">
      <div class="integrity-head"><div><p class="eyebrow">Preuve de calcul</p><h2>Pourquoi ce montant ?</h2></div><span class="integrity-badge ${badgeClass}">${badge}</span></div>
      <div class="integrity-equation">${components}<div class="integrity-line total"><span>Safe disponible</span><strong>${safe.safe_to_spend_cents==null?'Indisponible':euro(safe.safe_to_spend_cents)}</strong></div></div>
      <div class="integrity-kpis">
        <div class="integrity-kpi"><span>Relevés rapprochés</span><strong>${summary.reconciled_count||0}/${summary.statement_count||0}</strong></div>
        <div class="integrity-kpi"><span>Anomalies bloquantes</span><strong>${hard}</strong></div>
        <div class="integrity-kpi"><span>Cohérence du Safe</span><strong>${safe.arithmetic_consistent?'100 %':'Erreur'}</strong></div>
      </div>
      ${reviews>0&&hard===0?'<p class="integrity-note"><strong>Les revues documentaires ne remettent pas en cause l’équilibre comptable.</strong> Elles correspondent à des imports ou lignes encore marqués pour contrôle qualité.</p>':''}
      ${months.length?`<div><div class="section-head"><div><p class="eyebrow">6 derniers mois consolidés</p><h3>Consommation classée</h3></div></div><div class="integrity-chart">${months.map(m=>{const ratio=Math.round(100*Number(m.consumption_cents||0)/maxConsumption);const level=ratio>80?'high':ratio>55?'mid':'low';return `<div class="integrity-month" data-level="${level}"><span>${shortMonth(m.month)}</span><div class="integrity-bar"><i style="width:${ratio}%"></i></div><strong>${euro(m.consumption_cents)}</strong></div>`}).join('')}</div></div>`:''}
      <details><summary>Contrôles des relevés</summary>
        ${warningStatements.length?`<div class="integrity-audit-list">${warningStatements.map(s=>`<div class="integrity-audit-row"><div><strong>${s.period_end||s.filename}</strong><small>${(s.hard_issues||[]).map(labelIssue).join(' · ')}</small></div><span>${s.closing_balance_cents==null?'—':euro(s.closing_balance_cents)}</span></div>`).join('')}</div>`:'<p class="integrity-note">Aucune anomalie comptable bloquante détectée sur les relevés audités.</p>'}
        ${reviewStatements.length?`<div class="integrity-audit-list">${reviewStatements.map(s=>`<div class="integrity-audit-row"><div><strong>${s.period_end||s.filename}</strong><small>${(s.review_issues||[]).map(labelIssue).join(' · ')}</small></div><span>Revue qualité</span></div>`).join('')}</div>`:''}
      </details>
      <p class="integrity-note">Le Safe est reconstruit séparément de l’historique. Les transferts internes, remboursements et objectifs déjà financés ne sont pas comptés comme consommation.</p>
    </section>`;
  }

  let busy=false;
  async function inject(){
    if(busy||document.getElementById(CARD_ID))return;
    const root=document.querySelector('[data-screen="home"]');if(!root||!root.classList.contains('active'))return;
    const anchor=document.getElementById('financialIntelligenceCard')||root.querySelector('.card.hero');if(!anchor)return;
    busy=true;
    try{const data=await fetchIntegrity();if(!document.getElementById(CARD_ID))anchor.insertAdjacentHTML('afterend',render(data));}catch(_){/* Keep primary cockpit usable. */}finally{busy=false;}
  }
  const observer=new MutationObserver(()=>queueMicrotask(inject));
  const start=()=>{const home=document.querySelector('[data-screen="home"]');if(home)observer.observe(home,{childList:true,subtree:false});document.querySelectorAll('[data-nav="home"]').forEach(btn=>btn.addEventListener('click',()=>setTimeout(inject,0)));inject();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
