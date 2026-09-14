(()=>{
  const ROOT_ID='wealthClarityView';
  let busy=false;
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML;};
  const fmtDate=value=>{if(!value)return 'Non daté';const d=new Date(`${String(value).slice(0,10)}T12:00:00`);return Number.isNaN(d.getTime())?String(value):new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short',year:'numeric'}).format(d);};
  const labelKind=kind=>({checking:'Compte courant',joint:'Compte commun',cash:'Liquidités',savings:'Épargne',livret:'Épargne',ldds:'Épargne',locked_savings:'Épargne bloquée',investment:'Investissement',pea:'PEA',cto:'CTO',life_insurance:'Assurance-vie',loan:'Dette',debt:'Dette'})[(kind||'').toLowerCase()]||'Autre compte';

  function groupsFromAccounts(accounts){
    const groups={cash:{label:'Liquidités',value:0,count:0},savings:{label:'Épargne',value:0,count:0},investments:{label:'Investissements',value:0,count:0},liabilities:{label:'Dettes financières',value:0,count:0}};
    for(const a of accounts||[]){
      if(Number(a.include_in_wealth??1)===0)continue;
      const kind=(a.kind||'').toLowerCase();
      const known=Boolean(a.balance_as_of);
      if(!known)continue;
      const value=Number(a.current_balance_cents||0);
      if(['checking','cash','joint'].includes(kind)){groups.cash.value+=value;groups.cash.count++;}
      else if(['savings','livret','ldds','locked_savings'].includes(kind)){groups.savings.value+=value;groups.savings.count++;}
      else if(['investment','pea','cto','life_insurance'].includes(kind)){groups.investments.value+=value;groups.investments.count++;}
      else if(['loan','debt'].includes(kind)){groups.liabilities.value+=Math.abs(value);groups.liabilities.count++;}
    }
    return groups;
  }

  function trend(history){
    const rows=(history||[]).filter(r=>r.net_worth_cents!=null).slice(-8);
    if(rows.length<2)return '<p class="wc-muted">Pas assez d’historique consolidé pour tracer une évolution fiable.</p>';
    const vals=rows.map(r=>Number(r.net_worth_cents)),min=Math.min(...vals),max=Math.max(...vals),span=Math.max(1,max-min),w=620,h=150,p=14;
    const pts=vals.map((v,i)=>`${p+i*(w-2*p)/(vals.length-1)},${p+(max-v)*(h-2*p)/span}`).join(' ');
    return `<div class="wc-chart"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Évolution du patrimoine net"><polyline points="${pts}"/>${vals.map((v,i)=>{const x=p+i*(w-2*p)/(vals.length-1),y=p+(max-v)*(h-2*p)/span;return `<circle cx="${x}" cy="${y}" r="4"><title>${fmtDate(rows[i].date)} · ${euro(v)}</title></circle>`}).join('')}</svg><div><span>${fmtDate(rows[0].date)}</span><span>${fmtDate(rows.at(-1).date)}</span></div></div>`;
  }

  function accountsHtml(accounts){
    const rows=(accounts||[]).filter(a=>Number(a.include_in_wealth??1)!==0).sort((a,b)=>Number(b.current_balance_cents||0)-Number(a.current_balance_cents||0));
    if(!rows.length)return '<p class="wc-muted">Aucun compte patrimonial renseigné.</p>';
    return rows.map(a=>{
      const known=Boolean(a.balance_as_of);
      return `<div class="wc-account"><div><strong>${esc(a.name)}</strong><small>${esc(labelKind(a.kind))} · ${known?`valorisé au ${fmtDate(a.balance_as_of)}`:'solde non renseigné'}</small></div><strong class="${known?'':'wc-unknown'}">${known?euro(a.current_balance_cents):'Non renseigné'}</strong></div>`;
    }).join('');
  }

  function goalsHtml(goals){
    const rows=(goals||[]).slice(0,8);
    if(!rows.length)return '<p class="wc-muted">Aucun objectif financier actif.</p>';
    return rows.map(g=>{
      const current=Number(g.effective_current_cents??g.current_cents??0),target=Number(g.target_cents||0),progress=target?Math.min(100,current/target*100):0;
      const status=({achieved:'Atteint',on_track:'Dans les temps',at_risk:'À surveiller',off_track:'En retard',late:'Échéance dépassée',no_deadline:'Sans échéance'})[g.status]||'À vérifier';
      const currentLabel=current>0?euro(current):'À financer';
      const monthly=g.required_monthly_cents==null?'Effort non calculable':`${euro(g.required_monthly_cents)}/mois requis`;
      return `<article class="wc-goal"><div class="wc-goal-top"><div><strong>${esc(g.name)}</strong><small>${status}${g.target_date?` · cible ${fmtDate(g.target_date)}`:''}</small></div><span>${Math.round(progress)} %</span></div><div class="wc-track"><i style="width:${progress}%"></i></div><div class="wc-goal-bottom"><span>${currentLabel} / ${euro(target)}</span><span>${monthly}</span></div></article>`;
    }).join('');
  }

  function render(w){
    const groups=groupsFromAccounts(w.accounts);
    const physicalKnown=(w.assets||[]).some(a=>Number(a.include_in_net_worth??1)!==0 && a.valuation_date);
    const physical=physicalKnown?Number(w.physical_assets_cents||0):null;
    const debtKnown=groups.liabilities.count>0 || (w.assets||[]).some(a=>Number(a.debt_cents||0)>0);
    const debt=debtKnown?Number(w.total_debt_cents||0):null;
    const buckets=[groups.cash,groups.savings,groups.investments].filter(x=>x.count>0);
    if(physicalKnown)buckets.push({label:'Actifs physiques',value:physical,count:1});
    const allocationBase=Math.max(1,buckets.reduce((s,b)=>s+Math.max(0,b.value),0));
    const dated=(w.accounts||[]).filter(a=>a.balance_as_of).map(a=>a.balance_as_of).sort();
    const oldest=dated[0]||null;
    const coverage=`${dated.length}/${(w.accounts||[]).filter(a=>Number(a.include_in_wealth??1)!==0).length} compte(s) valorisé(s)`;
    return `<section id="${ROOT_ID}" class="wc-stack">
      <section class="card wc-hero"><div><p class="eyebrow">Patrimoine consolidé</p><span>Patrimoine net connu</span><strong>${euro(w.net_worth_cents)}</strong><p>Somme des actifs renseignés moins les dettes effectivement enregistrées. Les éléments non renseignés ne sont plus convertis en faux 0 €.</p></div><div class="wc-side"><div><span>Actifs connus</span><strong>${euro(w.total_assets_cents)}</strong></div><div><span>Dettes</span><strong>${debt===null?'Non renseignées':euro(debt)}</strong></div></div></section>
      <section class="wc-status"><strong>${coverage}</strong><span>${oldest?`Valorisation la plus ancienne : ${fmtDate(oldest)}`:'Dates de valorisation à compléter'}</span></section>
      <section class="wc-kpis">${buckets.map(b=>`<article class="card"><span>${b.label}</span><strong>${euro(b.value)}</strong><small>${b.count} source(s) valorisée(s)</small></article>`).join('')}</section>
      <section class="card"><div class="section-head"><div><p class="eyebrow">Allocation connue</p><h2>Où se trouve ton patrimoine financier</h2></div></div><div class="wc-allocation">${buckets.map(b=>`<div><div><span>${b.label}</span><strong>${euro(b.value)}</strong></div><div class="wc-track"><i style="width:${Math.max(2,Math.max(0,b.value)/allocationBase*100)}%"></i></div><small>${(Math.max(0,b.value)/allocationBase*100).toFixed(1).replace('.',',')} % des actifs renseignés</small></div>`).join('')}</div>${!physicalKnown?'<p class="wc-note">Actifs physiques : non renseignés, donc exclus de cette répartition.</p>':''}${!debtKnown?'<p class="wc-note">Dettes patrimoniales : aucune valeur enregistrée. Flow ne suppose pas qu’elles valent 0 €.</p>':''}</section>
      <section class="card"><div class="section-head"><div><p class="eyebrow">Évolution</p><h2>Patrimoine net consolidé</h2></div></div>${trend(w.history)}</section>
      <section class="card"><div class="section-head"><div><p class="eyebrow">Comptes</p><h2>Valeurs utilisées dans le calcul</h2></div></div><div class="wc-accounts">${accountsHtml(w.accounts)}</div></section>
      <section class="card"><div class="section-head"><div><p class="eyebrow">Objectifs</p><h2>Progression et effort requis</h2></div></div><div class="wc-goals">${goalsHtml(w.goals)}</div></section>
    </section>`;
  }

  async function enhance(){
    if(busy)return;
    const root=document.querySelector('[data-screen="wealth"]');
    if(!root||!root.classList.contains('active'))return;
    const existing=document.getElementById('wealthDecisionView');
    if(!existing)return;
    busy=true;
    try{
      const r=await fetch('/api/v2.2/wealth',{cache:'no-store'});if(!r.ok)throw new Error();const w=await r.json();
      document.getElementById(ROOT_ID)?.remove();
      existing.insertAdjacentHTML('afterend',render(w));
      existing.hidden=true;
    }catch(_){/* preserve existing wealth page if enhancement fails */}
    finally{busy=false;}
  }
  const observer=new MutationObserver(()=>queueMicrotask(enhance));
  const start=()=>{const root=document.querySelector('[data-screen="wealth"]');if(root)observer.observe(root,{childList:true,subtree:false});document.querySelectorAll('[data-nav="wealth"]').forEach(b=>b.addEventListener('click',()=>setTimeout(enhance,0)));enhance();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
