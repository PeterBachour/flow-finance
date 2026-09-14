(()=>{
const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:0}).format((Number(c)||0)/100);
const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML};
const api=async url=>{const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error(await r.text());return r.json()};
let horizon=12;
let scenarioId='';
const statusLabel=s=>({achieved:'Atteint',on_track:'Dans les temps',at_risk:'À surveiller',off_track:'En retard',late:'Échéance dépassée',no_deadline:'Sans échéance'})[s]||s;
const signalLabel=s=>({comfortable:'Liquidité confortable',watch:'Liquidité à surveiller',tight:'Liquidité serrée'})[s]||s;

async function render(){
  const host=document.querySelector('[data-v33-dashboard]');
  if(!host)return;
  host.innerHTML='<div class="skeleton tall"></div>';
  try{
    const suffix=`months=${horizon}${scenarioId?`&scenario_id=${scenarioId}`:''}`;
    const [goals,wealth,scenarios]=await Promise.all([
      api(`/api/v3.3/goals-forecast?${suffix}`),
      api(`/api/v3.3/wealth-forecast?${suffix}`),
      api('/api/v3.2/scenarios')
    ]);
    host.innerHTML=`
      <section class="card">
        <div class="section-head"><div><p class="eyebrow">Trajectoire patrimoniale</p><h2>Projection ${horizon} mois</h2></div><div class="chips">${[6,12].map(m=>`<button class="chip ${m===horizon?'active':''}" data-v33-horizon="${m}">${m}M</button>`).join('')}</div></div>
        <select class="field" id="v33Scenario"><option value="">Trajectoire de référence</option>${scenarios.map(s=>`<option value="${s.id}" ${String(s.id)===String(scenarioId)?'selected':''}>${esc(s.name)}</option>`).join('')}</select>
        <div class="metric-grid" style="margin-top:10px">
          <div class="metric"><span>Patrimoine actuel</span><strong>${euro(wealth.current_net_worth_cents)}</strong></div>
          <div class="metric"><span>Patrimoine projeté</span><strong>${euro(wealth.projected_net_worth_cents)}</strong></div>
          <div class="metric"><span>Variation projetée</span><strong>${wealth.net_worth_delta_cents>=0?'+':''}${euro(wealth.net_worth_delta_cents)}</strong></div>
          <div class="metric"><span>Dette actuelle</span><strong>${euro(wealth.current_debt_cents)}</strong></div>
        </div>
        <div style="margin-top:10px">${wealth.months.map(m=>`<div class="row"><div><strong>${esc(m.month)}</strong><small>Liquidité ${euro(m.projected_liquid_balance_cents)} · point bas ${euro(m.low_point_cents)}</small></div><div class="money">${euro(m.projected_net_worth_cents)}</div></div>`).join('')}</div>
        <p class="hero-copy" style="color:var(--muted);margin-top:10px">${esc(wealth.method)}</p>
      </section>
      <section class="card">
        <div class="section-head"><div><p class="eyebrow">Objectifs</p><h2>Atteignabilité projetée</h2></div><span class="chip">${goals.goals.length}</span></div>
        <div class="metric-grid">
          <div class="metric"><span>Atteints</span><strong>${goals.counts.achieved}</strong></div>
          <div class="metric"><span>Dans les temps</span><strong>${goals.counts.on_track}</strong></div>
          <div class="metric"><span>À surveiller</span><strong>${goals.counts.at_risk}</strong></div>
          <div class="metric"><span>En retard</span><strong>${goals.counts.off_track}</strong></div>
        </div>
        <div style="margin-top:10px">${goals.goals.map(g=>`<div style="padding:12px 0;border-bottom:1px solid var(--line)"><div class="row" style="padding:0 0 7px;border:0"><div><strong>${esc(g.name)}</strong><small>${statusLabel(g.status)} · ${signalLabel(g.liquidity_signal)}</small></div><div class="money">${Math.round(g.projected_progress_pct||0)} %</div></div><div class="progress"><i style="width:${Math.min(100,g.projected_progress_pct||0)}%"></i></div><small style="display:block;margin-top:6px;color:var(--muted)">Aujourd’hui ${euro(g.effective_current_cents)} · projeté ${euro(g.projected_at_target_cents)} / ${euro(g.target_cents)}${g.required_monthly_cents!=null?` · requis ${euro(g.required_monthly_cents)}/mois`:''}${g.projected_gap_cents?` · écart ${euro(g.projected_gap_cents)}`:''}</small></div>`).join('')||'<div class="empty-state">Aucun objectif actif.</div>'}
        <p class="hero-copy" style="color:var(--muted);margin-top:10px">${esc(goals.method)}</p>
      </section>`;
    host.querySelectorAll('[data-v33-horizon]').forEach(b=>b.onclick=()=>{horizon=Number(b.dataset.v33Horizon);render()});
    host.querySelector('#v33Scenario').onchange=e=>{scenarioId=e.target.value;render()};
  }catch(e){host.innerHTML=`<div class="card danger">Projection patrimoine/objectifs indisponible : ${esc(e.message)}</div>`}
}

function inject(){
  const wealth=document.querySelector('[data-screen="wealth"]');
  if(!wealth||!wealth.children.length||wealth.querySelector('[data-v33-dashboard]'))return;
  const host=document.createElement('div');
  host.dataset.v33Dashboard='1';
  host.className='stack';
  wealth.appendChild(host);
  render();
}
const observer=new MutationObserver(()=>{
  const wealth=document.querySelector('[data-screen="wealth"]');
  if(wealth&&wealth.classList.contains('active')&&wealth.children.length)inject();
});
observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class']});
document.querySelectorAll('[data-nav="wealth"]').forEach(b=>b.addEventListener('click',()=>setTimeout(inject,80)));
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(inject,300));else setTimeout(inject,300);
})();
