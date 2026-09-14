(() => {
  const euro = cents => new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(cents)||0)/100);
  const esc = value => { const d=document.createElement('div'); d.textContent=value??''; return d.innerHTML; };
  const api = async url => { const r=await fetch(url,{cache:'no-store'}); if(!r.ok) throw new Error(await r.text()); return r.json(); };
  const q = selector => document.querySelector(selector);
  const state = {month:new Date().toISOString().slice(0,7), horizon:'7'};

  function hideLegacy(page){
    if(!page || page.querySelector(':scope > .v21-page')) return;
    const legacy=document.createElement('div');legacy.className='v21-legacy-hidden';legacy.hidden=true;
    while(page.firstChild) legacy.appendChild(page.firstChild);
    page.appendChild(legacy);
  }

  function homeShell(){
    const page=q('[data-page="home"]'); if(!page) return;
    hideLegacy(page);
    page.insertAdjacentHTML('beforeend',`<div class="v21-page" id="v21Home">
      <section class="v21-card v21-decision">
        <div class="v21-decision-head"><div><p class="v21-kicker">Disponible sans compromettre le mois</p><div class="v21-status" id="v21Status">Analyse…</div></div><span class="v21-muted" id="v21Confidence"></span></div>
        <div class="v21-safe" id="v21Safe">—</div><p class="v21-decision-copy" id="v21SafeCopy">Calcul du disponible sécurisé…</p>
        <div class="v21-decision-grid"><div><span>Aujourd'hui</span><strong id="v21Today">—</strong></div><div><span>7 jours</span><strong id="v21Week">—</strong></div><div><span>Point bas prévu</span><strong id="v21Low">—</strong></div></div>
      </section>
      <div class="v21-priority"><section class="v21-card v21-mini"><span>Prochaine grosse sortie</span><strong id="v21NextOutflow">—</strong><small id="v21NextOutflowMeta">—</small></section><section class="v21-card v21-mini"><span>Prochain revenu</span><strong id="v21NextIncome">—</strong><small id="v21NextIncomeMeta">—</small></section></div>
      <section class="v21-card"><div class="v21-section-head"><div><p class="v21-kicker">Calendrier financier</p><h2>Ce qui va se passer</h2></div><div class="v21-segment" id="v21Horizon"><button data-days="7" class="active">7 j</button><button data-days="30">30 j</button><button data-days="45">Salaire</button></div></div><div class="v21-timeline" id="v21Timeline"><div class="empty">Chargement…</div></div></section>
      <section class="v21-card"><div class="v21-section-head"><div><p class="v21-kicker">Insights</p><h2>À retenir ce mois-ci</h2></div></div><div class="v21-insights" id="v21Insights"></div></section>
      <section class="v21-card"><div class="v21-section-head"><div><p class="v21-kicker">Fiabilité</p><h2>Qualité des données</h2></div></div><div class="v21-quality"><div class="v21-score" id="v21QualityScore">—</div><div class="v21-quality-list" id="v21QualityIssues"></div></div></section>
    </div>`);
    q('#v21Horizon')?.querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{state.horizon=button.dataset.days;q('#v21Horizon').querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===button));renderTimeline(window.__v21Cockpit?.calendar||[])}));
  }

  function monthShell(){
    const page=q('[data-page="month"]'); if(!page) return;
    hideLegacy(page);
    page.insertAdjacentHTML('beforeend',`<div class="v21-page" id="v21Month">
      <section class="v21-card"><div class="v21-month-toolbar"><button id="v21Prev" aria-label="Mois précédent">‹</button><strong id="v21MonthName">—</strong><button id="v21Next" aria-label="Mois suivant">›</button></div></section>
      <div class="v21-month-grid"><section class="v21-card v21-stat"><span>Revenus</span><strong id="v21Income">—</strong><small id="v21IncomeDelta"></small></section><section class="v21-card v21-stat"><span>Charges fixes</span><strong id="v21Fixed">—</strong><small id="v21FixedDelta"></small></section><section class="v21-card v21-stat"><span>Dépenses variables</span><strong id="v21Variable">—</strong><small id="v21VariableDelta"></small></section><section class="v21-card v21-stat"><span>Épargne</span><strong id="v21Saving">—</strong><small id="v21SavingDelta"></small></section><section class="v21-card v21-stat"><span>Exceptionnel</span><strong id="v21Exceptional">—</strong><small>hors rythme habituel</small></section><section class="v21-card v21-stat"><span>Prévision fin de mois</span><strong id="v21Projected">—</strong><small id="v21ProjectedMeta">sur données connues</small></section></div>
      <section class="v21-card"><div class="v21-section-head"><div><p class="v21-kicker">Comparaison</p><h2>Ton rythme</h2></div></div><div class="v21-comparison" id="v21Comparison"></div></section>
      <section class="v21-card"><div class="v21-section-head"><div><p class="v21-kicker">Dépenses</p><h2>Par catégorie</h2></div></div><div id="v21Categories"></div></section>
    </div>`);
    q('#v21Prev')?.addEventListener('click',()=>shiftMonth(-1));q('#v21Next')?.addEventListener('click',()=>shiftMonth(1));
  }

  function statusLabel(value){return ({comfortable:'Confortable',prudent:'Vigilance',tight:'Serré',critical:'Critique'})[value]||value||'—'}
  function dateLabel(value){if(!value)return '—';return new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short'}).format(new Date(`${value}T12:00:00`))}
  function monthName(value){return new Intl.DateTimeFormat('fr-FR',{month:'long',year:'numeric'}).format(new Date(`${value}-15T12:00:00`))}
  function delta(current, reference){const d=(Number(current)||0)-(Number(reference)||0);return `${d>0?'+':''}${euro(d)} vs réf.`}

  function renderTimeline(events){
    const root=q('#v21Timeline');if(!root)return;
    const today=new Date();today.setHours(0,0,0,0);let limit=Number(state.horizon)||7;
    let rows=events.filter(event=>{const d=new Date(`${event.due_date}T12:00:00`);return (d-today)/86400000<=limit;});
    if(state.horizon==='45'){
      const structural=window.__v21Cockpit?.next_income; if(structural?.due_date){rows=events.filter(e=>e.due_date<=structural.due_date)}
    }
    root.innerHTML=rows.length?rows.slice(0,12).map(event=>`<div class="v21-event"><time>${dateLabel(event.due_date)}</time><div><strong>${esc(event.label)}</strong><small>${event.source==='recurring'?'Récurrent · ':''}${esc(event.certainty||'prévu')}</small></div><div class="v21-event-amount"><b class="${Number(event.amount_cents)>0?'v21-positive':'v21-negative'}">${Number(event.amount_cents)>0?'+':''}${euro(event.amount_cents)}</b><small>solde ${euro(event.balance_after_cents)}</small></div></div>`).join(''):'<div class="empty">Aucun mouvement prévu sur cet horizon.</div>';
  }

  async function loadHome(){
    try{
      const data=await api('/api/v2.1/cockpit');window.__v21Cockpit=data;const d=data.decision,s=d.safe_to_spend||{};
      q('#v21Safe').textContent=euro(s.until_income_cents);q('#v21Today').textContent=euro(s.today_cents);q('#v21Week').textContent=euro(s.week_cents);
      const low=d.forecast?.low_point?.balance_cents??d.projections?.realistic?.low_point?.balance_cents??0;q('#v21Low').textContent=euro(low);
      const status=q('#v21Status');status.textContent=statusLabel(s.status);status.dataset.state=s.status||'';
      q('#v21Confidence').textContent=d.confidence?`${Math.round((d.confidence.score||0)*100)} % confiance`:'';
      q('#v21SafeCopy').textContent=`Tu peux dépenser ${euro(s.until_income_cents)} sans compromettre les engagements et objectifs actuellement protégés.`;
      const out=data.next_outflow,income=data.next_income;q('#v21NextOutflow').textContent=out?euro(Math.abs(out.amount_cents)):'Aucune';q('#v21NextOutflowMeta').textContent=out?`${dateLabel(out.due_date)} · ${out.label}`:'sur les 45 prochains jours';q('#v21NextIncome').textContent=income?euro(income.amount_cents):'Non détecté';q('#v21NextIncomeMeta').textContent=income?`${dateLabel(income.due_date)} · ${income.label}`:'à confirmer';
      renderTimeline(data.calendar||[]);
      q('#v21Insights').innerHTML=(data.insights||[]).length?data.insights.slice(0,5).map(item=>`<div class="v21-insight"><strong>${esc(item.title)}</strong><span>${esc(item.body)}</span></div>`).join(''):'<div class="v21-insight"><strong>Rien d'anormal</strong><span>Aucune variation significative détectée sur le mois.</span></div>';
      q('#v21QualityScore').textContent=data.quality?.score??'—';q('#v21QualityIssues').innerHTML=(data.quality?.issues||[]).length?data.quality.issues.slice(0,4).map(item=>`<span>${esc(item.title)} · ${item.count}</span>`).join(''):'<span>Données cohérentes, aucun problème majeur détecté.</span>';
    }catch(error){q('#v21SafeCopy').textContent=`Cockpit indisponible : ${error.message}`}
  }

  function shiftMonth(delta){const d=new Date(`${state.month}-15T12:00:00`);d.setMonth(d.getMonth()+delta);state.month=d.toISOString().slice(0,7);loadMonth()}
  async function loadMonth(){
    try{
      const data=await api(`/api/v2.1/months/${state.month}`),c=data.current,p=data.previous,a3=data.average_3m,a6=data.average_6m;
      q('#v21MonthName').textContent=monthName(state.month);q('#v21Income').textContent=euro(c.income_cents);q('#v21Fixed').textContent=euro(c.fixed_cents);q('#v21Variable').textContent=euro(c.variable_cents);q('#v21Saving').textContent=euro(c.saving_cents);q('#v21Exceptional').textContent=euro(c.exceptional_cents);
      const hasProjection=c.projected_close_cents!==null&&c.projected_close_cents!==undefined;q('#v21Projected').textContent=hasProjection?euro(c.projected_close_cents):'—';q('#v21ProjectedMeta').textContent=hasProjection?'solde prévu à l’horizon':'prévision disponible sur le mois courant';
      q('#v21IncomeDelta').textContent=delta(c.income_cents,p.income_cents);q('#v21FixedDelta').textContent=delta(c.fixed_cents,p.fixed_cents);q('#v21VariableDelta').textContent=delta(c.variable_cents,p.variable_cents);q('#v21SavingDelta').textContent=delta(c.saving_cents,p.saving_cents);
      q('#v21Comparison').innerHTML=`<div><span>Mois précédent</span><strong>${euro(p.spent_cents)}</strong><small>dépenses</small></div><div><span>Moyenne 3 mois</span><strong>${euro(a3.spent_cents)}</strong><small>${delta(c.spent_cents,a3.spent_cents)}</small></div><div><span>Moyenne 6 mois</span><strong>${euro(a6.spent_cents)}</strong><small>${delta(c.spent_cents,a6.spent_cents)}</small></div>`;
      const cats=Object.entries(data.categories||{}).sort((a,b)=>b[1]-a[1]);q('#v21Categories').innerHTML=cats.length?cats.map(([name,value])=>`<div class="v21-category"><b>${esc(name)}</b><span>${euro(value)}</span></div>`).join(''):'<div class="empty">Aucune dépense catégorisée.</div>';
    }catch(error){q('#v21Categories').innerHTML=`<div class="empty">Données mensuelles indisponibles : ${esc(error.message)}</div>`}
  }

  function nav(){document.querySelectorAll('.nav button').forEach(button=>button.addEventListener('click',()=>{const tab=button.dataset.tab;if(tab==='home')setTimeout(loadHome,0);if(tab==='month')setTimeout(loadMonth,0)}))}
  function labels(){document.querySelectorAll('.nav button').forEach(button=>{const span=button.querySelector('span');if(!span)return;if(button.dataset.tab==='month')span.textContent='Mois';if(button.dataset.tab==='movements')span.textContent='Mouvements'});}
  function boot(){homeShell();monthShell();labels();nav();loadHome();loadMonth();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
