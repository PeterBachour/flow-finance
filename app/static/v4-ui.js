(()=>{
  const VERSION='6.6.2';
  const state={
    screen:'home',
    month:new Date().toISOString().slice(0,7),
    filter:'all',
    query:'',
    category:null
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

  function trajectoryChart(data){
    const band=Array.isArray(data?.uncertainty_band)?data.uncertainty_band:[];
    const realistic=data?.scenarios?.realistic||{};
    const prudent=data?.scenarios?.prudent||{};
    const available=data?.availability?.available===true;
    const values=band.flatMap(point=>[
      Number(point.optimistic_cents),
      Number(point.realistic_cents),
      Number(point.prudent_cents)
    ]).filter(Number.isFinite);
    const header='<div class="section-head"><div><p class="eyebrow">Trajectoire</p><h2>Évolution prévue du solde</h2></div></div>';
    if(!available||band.length<2||!values.length){
      return `<section class="card trajectory-card">${header}<p class="notice" role="status">La trajectoire reste indisponible tant que le solde de référence n'est pas fiable.</p></section>`;
    }
    const width=720,height=250,left=22,right=18,top=18,bottom=34;
    const minimum=Math.min(...values),maximum=Math.max(...values);
    const padding=Math.max(1,Math.round((maximum-minimum)*.08));
    const floor=minimum-padding,ceiling=maximum+padding,span=Math.max(1,ceiling-floor);
    const x=index=>left+(index*(width-left-right))/Math.max(1,band.length-1);
    const y=value=>top+((ceiling-Number(value))*(height-top-bottom))/span;
    const path=key=>band.map((point,index)=>`${index?'L':'M'}${x(index).toFixed(1)} ${y(point[key]).toFixed(1)}`).join(' ');
    const area=`${path('optimistic_cents')} ${[...band].reverse().map((point,index)=>`L${x(band.length-1-index).toFixed(1)} ${y(point.prudent_cents).toFixed(1)}`).join(' ')} Z`;
    const firstDate=band[0]?.date,lastDate=band.at(-1)?.date;
    const realisticEnd=Number(realistic.closing_balance_cents);
    const prudentEnd=Number(prudent.closing_balance_cents);
    const lowPoint=realistic.low_point||{};
    const confidence=({high:'Confiance élevée',medium:'Confiance moyenne',low:'Confiance limitée'})[data?.confidence?.level||data?.variable_spending?.confidence]||'Confiance à vérifier';
    return `<section class="card trajectory-card" aria-labelledby="trajectoryTitle">${header.replace('<h2>','<h2 id="trajectoryTitle">')}
      <div class="trajectory-summary">
        <div><span>Solde réaliste à l'horizon</span><strong>${euro(realisticEnd)}</strong><small>${dateLabel(lastDate)}</small></div>
        <div><span>Scénario prudent</span><strong>${euro(prudentEnd)}</strong><small>${dateLabel(lastDate)}</small></div>
        <div><span>Point bas réaliste</span><strong>${euro(lowPoint.balance_cents)}</strong><small>${dateLabel(lowPoint.date)}</small></div>
      </div>
      <div class="trajectory-plot">
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Solde projeté du ${dateLabel(firstDate)} au ${dateLabel(lastDate)}">
          <line class="trajectory-grid" x1="${left}" y1="${top}" x2="${left}" y2="${height-bottom}"></line>
          <line class="trajectory-grid" x1="${left}" y1="${height-bottom}" x2="${width-right}" y2="${height-bottom}"></line>
          <path class="trajectory-band" d="${area}"></path>
          <path class="trajectory-line trajectory-line-prudent" d="${path('prudent_cents')}"></path>
          <path class="trajectory-line trajectory-line-realistic" d="${path('realistic_cents')}"></path>
          <circle class="trajectory-point" cx="${x(band.length-1).toFixed(1)}" cy="${y(band.at(-1).realistic_cents).toFixed(1)}" r="4"></circle>
          <text class="trajectory-axis-label" x="${left}" y="${height-8}">${dateLabel(firstDate)}</text>
          <text class="trajectory-axis-label" x="${width-right}" y="${height-8}" text-anchor="end">${dateLabel(lastDate)}</text>
        </svg>
      </div>
      <div class="trajectory-legend" aria-label="Légende"><span><i class="realistic"></i>Réaliste</span><span><i class="prudent"></i>Prudent</span><span><i class="band"></i>Zone d'incertitude</span></div>
      <p class="subtle">${esc(confidence)}. La zone traduit l'écart entre les scénarios engagé et prudent. Les projections restent des estimations et ne modifient aucune donnée.</p>
    </section>`;
  }

  function openSimulation(){
    const dialog=q('#editDialog'),body=q('#editBody');
    const today=new Date().toISOString().slice(0,10);
    body.innerHTML=`<form id="quickSimulationForm" class="stack">
      <p class="subtle">Teste un achat sans créer de transaction réelle. Flow compare le disponible actuel et le disponible après cette dépense.</p>
      <label class="form-label">Montant en euros<input class="field" name="amount" type="number" min="0.01" step="0.01" required placeholder="Exemple : 250"></label>
      <label class="form-label">Date<input class="field" name="date" type="date" required value="${today}"></label>
      <label class="form-label">Libellé<input class="field" name="label" maxlength="180" value="Dépense simulée"></label>
      <button class="btn primary">Calculer l'impact</button>
      <div id="quickSimulationResult"></div>
    </form>`;
    dialog.showModal();
    q('#quickSimulationForm').addEventListener('submit',async event=>{
      event.preventDefault();
      const form=event.currentTarget.elements,result=q('#quickSimulationResult');
      result.innerHTML=skeleton();
      try{
        const data=await api('/api/simulations',{method:'POST',body:JSON.stringify({
          label:form.label.value||'Dépense simulée',
          amount_cents:-Math.round(Math.abs(Number(form.amount.value))*100),
          due_date:form.date.value
        })});
        const base=data.baseline||{},sim=data.simulated||{},delta=Number(data.impact?.safe_to_spend_delta_cents||0);
        result.innerHTML=`<div class="simulation-result-v7"><div><span>Disponible actuel</span><strong>${euro(base.safe_to_spend_cents)}</strong></div><div><span>Après achat</span><strong class="${Number(sim.safe_to_spend_cents)>=0?'positive':'danger'}">${euro(sim.safe_to_spend_cents)}</strong></div><div><span>Impact</span><strong class="danger">${euro(delta)}</strong></div></div>`;
      }catch(error){result.innerHTML=`<div class="notice">Simulation indisponible : ${esc(error.message)}</div>`;}
    });
  }

  async function renderHome(){
    const root=q('[data-screen="home"]');root.innerHTML=page('Aujourd’hui',todayLabel(),'Ce que tu peux réellement dépenser, et pourquoi.')+skeleton();
    try{
      const [dashboard,safeToSpend,trajectory,recurring,accuracy]=await Promise.all([
        api('/api/dashboard'),
        api('/api/v6/safe-to-spend'),
        api('/api/v6/trajectory'),
        api('/api/recurring'),
        api('/api/v6/forecast-accuracy').catch(()=>null)
      ]);
      const components=safeToSpend?.components||{},safe=safeToSpend?.safe_to_spend||{},realistic=trajectory?.scenarios?.realistic||{};
      const events=(realistic.timeline||[]).flatMap(day=>(day.events||[]).map(event=>({...event,date:event.date||day.date})));
      const upcoming=events.filter(event=>Number(event.amount_cents)<0).sort((a,b)=>String(a.date||'').localeCompare(String(b.date||''))).slice(0,4);
      const activeRecurring=(recurring||[]).filter(item=>Number(item.is_active)!==0&&Number(item.amount_cents)<0);
      const recurringMonthly=activeRecurring.reduce((sum,item)=>sum+monthlyEquivalent(item),0);
      const opening=Number(components.current_balance_cents??dashboard.accounts?.[0]?.current_balance_cents??0);
      const planned=Math.abs(Number(components.confirmed_commitments_cents||0));
      const recurringReserve=Math.abs(Number(components.probable_recurring_cents||0));
      const goals=Math.abs(Number(components.goal_reservations_cents||0));
      const reserve=Math.abs(Number(components.safety_reserve_cents||0));
      const hasAvailable=safeToSpend?.availability?.available===true&&Number.isFinite(safe.total_cents)&&Number.isFinite(safe.calculated_cents);
      const available=hasAvailable?safe.total_cents:null;
      const calculated=hasAvailable?safe.calculated_cents:null;
      const unavailableReason=({unavailable_stale_balance:'Le solde de référence est trop ancien.',unavailable_no_balance_date:'Aucun solde de référence fiable.',unavailable_no_account:'Aucun compte inclus dans le calcul.'})[safeToSpend?.availability?.status]||'Le solde de référence ne permet pas de calculer un montant fiable.';
      const nextIncome=dashboard?.forecast?.next_income;
      root.innerHTML=page('Aujourd’hui',todayLabel(),'Ce que tu peux réellement dépenser, et pourquoi.')+`
        <section class="card hero decision-hero-v7">
          <p class="hero-label">Disponible à dépenser</p>
          <div class="hero-amount">${hasAvailable?euro(available):'Indisponible'}</div>
          <p class="hero-copy">${hasAvailable?'Après les échéances prévues, les dépenses régulières, les objectifs et le coussin de sécurité.':esc(unavailableReason)}</p>
          ${hasAvailable?'<button class="btn hero-simulate" id="simulatePurchase">Simuler une dépense</button>':''}
          <div class="hero-facts">
            <div class="hero-fact"><span>Solde réel</span><strong>${euro(opening)}</strong><small>${dateLabel(dashboard.accounts?.[0]?.balance_as_of||safeToSpend?.as_of)}</small></div>
            <div class="hero-fact"><span>Réguliers / mois</span><strong>${euro(recurringMonthly)}</strong><small>${activeRecurring.length} actif(s)</small></div>
            <div class="hero-fact"><span>Prochain revenu</span><strong>${nextIncome?euro(nextIncome.amount_cents):'—'}</strong><small>${nextIncome?dateLabel(nextIncome.date):'Non identifié'}</small></div>
          </div>
        </section>
        <section class="card explain-card">
          <div class="section-head"><div><p class="eyebrow">Comprendre le calcul</p><h2>D'où vient ce montant</h2></div></div>
          ${hasAvailable?`<div class="formula">
            <div class="formula-row"><span>Solde réel</span><strong>${euro(opening)}</strong></div>
            <div class="formula-row"><span>- Échéances prévues</span><strong>${euro(-planned)}</strong></div>
            <div class="formula-row"><span>- Dépenses régulières réservées</span><strong>${euro(-recurringReserve)}</strong></div>
            <div class="formula-row"><span>- Objectifs réservés</span><strong>${euro(-goals)}</strong></div>
            <div class="formula-row"><span>- Coussin de sécurité</span><strong>${euro(-reserve)}</strong></div>
            <div class="formula-row formula-result"><span>= Résultat après réserves</span><strong>${euro(calculated)}</strong></div>
          </div><p class="subtle">Le disponible est limité à zéro si le résultat après réserves est négatif.</p>${calculated<0?`<p class="notice">Il manque ${euro(-calculated)} pour couvrir les réserves prévues.</p>`:''}`:`<p class="notice" role="status">${esc(unavailableReason)} Actualise le solde ou importe un relevé récent avant de simuler une dépense.</p>`}
        </section>
        ${trajectoryChart(trajectory)}
        <section class="card">
          <div class="section-head"><div><p class="eyebrow">À venir</p><h2>Prochaines sorties</h2></div><button class="section-action" data-go="recurring">Voir les réguliers</button></div>
          <div class="stack">${upcoming.map(event=>`<div class="decision-row compact-decision"><div><strong>${esc(event.label||'Échéance')}</strong><small>${dateLabel(event.date)} · ${esc(event.source||event.certainty||'Prévision')}</small></div><div class="money negative">${euro(event.amount_cents)}</div></div>`).join('')||'<div class="empty-state">Aucune sortie identifiée sur l’horizon actuel.</div>'}</div>
        </section>
        ${forecastAccuracyCard(accuracy)}
        <section class="home-actions-v7">
          <button class="card action-card-v7" data-go="month"><span>Ce mois-ci</span><strong>Comprendre mes dépenses</strong><small>Budget, fin de mois et catégories</small></button>
          <button class="card action-card-v7" data-go="movements"><span>Mouvements</span><strong>Voir mes transactions</strong><small>Rechercher et corriger</small></button>
          <button class="card action-card-v7" data-go="wealth"><span>Patrimoine</span><strong>Suivre mes objectifs</strong><small>Épargne, actifs et dettes</small></button>
        </section>`;
      bindNavigation(root);
      q('#simulatePurchase')?.addEventListener('click',openSimulation);
    }catch(error){renderError(root,'Accueil',error,'home');}
  }

  function monthlyRecurringCard(data){
    const header='<div class="section-head"><div><p class="eyebrow">Dépenses régulières</p><h2>Échéances du mois</h2></div><button class="btn secondary" data-go="recurring">Gérer</button></div>';
    if(!data)return `<section class="card">${header}<p class="notice" role="status">Suivi indisponible. Les paiements et le restant ne peuvent pas être vérifiés.</p><button class="btn secondary" id="retryRecurringStatus">Réessayer</button></section>`;
    const summary=data.summary||{},items=data.items||[];
    if(!items.length)return `<section class="card">${header}<p class="empty-state">Aucune échéance régulière prévue pour ce mois.</p></section>`;
    const labels={paid:'Paiement détecté',upcoming:'À venir',overdue:'À vérifier'};
    const rows=items.map(item=>`<article class="monthly-recurring-row"><div class="monthly-recurring-main"><strong>${esc(item.label)}</strong><small>Échéance : ${dateLabel(item.due_date)}${item.matched_booking_date?' · Mouvement : '+dateLabel(item.matched_booking_date):''}</small></div><div class="monthly-recurring-amount"><strong>${euro(Math.abs(Number(item.amount_cents)||0))}</strong><span class="monthly-recurring-status" data-status="${esc(item.status)}">${labels[item.status]||'À vérifier'}</span></div></article>`).join('');
    return `<section class="card">${header}
      <div class="monthly-recurring-totals">
        <div><span>Prévu ce mois</span><strong>${euro(summary.expected_cents)}</strong></div>
        <div><span>Rapproché</span><strong>${euro(summary.paid_cents)}</strong></div>
        <div><span>Restant attendu</span><strong>${euro(summary.remaining_cents)}</strong></div>
      </div>
      ${Number(summary.overdue_cents)>0?`<p class="notice">${euro(summary.overdue_cents)} d'échéances passées sans paiement détecté, inclus dans le restant attendu.</p>`:''}
      <p class="subtle">Montants prévus des échéances du mois, distincts de l'équivalent mensuel. Le rapprochement est automatique et estimatif. Une échéance passée sans mouvement détecté reste à vérifier, notamment si les imports sont incomplets.</p>
      <div class="monthly-recurring-list">${rows}</div>
    </section>`;
  }

  function monthToolbar(month){
    return `<section class="card month-toolbar"><button class="icon-btn" id="prevMonth" aria-label="Mois précédent">‹</button><div class="month-title"><strong>${monthLabel(month)}</strong><input class="field" id="monthPicker" type="month" value="${month}" aria-label="Mois à consulter"></div><button class="icon-btn" id="nextMonth" aria-label="Mois suivant">›</button></section>`;
  }
  function bindMonthToolbar(){
    q('#prevMonth').addEventListener('click',()=>shiftMonth(-1));
    q('#nextMonth').addEventListener('click',()=>shiftMonth(1));
    q('#monthPicker').addEventListener('change',event=>{
      const month=event.target.value;
      if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(month))return;
      state.month=month;
      return renderMonth();
    });
  }

  function monthlyCategoryBreakdown(lines){
    const categories=(lines||[]).filter(item=>Number.isFinite(Number(item.spent_cents))&&Number(item.spent_cents)>0)
      .map(item=>({...item,spent_cents:Number(item.spent_cents)})).sort((a,b)=>b.spent_cents-a.spent_cents);
    const total=categories.reduce((sum,item)=>sum+item.spent_cents,0);
    if(!total)return '<div class="empty-state">Aucune dépense dans les catégories du budget pour ce mois.</div>';
    const visible=categories.slice(0,6),others=categories.slice(6);
    if(others.length)visible.push({category:`Autres catégories (${others.length})`,spent_cents:others.reduce((sum,item)=>sum+item.spent_cents,0),aggregate:true});
    return `<p class="subtle">${euro(total)} dépensés dans les catégories du budget. Les parts ci-dessous portent sur ce total ; les dépenses hors budget ne sont pas incluses.</p><div class="budget-list">${visible.map(item=>{
      const share=item.spent_cents/total*100,percent=new Intl.NumberFormat('fr-FR',{maximumFractionDigits:1}).format(share);
      const planned=Number(item.planned_cents),remaining=Number(item.recommended_remaining_cents);
      const budget=!item.aggregate&&item.planned_cents!=null&&Number.isFinite(planned)?`<small>Budget prévu : ${euro(planned)}${planned>0&&item.spent_cents>planned?' · Dépassé de '+euro(item.spent_cents-planned):''}</small>`:'';
      const allowance=!item.aggregate&&item.recommended_remaining_cents!=null&&Number.isFinite(remaining)?`<small>Reste recommandé : ${euro(remaining)}</small>`:'';
      const category=item.aggregate?'':` data-category="${esc(item.category)}" role="button" tabindex="0" aria-label="Voir les mouvements de ${esc(item.category)}"`;
      return `<article class="budget-item budget-category-link"${category}><div class="budget-item-head"><div><strong>${esc(item.category)}</strong><small>${percent} % des dépenses des catégories du budget</small>${budget}${allowance}</div><div class="money">${euro(item.spent_cents)}<small>dépensés</small></div></div><div class="budget-track" role="img" aria-label="Part des dépenses : ${percent} %"><i style="width:${share}%"></i></div></article>`;
    }).join('')}</div>`;
  }

  function monthlySpendingTrend(data,month){
    const rows=[
      {label:monthLabel(month),amount:data?.current?.spent_cents==null?NaN:Number(data.current.spent_cents),kind:'current'},
      {label:'Mois précédent',amount:data?.previous?.spent_cents==null?NaN:Number(data.previous.spent_cents),kind:'previous'},
      {label:'Moyenne 3 mois',amount:data?.average_3m?.spent_cents==null?NaN:Number(data.average_3m.spent_cents),kind:'average'},
      {label:'Moyenne 6 mois',amount:data?.average_6m?.spent_cents==null?NaN:Number(data.average_6m.spent_cents),kind:'average'}
    ].filter(item=>Number.isFinite(item.amount)&&item.amount>=0);
    const maximum=Math.max(1,...rows.map(item=>item.amount));
    const current=rows.find(item=>item.kind==='current')?.amount;
    const previous=rows.find(item=>item.kind==='previous')?.amount;
    const delta=Number.isFinite(current)&&Number.isFinite(previous)?current-previous:null;
    const selectedIsCurrent=month===new Date().toISOString().slice(0,7);
    if(!rows.length)return '<section class="card"><div class="section-head"><div><p class="eyebrow">Évolution</p><h2>Dépenses comparées</h2></div></div><div class="empty-state">Aucune donnée comparable disponible.</div></section>';
    return `<section class="card spending-trend" aria-labelledby="spendingTrendTitle">
      <div class="section-head"><div><p class="eyebrow">Évolution</p><h2 id="spendingTrendTitle">Dépenses comparées</h2></div>${delta==null?'':`<span class="trend-delta ${delta<=0?'positive':'danger'}">${delta>0?'+':''}${euro(delta)} vs précédent</span>`}</div>
      <div class="spending-bars">${rows.map(item=>{
        const width=item.amount/maximum*100;
        return `<div class="spending-bar-row"><div class="spending-bar-head"><span>${esc(item.label)}</span><strong>${euro(item.amount)}</strong></div><div class="spending-bar-track" role="img" aria-label="${esc(item.label)} : ${euro(item.amount)}"><i class="${item.kind}" style="width:${width.toFixed(1)}%"></i></div></div>`;
      }).join('')}</div>
      <p class="subtle">${selectedIsCurrent?'Le mois en cours est partiel : son montant correspond uniquement aux mouvements importés à ce jour.':'Comparaison fondée sur les mouvements importés pour chaque période.'} Les transferts internes sont exclus.</p>
    </section>`;
  }

  let monthRequest=0;
  async function renderMonth(){
    const request=++monthRequest,month=state.month;
    const root=q('[data-screen="month"]');root.innerHTML=page('Ce mois-ci','Mois','Revenus, dépenses, réguliers et ce qui devrait rester.')+monthToolbar(month)+skeleton();
    bindMonthToolbar();
    try{
      const [monthData,adaptive,closeout,dashboard,recurring,recurringStatus]=await Promise.all([
        api(`/api/v2.1/months/${month}`),
        api(`/api/v3.5/adaptive-budget?month=${month}`),
        api(`/api/v3.5/closeout?month=${month}`),
        api('/api/dashboard'),
        api('/api/recurring'),
        api(`/api/recurring/status?month=${month}`).catch(()=>null)
      ]);
      if(request!==monthRequest||month!==state.month)return;
      const current=monthData.current||{},lines=adaptive.lines||[];
      const closing=monthData.closing_explanation||{};
      const hasClosing=closing.status==='available'&&Number.isFinite(closing.closing_balance_cents);
      const monthClose=hasClosing?closing.closing_balance_cents:null;
      const income=Number(current.income_cents||0),spent=Number(current.spent_cents||0);
      const activeRecurring=(recurring||[]).filter(item=>Number(item.is_active)!==0&&Number(item.amount_cents)<0);
      const recurringMonthly=activeRecurring.reduce((sum,item)=>sum+monthlyEquivalent(item),0);
      root.innerHTML=page('Ce mois-ci','Mois','Revenus, dépenses, réguliers et ce qui devrait rester.')+`
        ${monthToolbar(month)}
        <section class="card month-balance month-balance-v7"><div><p class="eyebrow">Ce qui devrait rester</p><strong class="${monthClose>=0?'positive':'danger'}">${hasClosing?euro(monthClose):'Indisponible'}</strong><small class="subtle">Solde estimé à la fin du mois</small></div></section>
        <section class="month-flow-v7">
          <article class="card metric"><span>Revenus</span><strong>${euro(income)}</strong><small>sur le mois</small></article>
          <article class="card metric"><span>Dépenses</span><strong>${euro(spent)}</strong><small>hors transferts internes</small></article>
          <article class="card metric"><span>Réguliers</span><strong>${euro(recurringMonthly)}</strong><small>équivalent mensuel</small></article>
          <article class="card metric metric-accent"><span>Reste pilotable</span><strong>${euro(adaptive.adaptive_pool_cents)}</strong><small>${adaptive.days_left||0} jour(s)</small></article>
        </section>
        ${monthlySpendingTrend(monthData,month)}
        <section class="card explain-card">
          <div class="section-head"><div><p class="eyebrow">Calcul du restant</p><h2>Comment arrive-t-on à la fin de mois</h2></div></div>
          ${hasClosing?`<div class="formula">
            <div class="formula-row"><span>Solde de référence au ${dateLabel(closing.as_of)}</span><strong>${euro(closing.opening_balance_cents)}</strong></div>
            <div class="formula-row"><span>+ Revenus attendus jusqu'au ${dateLabel(closing.target_date)}</span><strong>${euro(closing.expected_income_cents)}</strong></div>
            <div class="formula-row"><span>- Échéances restantes</span><strong>${euro(-closing.expected_outflows_cents)}</strong></div>
            <div class="formula-row"><span>- Dépenses variables estimées</span><strong>${euro(-closing.variable_spending_cents)}</strong></div>
            <div class="formula-row formula-result"><span>= Solde estimé fin de mois</span><strong>${euro(monthClose)}</strong></div>
          </div><p class="subtle">Projection réaliste depuis le solde de référence. Les mouvements déjà constatés ne sont pas déduits une seconde fois. Les transferts prévus affectent la trésorerie ; le coussin de sécurité n'est pas une dépense.</p><p class="subtle">Dépenses variables : ${euro(closing.assumptions?.realistic_daily_cents)} / jour, estimées sur l'historique. Cette estimation ne garantit pas le solde final. Confiance : ${esc(({confirmed:'confirmée',probable:'probable',estimated:'estimée',uncertain:'incertaine'})[closing.confidence?.level]||'à vérifier')}.</p>`:`<p class="notice">${closing.reason==='selected_month_not_current'?'La projection de fin de mois est disponible uniquement pour le mois en cours. Les revenus et dépenses ci-dessous concernent le mois sélectionné.':'Le solde de référence est absent, obsolète ou insuffisant pour calculer la fin de mois.'}</p>`}
        </section>
        ${monthlyRecurringCard(recurringStatus)}
        <section class="card">
          <div class="section-head"><div><p class="eyebrow">Où part l'argent</p><h2>Principales catégories</h2></div></div>
          ${monthlyCategoryBreakdown(lines)}
        </section>
        <section class="card month-status-v7"><p class="eyebrow">Écart au budget</p><strong class="${Number(closeout.variance_cents)<0?'danger':'positive'}">${euro(closeout.variance_cents)}</strong><p class="subtle">Taux d'épargne : ${closeout.savings_rate_pct??'—'} %</p></section>`;
      q('#retryRecurringStatus')?.addEventListener('click',renderMonth);
      bindMonthToolbar();
      root.querySelectorAll('[data-category]').forEach(card=>{const open=()=>{state.category=card.dataset.category;state.query='';state.filter='all';nav('movements');};card.addEventListener('click',open);card.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open();}});});
      bindNavigation(root);
    }catch(error){if(request===monthRequest&&month===state.month)renderError(root,'Mois',error,'month');}
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

  function movementSelectionSummary(rows){
    const items=rows||[];
    const expenses=items.filter(item=>Number(item.amount_cents)<0&&!item.is_internal_transfer&&!item.exclude_from_analytics);
    const incomes=items.filter(item=>Number(item.amount_cents)>0&&!item.is_internal_transfer&&!item.exclude_from_analytics);
    const expenseTotal=expenses.reduce((sum,item)=>sum+Math.abs(Number(item.amount_cents)||0),0);
    const incomeTotal=incomes.reduce((sum,item)=>sum+Number(item.amount_cents||0),0);
    const net=incomeTotal-expenseTotal;
    return `<div class="movement-totals"><div><span>Dépenses de la sélection</span><strong class="negative">-${euro(expenseTotal)}</strong></div><div><span>Revenus de la sélection</span><strong class="positive">+${euro(incomeTotal)}</strong></div><div><span>Solde net de la sélection</span><strong class="${net>=0?'positive':'negative'}">${net>=0?'+':''}${euro(net)}</strong></div></div>`;
  }

  let movementRequest=0;
  async function renderMovements(){
    const request=++movementRequest,month=state.month,query=state.query,filter=state.filter,category=state.category;
    const isCurrent=()=>request===movementRequest&&month===state.month&&query===state.query&&filter===state.filter&&category===state.category;
    const root=q('[data-screen="movements"]');root.innerHTML=page('Historique','Mouvements','Toutes tes opérations, sans bruit technique.')+skeleton();
    try{
      const params=new URLSearchParams({month,limit:'250'});
      if(query)params.set('q',query);
      if(category)params.set('category',category);
      if(filter==='uncategorized')params.set('quality','uncategorized');
      const [rows,summary]=await Promise.all([
        api(`/api/v3.1/movements?${params}`),
        api(`/api/v3.1/movement-summary?month=${month}`)
      ]);
      if(!isCurrent())return;
      let visible=rows||[];
      if(filter==='expense')visible=visible.filter(item=>Number(item.amount_cents)<0&&!item.is_internal_transfer);
      if(filter==='income')visible=visible.filter(item=>Number(item.amount_cents)>0&&!item.is_internal_transfer);
      const groups=[];
      visible.forEach(item=>{
        const day=String(item.booking_date||'');
        let group=groups.find(entry=>entry.date===day);
        if(!group){group={date:day,items:[]};groups.push(group);}
        group.items.push(item);
      });
      const listMarkup=groups.map(group=>`<section class="movement-day">
        <div class="movement-day-head"><strong>${dateLabel(group.date)}</strong><span>${group.items.length} opération(s)</span></div>
        <div class="movement-bank-list">${group.items.map(item=>{
          const positive=Number(item.amount_cents)>0;
          const transfer=Boolean(item.is_internal_transfer);
          const label=item.user_label||item.label;
          return `<button class="movement-bank-row" data-edit="${item.id}">
            <div class="movement-bank-copy">
              <strong>${esc(label)}</strong>
              <small>${esc(item.category||'Non catégorisé')}${transfer?' · Transfert interne':''}</small>
            </div>
            <div class="money ${positive?'positive':'negative'}">${positive?'+':''}${euro(item.amount_cents)}</div>
          </button>`;
        }).join('')}</div>
      </section>`).join('');
      root.innerHTML=page('Historique','Mouvements','Toutes tes opérations, sans bruit technique.')+`
        <section class="card movement-overview movement-overview-v7">
          <div class="section-head"><div><p class="eyebrow">${monthLabel(month)}</p><h2>Résumé du mois</h2></div><span class="confidence-pill">${rows.length} opération(s)</span></div>
          ${movementSelectionSummary(visible)}
          <div class="movement-selection-note">${query||filter!=='all'?`Montants calculés sur les mouvements affichés. `:''}Les transferts internes et mouvements exclus des analyses ne sont pas inclus. <strong>${summary.uncategorized||0}</strong> mouvement(s) restent à classer sur le mois.${rows.length>=250?'<br>Affichage limité aux 250 mouvements les plus récents de cette sélection.':''}</div>
        </section>
        <section class="card movement-controls-v7">
          <div class="month-picker-controls"><button class="icon-btn" id="movementPrevMonth" aria-label="Mois précédent">‹</button><input id="movementMonth" type="month" value="${month}" aria-label="Mois des mouvements"><button class="icon-btn" id="movementNextMonth" aria-label="Mois suivant">›</button></div>
          <label class="search-field search-field-large"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"></circle><path d="m16 16 4 4"></path></svg><input id="movementSearch" autocomplete="off" placeholder="Rechercher" value="${esc(query)}"></label>
          ${category?`<div class="notice movement-category-filter">Catégorie : <strong>${esc(category)}</strong><button class="chip" id="clearMovementCategory" type="button">Effacer</button></div>`:''}
          <div class="chips movement-filter-v7">${[['all','Tous'],['expense','Dépenses'],['income','Revenus'],['uncategorized','À classer']].map(([key,label])=>`<button class="chip ${filter===key?'active':''}" data-filter="${key}">${label}</button>`).join('')}</div>
        </section>
        <section class="card movement-operations-v7">
          <div class="section-head"><div><p class="eyebrow">Opérations</p><h2>${visible.length} mouvement(s)</h2></div></div>
          ${listMarkup||'<div class="empty-state">Aucun mouvement pour cette sélection.</div>'}
        </section>`;
      q('#movementSearch').addEventListener('input',event=>{state.query=event.target.value;clearTimeout(window.__flowSearch);window.__flowSearch=setTimeout(renderMovements,260);});
      q('#movementMonth').addEventListener('change',event=>{if(event.target.value){state.month=event.target.value;renderMovements();}});
      q('#movementPrevMonth').addEventListener('click',()=>shiftMovementMonth(-1));
      q('#movementNextMonth').addEventListener('click',()=>shiftMovementMonth(1));
      q('#clearMovementCategory')?.addEventListener('click',()=>{state.category=null;renderMovements();});
      root.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{state.filter=button.dataset.filter;renderMovements();}));
      root.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',()=>openMovement(Number(button.dataset.edit))));
    }catch(error){if(isCurrent())renderError(root,'Mouvements',error,'movements');}
  }

  function shiftMovementMonth(delta){const d=new Date(`${state.month}-15T12:00:00`);d.setMonth(d.getMonth()+delta);state.month=d.toISOString().slice(0,7);renderMovements();}

  async function openMovement(id){
    const dialog=q('#editDialog'),body=q('#editBody');dialog.showModal();body.innerHTML=skeleton();
    try{
      const [rows,categories,accounts]=await Promise.all([api('/api/v3.1/movements?limit=500'),api('/api/categories'),api('/api/accounts')]);
      const movement=rows.find(item=>item.id===id);
      if(!movement)throw new Error('Mouvement introuvable');
      body.innerHTML=`<form id="editForm" class="stack">
        <p class="eyebrow">${dateLabel(movement.booking_date)} · ${esc(movement.account_name||'Compte')}</p>
        <div class="movement-edit-amount ${Number(movement.amount_cents)>=0?'positive':'negative'}">${Number(movement.amount_cents)>=0?'+':''}${euro(movement.amount_cents)}</div>
        <label class="form-label">Nom affiché<input class="field" name="user_label" value="${esc(movement.user_label||'')}" placeholder="${esc(movement.label)}"></label>
        <label class="form-label">Catégorie<select class="field" name="category"><option value="">Non catégorisé</option>${categories.map(category=>`<option value="${esc(category.name)}" ${category.name===movement.category?'selected':''}>${esc(category.name)}</option>`).join('')}</select></label>
        <label class="form-label">Type<select class="field" name="transaction_type">
          ${[['expense','Dépense'],['income','Revenu'],['refund','Remboursement'],['transfer','Transfert']].map(([value,label])=>`<option value="${value}" ${movement.transaction_type===value?'selected':''}>${label}</option>`).join('')}
        </select></label>
        <label class="toggle-row"><span><strong>Transfert interne</strong><small>Ne compte pas comme dépense ou revenu</small></span><input type="checkbox" name="is_internal_transfer" ${movement.is_internal_transfer?'checked':''}></label>
        <label class="toggle-row"><span><strong>Dépense exceptionnelle</strong><small>Ne doit pas influencer mes habitudes</small></span><input type="checkbox" name="is_exceptional" ${movement.is_exceptional?'checked':''}></label>
        <label class="toggle-row"><span><strong>Exclure des analyses</strong><small>Garder l'opération visible mais hors statistiques</small></span><input type="checkbox" name="exclude_from_analytics" ${movement.exclude_from_analytics?'checked':''}></label>
        <button class="btn primary">Enregistrer</button>
        ${Number(movement.amount_cents)<0?`<button type="button" class="btn secondary" id="makeRecurring">Créer un régulier depuis ce mouvement</button>`:''}
      </form>`;
      q('#editForm').addEventListener('submit',async event=>{
        event.preventDefault();
        const form=event.currentTarget.elements;
        await api(`/api/v3.1/movements/${id}`,{method:'PATCH',body:JSON.stringify({
          user_label:form.user_label.value||null,
          category:form.category.value||null,
          transaction_type:form.transaction_type.value,
          is_internal_transfer:form.is_internal_transfer.checked,
          is_exceptional:form.is_exceptional.checked,
          exclude_from_analytics:form.exclude_from_analytics.checked
        })});
        dialog.close();renderMovements();
      });
      q('#makeRecurring')?.addEventListener('click',()=>{
        dialog.close();
        const parsedDay=Math.max(1,Math.min(31,Number(String(movement.booking_date).slice(8,10))||1));
        openRecurringEditor({
          account_id:movement.account_id,
          label:movement.user_label||movement.label,
          amount_cents:movement.amount_cents,
          day_of_month:parsedDay,
          category:movement.category,
          frequency:'monthly'
        },accounts,categories);
      });
    }catch(error){body.innerHTML=`<div class="notice">Modification indisponible : ${esc(error.message)}</div>`;}
  }


  function wealthGoalCard(goal){
    const progress=Math.min(100,Math.max(0,Number(goal.progress_pct)||0));
    const deadline=goal.target_date?new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short',year:'numeric'}).format(new Date(`${goal.target_date}T12:00:00`)):'Sans date';
    return `<article class="goal-card"><div class="goal-head"><div><strong>${esc(goal.name)}</strong><small>${statusLabel(goal.status)} · échéance : ${deadline}</small></div><span class="goal-pct">${Math.round(progress)} % financé</span></div>
      <div class="progress" role="progressbar" aria-label="${esc(goal.name)} : financement actuel" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}"><i style="width:${progress}%"></i></div>
      <div class="goal-meta"><span>Déjà financé : ${euro(goal.effective_current_cents)}</span><span>Cible : ${euro(goal.target_cents)}</span></div>
      <div class="goal-meta"><span>Reste à financer : ${euro(goal.remaining_cents)}</span><span>Versement prévu : ${euro(goal.monthly_contribution_cents)} / mois</span></div>
      <p class="subtle">${goal.status==='achieved'?'Objectif déjà financé.':goal.required_monthly_cents==null?'Aucun rythme requis calculé sans échéance.':goal.months_remaining===0?'Échéance dépassée : le reste à financer ne constitue pas un nouveau prélèvement.':`Rythme nécessaire : ${euro(goal.required_monthly_cents)} / mois sur ${goal.months_remaining} mois.`}</p>
      ${goal.target_date?`<details><summary>Projection à l'échéance</summary><p class="subtle">${euro(goal.projected_at_target_cents)} prévus à l'échéance, avec ${euro(goal.monthly_contribution_cents)} versés chaque mois. Manque estimé : ${euro(goal.projected_gap_cents)}. Ces versements sont une hypothèse, pas de l'argent déjà financé.</p></details>`:''}
    </article>`;
  }

  async function renderWealth(){
    const root=q('[data-screen="wealth"]');
    root.innerHTML=page('Construction','Patrimoine','Voir ce qui est disponible, investi et encore dû.')+skeleton();
    try{
      const [wealth,goals,strategy]=await Promise.all([
        api('/api/v2.2/wealth'),
        api('/api/v3.3/goals-forecast?months=12').catch(()=>null),
        api('/api/v3.8/strategy?months=3').catch(()=>null)
      ]);
      const liquid=Math.max(0,Number(wealth.cash_cents)||0),savings=Math.max(0,Number(wealth.savings_cents)||0),investments=Math.max(0,Number(wealth.investments_cents)||0),allocationTotal=Math.max(1,liquid+savings+investments);
      const unavailable=label=>`<p class="notice" role="status">${label} indisponible. Les avoirs restent affichés.</p><button class="btn secondary" data-retry-wealth>Réessayer</button>`;
      root.innerHTML=page('Construction','Patrimoine','Voir ce qui est disponible, investi et encore dû.')+`
        <section class="card hero">
          <div class="hero-top"><span class="status-pill">Vue consolidée</span><span class="confidence-pill">au ${dateLabel(wealth.as_of)}</span></div>
          <p class="hero-label">Patrimoine net</p><div class="hero-amount">${euro(wealth.net_worth_cents)}</div>
          <p class="hero-copy">Valeur des actifs moins les dettes enregistrées.</p>
          <div class="wealth-breakdown"><div><span>Actifs</span><strong>${euro(wealth.total_assets_cents)}</strong></div><div><span>Dettes</span><strong>${euro(wealth.total_debt_cents)}</strong></div><div><span>Protégé</span><strong>${strategy?euro(strategy.protected_cents):'Indisponible'}</strong></div></div>
        </section>
        <section class="card explain-card">
          <div class="section-head"><div><p class="eyebrow">Lecture simple</p><h2>Comment lire ce patrimoine</h2></div></div>
          <p class="subtle">Le patrimoine net est calculé ainsi : actifs moins dettes. Les liquidités sont les soldes des comptes ; l'épargne et les investissements ne sont pas automatiquement dépensables.</p>
          <div class="formula"><div class="formula-row"><span>Actifs</span><strong>${euro(wealth.total_assets_cents)}</strong></div><div class="formula-row"><span>- Dettes</span><strong>${euro(wealth.total_debt_cents)}</strong></div><div class="formula-row formula-result"><span>= Patrimoine net</span><strong>${euro(wealth.net_worth_cents)}</strong></div></div>
          <p class="subtle">Le montant protégé est fourni par l'analyse de stratégie. Il est indisponible si cette analyse ne peut pas être chargée.</p>
        </section>
        <section class="card">
          <div class="section-head"><div><p class="eyebrow">Répartition financière</p><h2>Où se trouve ton argent</h2></div></div>
          <div class="allocation-bar" aria-label="Répartition des avoirs"><i style="width:${liquid/allocationTotal*100}%"></i><i style="width:${savings/allocationTotal*100}%"></i><i style="width:${investments/allocationTotal*100}%"></i></div>
          <div class="allocation-legend"><span>Liquidités<b>${euro(liquid)}</b></span><span>Épargne<b>${euro(savings)}</b></span><span>Investissements<b>${euro(investments)}</b></span></div>
        </section>
        <section class="card">
          <div class="section-head"><div><p class="eyebrow">Stratégie</p><h2>Ordre d'allocation</h2></div></div>
          ${strategy?`<p class="subtle">${esc(strategy.headline)} · surplus stratégique ${euro(strategy.strategic_surplus_cents)}</p>${(strategy.buckets||[]).map((bucket,index)=>`<div class="decision-row"><span class="decision-icon">${index+1}</span><div><strong>${esc(bucket.label)}</strong><small>${esc(bucket.reason)}</small></div><div class="money">${euro(bucket.amount_cents)}</div></div>`).join('')||'<div class="empty-state">Aucune allocation recommandée.</div>'}<p class="subtle">${esc(strategy.method)}</p>`:unavailable('Analyse de stratégie')}
        </section>
        <section class="card">
          <div class="section-head"><div><p class="eyebrow">Objectifs</p><h2>Financement des objectifs</h2><p class="subtle">La progression montre le financement actuel. Les projections reposent sur les versements mensuels configurés.</p></div></div>
          ${goals?(goals.goals||[]).map(wealthGoalCard).join('')||'<div class="empty-state">Aucun objectif patrimonial défini.</div>':unavailable('Suivi des objectifs')}
        </section>`;
      root.querySelectorAll('[data-retry-wealth]').forEach(button=>button.addEventListener('click',renderWealth));
    }catch(error){renderError(root,'Patrimoine',error,'wealth');}
  }


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
    const root=q('[data-screen="recurring"]');
    root.innerHTML=page('Pilotage','Dépenses régulières','Tout ce qui revient et réduit ton disponible.')+skeleton();
    try{
      const data=await Promise.all([api('/api/recurring?include_inactive=true'),api('/api/accounts'),api('/api/categories')]);
      const recurring=data[0]||[],accounts=data[1]||[],categories=data[2]||[];
      const active=recurring.filter(item=>Number(item.is_active)!==0&&Number(item.amount_cents)<0);
      const inactive=recurring.filter(item=>Number(item.is_active)===0&&Number(item.amount_cents)<0);
      const monthly=active.reduce((sum,item)=>sum+monthlyEquivalent(item),0);
      const activeRows=active.map(item=>
        '<article class="recurring-manage-row">'+
          '<div class="recurring-main"><strong>'+esc(item.label)+'</strong><small>'+esc(item.category||'Non catégorisé')+' · '+frequencyLabel(item.frequency)+'</small></div>'+
          '<div class="recurring-date"><span>Prochaine date</span><strong>'+(item.next_occurrence?dateLabel(item.next_occurrence):'le '+(item.day_of_month||'—'))+'</strong></div>'+
          '<div class="money negative">'+euro(item.amount_cents)+'</div>'+
          '<div class="recurring-actions"><button class="btn secondary recurring-edit" data-id="'+item.id+'">Modifier</button><button class="btn secondary recurring-toggle" data-id="'+item.id+'" data-active="1">Mettre en pause</button></div>'+
        '</article>'
      ).join('');
      const inactiveRows=inactive.map(item=>
        '<article class="recurring-manage-row recurring-paused">'+
          '<div class="recurring-main"><strong>'+esc(item.label)+'</strong><small>'+esc(item.category||'Non catégorisé')+' · '+frequencyLabel(item.frequency)+' · En pause</small></div>'+
          '<div class="money negative">'+euro(item.amount_cents)+'</div>'+
          '<div class="recurring-actions"><button class="btn secondary recurring-edit" data-id="'+item.id+'">Modifier</button><button class="btn secondary recurring-toggle" data-id="'+item.id+'" data-active="0">Réactiver</button></div>'+
        '</article>'
      ).join('');
      root.innerHTML=page('Pilotage','Dépenses régulières','Tout ce qui revient et réduit ton disponible.')+
        '<section class="card recurring-summary"><div><p class="eyebrow">Réservé chaque mois</p><strong>'+euro(monthly)+'</strong><p class="subtle">Équivalent mensuel des dépenses régulières actives.</p></div><button class="btn primary" id="addRecurring">Ajouter</button></section>'+
        '<section class="card"><div class="section-head"><div><p class="eyebrow">Actifs</p><h2>'+active.length+' dépense(s)</h2></div></div><div class="recurring-manage-list">'+(activeRows||'<div class="empty-state">Aucune dépense régulière active.</div>')+'</div></section>'+
        (inactive.length?'<section class="card"><details><summary class="recurring-paused-summary"><span><p class="eyebrow">En pause</p><strong>'+inactive.length+' dépense(s)</strong></span></summary><div class="recurring-manage-list">'+inactiveRows+'</div></details></section>':'')+
        '<section class="card recurring-help"><p class="eyebrow">Impact prévisionnel</p><p class="subtle">Une dépense mise en pause est retirée des prévisions. La réactivation la remet immédiatement dans le forecast.</p></section>'+
        '<button class="btn secondary" data-go="month">Retour au mois</button>';
      q('#addRecurring').addEventListener('click',()=>openRecurringEditor({},accounts,categories));
      root.querySelectorAll('.recurring-edit').forEach(button=>button.addEventListener('click',()=>{
        const item=recurring.find(entry=>String(entry.id)===button.dataset.id)||{};
        openRecurringEditor(item,accounts,categories);
      }));
      root.querySelectorAll('.recurring-toggle').forEach(button=>button.addEventListener('click',async()=>{
        const activeNow=button.dataset.active==='1';
        const item=recurring.find(entry=>String(entry.id)===button.dataset.id);
        const label=item?.label||'cette dépense régulière';
        const message=activeNow?'Mettre '+label+' en pause ?':'Réactiver '+label+' ?';
        if(!window.confirm(message))return;
        button.disabled=true;
        try{
          await api('/api/recurring/'+button.dataset.id,{method:'PATCH',body:JSON.stringify({is_active:!activeNow})});
          renderRecurring();
        }catch(error){button.disabled=false;alert(error.message);}
      }));
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
