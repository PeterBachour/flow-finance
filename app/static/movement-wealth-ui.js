(()=>{
  const MOVEMENT_ID='movementDecisionView';
  const WEALTH_ID='wealthDecisionView';
  const movementState={period:'30d',flow_type:'all',category:'',account_id:'',min_cents:'',max_cents:'',sort:'date_desc',q:''};
  let busyMovements=false,busyWealth=false,searchTimer=null;

  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const pct=v=>`${Number(v||0).toFixed(1).replace('.',',')} %`;
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML;};
  const fmtDate=value=>{if(!value)return 'Non renseigné';const d=new Date(`${String(value).slice(0,10)}T12:00:00`);return Number.isNaN(d.getTime())?String(value):new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short',year:'numeric'}).format(d);};
  const api=async(url,options={})=>{const r=await fetch(url,{cache:'no-store',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});if(!r.ok)throw new Error((await r.text())||`HTTP ${r.status}`);return r.status===204?null:r.json();};

  function movementQuery(){
    const p=new URLSearchParams({period:movementState.period,flow_type:movementState.flow_type,sort:movementState.sort,limit:'200'});
    if(movementState.q)p.set('q',movementState.q);
    if(movementState.category)p.set('category',movementState.category);
    if(movementState.account_id)p.set('account_id',movementState.account_id);
    if(movementState.min_cents)p.set('min_cents',String(Math.round(Number(movementState.min_cents)*100)));
    if(movementState.max_cents)p.set('max_cents',String(Math.round(Number(movementState.max_cents)*100)));
    return p;
  }

  const periodLabel=p=>({30d:'30 derniers jours',3m:'3 derniers mois',6m:'6 derniers mois',12m:'12 derniers mois'})[p]||p;
  const typeLabel=t=>({all:'Tous',expense:'Dépenses',income:'Revenus',transfer:'Transferts',exceptional:'Exceptionnels',uncategorized:'À catégoriser'})[t]||t;

  function movementHtml(data){
    const s=data.summary||{},cmp=data.comparison||{},top=data.top_category;
    const rows=data.rows||[],cats=data.categories||[];
    const delta=cmp.expense_delta_pct;
    return `<section id="${MOVEMENT_ID}" class="mw-stack mw-movement-stack">
      <section class="mw-filter-shell">
        <label class="mw-search"><span>⌕</span><input id="mwSearch" value="${esc(movementState.q)}" placeholder="Rechercher une dépense, un marchand…"></label>
        <div class="mw-scroll-chips">${['30d','3m','6m','12m'].map(p=>`<button class="mw-chip ${movementState.period===p?'active':''}" data-period="${p}">${periodLabel(p)}</button>`).join('')}</div>
        <div class="mw-scroll-chips">${['all','expense','income','transfer','exceptional','uncategorized'].map(t=>`<button class="mw-chip ${movementState.flow_type===t?'active':''}" data-type="${t}">${typeLabel(t)}</button>`).join('')}</div>
        <details class="mw-advanced"><summary>Filtres avancés</summary><div class="mw-filter-grid">
          <label>Catégorie<select id="mwCategory"><option value="">Toutes</option>${(data.filters?.categories||[]).map(c=>`<option value="${esc(c)}" ${movementState.category===c?'selected':''}>${esc(c)}</option>`).join('')}</select></label>
          <label>Compte<select id="mwAccount"><option value="">Tous</option>${(data.filters?.accounts||[]).map(a=>`<option value="${a.id}" ${String(movementState.account_id)===String(a.id)?'selected':''}>${esc(a.name)}</option>`).join('')}</select></label>
          <label>Montant min. €<input id="mwMin" inputmode="decimal" value="${esc(movementState.min_cents)}" placeholder="0"></label>
          <label>Montant max. €<input id="mwMax" inputmode="decimal" value="${esc(movementState.max_cents)}" placeholder="500"></label>
          <label>Tri<select id="mwSort"><option value="date_desc" ${movementState.sort==='date_desc'?'selected':''}>Plus récent</option><option value="date_asc" ${movementState.sort==='date_asc'?'selected':''}>Plus ancien</option><option value="amount_desc" ${movementState.sort==='amount_desc'?'selected':''}>Montant décroissant</option><option value="amount_asc" ${movementState.sort==='amount_asc'?'selected':''}>Montant croissant</option></select></label>
          <button class="mw-reset" id="mwReset">Réinitialiser</button>
        </div></details>
      </section>

      <section class="card mw-movement-overview">
        <div class="mw-overview-head"><div><p class="eyebrow">${fmtDate(data.date_from)} → ${fmtDate(data.date_to)}</p><h2>${periodLabel(data.period)}</h2></div><div class="mw-net-compact"><span>Net</span><strong class="${Number(s.net_cents)>=0?'positive':'danger'}">${Number(s.net_cents)>=0?'+':''}${euro(s.net_cents)}</strong></div></div>
        <div class="mw-inline-kpis"><div><span>Dépenses</span><strong>${euro(s.expenses_cents)}</strong></div><div><span>Revenus</span><strong>${euro(s.income_cents)}</strong></div><div><span>Opérations</span><strong>${s.total||0}</strong></div><div><span>Moy. dépense</span><strong>${euro(s.average_expense_cents)}</strong></div></div>
        <div class="mw-context-row"><span>${top?`Top catégorie : <strong>${esc(top.category)}</strong> · ${euro(top.amount_cents)}`:'Aucune catégorie dominante'}</span><span>${delta==null?'Comparaison indisponible':`Dépenses ${delta>=0?'+':''}${String(delta).replace('.',',')} % vs période précédente`}</span></div>
      </section>

      <details class="card mw-details"><summary>Répartition par catégorie</summary><div class="mw-category-list">${cats.length?cats.slice(0,8).map(c=>{const share=Number(s.expenses_cents)?Number(c.amount_cents)/Number(s.expenses_cents)*100:0;return `<div class="mw-category"><div><span>${esc(c.category)}</span><strong>${euro(c.amount_cents)}</strong></div><div class="mw-track"><i style="width:${Math.max(2,share)}%"></i></div><small>${pct(share)} · ${c.count} opération(s)</small></div>`;}).join(''):'<p class="subtle">Aucune dépense analysable.</p>'}</div></details>

      <section class="card mw-movement-list-card"><div class="section-head"><div><p class="eyebrow">Résultats</p><h2>${rows.length}${Number(s.total)>rows.length?' premiers':''} mouvement(s)</h2></div>${Number(s.uncategorized)>0?`<span class="mw-review-pill">${s.uncategorized} à catégoriser</span>`:''}</div><div class="movement-list">${rows.map(item=>{const positive=Number(item.amount_cents)>0;const transfer=Number(item.is_internal_transfer)===1;return `<button class="row movement-row list-button mw-row" data-mw-edit="${item.id}"><span class="movement-icon ${positive?'income':'expense'}">${transfer?'↔':positive?'↑':'↓'}</span><div><strong>${esc(item.user_label||item.label)}</strong><small>${fmtDate(item.booking_date)} · ${esc(item.category||'Non catégorisé')}${item.account_name?` · ${esc(item.account_name)}`:''}</small></div><div class="money ${positive?'positive':'negative'}">${positive?'+':''}${euro(item.amount_cents)}</div></button>`;}).join('')||'<div class="empty-state">Aucun mouvement ne correspond aux filtres.</div>'}</div></section>
    </section>`;
  }

  function bindMovementControls(root){
    root.querySelectorAll('[data-period]').forEach(b=>b.addEventListener('click',()=>{movementState.period=b.dataset.period;enhanceMovements(true);}));
    root.querySelectorAll('[data-type]').forEach(b=>b.addEventListener('click',()=>{movementState.flow_type=b.dataset.type;enhanceMovements(true);}));
    root.querySelector('#mwSearch')?.addEventListener('input',e=>{movementState.q=e.target.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>enhanceMovements(true),250);});
    [['mwCategory','category'],['mwAccount','account_id'],['mwMin','min_cents'],['mwMax','max_cents'],['mwSort','sort']].forEach(([id,key])=>root.querySelector(`#${id}`)?.addEventListener('change',e=>{movementState[key]=e.target.value;enhanceMovements(true);}));
    root.querySelector('#mwReset')?.addEventListener('click',()=>{Object.assign(movementState,{period:'30d',flow_type:'all',category:'',account_id:'',min_cents:'',max_cents:'',sort:'date_desc',q:''});enhanceMovements(true);});
    root.querySelectorAll('[data-mw-edit]').forEach(b=>b.addEventListener('click',()=>openMovement(Number(b.dataset.mwEdit))));
  }

  async function enhanceMovements(force=false){
    if(busyMovements)return;
    const root=document.querySelector('[data-screen="movements"]');
    if(!root||!root.classList.contains('active'))return;
    if(!force&&root.querySelector(`#${MOVEMENT_ID}`))return;
    busyMovements=true;
    try{
      const data=await api(`/api/v4.6/movements/analysis?${movementQuery()}`);
      const head=root.querySelector('.page-head');
      if(!head)return;
      document.getElementById(MOVEMENT_ID)?.remove();
      head.insertAdjacentHTML('afterend',movementHtml(data));
      Array.from(root.children).forEach(el=>{if(el===head||el.id===MOVEMENT_ID)return;el.hidden=true;el.dataset.preV5Hidden='1';});
      head.classList.add('mw-page-head-compact');
      const copy=head.querySelector('.subtle');if(copy)copy.textContent='Filtre ton historique et comprends immédiatement où part ton argent.';
      bindMovementControls(root);
    }catch(error){console.warn('Flow movements enhancement unavailable',error);}
    finally{busyMovements=false;}
  }

  async function openMovement(id){
    const dialog=document.getElementById('editDialog'),body=document.getElementById('editBody');
    if(!dialog||!body)return;dialog.showModal();body.innerHTML='<div class="skeleton tall"></div>';
    try{
      const [data,categories]=await Promise.all([api(`/api/v4.6/movements/analysis?period=12m&limit=500`),api('/api/categories')]);
      const m=(data.rows||[]).find(x=>Number(x.id)===id);if(!m)throw new Error('Mouvement introuvable');
      body.innerHTML=`<form id="mwEditForm" class="stack"><p class="eyebrow">${fmtDate(m.booking_date)} · ${esc(m.account_name||'Compte')}</p><h3>${esc(m.label)}</h3><label class="form-label">Libellé personnel<input class="field" name="user_label" value="${esc(m.user_label||'')}"></label><label class="form-label">Catégorie<select class="field" name="category"><option value="">Non catégorisé</option>${categories.map(c=>`<option value="${esc(c.name)}" ${c.name===m.category?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label><label class="toggle-row"><span><strong>Transfert interne</strong><small>Exclu de la consommation</small></span><input type="checkbox" name="is_internal_transfer" ${m.is_internal_transfer?'checked':''}></label><label class="toggle-row"><span><strong>Exceptionnel</strong><small>Isolé des tendances courantes</small></span><input type="checkbox" name="is_exceptional" ${m.is_exceptional?'checked':''}></label><button class="btn primary">Enregistrer</button></form>`;
      body.querySelector('#mwEditForm').addEventListener('submit',async e=>{e.preventDefault();const f=e.currentTarget.elements;await api(`/api/v3.1/movements/${id}`,{method:'PATCH',body:JSON.stringify({user_label:f.user_label.value||null,category:f.category.value||null,is_internal_transfer:f.is_internal_transfer.checked,is_exceptional:f.is_exceptional.checked})});dialog.close();enhanceMovements(true);});
    }catch(error){body.innerHTML=`<div class="notice">${esc(error.message)}</div>`;}
  }

  function wealthTrend(history){
    const rows=(history||[]).slice(-10);if(rows.length<2)return '<p class="subtle">Historique insuffisant.</p>';
    const vals=rows.map(r=>Number(r.net_worth_cents||0)),min=Math.min(...vals),max=Math.max(...vals),span=Math.max(1,max-min),w=620,h=135,p=12;
    const pts=vals.map((v,i)=>`${p+i*(w-2*p)/(vals.length-1)},${p+(max-v)*(h-2*p)/span}`).join(' ');
    return `<div class="mw-wealth-chart"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Évolution patrimoine"><polyline points="${pts}" class="mw-wealth-line"/></svg><div><span>${fmtDate(rows[0].date)}</span><span>${fmtDate(rows.at(-1).date)}</span></div></div>`;
  }

  function wealthHtml(wealth,quality){
    const groups=[['Liquidités',Number(wealth.cash_cents||0),'comptes courants et cash'],['Épargne',Number(wealth.savings_cents||0),'livrets et épargne'],['Investissements',Number(wealth.investments_cents||0),'placements financiers'],['Actifs physiques',Number(wealth.physical_assets_cents||0),'valorisations déclarées']].filter(([,v])=>v>0);
    const accounts=(wealth.accounts||[]).filter(a=>Number(a.include_in_wealth??1)!==0);
    const goals=(wealth.goals||[]);
    return `<section id="${WEALTH_ID}" class="mw-stack">
      <section class="card mw-wealth-hero"><div><p class="eyebrow">Vue consolidée · ${fmtDate(wealth.as_of)}</p><span>Patrimoine net</span><strong>${euro(wealth.net_worth_cents)}</strong><p>Somme des valeurs connues. Chaque compte conserve sa propre date de valorisation.</p></div><div class="mw-wealth-side"><span>Actifs connus</span><strong>${euro(wealth.total_assets_cents)}</strong><span>Dettes renseignées</span><strong>${Number(wealth.total_debt_cents)>0?euro(wealth.total_debt_cents):'Non renseignées'}</strong></div></section>
      <section class="mw-kpis mw-wealth-kpis">${groups.map(([label,value,copy])=>`<article class="card"><span>${label}</span><strong>${euro(value)}</strong><small>${copy}</small></article>`).join('')}</section>
      ${quality.status!=='fresh'?`<section class="mw-compact-status"><div><span class="mw-status-dot"></span><strong>${quality.stale_accounts.length+quality.undated_accounts.length} valeur(s) à actualiser</strong></div><p>Les montants restent visibles mais leur date est signalée ci-dessous.</p></section>`:''}
      <section class="card"><div class="section-head"><div><p class="eyebrow">Comptes</p><h2>Valeurs connues</h2></div></div><div class="mw-account-list">${accounts.map(a=>{const hasDate=Boolean(a.balance_as_of);const stale=(quality.stale_accounts||[]).some(x=>Number(x.id)===Number(a.id));return `<div class="mw-account"><div><strong>${esc(a.name)}</strong><small>${esc(a.kind||'Compte')} · ${hasDate?`au ${fmtDate(a.balance_as_of)}`:'date non renseignée'}${stale?' · à actualiser':''}</small></div><div class="mw-account-value"><strong>${hasDate?euro(a.current_balance_cents):'Non renseigné'}</strong><button class="mw-edit-balance" data-balance="${a.id}">Mettre à jour</button></div></div>`;}).join('')||'<p class="subtle">Aucun compte patrimonial.</p>'}</div></section>
      <section class="card"><div class="section-head"><div><p class="eyebrow">Évolution</p><h2>Patrimoine net</h2></div></div>${wealthTrend(wealth.history)}</section>
      <section class="card"><div class="section-head"><div><p class="eyebrow">Objectifs</p><h2>À financer</h2></div></div><div class="mw-goal-list">${goals.map(g=>{const current=Number(g.effective_current_cents??g.current_cents??0),target=Number(g.target_cents||0),progress=target?Math.min(100,current/target*100):0;return `<article class="mw-goal"><div><strong>${esc(g.name)}</strong><span>${Math.round(progress)} %</span></div><div class="mw-track"><i style="width:${progress}%"></i></div><div><small>${current>0?`${euro(current)} constitués`:'À financer'} · cible ${euro(target)}</small><small>${g.required_monthly_cents==null?'Effort à définir':`${euro(g.required_monthly_cents)}/mois requis`}</small></div></article>`;}).join('')||'<p class="subtle">Aucun objectif actif.</p>'}</div></section>
    </section>`;
  }

  async function enhanceWealth(force=false){
    if(busyWealth)return;const root=document.querySelector('[data-screen="wealth"]');if(!root||!root.classList.contains('active'))return;if(!force&&root.querySelector(`#${WEALTH_ID}`))return;
    busyWealth=true;
    try{const [wealth,quality]=await Promise.all([api('/api/v2.2/wealth'),api('/api/v4.6/wealth/quality')]);const head=root.querySelector('.page-head');if(!head)return;document.getElementById(WEALTH_ID)?.remove();head.insertAdjacentHTML('afterend',wealthHtml(wealth,quality));Array.from(root.children).forEach(el=>{if(el===head||el.id===WEALTH_ID)return;el.hidden=true;el.dataset.preV5Hidden='1';});const copy=head.querySelector('.subtle');if(copy)copy.textContent='Tes actifs, objectifs et dates de valorisation — sans faux zéros.';root.querySelectorAll('[data-balance]').forEach(b=>b.addEventListener('click',()=>openBalance(Number(b.dataset.balance),wealth.accounts)));}catch(error){console.warn('Flow wealth enhancement unavailable',error);}finally{busyWealth=false;}
  }

  function openBalance(id,accounts){
    const a=(accounts||[]).find(x=>Number(x.id)===id),dialog=document.getElementById('editDialog'),body=document.getElementById('editBody');if(!a||!dialog||!body)return;dialog.showModal();const today=new Date().toISOString().slice(0,10);body.innerHTML=`<form id="mwBalanceForm" class="stack"><p class="eyebrow">Patrimoine</p><h3>${esc(a.name)}</h3><label class="form-label">Nouveau solde (€)<input class="field" name="balance" inputmode="decimal" value="${(Number(a.current_balance_cents||0)/100).toFixed(2)}" required></label><label class="form-label">Date de valeur<input class="field" name="date" type="date" value="${a.balance_as_of||today}" required></label><p class="subtle">Cette mise à jour crée aussi un snapshot historisé. Elle ne crée aucun mouvement bancaire.</p><button class="btn primary">Mettre à jour le solde</button></form>`;body.querySelector('#mwBalanceForm').addEventListener('submit',async e=>{e.preventDefault();const f=e.currentTarget.elements,amount=Math.round(Number(String(f.balance.value).replace(',','.'))*100);if(!Number.isFinite(amount))return;await api(`/api/accounts/${id}/balance`,{method:'PUT',body:JSON.stringify({current_balance_cents:amount,balance_as_of:f.date.value})});dialog.close();enhanceWealth(true);});
  }

  function enhance(){enhanceMovements();enhanceWealth();}
  const observer=new MutationObserver(()=>queueMicrotask(enhance));
  const start=()=>{document.querySelectorAll('[data-screen="movements"],[data-screen="wealth"]').forEach(s=>observer.observe(s,{childList:true,subtree:false}));document.querySelectorAll('[data-nav="movements"],[data-nav="wealth"]').forEach(b=>b.addEventListener('click',()=>setTimeout(enhance,40)));enhance();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();