(()=>{
  const ID='monthConsolidationView';
  let busy=false;
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML;};
  const localMonth=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;};
  const monthFromRoot=root=>root.querySelector('.month-title small')?.textContent?.trim()||localMonth();
  const statusLabel=status=>({consolidated:'Consolidé',ready:'Prêt à clôturer',blocked:'À revoir',statement_missing:'Relevé manquant'})[status]||'À vérifier';
  const blockerLabel=key=>({review_rows:'mouvements à revoir',missing_closing_balance:'solde de clôture absent',quality_not_validated:'qualité du relevé non validée',statement_missing:'relevé bancaire absent'})[key]||key;

  function render(data){
    const current=data.month===localMonth();
    if(current&&data.status==='statement_missing'){
      return `<section id="${ID}" class="mc-card mc-estimated"><div><span class="mc-dot"></span><strong>Mois en cours · mode estimé</strong></div><p>Le mois sera consolidé après réception du relevé bancaire de clôture. Flow n’invente aucune opération entre-temps.</p></section>`;
    }
    const closures=data.closures||[],candidates=data.candidates||[];
    return `<section id="${ID}" class="card mc-card">
      <div class="mc-head"><div><p class="eyebrow">Source de vérité</p><h2>${statusLabel(data.status)}</h2></div><span class="mc-pill ${esc(data.status)}">${esc(data.month)}</span></div>
      ${data.status==='consolidated'?`<p class="mc-copy">Ce mois est consolidé à partir ${closures.length>1?'des relevés bancaires validés':'du relevé bancaire validé'} ci-dessous.</p>`:''}
      ${data.status==='statement_missing'?'<p class="mc-copy">Aucun relevé de clôture validé n’est disponible pour ce mois. Les chiffres historiques ne doivent pas être considérés comme consolidés.</p>':''}
      ${data.status==='blocked'?`<p class="mc-copy">Le relevé existe mais ${Number(data.pending_review_rows)||0} mouvement(s) doivent encore être revus avant clôture.</p>`:''}
      <div class="mc-list">
        ${closures.map(row=>`<article class="mc-row done"><div><strong>${esc(row.account_name)}</strong><small>${esc(row.filename)} · clôturé le ${esc(String(row.closed_at||'').slice(0,10))}</small></div><strong>${euro(row.closing_balance_cents)}</strong></article>`).join('')}
        ${candidates.filter(row=>!closures.some(c=>Number(c.account_id)===Number(row.account_id))).map(row=>`<article class="mc-row ${row.closable?'ready':'blocked'}"><div><strong>${esc(row.account_name)}</strong><small>${esc(row.filename)} · ${esc(row.period_end||'date inconnue')}</small>${row.blockers?.length?`<small>${row.blockers.map(blockerLabel).join(' · ')}</small>`:''}</div><div class="mc-actions"><strong>${row.closing_balance_cents==null?'—':euro(row.closing_balance_cents)}</strong>${row.closable?`<button class="chip active" data-close-month="${row.account_id}" data-month="${esc(data.month)}">Clôturer</button>`:''}</div></article>`).join('')}
      </div>
      ${(data.missing_accounts||[]).length?`<details class="mc-details"><summary>Comptes sans relevé de clôture (${data.missing_accounts.length})</summary><div>${data.missing_accounts.map(a=>`<span>${esc(a.name)}</span>`).join('')}</div></details>`:''}
      <p class="mc-method">${esc(data.principle||'')}</p>
    </section>`;
  }

  async function closeMonth(month,accountId,button){
    if(!confirm('Confirmer la clôture de ce mois à partir de ce relevé bancaire ?'))return;
    button.disabled=true;
    try{
      const r=await fetch(`/api/v4.9/months/${encodeURIComponent(month)}/accounts/${accountId}/close`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation:'CLOTURER'})});
      if(!r.ok)throw new Error(await r.text());
      await enhance(true);
    }catch(error){alert(`Clôture impossible : ${error.message}`);button.disabled=false;}
  }

  async function enhance(force=false){
    if(busy)return;
    const root=document.querySelector('[data-screen="month"]');
    if(!root||!root.classList.contains('active'))return;
    const toolbar=root.querySelector('.month-toolbar');
    if(!toolbar)return;
    const month=monthFromRoot(root);
    const existing=document.getElementById(ID);
    if(existing&&!force&&existing.dataset.month===month)return;
    busy=true;
    try{
      const r=await fetch(`/api/v4.9/month-status?month=${encodeURIComponent(month)}`,{cache:'no-store'});
      if(!r.ok)throw new Error();
      const data=await r.json();
      existing?.remove();
      toolbar.insertAdjacentHTML('afterend',render(data));
      const view=document.getElementById(ID);if(view)view.dataset.month=month;
      view?.querySelectorAll('[data-close-month]').forEach(button=>button.addEventListener('click',()=>closeMonth(button.dataset.month,button.dataset.closeMonth,button)));
    }catch(_){/* base month screen remains usable */}
    finally{busy=false;}
  }

  const observer=new MutationObserver(()=>queueMicrotask(()=>enhance(false)));
  const start=()=>{const root=document.querySelector('[data-screen="month"]');if(root)observer.observe(root,{childList:true,subtree:true});document.querySelectorAll('[data-nav="month"]').forEach(b=>b.addEventListener('click',()=>setTimeout(()=>enhance(true),80)));enhance();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
