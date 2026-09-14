(()=>{
  const CARD_ID='financialIntelligenceCard';
  const DIALOG_ID='fiBalanceDialog';
  let cache=null;
  let cacheAt=0;
  let injecting=false;

  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const euroInput=c=>(Number(c||0)/100).toFixed(2).replace('.',',');
  const fmtDate=value=>{
    if(!value)return '—';
    const d=new Date(`${value}T12:00:00`);
    return Number.isNaN(d.getTime())?value:new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short'}).format(d);
  };
  const localDate=()=>{
    const d=new Date();
    const y=d.getFullYear();
    const m=String(d.getMonth()+1).padStart(2,'0');
    const day=String(d.getDate()).padStart(2,'0');
    return `${y}-${m}-${day}`;
  };
  const confidenceLabel=value=>({high:'Élevée',medium:'Moyenne',low:'Faible',unavailable:'Indisponible'})[value]||value||'—';

  const fetchIntel=async(force=false)=>{
    if(!force&&cache&&Date.now()-cacheAt<30000)return cache;
    const r=await fetch('/api/finance/intelligence?history_months=12',{cache:'no-store'});
    if(!r.ok)throw new Error(`HTTP ${r.status}`);
    cache=await r.json();
    cacheAt=Date.now();
    return cache;
  };

  const renderCard=data=>{
    const h=data.headline||{};
    const q=data.data_quality||{};
    const safe=data.safe_to_spend||{};
    const forecast=data.forecast||{};
    const pos=data.current_position||{};
    const balanceStale=q.balance_freshness_status!=='current';
    const monthlyPending=q.transaction_freshness_status==='monthly_statement_pending';
    const consolidated=Boolean(q.current_month_observed)||q.cycle_status==='consolidated';
    const projectedBank=forecast.projected_bank_balance_at_horizon_cents;
    const margin=forecast.projected_margin_above_safety_cents ?? forecast.expected_remaining_after_variable_spend_cents;
    const rate=h.recommended_daily_spend_cents ?? pos.recommended_daily_spend_cents ?? forecast.variable_daily_rate_cents;
    const protected=Number(safe.planned_commitments_cents||0)+Number(safe.recurring_commitments_cents||0)+Number(safe.goal_contributions_cents||0);

    return `<section class="card fi-card" id="${CARD_ID}" aria-label="Fiabilité et projection financières">
      <div class="section-head fi-head">
        <div><p class="eyebrow">Données et projection</p><h2>Ce que Flow sait aujourd’hui</h2></div>
        <div class="fi-actions"><button class="fi-balance-btn" type="button" data-fi-update-balance>Actualiser le solde</button></div>
      </div>
      <div class="fi-status-row">
        <span class="fi-freshness ${balanceStale?'stale':'current'}">Solde ${balanceStale?'à actualiser':'à jour'}</span>
        <span class="fi-freshness ${consolidated?'current':'pending'}">${consolidated?'Mois consolidé':(monthlyPending?'Relevé mensuel en attente':'Mois estimé')}</span>
      </div>
      <div class="fi-primary-grid">
        <article class="fi-primary"><span>Solde projeté au ${fmtDate(forecast.horizon_end)}</span><strong>${euro(projectedBank)}</strong><small>Après engagements protégés et dépenses variables projetées.</small></article>
        <article class="fi-primary scenario"><span>Marge au-dessus de la réserve</span><strong>${euro(margin)}</strong><small>Réserve de sécurité : ${euro(safe.safety_reserve_cents)}</small></article>
      </div>
      <div class="fi-metrics">
        <div><span>Safe jusqu’au salaire</span><strong>${euro(safe.safe_to_spend_cents)}</strong></div>
        <div><span>Engagements protégés</span><strong>${euro(protected)}</strong></div>
        <div><span>Rythme conseillé</span><strong>${euro(rate)}/j</strong></div>
        <div><span>Confiance tendance</span><strong>${confidenceLabel(q.trend_confidence)}</strong></div>
      </div>
      <details class="fi-details"><summary>Sources et couverture</summary><div class="fi-quality">
        <span>Solde réel au ${fmtDate(q.balance_as_of)}</span>
        <span>Dernier relevé consolidé : ${fmtDate(q.statement_coverage_end)}</span>
        <span>Historique analytique couvert à ${Number(q.historical_coverage_pct||0).toFixed(1).replace('.',',')} %</span>
        <span>Prochain salaire : ${fmtDate(h.next_salary_date||safe.next_salary_date)}</span>
      </div></details>
      ${!consolidated?'<p class="fi-note"><strong>Mode estimé normal.</strong> Pendant le mois, Flow s’appuie sur le solde réel, les engagements connus et l’historique. Le détail des opérations sera consolidé avec le relevé de fin de mois. Aucun mouvement n’est inventé à partir du solde.</p>':''}
    </section>`;
  };

  const ensureDialog=()=>{
    let dialog=document.getElementById(DIALOG_ID);
    if(dialog)return dialog;
    document.body.insertAdjacentHTML('beforeend',`<dialog id="${DIALOG_ID}" class="fi-balance-dialog">
      <form method="dialog" class="fi-balance-panel" data-fi-balance-form>
        <div class="fi-dialog-head"><div><p class="eyebrow">Donnée opérationnelle</p><h2>Actualiser le solde</h2></div><button type="button" class="fi-dialog-close" aria-label="Fermer">×</button></div>
        <p class="fi-dialog-copy">Le solde réel sert d’ancre au pilotage du mois. Cette action conserve un snapshot auditable sans créer ni déduire de transaction.</p>
        <label class="fi-field"><span>Compte</span><select name="account_id" required></select></label>
        <label class="fi-field"><span>Solde actuel</span><div class="fi-money-input"><input name="balance" inputmode="decimal" autocomplete="off" required><b>€</b></div></label>
        <label class="fi-field"><span>Date du solde</span><input name="balance_as_of" type="date" required></label>
        <p class="fi-form-status" aria-live="polite"></p>
        <button class="fi-submit" type="submit">Enregistrer le solde</button>
      </form>
    </dialog>`);
    dialog=document.getElementById(DIALOG_ID);
    dialog.querySelector('.fi-dialog-close').addEventListener('click',()=>dialog.close());
    dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
    dialog.querySelector('[data-fi-balance-form]').addEventListener('submit',saveBalance);
    return dialog;
  };

  const loadSafeAccounts=async select=>{
    const r=await fetch('/api/accounts',{cache:'no-store'});
    if(!r.ok)throw new Error(`HTTP ${r.status}`);
    const accounts=(await r.json()).filter(a=>Number(a.is_active)!==0&&Number(a.include_in_safe_to_spend)===1);
    if(!accounts.length)throw new Error('Aucun compte inclus dans le Safe-to-spend');
    select.innerHTML=accounts.map(a=>`<option value="${a.id}" data-balance="${a.current_balance_cents||0}" data-date="${a.balance_as_of||''}">${a.name}</option>`).join('');
  };

  const loadBalanceDialog=async()=>{
    const dialog=ensureDialog();
    const status=dialog.querySelector('.fi-form-status');
    const select=dialog.querySelector('select[name="account_id"]');
    status.textContent='Chargement…';
    try{
      await loadSafeAccounts(select);
      const syncFields=()=>{
        const option=select.selectedOptions[0];
        dialog.querySelector('input[name="balance"]').value=euroInput(option?.dataset.balance||0);
        dialog.querySelector('input[name="balance_as_of"]').value=option?.dataset.date||localDate();
      };
      select.onchange=syncFields;
      syncFields();
      status.textContent='';
      dialog.showModal();
    }catch(err){status.textContent=`Impossible de charger les comptes : ${err.message}`;dialog.showModal();}
  };

  async function saveBalance(event){
    event.preventDefault();
    const form=event.currentTarget;
    const dialog=form.closest('dialog');
    const status=form.querySelector('.fi-form-status');
    const submit=form.querySelector('.fi-submit');
    const accountId=Number(form.account_id.value);
    const raw=String(form.balance.value||'').trim().replace(/\s/g,'').replace(',','.');
    const amount=Number(raw);
    if(!Number.isFinite(amount)){status.textContent='Saisis un solde valide.';return;}
    submit.disabled=true;
    status.textContent='Enregistrement…';
    try{
      const r=await fetch(`/api/finance/accounts/${accountId}/balance`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_balance_cents:Math.round(amount*100),balance_as_of:form.balance_as_of.value})});
      if(!r.ok)throw new Error((await r.text())||`HTTP ${r.status}`);
      await refreshCard();
      status.textContent='Solde enregistré.';
      dialog.close();
    }catch(err){status.textContent=`Échec : ${err.message}`;}finally{submit.disabled=false;}
  }

  async function refreshCard(){cache=null;cacheAt=0;await fetchIntel(true);document.getElementById(CARD_ID)?.remove();await inject();}

  async function inject(){
    if(injecting)return;
    const root=document.querySelector('[data-screen="home"]');
    if(!root||!root.classList.contains('active')||document.getElementById(CARD_ID))return;
    const hero=root.querySelector('.card.hero');
    if(!hero)return;
    injecting=true;
    try{
      const data=await fetchIntel();
      if(document.getElementById(CARD_ID))return;
      const anchor=root.querySelector('.home-summary')||hero;
      anchor.insertAdjacentHTML('afterend',renderCard(data));
      document.getElementById(CARD_ID)?.querySelector('[data-fi-update-balance]')?.addEventListener('click',loadBalanceDialog);
    }catch(_){
      const anchor=root.querySelector('.home-summary')||hero;
      if(!document.getElementById(CARD_ID))anchor.insertAdjacentHTML('afterend',`<section class="card fi-card" id="${CARD_ID}"><p class="eyebrow">Données et projection</p><p class="subtle">Projection détaillée indisponible pour le moment.</p></section>`);
    }finally{injecting=false;}
  }

  const observer=new MutationObserver(()=>queueMicrotask(inject));
  const start=()=>{const home=document.querySelector('[data-screen="home"]');if(home)observer.observe(home,{childList:true,subtree:false});document.querySelectorAll('[data-nav="home"]').forEach(btn=>btn.addEventListener('click',()=>setTimeout(inject,0)));inject();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
