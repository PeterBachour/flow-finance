(()=>{
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const fmtDate=value=>{
    if(!value)return '—';
    const d=new Date(`${value}T12:00:00`);
    return Number.isNaN(d.getTime())?value:new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short'}).format(d);
  };
  const confidence=value=>({high:'Élevée',medium:'Moyenne',low:'Faible'})[value]||'—';

  async function enhance(){
    const card=document.getElementById('financialIntelligenceCard');
    if(!card||card.dataset.balanceOnlyEnhanced==='1')return;
    try{
      const r=await fetch('/api/finance/intelligence?history_months=12',{cache:'no-store'});
      if(!r.ok)return;
      const data=await r.json();
      const q=data.data_quality||{};
      const p=data.current_position||{};
      if(q.decision_mode!=='balance_only'||p.status!=='balance_estimated')return;

      card.dataset.balanceOnlyEnhanced='1';
      const details=card.querySelector('.fi-details');
      const html=`<div class="fi-current-month fi-balance-only" data-balance-only-panel>
        <div><span>Sortie nette estimée</span><strong>${euro(p.estimated_net_outflow_mtd_cents)}</strong></div>
        <div><span>Attendu à date</span><strong>${euro(p.expected_to_date_cents)}</strong></div>
        <div><span>Projection indicative</span><strong>${euro(p.projected_full_month_cents)}</strong></div>
      </div>
      <p class="fi-note fi-balance-only-note"><strong>Septembre suivi par solde.</strong> Solde réel au ${fmtDate(q.balance_as_of)} comparé au dernier solde bancaire confirmé du ${fmtDate(p.reference_balance_date)}. Le détail des transactions n’est pas encore disponible ; la sortie nette estimée peut donc inclure dépenses, virements ou autres mouvements. Confiance : ${confidence(p.confidence)}.</p>`;
      if(details)details.insertAdjacentHTML('beforebegin',html);else card.insertAdjacentHTML('beforeend',html);

      const staleChip=[...card.querySelectorAll('.fi-freshness')].find(el=>el.textContent.includes('Mouvements'));
      if(staleChip){
        staleChip.textContent='Mouvements en attente du relevé';
        staleChip.classList.add('stale');
      }
      const oldNote=[...card.querySelectorAll('.fi-note')].find(el=>el.textContent.includes('Importe un CSV récent'));
      if(oldNote)oldNote.remove();
    }catch(_){/* Progressive enhancement only. */}
  }

  const observer=new MutationObserver(()=>queueMicrotask(enhance));
  const start=()=>{
    observer.observe(document.body,{childList:true,subtree:true});
    enhance();
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
