(()=>{
  const VERSION='6.4.0';
  const state={scenario:'realistic',range:'cycle',selected:0};
  let payload=null,loading=false;
  const q=(selector,root=document)=>root.querySelector(selector);
  const euro=cents=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:0}).format((Number(cents)||0)/100);
  const esc=value=>{const node=document.createElement('div');node.textContent=value??'';return node.innerHTML;};
  const dateLabel=value=>{const d=new Date(`${String(value).slice(0,10)}T12:00:00`);return Number.isNaN(d.getTime())?String(value):new Intl.DateTimeFormat('fr-FR',{weekday:'short',day:'numeric',month:'short'}).format(d);};
  const confidenceLabel=value=>({high:'Confiance élevée',medium:'Confiance moyenne',low:'Confiance faible'})[value]||'Confiance à vérifier';
  const scenarioLabel=value=>({engaged:'Engagé',realistic:'Réaliste',prudent:'Prudent'})[value]||value;
  const statusFor=data=>!data.availability?.available?'unavailable':Number(data.safe_to_spend?.total_cents||0)<=0?'critical':Number(data.safe_to_spend?.today_cents||0)<1500?'prudent':'comfortable';
  const statusLabel=value=>({unavailable:'Données à actualiser',critical:'Critique',prudent:'Prudent',comfortable:'Maîtrisé'})[value]||'À vérifier';
  function pointsFor(data){const source=data.scenarios?.[state.scenario]?.timeline||[];return state.range==='week'?source.slice(0,Math.min(8,source.length)):source;}
  function chart(data){
    const points=pointsFor(data);if(points.length<2)return '<div class="trajectory-empty">Projection insuffisante.</div>';
    const width=720,height=250,pad={x:28,y:22,b:34},band=(data.uncertainty_band||[]).slice(0,points.length);
    const values=[...points.map(p=>Number(p.balance_cents)||0),...band.flatMap(p=>[Number(p.optimistic_cents)||0,Number(p.prudent_cents)||0]),Number(data.scenarios?.[state.scenario]?.protected_cents)||0];
    let min=Math.min(...values),max=Math.max(...values);if(min===max){min-=100;max+=100;}const spread=max-min;
    const x=i=>pad.x+i*(width-pad.x*2)/Math.max(1,points.length-1),y=v=>pad.y+(max-v)*(height-pad.y-pad.b)/spread;
    const line=points.map((p,i)=>`${i?'L':'M'} ${x(i).toFixed(1)} ${y(Number(p.balance_cents)||0).toFixed(1)}`).join(' ');
    const upper=band.map((p,i)=>`${x(i).toFixed(1)},${y(Number(p.optimistic_cents)||0).toFixed(1)}`).join(' ');
    const lower=[...band].reverse().map((p,j)=>{const i=band.length-1-j;return `${x(i).toFixed(1)},${y(Number(p.prudent_cents)||0).toFixed(1)}`;}).join(' ');
    const bandMarkup=band.length?`<polygon class="trajectory-band" points="${upper} ${lower}"></polygon>`:'';
    const protectedValue=Number(data.scenarios?.[state.scenario]?.protected_cents)||0;
    const ticks=[0,Math.floor((points.length-1)/2),points.length-1].filter((v,i,a)=>a.indexOf(v)===i);
    const markers=points.map((p,i)=>`<g class="trajectory-marker ${i===state.selected?'selected':''}" data-day-index="${i}" role="button" tabindex="0" aria-label="${esc(dateLabel(p.date))}, solde ${esc(euro(p.balance_cents))}"><circle class="hit" cx="${x(i)}" cy="${y(p.balance_cents)}" r="14"></circle><circle cx="${x(i)}" cy="${y(p.balance_cents)}" r="${(p.events||[]).length?5:3}"></circle></g>`).join('');
    return `<svg class="trajectory-chart" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="trajectoryTitle trajectoryDesc"><title id="trajectoryTitle">Trajectoire ${scenarioLabel(state.scenario)}</title><desc id="trajectoryDesc">Projection quotidienne du solde jusqu'au prochain salaire. Chaque point peut être sélectionné.</desc><line class="trajectory-reserve" x1="${pad.x}" x2="${width-pad.x}" y1="${y(protectedValue)}" y2="${y(protectedValue)}"></line><text class="trajectory-reserve-label" x="${width-pad.x}" y="${Math.max(12,y(protectedValue)-7)}" text-anchor="end">Seuil protégé</text>${bandMarkup}<path class="trajectory-line ${state.scenario}" d="${line}"></path>${markers}${ticks.map(i=>`<text class="trajectory-axis" x="${x(i)}" y="${height-8}" text-anchor="${i===0?'start':i===points.length-1?'end':'middle'}">${esc(dateLabel(points[i].date))}</text>`).join('')}</svg>`;
  }
  function selectedDetail(data){
    const points=pointsFor(data);state.selected=Math.min(state.selected,Math.max(0,points.length-1));const item=points[state.selected]||{},events=item.events||[];
    const eventMarkup=events.length?events.map(event=>`<span><b>${esc(event.label)}</b> ${event.amount_cents>0?'+':''}${euro(event.amount_cents)}</span>`).join(''):'<span>Aucun mouvement prévu ce jour.</span>';
    return `<div class="trajectory-detail"><div><span>${esc(dateLabel(item.date))}</span><strong>${euro(item.balance_cents)}</strong><small>Disponible après protections : ${euro(item.spendable_balance_cents)}</small></div><div class="trajectory-events">${eventMarkup}</div></div>`;
  }
  function bind(card){
    card.querySelectorAll('[data-scenario]').forEach(button=>button.addEventListener('click',()=>{state.scenario=button.dataset.scenario;state.selected=0;renderCard();}));
    card.querySelectorAll('[data-range]').forEach(button=>button.addEventListener('click',()=>{state.range=button.dataset.range;state.selected=0;renderCard();}));
    card.querySelectorAll('[data-day-index]').forEach(marker=>{const choose=()=>{state.selected=Number(marker.dataset.dayIndex)||0;renderCard();};marker.addEventListener('click',choose);marker.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();choose();}});});
  }
  function renderHero(data,home){
    const hero=q('.card.hero',home);if(!hero)return;const safe=data.safe_to_spend||{},availability=data.availability||{},horizon=data.horizon||{},confidence=data.confidence||{},status=statusFor(data);
    hero.innerHTML=`<div class="hero-top"><span class="status-pill" data-status="${status}">${statusLabel(status)}</span><span class="confidence-pill">${confidenceLabel(confidence.level)}</span></div><p class="hero-label">Tu peux dépenser aujourd'hui</p><div class="hero-amount">${availability.available?euro(safe.today_cents):'—'}</div><p class="hero-copy">${availability.available?'Ce rythme protège les échéances, objectifs et la réserve jusqu’au prochain revenu.':'Le solde est trop ancien pour certifier un montant. Actualise les données bancaires avant toute décision.'}</p><div class="hero-facts"><div class="hero-fact"><span>Disponible total</span><strong>${availability.available?euro(safe.total_cents):'Indisponible'}</strong><small>jusqu'au revenu</small></div><div class="hero-fact"><span>Horizon</span><strong>${horizon.days||0} jours</strong><small>${dateLabel(horizon.end)}</small></div><div class="hero-fact"><span>Point bas prudent</span><strong>${euro(data.scenarios?.prudent?.low_point?.balance_cents)}</strong><small>${dateLabel(data.scenarios?.prudent?.low_point?.date)}</small></div></div>`;
    hero.dataset.v63Decision='true';
  }
  function renderCard(){
    const home=q('[data-screen="home"]');if(!home||!payload)return;let card=q('[data-v63-trajectory]',home);
    if(!card){card=document.createElement('section');card.className='card trajectory-card';card.dataset.v63Trajectory='true';const anchor=q('.home-summary',home);(anchor||q('.hero',home))?.insertAdjacentElement('afterend',card);}
    const scenarios=['engaged','realistic','prudent'].map(key=>`<button class="chip ${state.scenario===key?'active':''}" data-scenario="${key}" aria-pressed="${state.scenario===key}">${scenarioLabel(key)}</button>`).join('');
    card.innerHTML=`<div class="section-head trajectory-head"><div><p class="eyebrow">Prévision quotidienne</p><h2>Jusqu'au prochain salaire</h2></div><span class="confidence-pill light">${confidenceLabel(payload.variable_spending?.confidence)}</span></div><div class="trajectory-controls"><div class="chips" aria-label="Scénario">${scenarios}</div><div class="chips" aria-label="Période"><button class="chip ${state.range==='week'?'active':''}" data-range="week" aria-pressed="${state.range==='week'}">7 jours</button><button class="chip ${state.range==='cycle'?'active':''}" data-range="cycle" aria-pressed="${state.range==='cycle'}">Cycle</button></div></div><div class="trajectory-plot">${chart(payload)}</div>${selectedDetail(payload)}<div class="trajectory-legend"><span><i class="line-key"></i>${scenarioLabel(state.scenario)}</span><span><i class="band-key"></i>Zone d'incertitude</span><span><i class="event-key"></i>Événement prévu</span></div>`;
    bind(card);
  }
  async function mount(force=false){
    if(loading)return;const home=q('[data-screen="home"]'),hero=q('.card.hero',home);if(!home||!hero||!home.classList.contains('active'))return;
    if(!force&&payload&&q('[data-v63-trajectory]',home)){renderHero(payload,home);return;}loading=true;
    try{const response=await fetch('/api/v6/trajectory',{cache:'no-store'});if(!response.ok)throw new Error(`HTTP ${response.status}`);payload=await response.json();if(payload.availability&&!payload.availability.available)return;renderHero(payload,home);renderCard();home.dataset.v63Home='true';}
    catch(error){console.warn('Flow V6.3 trajectory unavailable; keeping previous cockpit',error);}finally{loading=false;}
  }
  const observer=new MutationObserver(()=>queueMicrotask(()=>mount(false)));
  const start=()=>{const home=q('[data-screen="home"]');if(home)observer.observe(home,{childList:true,subtree:false});document.querySelectorAll('[data-nav="home"]').forEach(button=>button.addEventListener('click',()=>setTimeout(()=>mount(true),80)));setTimeout(()=>mount(false),120);};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();