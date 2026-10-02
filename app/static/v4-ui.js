(()=>{
  const VERSION='6.5.0';
  const state={
    screen:'home',
    month:new Date().toISOString().slice(0,7),
    filter:'all',
    query:''
  };

  const q=selector=>document.querySelector(selector);
  const qa=selector=>[...document.querySelectorAll(selector)];
  const euro=cents=>new Intl.NumberFormat('fr-FR',{
    style:'currency',
    currency:'EUR',
    maximumFractionDigits:2
  }).format((Number(cents)||0)/100);
  const esc=value=>{
    const node=document.createElement('div');
    node.textContent=value??'';
    return node.innerHTML;
  };
  const api=async(url,options={})=>{
    const headers=options.body instanceof FormData?{}:{'Content-Type':'application/json'};
    const response=await fetch(url,{
      cache:'no-store',
      ...options,
      headers:{...headers,...(options.headers||{})}
    });
    if(!response.ok)throw new Error((await response.text())||`HTTP ${response.status}`);
    return response.status===204?null:response.json();
  };

  const icon=(name)=>{
    const paths={
      calendar:'<rect x="3" y="5" width="18" height="16" rx="3"></rect><path d="M8 3v4M16 3v4M3 10h18"></path>',
      wallet:'<path d="M4 6.5A2.5 2.5 0 0 1 6.5 4H19a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6.5A2.5 2.5 0 0 1 4 17.5Z"></path><path d="M4 8h15M16 13h5"></path>',
      arrow:'<path d="M5 12h14M14 7l5 5-5 5"></path>',
      trend:'<path d="m4 17 5-5 4 3 7-8"></path><path d="M15 7h5v5"></path>',
      check:'<path d="m5 12 4 4L19 6"></path>',
      alert:'<path d="M12 8v5M12 17h.01"></path><path d="M10.3 3.8 2.7 17a2 2 0 0 0 1.7 3h15.2a2 2 0 0 0 1.7-3L13.7 3.8a2 2 0 0 0-3.4 0Z"></path>',
      income:'<path d="M12 4v16M7 9l5-5 5 5"></path>',
      expense:'<path d="M12 4v16M7 15l5 5 5-5"></path>',
      spark:'<path d="m12 3 1.4 4.6L18 9l-4.6 1.4L12 15l-1.4-4.6L6 9l4.6-1.4Z"></path><path d="m19 15 .7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7Z"></path>',
      shield:'<path d="M12 3 5 6v5c0 4.8 2.9 8 7 10 4.1-2 7-5.2 7-10V6Z"></path><path d="m9 12 2 2 4-4"></path>'
    };
    return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name]||paths.spark}</svg>`;
  };
  const todayLabel=()=>new Intl.DateTimeFormat('fr-FR',{
    weekday:'long',
    day:'numeric',
    month:'long'
  }).format(new Date());
  const dateLabel=value=>{
    if(!value)return 'Date inconnue';
    const parsed=new Date(`${String(value).slice(0,10)}T12:00:00`);
    if(Number.isNaN(parsed.getTime()))return String(value);
    return new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short'}).format(parsed);
  };
  const monthLabel=value=>{
    const parsed=new Date(`${value}-15T12:00:00`);
    return new Intl.DateTimeFormat('fr-FR',{month:'long',year:'numeric'}).format(parsed);
  };
  const page=(kicker,title,copy='')=>`<header class="page-head"><p class="eyebrow">${esc(kicker)}</p><h1>${esc(title)}</h1>${copy?`<p class="subtle">${esc(copy)}</p>`:''}</header>`;
  const skeleton=()=>'<div class="skeleton tall" aria-label="Chargement"></div>';
  const safeLabel=status=>({comfortable:'Confortable',prudent:'Prudent',tight:'Serré',critical:'Critique'})[status]||'À vérifier';
  const healthLabel=status=>({excellent:'Excellente',good:'Bonne',watch:'À surveiller',fragile:'Fragile'})[status]||'À vérifier';
  const statusLabel=status=>({achieved:'Atteint',on_track:'Dans les temps',at_risk:'À surveiller',off_track:'En retard',late:'Échéance dépassée',no_deadline:'Sans échéance'})[status]||status||'—';
  const lineStatus=status=>({ok:'Maîtrisé',over:'Dépassé',comfortable:'Maîtrisé',good:'Maîtrisé',watch:'À surveiller',warning:'À surveiller',exceeded:'Dépassé',critical:'Dépassé'})[status]||status||'Suivi';

  function renderError(root,title,error,screen){root.innerHTML=page('Indisponible',title,'Les données n’ont pas pu être chargées.')+`<section class="card empty-state"><div><strong>Réessaie dans un instant.</strong><p class="subtle">${esc(error?.message||'Erreur réseau')}</p><button class="btn primary" data-retry="${screen}">Réessayer</button></div></section>`;root.querySelector('[data-retry]')?.addEventListener('click',()=>render(screen));}
  function nav(name){state.screen=name;qa('.screen').forEach(screen=>screen.classList.toggle('active',screen.dataset.screen===name));qa('.bottom-nav [data-nav]').forEach(button=>{const active=button.dataset.nav===name;button.classList.toggle('active',active);button.setAttribute('aria-current',active?'page':'false');});window.scrollTo({top:0,behavior:'instant'});render(name);}
  function bindNavigation(root=document){root.querySelectorAll('[data-go]').forEach(button=>button.addEventListener('click',()=>nav(button.dataset.go)));root.querySelectorAll('[data-open-settings]').forEach(button=>button.addEventListener('click',openSystem));}

  function forecastAccuracyCard(data){
    const modes=[
      ['engaged','Engagée'],
      ['realistic','Réaliste'],
      ['prudent','Prudente']
    ];
    const comparisons=(data?.modes||{});
    const hasResults=data?.status==='available';
    const rows=hasResults?modes.map(([key,label])=>{
      const result=comparisons[key]||{};
      const bias=Number(result.mean_error_cents||0);
      const biasLabel=bias>0?'solde prévu supérieur au relevé':bias<0?'solde prévu inférieur au relevé':'écart moyen nul';
      return `<article class="accuracy-mode"><div class="accuracy-mode-head"><strong>${label}</strong><span>${Number(result.comparison_count||0)} comparaison(s)</span></div><p class="accuracy-error-label">Erreur moyenne absolue</p><strong class="accuracy-error">${euro(result.mean_absolute_error_cents)}</strong><small>${biasLabel} · ${euro(Math.abs(bias))}</small></article>`;
    }).join(''):'<div class="empty-state">Aucune comparaison fiable disponible pour le moment.</div>';
    const detail=hasResults
      ?'Une erreur plus faible signifie que le solde projeté était plus proche du relevé confirmé.'
      :Number(data?.snapshot_count||0)>0
        ?'Les prévisions sont enregistrées, mais aucun relevé confirmé ne correspond encore à leurs dates projetées.'
        :'Aucune prévision enregistrée dans la période analysée.';
    return `<section class="card forecast-accuracy" aria-labelledby="forecastAccuracyTitle"><div class="section-head"><div><p class="eyebrow">Fiabilité des prévisions</p><h2 id="forecastAccuracyTitle">Prévu et constaté</h2></div><span class="confidence-pill">${Number(data?.snapshot_count||0)} capture(s)</span></div><p class="subtle">Comparaison aux soldes confirmés des relevés. ${esc(detail)}</p>${hasResults?`<div class="forecast-accuracy-grid">${rows}</div><p class="accuracy-footnote">La valeur moyenne affichée indique la différence entre le solde prévu et le solde du relevé.</p>`:rows}</section>`;
  }

  async function renderHome(){
    const root=q('[data-screen="home"]');root.innerHTML=page('Aujourd’hui',todayLabel(),'Ce que tu peux réellement dépenser, et pourquoi.')+skeleton();
    try{
      const [dashboard,safeToSpend,trajectory,recurring]=await Promise.all([
        api('/api/dashboard'),
        api('/api/v6/safe-to-spend'),
        api('/api/v6/trajectory'),
        api('/api/recurring')
      ]);
      const components=safeToSpend?.components||{},safe=safeToSpend?.safe_to_spend||{},realistic=trajectory?.scenarios?.realistic||{};
      const events=(realistic.timeline||[]).flatMap(day=>(day.events||[]).map(event=>({...event,date:event.date||day.date})));
      const upcoming=events.filter(event=>Number(event.amount_cents)<0).sort((a,b)=>String(a.date||'').localeCompare(String(b.date||''))).slice(0,4);
      const activeRecurring=(recurring||[]).filter(item=>Number(item.is_active)!==0&&Number(item.amount_cents)<0);
      const recurringMonthly=activeRecurring.reduce((sum,item)=>sum+monthlyEquivalent(item),0);
      const opening=Number(components.current_balance_cents??dashboard.accounts?.[0]?.current_balance_cents??0);
      const planned=Math.abs(Number(components.planned_outflows_cents||0));
      const recurringReserve=Math.abs(Number(components.recurring_outflows_cents??components.recurring_reserve_cents??0));
      const goals=Math.abs(Number(components.goal_reservations_cents||0));
      const reserve=Math.abs(Number(components.safety_reserve_cents||0));
      const available=Number(safe.calculated_cents??safe.today_cents??0);
      const nextIncome=dashboard?.forecast?.next_income;
      root.innerHTML=page('Aujourd’hui',todayLabel(),'Ce que tu peux réellement dépenser, et pourquoi.')+`
        <section class="card hero decision-hero-v7">
          <p class="hero-label">Disponible à dépenser</p>
          <div class="hero-amount">${euro(available)}</div>
          <p class="hero-copy">Après les échéances prévues, les dépenses régulières, les objectifs et le coussin de sécurité.</p>
          <div class="hero-facts">
            <div class="hero-fact"><span>Solde réel</span><strong>${euro(opening)}</strong><small>${dateLabel(dashboard.accounts?.[0]?.balance_as_of||safeToSpend?.as_of)}</small></div>
            <div class="hero-fact"><span>Réguliers / mois</span><strong>${euro(recurringMonthly)}</strong><small>${activeRecurring.length} actif(s)</small></div>
            <div class="hero-fact"><span>Prochain revenu</span><strong>${nextIncome?euro(nextIncome.amount_cents):'—'}</strong><small>${nextIncome?dateLabel(nextIncome.date):'Non identifié'}</small></div>
          </div>
        </section>
        <section class="card explain-card">
          <div class="section-head"><div><p class="eyebrow">Comprendre le calcul</p><h2>D'où vient ce montant</h2></div></div>
          <div class="formula">
            <div class="formula-row"><span>Solde réel</span><strong>${euro(opening)}</strong></div>
            <div class="formula-row"><span>- Échéances prévues</span><strong>${euro(-planned)}</strong></div>
            <div class="formula-row"><span>- Dépenses régulières réservées</span><strong>${euro(-recurringReserve)}</strong></div>
            <div class="formula-row"><span>- Objectifs réservés</span><strong>${euro(-goals)}</strong></div>
            <div class="formula-row"><span>- Coussin de sécurité</span><strong>${euro(-reserve)}</strong></div>
            <div class="formula-row formula-result"><span>= Disponible à dépenser</span><strong>${euro(available)}</strong></div>
          </div>
        </section>
        <section class="card">
          <div class="section-head"><div><p class="eyebrow">À venir</p><h2>Prochaines sorties</h2></div><button class="section-action" data-go="recurring">Voir les réguliers</button></div>
          <div class="stack">${upcoming.map(event=>`<div class="decision-row compact-decision"><div><strong>${esc(event.label||'Échéance')}</strong><small>${dateLabel(event.date)} · ${esc(event.source||event.certainty||'Prévision')}</small></div><div class="money negative">${euro(event.amount_cents)}</div></div>`).join('')||'<div class="empty-state">Aucune sortie identifiée sur l’horizon actuel.</div>'}</div>
        </section>
        <section class="home-actions-v7">
          <button class="card action-card-v7" data-go="month"><span>Ce mois-ci</span><strong>Comprendre mes dépenses</strong><small>Budget, fin de mois et catégories</small></button>
          <button class="card action-card-v7" data-go="movements"><span>Mouvements</span><strong>Voir mes transactions</strong><small>Rechercher et corriger</small></button>
          <button class="card action-card-v7" data-go="wealth"><span>Patrimoine</span><strong>Suivre mes objectifs</strong><small>Épargne, actifs et dettes</small></button>
        </section>`;
      bindNavigation(root);
    }catch(error){renderError(root,'Accueil',error,'home');}
  }

  async function renderMonth(){
    const root=q('[data-screen="month"]');root.innerHTML=page('Ce mois-ci','Mois','Revenus, dépenses, réguliers et ce qui devrait rester.')+skeleton();
    try{
      const [monthData,adaptive,closeout,dashboard,recurring]=await Promise.all([
        api(`/api/v2.1/months/${state.month}`),
        api(`/api/v3.5/adaptive-budget?month=${state.month}`),
        api(`/api/v3.5/closeout?month=${state.month}`),
        api('/api/dashboard'),
        api('/api/recurring')
      ]);
      const current=monthData.current||{},lines=adaptive.lines||[];
      const monthClose=Number(current.projected_close_cents);
      const monthOpening=Number(dashboard?.accounts?.reduce((sum,item)=>sum+Number(item.current_balance_cents||0),0)||0);
      const income=Number(current.income_cents||0),spent=Number(current.spent_cents||0),net=income-spent;
      const plannedAdjustment=Number.isFinite(monthClose)?monthClose-monthOpening-net:0;
      const activeRecurring=(recurring||[]).filter(item=>Number(item.is_active)!==0&&Number(item.amount_cents)<0);
      const recurringMonthly=activeRecurring.reduce((sum,item)=>sum+monthlyEquivalent(item),0);
      const topCategories=[...lines].sort((a,b)=>Number(b.spent_cents||0)-Number(a.spent_cents||0)).slice(0,6);
      root.innerHTML=page('Ce mois-ci','Mois','Revenus, dépenses, réguliers et ce qui devrait rester.')+`
        <section class="card month-toolbar"><button class="icon-btn" id="prevMonth" aria-label="Mois précédent">‹</button><div class="month-title"><strong>${monthLabel(state.month)}</strong><small>${state.month}</small></div><button class="icon-btn" id="nextMonth" aria-label="Mois suivant">›</button></section>
        <section class="card month-balance month-balance-v7"><div><p class="eyebrow">Ce qui devrait rester</p><strong class="${monthClose>=0?'positive':'danger'}">${Number.isFinite(monthClose)?euro(monthClose):'Indisponible'}</strong><small class="subtle">Solde estimé à la fin du mois</small></div></section>
        <section class="month-flow-v7">
          <article class="card metric"><span>Revenus</span><strong>${euro(income)}</strong><small>sur le mois</small></article>
          <article class="card metric"><span>Dépenses</span><strong>${euro(spent)}</strong><small>hors transferts internes</small></article>
          <article class="card metric"><span>Réguliers</span><strong>${euro(recurringMonthly)}</strong><small>équivalent mensuel</small></article>
          <article class="card metric metric-accent"><span>Reste pilotable</span><strong>${euro(adaptive.adaptive_pool_cents)}</strong><small>${adaptive.days_left||0} jour(s)</small></article>
        </section>
        <section class="card explain-card">
          <div class="section-head"><div><p class="eyebrow">Calcul du restant</p><h2>Comment arrive-t-on à la fin de mois</h2></div></div>
          <div class="formula">
            <div class="formula-row"><span>Solde réel de départ</span><strong>${euro(monthOpening)}</strong></div>
            <div class="formula-row"><span>+ Revenus - dépenses constatées</span><strong>${euro(net)}</strong></div>
            <div class="formula-row"><span>+/- Échéances et prévisions restantes</span><strong>${euro(plannedAdjustment)}</strong></div>
            <div class="formula-row formula-result"><span>= Solde estimé fin de mois</span><strong>${Number.isFinite(monthClose)?euro(monthClose):'—'}</strong></div>
          </div>
        </section>
        <section class="card recurring-entry recurring-entry-v7">
          <div><p class="eyebrow">Dépenses régulières</p><h2>${euro(recurringMonthly)} / mois</h2><p class="subtle">${activeRecurring.length} charge(s) active(s). Modifie montants et dates depuis la vue dédiée.</p></div>
          <button class="btn secondary" data-go="recurring">Gérer</button>
        </section>
        <section class="card">
          <div class="section-head"><div><p class="eyebrow">Où part l'argent</p><h2>Principales catégories</h2></div></div>
          <div class="budget-list">${topCategories.map(item=>{const spentValue=Number(item.spent_cents)||0,planned=Math.max(0,Number(item.planned_cents)||0),ratio=planned?Math.min(100,Math.round(spentValue/planned*100)):0;return `<article class="budget-item"><div class="budget-item-head"><div><strong>${esc(item.category)}</strong><small>${euro(spentValue)} dépensés${planned?' sur '+euro(planned):''}</small></div><div class="money">${euro(item.recommended_remaining_cents)}</div></div><div class="budget-track ${ratio>90?'warning':''}"><i style="width:${ratio}%"></i></div></article>`;}).join('')||'<div class="empty-state">Aucune dépense catégorisée pour ce mois.</div>'}</div>
        </section>
        <section class="card month-status-v7"><p class="eyebrow">Écart au budget</p><strong class="${Number(closeout.variance_cents)<0?'danger':'positive'}">${euro(closeout.variance_cents)}</strong><p class="subtle">Taux d'épargne : ${closeout.savings_rate_pct??'—'} %</p></section>`;
      q('#prevMonth').addEventListener('click',()=>shiftMonth(-1));
      q('#nextMonth').addEventListener('click',()=>shiftMonth(1));
      bindNavigation(root);
    }catch(error){renderError(root,'Mois',error,'month');}
  }
  function shiftMonth(delta){const d=new Date(`${state.month}-15T12:00:00`);d.setMonth(d.getMonth()+delta);state.month=d.toISOString().slice(0,7);renderMonth();}

  function openGroupPreview(preview,{category,transactionType}={}){
    const dialog=q('#groupReviewDialog'),body=q('#groupReviewBody');
    if(!dialog||!body)return Promise.resolve(window.confirm('Confirmer la validation de cette sélection ?'));
    const p=preview||{},movements=p.movements||[],groups=p.groups||[];
    const amountClass=Number(p.net_amount_cents||0)>=0?'positive':'negative';
    const typeLabel={expense:'Dépense',income:'Revenu',transfer:'Transfert',refund:'Remboursement'}[transactionType]||'Dépense';
    const groupLines=groups.length?groups.map(group=>`<div class="group-preview-line"><div><strong>${esc(group.normalized_label)}</strong><small>${group.pending_count} mouvement(s)</small></div></div>`).join(''):`<div class="group-preview-line"><div><strong>${esc(p.normalized_label||'Groupe sélectionné')}</strong><small>${p.pending_count||0} mouvement(s)</small></div></div>`;
    const movementLines=movements.slice(0,12).map(item=>{const amount=Number(item.amount_cents)||0;return `<div class="group-preview-movement"><div><strong>${esc(item.label||'Mouvement')}</strong><small>${dateLabel(item.booking_date)}</small></div><span class="money ${amount>=0?'positive':'negative'}">${amount>=0?'+':''}${euro(amount)}</span></div>`;}).join('');
    body.innerHTML=`<div class="group-preview-intro"><span class="status-pill">Aperçu uniquement</span><p>Rien ne sera modifié avant l'appui sur 'Valider'.</p></div><div class="group-preview-summary"><div><span>Groupes</span><strong>${groups.length||1}</strong></div><div><span>Mouvements</span><strong>${p.pending_count||0}</strong></div><div><span>Débits</span><strong>${p.debit_count||0}</strong></div><div><span>Crédits</span><strong>${p.credit_count||0}</strong></div><div class="group-preview-total"><span>Impact net</span><strong class="${amountClass}">${Number(p.net_amount_cents||0)>=0?'+':''}${euro(p.net_amount_cents||0)}</strong></div></div><section class="group-preview-section"><div class="section-head"><div><p class="eyebrow">Application prévue</p><h3>${esc(category||'Catégorie')}</h3></div><span class="chip">${typeLabel}</span></div><p class="subtle">La catégorie sera appliquée à tous les mouvements listés ci-dessous.</p></section><section class="group-preview-section"><div class="section-head"><div><p class="eyebrow">Groupes concernés</p><h3>${groups.length||1} groupe(s)</h3></div></div><div class="group-preview-groups">${groupLines}</div></section><section class="group-preview-section"><div class="section-head"><div><p class="eyebrow">Détail</p><h3>${movements.length>12?`12 premiers mouvements sur ${movements.length}`:`${movements.length} mouvement(s)`}</h3></div></div><div class="group-preview-movements">${movementLines||'<p class="subtle">Aucun détail disponible.</p>'}</div></section>`;
    dialog.showModal();
    return new Promise(resolve=>{const finish=result=>{dialog.close();resolve(result);};q('#groupReviewCancel').onclick=()=>finish(false);q('#groupReviewCancelBottom').onclick=()=>finish(false);q('#groupReviewConfirm').onclick=()=>finish(true);});
  }

  function bindGroupReviewModal(root){
    root.addEventListener('click',async event=>{
      const button=event.target.closest('.group-review-apply,#batchGroupReview');
      if(!button)return;
      event.preventDefault();
      event.stopPropagation();
      const category=q('#batchGroupCategory')?.value;
      const transactionType=q('#batchGroupType')?.value;
      const labels=button.id==='batchGroupReview'?[...root.querySelectorAll('[data-group-select]:checked')].map(input=>input.value):[button.dataset.groupLabel];
      if(!labels.length){alert('Sélectionne au moins un groupe.');return;}
      if(!category){alert(button.id==='batchGroupReview'?'Choisis une catégorie commune.':'Choisis une catégorie avant de continuer.');return;}
      button.disabled=true;
      const endpoint=button.id==='batchGroupReview'?'/api/imports/inbox/group-review/batch':'/api/imports/inbox/group-review';
      const payload=button.id==='batchGroupReview'?{normalized_labels:labels,category,transaction_type:transactionType,confirm:false}:{normalized_label:labels[0],category,transaction_type:transactionType,confirm:false};
      try{
        const preview=await api(endpoint,{method:'POST',body:JSON.stringify(payload)});
        const confirmed=await openGroupPreview(preview.preview||{},{category,transactionType});
        if(!confirmed){button.disabled=false;return;}
        const confirmPayload={...payload,confirm:true};
        await api(endpoint,{method:'POST',body:JSON.stringify(confirmPayload)});
        renderMovements();
      }catch(error){button.disabled=false;alert(error.message);}
    },true);
  }

  async function renderMovements(){
    const root=q('[data-screen="movements"]');root.innerHTML=page('Contrôle','Mouvements','Comprendre où part ton argent et corriger les opérations.')+skeleton();
    try{
      const params=new URLSearchParams({month:state.month,limit:'150'});if(state.query)params.set('q',state.query);if(state.filter!=='all')params.set('quality',state.filter);
      const [rowsResult,summaryResult,intelligenceResult,groupResult,categoriesResult]=await Promise.allSettled([api(`/api/v3.1/movements?${params}`),api(`/api/v3.1/movement-summary?month=${state.month}`),api('/api/v3.7/data-intelligence'),api('/api/imports/inbox/groups?limit=12'),api('/api/categories')]);const rows=rowsResult.status==='fulfilled'?rowsResult.value:[];const summary=summaryResult.status==='fulfilled'?summaryResult.value:{};const intelligence=intelligenceResult.status==='fulfilled'?intelligenceResult.value:{};const groupData=groupResult.status==='fulfilled'?groupResult.value:{total_pending:0,groups:[],error:'Impossible de charger les groupes de revue.'};const categories=categoriesResult.status==='fulfilled'?categoriesResult.value:[];
      const expenses=rows.filter(item=>Number(item.amount_cents)<0&&!item.is_internal_transfer&&!item.exclude_from_analytics);
      const incomes=rows.filter(item=>Number(item.amount_cents)>0&&!item.is_internal_transfer&&!item.exclude_from_analytics);
      const expenseTotal=expenses.reduce((sum,item)=>sum+Math.abs(Number(item.amount_cents)||0),0),incomeTotal=incomes.reduce((sum,item)=>sum+Number(item.amount_cents||0),0);
      const categoryTotals={};expenses.forEach(item=>{const key=item.category||'Non catégorisé';categoryTotals[key]=(categoryTotals[key]||0)+Math.abs(Number(item.amount_cents)||0);});
      const categoryMarkup=`<section class="card movement-categories"><div class="section-head"><div><p class="eyebrow">Où part l'argent</p><h2>Par catégorie</h2></div><span class="subtle">${Object.keys(categoryTotals).length} catégorie(s)</span></div><div class="category-list">${Object.entries(categoryTotals).sort((a,b)=>b[1]-a[1]).slice(0,8).map(([category,total])=>{const pct=expenseTotal?Math.round(total/expenseTotal*100):0;return `<div class="category-row"><div class="category-name"><strong>${esc(category)}</strong><small>${pct} % des dépenses</small></div><div class="category-value"><strong>${euro(total)}</strong><i><b style="width:${pct}%"></b></i></div></div>`;}).join('')||'<div class="empty-state">Aucune dépense catégorisée pour ce mois.</div>'}</div></section>`;
      const guide=`<section class="card explain-card movement-guide"><p class="eyebrow">Comment lire cette page</p><p class="subtle">Les dépenses diminuent ton solde, les revenus l'augmentent. Les transferts entre tes comptes sont exclus des totaux. Ouvre une opération pour modifier sa catégorie ou son libellé.</p></section>`;
      const groupMarkup=`<section class="card movement-group-review"><div class="section-head"><div><p class="eyebrow">Revue groupée</p><h2>À valider par groupe</h2></div><span class="subtle">${groupData.error?'Indisponible':`${groupData.total_pending||0} en attente`}</span></div><p class="subtle">Sélectionne plusieurs groupes pour les valider ensemble. Un aperçu de l'impact sera affiché avant confirmation.</p><div class="group-review-batch"><select id="batchGroupCategory" aria-label="Catégorie commune"><option value="">Catégorie commune</option>${(categories||[]).map(category=>`<option value="${esc(category.name)}">${esc(category.name)}</option>`).join('')}</select><select id="batchGroupType" aria-label="Type commun"><option value="expense">Dépense</option><option value="income">Revenu</option><option value="transfer">Transfert</option><option value="refund">Remboursement</option></select><button class="btn primary" id="batchGroupReview">Aperçu de la sélection</button></div><div class="group-review-list">${(groupData.groups||[]).slice(0,20).map(group=>{return `<label class="group-review-row"><input type="checkbox" data-group-select value="${esc(group.normalized_label)}"><span><strong>${esc(group.normalized_label)}</strong><small>${group.occurrence_count} mouvement(s) · ${euro(group.net_amount_cents||0)}</small></span><button type="button" class="btn secondary group-review-apply" data-group-label="${esc(group.normalized_label)}">Aperçu</button></label>`;}).join('')||'<div class="empty-state">${groupData.error?esc(groupData.error):\'Aucun groupe à revoir.\'}</div>'}</div></section>`;
      root.innerHTML=page('Contrôle','Mouvements','Comprendre où part ton argent et corriger les opérations.')+`<section class="card movement-overview"><div class="section-head"><div><p class="eyebrow">${monthLabel(state.month)}</p><h2>Vue du mois</h2></div><span class="confidence-pill">${rows.length} opération(s)</span></div><div class="movement-totals"><div><span>Dépenses</span><strong class="negative">-${euro(expenseTotal)}</strong></div><div><span>Revenus</span><strong class="positive">+${euro(incomeTotal)}</strong></div><div><span>À classer</span><strong>${summary.uncategorized||0}</strong></div></div></section>${guide}${groupMarkup}<section class="card movement-month-picker"><div><p class="eyebrow">Période</p><strong>Afficher les mouvements de</strong></div><div class="month-picker-controls"><button class="icon-btn" id="movementPrevMonth" aria-label="Mois précédent">‹</button><input id="movementMonth" type="month" value="${state.month}" aria-label="Mois des mouvements"><button class="icon-btn" id="movementNextMonth" aria-label="Mois suivant">›</button></div></section><section class="toolbar sticky-tools"><label class="search-field"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"></circle><path d="m16 16 4 4"></path></svg><input id="movementSearch" autocomplete="off" placeholder="Rechercher un mouvement" value="${esc(state.query)}"></label><div class="chips">${[['all','Tous'],['uncategorized','À catégoriser'],['unmatched_transfer','Transferts'],['exceptional','Exceptionnels'],['excluded','Hors analyses']].map(([key,label])=>`<button class="chip ${state.filter===key?'active':''}" data-filter="${key}">${label}</button>`).join('')}</div></section>${categoryMarkup}<section class="card movement-operations"><div class="section-head"><div><p class="eyebrow">Détail</p><h2>Opérations</h2></div><span class="subtle">${rows.length} résultat(s)</span></div><div class="movement-list">${rows.map(item=>{const positive=Number(item.amount_cents)>0;return `<button class="row movement-row list-button" data-edit="${item.id}"><span class="movement-icon ${positive?'income':'expense'}">${icon(positive?'income':'expense')}</span><div><strong>${esc(item.user_label||item.label)}</strong><small>${dateLabel(item.booking_date)} · ${esc(item.category||'Non catégorisé')}${item.account_name?` · ${esc(item.account_name)}`:''}</small></div><div class="money ${positive?'positive':'negative'}">${positive?'+':''}${euro(item.amount_cents)}</div></button>`;}).join('')||'<div class="empty-state">Aucun mouvement ne correspond à ces filtres.</div>'}</div></section><section class="card movement-suggestions"><details><summary><span><p class="eyebrow">Automatisation</p><strong>Suggestions de marchands</strong></span><span class="chip">${(intelligence.merchant_suggestions||[]).length}</span></summary><div class="suggestion-list">${(intelligence.merchant_suggestions||[]).slice(0,5).map(item=>`<div class="row"><div><strong>${esc(item.canonical_name)}</strong><small>${item.occurrences} occurrence(s) · ${Math.round(item.confidence*100)} % de confiance</small></div>${item.confirmed?'<span class="chip active">Confirmé</span>':`<button class="chip merchant-confirm" data-merchant-key="${esc(item.normalized_key)}" data-merchant-name="${esc(item.canonical_name)}">Confirmer</button>`}</div>`).join('')||'<div class="empty-state">Aucune suggestion actuellement.</div>'}</div></details></section>`;
      q('#movementSearch').addEventListener('input',event=>{state.query=event.target.value;clearTimeout(window.__flowSearch);window.__flowSearch=setTimeout(renderMovements,260);});
      q('#movementMonth').addEventListener('change',event=>{if(event.target.value){state.month=event.target.value;renderMovements();}});
      q('#movementPrevMonth').addEventListener('click',()=>{shiftMovementMonth(-1);});
      q('#movementNextMonth').addEventListener('click',()=>{shiftMovementMonth(1);});
      root.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{state.filter=button.dataset.filter;renderMovements();}));
      root.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',()=>openMovement(Number(button.dataset.edit))));
      root.querySelectorAll('.group-review-apply').forEach(button=>button.addEventListener('click',async()=>{const category=q('#batchGroupCategory').value;const transactionType=q('#batchGroupType').value;if(!category){alert('Choisis une catégorie avant de continuer.');return;}button.disabled=true;try{const preview=await api('/api/imports/inbox/group-review',{method:'POST',body:JSON.stringify({normalized_label:button.dataset.groupLabel,category,transaction_type:transactionType,confirm:false})});const p=preview.preview||{};const confirmed=window.confirm(`Aperçu de validation\\n\\n${p.pending_count||0} mouvement(s)\\nDébits : ${p.debit_count||0}\\nCrédits : ${p.credit_count||0}\\nImpact net : ${euro(p.net_amount_cents||0)}\\n\\nConfirmer uniquement ce groupe ?`);if(confirmed){await api('/api/imports/inbox/group-review',{method:'POST',body:JSON.stringify({normalized_label:button.dataset.groupLabel,category,transaction_type:transactionType,confirm:true})});renderMovements();}else{button.disabled=false;}}catch(error){button.disabled=false;alert(error.message);}}));

      q('#batchGroupReview')?.addEventListener('click',async()=>{const labels=[...root.querySelectorAll('[data-group-select]:checked')].map(input=>input.value);const category=q('#batchGroupCategory').value;const transactionType=q('#batchGroupType').value;if(!labels.length){alert('Sélectionne au moins un groupe.');return;}if(!category){alert('Choisis une catégorie commune.');return;}const button=q('#batchGroupReview');button.disabled=true;try{const preview=await api('/api/imports/inbox/group-review/batch',{method:'POST',body:JSON.stringify({normalized_labels:labels,category,transaction_type:transactionType,confirm:false})});const p=preview.preview||{};const confirmed=window.confirm(`Aperçu de validation groupée\\n\\n${p.groups?.length||labels.length} groupe(s)\\n${p.pending_count||0} mouvement(s)\\nDébits : ${p.debit_count||0}\\nCrédits : ${p.credit_count||0}\\nImpact net : ${euro(p.net_amount_cents||0)}\\n\\nConfirmer la validation de toute la sélection ?`);if(confirmed){await api('/api/imports/inbox/group-review/batch',{method:'POST',body:JSON.stringify({normalized_labels:labels,category,transaction_type:transactionType,confirm:true})});renderMovements();}else{button.disabled=false;}}catch(error){button.disabled=false;alert(error.message);}});
      bindGroupReviewModal(root);
      root.querySelectorAll('.merchant-confirm').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{await api('/api/v3.7/merchant-aliases',{method:'POST',body:JSON.stringify({normalized_key:button.dataset.merchantKey,canonical_name:button.dataset.merchantName})});renderMovements();}catch(error){button.disabled=false;alert(error.message);}}));
    }catch(error){renderError(root,'Mouvements',error,'movements');}
  }

  function shiftMovementMonth(delta){const d=new Date(`${state.month}-15T12:00:00`);d.setMonth(d.getMonth()+delta);state.month=d.toISOString().slice(0,7);renderMovements();}

  async function openMovement(id){const dialog=q('#editDialog'),body=q('#editBody');dialog.showModal();body.innerHTML=skeleton();try{const [rows,categories]=await Promise.all([api('/api/v3.1/movements?limit=500'),api('/api/categories')]);const movement=rows.find(item=>item.id===id);if(!movement)throw new Error('Mouvement introuvable');body.innerHTML=`<form id="editForm" class="stack"><p class="eyebrow">${dateLabel(movement.booking_date)} · ${esc(movement.account_name||'Compte')}</p><h3>${esc(movement.label)}</h3><label class="form-label">Libellé personnel<input class="field" name="user_label" value="${esc(movement.user_label||'')}" placeholder="Nom lisible"></label><label class="form-label">Catégorie<select class="field" name="category"><option value="">Non catégorisé</option>${categories.map(category=>`<option ${category.name===movement.category?'selected':''}>${esc(category.name)}</option>`).join('')}</select></label><label class="toggle-row"><span><strong>Transfert interne</strong><small>Exclu des revenus et dépenses</small></span><input type="checkbox" name="is_internal_transfer" ${movement.is_internal_transfer?'checked':''}></label><label class="toggle-row"><span><strong>Dépense exceptionnelle</strong><small>Isolée des tendances courantes</small></span><input type="checkbox" name="is_exceptional" ${movement.is_exceptional?'checked':''}></label><label class="toggle-row"><span><strong>Exclure des analyses</strong><small>Reste visible dans l’historique</small></span><input type="checkbox" name="exclude_from_analytics" ${movement.exclude_from_analytics?'checked':''}></label><button class="btn primary">Enregistrer les corrections</button></form>`;q('#editForm').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget.elements;await api(`/api/v3.1/movements/${id}`,{method:'PATCH',body:JSON.stringify({user_label:form.user_label.value||null,category:form.category.value||null,is_internal_transfer:form.is_internal_transfer.checked,is_exceptional:form.is_exceptional.checked,exclude_from_analytics:form.exclude_from_analytics.checked})});dialog.close();renderMovements();});}catch(error){body.innerHTML=`<div class="notice">Modification indisponible : ${esc(error.message)}</div>`;}}

  async function renderWealth(){const root=q('[data-screen="wealth"]');root.innerHTML=page('Construction','Patrimoine','Voir ce qui est disponible, investi et encore dû.')+skeleton();try{const [wealth,goals,strategy]=await Promise.all([api('/api/v2.2/wealth'),api('/api/v3.3/goals-forecast?months=12'),api('/api/v3.8/strategy?months=3')]);const liquid=Math.max(0,Number(wealth.cash_cents)||0),savings=Math.max(0,Number(wealth.savings_cents)||0),investments=Math.max(0,Number(wealth.investments_cents)||0),allocationTotal=Math.max(1,liquid+savings+investments);root.innerHTML=page('Construction','Patrimoine','Voir ce qui est disponible, investi et encore dû.')+`<section class="card hero"><div class="hero-top"><span class="status-pill">Vue consolidée</span><span class="confidence-pill">au ${dateLabel(wealth.as_of)}</span></div><p class="hero-label">Patrimoine net</p><div class="hero-amount">${euro(wealth.net_worth_cents)}</div><p class="hero-copy">${esc(strategy.headline)} · surplus stratégique ${euro(strategy.strategic_surplus_cents)}</p><div class="wealth-breakdown"><div><span>Actifs</span><strong>${euro(wealth.total_assets_cents)}</strong></div><div><span>Dettes</span><strong>${euro(wealth.total_debt_cents)}</strong></div><div><span>Protégé</span><strong>${euro(strategy.protected_cents)}</strong></div></div></section><section class="card explain-card"><div class="section-head"><div><p class="eyebrow">Lecture simple</p><h2>Comment lire ce patrimoine</h2></div></div><p class="subtle">Le patrimoine net est calculé ainsi : actifs moins dettes. Les liquidités sont l’argent disponible sur les comptes ; l’épargne et les investissements construisent le patrimoine mais ne sont pas automatiquement dépensables.</p><div class="formula"><div class="formula-row"><span>Actifs</span><strong>${euro(wealth.total_assets_cents)}</strong></div><div class="formula-row"><span>- Dettes</span><strong>${euro(wealth.total_debt_cents)}</strong></div><div class="formula-row formula-result"><span>= Patrimoine net</span><strong>${euro(wealth.net_worth_cents)}</strong></div></div><p class="subtle">La somme protégée correspond aux objectifs et réserves déjà affectés. Elle est séparée de l’argent que tu peux dépenser aujourd’hui.</p></section><section class="card"><div class="section-head"><div><p class="eyebrow">Répartition financière</p><h2>Où se trouve ton argent</h2></div></div><div class="allocation-bar" aria-label="Répartition des avoirs"><i style="width:${liquid/allocationTotal*100}%"></i><i style="width:${savings/allocationTotal*100}%"></i><i style="width:${investments/allocationTotal*100}%"></i></div><div class="allocation-legend"><span>Liquidités<b>${euro(liquid)}</b></span><span>Épargne<b>${euro(savings)}</b></span><span>Investissements<b>${euro(investments)}</b></span></div></section><section class="card"><div class="section-head"><div><p class="eyebrow">Stratégie</p><h2>Ordre d’allocation</h2></div></div>${(strategy.buckets||[]).map((bucket,index)=>`<div class="decision-row"><span class="decision-icon">${index+1}</span><div><strong>${esc(bucket.label)}</strong><small>${esc(bucket.reason)}</small></div><div class="money">${euro(bucket.amount_cents)}</div></div>`).join('')||'<div class="empty-state">Aucune allocation recommandée.</div>'}<p class="subtle">${esc(strategy.method)}</p></section><section class="card"><div class="section-head"><div><p class="eyebrow">Objectifs</p><h2>Trajectoire à 12 mois</h2></div></div>${(goals.goals||[]).map(goal=>{const progress=Math.min(100,Math.max(0,Number(goal.projected_progress_pct)||0));return `<article class="goal-card"><div class="goal-head"><div><strong>${esc(goal.name)}</strong><small>${statusLabel(goal.status)} · cible ${goal.target_date?dateLabel(goal.target_date):'sans date'}</small></div><span class="goal-pct">${Math.round(progress)} %</span></div><div class="progress"><i style="width:${progress}%"></i></div><div class="goal-meta"><span>Effort ${goal.required_monthly_cents==null?'—':euro(goal.required_monthly_cents)+'/mois'}</span><span>Écart ${euro(goal.projected_gap_cents)}</span></div></article>`;}).join('')||'<div class="empty-state">Aucun objectif patrimonial n’est défini.</div>'}</section>`;}catch(error){renderError(root,'Patrimoine',error,'wealth');}}

  async function setDecision(key,status){await api(`/api/v3.6/decision-inbox/${encodeURIComponent(key)}`,{method:'PATCH',body:JSON.stringify({status})});openSystem();if(state.screen==='home')renderHome();}
  async function runRoutines(){const status=await api('/api/v3.6/routine-status');for(const routine of status.routines||[]){if(!routine.due)continue;if(routine.key==='month_open')await api(`/api/v3.6/open-month?month=${encodeURIComponent(routine.period)}`,{method:'POST'});if(routine.key==='month_close')await api(`/api/v3.6/close-month?month=${encodeURIComponent(routine.period)}`,{method:'POST'});if(routine.key==='weekly_review')await api('/api/v3.6/weekly-review',{method:'POST'});}await api('/api/v3.6/reconcile',{method:'POST'});openSystem();if(state.screen==='home')renderHome();}
  const frequencyLabel=value=>({weekly:'Hebdomadaire',monthly:'Mensuelle',quarterly:'Trimestrielle',yearly:'Annuelle'})[value]||'Mensuelle';
  const monthlyEquivalent=item=>{const amount=Math.abs(Number(item.amount_cents)||0);return item.frequency==='weekly'?Math.round(amount*52/12):item.frequency==='quarterly'?Math.round(amount/3):item.frequency==='yearly'?Math.round(amount/12):amount;};

  function recurringFormMarkup(item={},accounts=[],categories=[]){
    const amount=Math.abs(Number(item.amount_cents)||0)/100;
    return `<form id="recurringEditorForm" class="stack">
      <label class="form-label">Nom<input class="field" name="label" required maxlength="180" value="${esc(item.label||'')}"></label>
      <label class="form-label">Montant en euros<input class="field" name="amount" type="number" min="0" step="0.01" required value="${amount||''}"></label>
      <label class="form-label">Jour du mois<input class="field" name="day" type="number" min="1" max="31" required value="${item.day_of_month||1}"></label>
      <label class="form-label">Prochaine date<input class="field" name="next" type="date" value="${item.next_occurrence||''}"></label>
      <label class="form-label">Fréquence<select class="field" name="frequency">
        ${[['monthly','Mensuelle'],['weekly','Hebdomadaire'],['quarterly','Trimestrielle'],['yearly','Annuelle']].map(([value,label])=>`<option value="${value}" ${(item.frequency||'monthly')===value?'selected':''}>${label}</option>`).join('')}
      </select></label>
      <label class="form-label">Catégorie<select class="field" name="category"><option value="">Non catégorisé</option>${categories.map(category=>`<option value="${esc(category.name)}" ${item.category===category.name?'selected':''}>${esc(category.name)}</option>`).join('')}</select></label>
      <label class="form-label">Compte<select class="field" name="account">${accounts.map(account=>`<option value="${account.id}" ${Number(item.account_id)===Number(account.id)?'selected':''}>${esc(account.name)}</option>`).join('')}</select></label>
      <button class="btn primary">${item.id?'Enregistrer les modifications':'Ajouter la dépense régulière'}</button>
    </form>`;
  }

  async function openRecurringEditor(item,accounts,categories){
    const dialog=q('#editDialog'),body=q('#editBody');
    body.innerHTML=recurringFormMarkup(item,accounts,categories);
    dialog.showModal();
    q('#recurringEditorForm').addEventListener('submit',async event=>{
      event.preventDefault();
      const form=event.currentTarget.elements;
      const payload={
        account_id:Number(form.account.value),
        label:form.label.value.trim(),
        amount_cents:-Math.round(Math.abs(Number(form.amount.value))*100),
        day_of_month:Number(form.day.value),
        next_occurrence:form.next.value||null,
        frequency:form.frequency.value,
        category:form.category.value||null,
        kind:'commitment',
        certainty:'expected'
      };
      try{
        await api(item.id?`/api/recurring/${item.id}`:'/api/recurring',{method:item.id?'PATCH':'POST',body:JSON.stringify(payload)});
        dialog.close();
        renderRecurring();
      }catch(error){alert(error.message);}
    });
  }

  async function renderRecurring(){
    const root=q('[data-screen="recurring"]');root.innerHTML=page('Pilotage','Dépenses régulières','Tout ce qui revient et réduit ton disponible.')+skeleton();
    try{
      const [recurring,accounts,categories]=await Promise.all([api('/api/recurring?include_inactive=true'),api('/api/accounts'),api('/api/categories')]);
      const active=(recurring||[]).filter(item=>Number(item.is_active)!==0&&Number(item.amount_cents)<0);
      const monthly=active.reduce((sum,item)=>sum+monthlyEquivalent(item),0);
      const rows=active.map(item=>`<article class="recurring-manage-row">
        <div class="recurring-main"><strong>${esc(item.label)}</strong><small>${esc(item.category||'Non catégorisé')} · ${frequencyLabel(item.frequency)}</small></div>
        <div class="recurring-date"><span>Prochaine date</span><strong>${item.next_occurrence?dateLabel(item.next_occurrence):`le ${item.day_of_month||'—'}`}</strong></div>
        <div class="money negative">${euro(item.amount_cents)}</div>
        <button class="btn secondary recurring-edit" data-id="${item.id}">Modifier</button>
      </article>`).join('');
      root.innerHTML=page('Pilotage','Dépenses régulières','Tout ce qui revient et réduit ton disponible.')+`
        <section class="card recurring-summary"><div><p class="eyebrow">Réservé chaque mois</p><strong>${euro(monthly)}</strong><p class="subtle">Équivalent mensuel des dépenses régulières actives.</p></div><button class="btn primary" id="addRecurring">Ajouter</button></section>
        <section class="card"><div class="section-head"><div><p class="eyebrow">Calendrier</p><h2>${active.length} dépense(s) active(s)</h2></div></div><div class="recurring-manage-list">${rows||'<div class="empty-state">Aucune dépense régulière active.</div>'}</div></section>
        <section class="card recurring-help"><p class="eyebrow">Impact prévisionnel</p><p class="subtle">Le montant, le jour et la fréquence servent au forecast. Une modification change les prévisions futures, jamais les transactions bancaires déjà constatées.</p></section>
        <button class="btn secondary" data-go="month">Retour au mois</button>`;
      q('#addRecurring').addEventListener('click',()=>openRecurringEditor({},accounts,categories));
      root.querySelectorAll('.recurring-edit').forEach(button=>button.addEventListener('click',()=>openRecurringEditor(active.find(item=>String(item.id)===button.dataset.id)||{},accounts,categories)));
      bindNavigation(root);
    }catch(error){renderError(root,'Dépenses régulières',error,'recurring');}
  }

  function render(name){({home:renderHome,month:renderMonth,movements:renderMovements,wealth:renderWealth,recurring:renderRecurring})[name]?.();}
  function openSearch(){q('#searchDialog').showModal();setTimeout(()=>q('#globalSearch').focus(),80);}
  let searchTimer;
  function doSearch(){clearTimeout(searchTimer);const term=q('#globalSearch').value.trim(),output=q('#globalSearchResults');if(term.length<2){output.innerHTML='<div class="empty-state">Saisis au moins 2 caractères.</div>';return;}searchTimer=setTimeout(async()=>{try{const data=await api(`/api/v2.4/search?q=${encodeURIComponent(term)}&limit=10`);output.innerHTML=(data.results||[]).map(result=>`<button class="row list-button" data-type="${esc(result.type)}"><div><strong>${esc(result.title)}</strong><small>${esc(result.subtitle||result.type)}</small></div>${result.amount_cents!=null?`<div class="money">${euro(result.amount_cents)}</div>`:''}</button>`).join('')||'<div class="empty-state">Aucun résultat.</div>';output.querySelectorAll('[data-type]').forEach(button=>button.addEventListener('click',()=>{q('#searchDialog').close();nav(['movement','import','payroll','planned'].includes(button.dataset.type)?'movements':['goal','asset','account'].includes(button.dataset.type)?'wealth':'home');}));}catch(error){output.innerHTML='<div class="notice">Recherche momentanément indisponible.</div>';}},200);}

  async function openSystem(){const dialog=q('#settingsDialog');if(!dialog.open)dialog.showModal();const root=q('#systemCenter');root.innerHTML=skeleton();const results=await Promise.allSettled([api('/api/v3/system'),api('/api/update/status'),api('/api/v3.6/routine-status'),api('/api/v3.6/decision-inbox')]);const system=results[0].status==='fulfilled'?results[0].value:null,update=results[1].status==='fulfilled'?results[1].value:null,routines=results[2].status==='fulfilled'?results[2].value:null,inbox=results[3].status==='fulfilled'?results[3].value:null;root.innerHTML=`<section class="settings-section"><h3>Apparence</h3><div class="chips"><button class="chip" data-theme="system">Système</button><button class="chip" data-theme="light">Clair</button><button class="chip" data-theme="dark">Sombre</button></div></section><section class="settings-section"><div class="section-head"><div><p class="eyebrow">Routine</p><h3>Pilotage automatique</h3></div>${routines?`<button class="btn secondary" id="runRoutines">Exécuter</button>`:''}</div>${routines?(routines.routines||[]).map(routine=>`<div class="routine-row"><div><strong>${esc(routine.label)}</strong><small>${esc(routine.period)}${routine.count!=null?` · ${routine.count}`:''}</small></div><span class="chip ${routine.due?'warning':'active'}">${routine.due?'À faire':'À jour'}</span></div>`).join(''):'<p class="subtle">Statut des routines indisponible.</p>'}</section><section class="settings-section"><div class="section-head"><div><p class="eyebrow">Décisions</p><h3>${inbox?.open_count||0} élément(s) à traiter</h3></div></div>${inbox?(inbox.items||[]).slice(0,6).map(item=>`<article class="release"><div class="row"><div><strong>${esc(item.title)}</strong><small>${esc(item.detail)}</small></div>${item.amount_cents!=null?`<div class="money">${euro(item.amount_cents)}</div>`:''}</div><div class="toolbar"><button class="chip" data-dismiss="${esc(item.key)}">Ignorer</button><button class="chip active" data-done="${esc(item.key)}">Traité</button></div></article>`).join('')||'<div class="empty-state">Aucune décision en attente.</div>':'<p class="subtle">Centre de décisions indisponible.</p>'}</section><section class="settings-section"><div class="section-head"><div><p class="eyebrow">Application</p><h3>Mise à jour</h3></div><button class="section-action" id="openChangelog">Nouveautés</button></div><div class="system-grid"><div class="system-item"><span>Version installée</span><strong>${esc(update?.local_version||system?.version||VERSION)}</strong></div><div class="system-item"><span>État</span><strong>${update?.update_available?'Mise à jour disponible':'À jour'}</strong></div></div><p class="subtle">${esc(update?.message||'La vérification garantit que l’interface et le cache PWA utilisent la même version.')}</p><div class="toolbar"><button class="btn secondary" id="checkUpdate">Vérifier</button>${update?.update_available?'<button class="btn primary" id="runUpdate">Mettre à jour</button>':''}</div></section><section class="settings-section"><h3>Diagnostic</h3><div class="system-grid"><div class="system-item"><span>Commit</span><strong>${esc((system?.commit||'').slice(0,10)||'—')}</strong></div><div class="system-item"><span>Mouvements</span><strong>${system?.database?.counts?.transactions??'—'}</strong></div><div class="system-item"><span>Imports</span><strong>${system?.database?.counts?.imports??'—'}</strong></div><div class="system-item"><span>Base</span><strong>${system?.database?'Connectée':'À vérifier'}</strong></div></div></section>`;root.querySelectorAll('[data-theme]').forEach(button=>{const selected=(localStorage.getItem('flow-theme')||'system')===button.dataset.theme;button.classList.toggle('active',selected);button.addEventListener('click',()=>{localStorage.setItem('flow-theme',button.dataset.theme);applyTheme();openSystem();});});q('#runRoutines')?.addEventListener('click',runRoutines);root.querySelectorAll('[data-dismiss]').forEach(button=>button.addEventListener('click',()=>setDecision(button.dataset.dismiss,'dismissed')));root.querySelectorAll('[data-done]').forEach(button=>button.addEventListener('click',()=>setDecision(button.dataset.done,'done')));q('#openChangelog')?.addEventListener('click',openChangelog);q('#checkUpdate')?.addEventListener('click',async()=>{await api('/api/update/check',{method:'POST',body:'{}'});setTimeout(openSystem,1500);});q('#runUpdate')?.addEventListener('click',async()=>{if(!confirm('Mettre Flow à jour maintenant ?'))return;await api('/api/update',{method:'POST',body:JSON.stringify({confirmation:'METTRE A JOUR'})});setTimeout(()=>location.reload(),6000);});}
  async function openChangelog(){q('#changelogDialog').showModal();const root=q('#changelogList');root.innerHTML=skeleton();try{const data=await api('/api/v3/changelog');root.innerHTML=(data.releases||[]).map(release=>`<article class="release"><p class="eyebrow">${esc(release.date)} · ${esc(release.version)}</p><h3>${esc(release.title)}</h3><ul>${release.highlights.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></article>`).join('');}catch(error){root.innerHTML='<div class="notice">Historique indisponible.</div>';}}
  function applyTheme(){document.documentElement.dataset.theme=localStorage.getItem('flow-theme')||'system';}
  async function autoDaily(){const today=new Date().toISOString().slice(0,10),key=`flow-v4-routine-${today}`;if(localStorage.getItem(key))return;try{const status=await api('/api/v3.6/routine-status');for(const routine of status.routines||[]){if(routine.key==='month_open'&&routine.due)await api(`/api/v3.6/open-month?month=${encodeURIComponent(routine.period)}`,{method:'POST'});if(routine.key==='month_close'&&routine.due)await api(`/api/v3.6/close-month?month=${encodeURIComponent(routine.period)}`,{method:'POST'});}await api('/api/v3.6/reconcile',{method:'POST'});localStorage.setItem(key,'1');}catch(error){}}
  async function versionGuard(){try{const data=await api('/api/version');if(data.version!==VERSION){const key=`flow-v4-reload-${data.version}`;if(!sessionStorage.getItem(key)){sessionStorage.setItem(key,'1');location.reload();}}}catch(error){}}
  async function pwa(){if(!('serviceWorker' in navigator))return;try{const registration=await navigator.serviceWorker.register(`/sw.js?v=${VERSION}`,{updateViaCache:'none'});await registration.update();let reloading=false;navigator.serviceWorker.addEventListener('controllerchange',()=>{if(reloading)return;reloading=true;location.reload();});}catch(error){}}
  function connectivity(){let banner=q('#offlineBanner');if(!navigator.onLine&&!banner){banner=document.createElement('div');banner.id='offlineBanner';banner.className='offline-banner';banner.textContent='Hors ligne · dernières données affichées';document.body.appendChild(banner);}else if(navigator.onLine&&banner){banner.remove();}}
  function boot(){applyTheme();qa('[data-nav]').forEach(button=>button.addEventListener('click',()=>nav(button.dataset.nav)));qa('[data-close]').forEach(button=>button.addEventListener('click',()=>q(`#${button.dataset.close}`).close()));qa('.sheet-dialog').forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();}));q('#searchBtn').addEventListener('click',openSearch);q('#settingsBtn').addEventListener('click',openSystem);q('#globalSearch').addEventListener('input',doSearch);q('#closeEdit').addEventListener('click',()=>q('#editDialog').close());window.addEventListener('online',connectivity);window.addEventListener('offline',connectivity);connectivity();renderHome();autoDaily();versionGuard();pwa();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
