function ensureDecisionUi(){
  const form=document.querySelector('#simulationForm');if(!form||document.querySelector('#scenarioBuffer'))return;
  const buffer=document.createElement('input');buffer.id='scenarioBuffer';buffer.name='exceptionalBuffer';buffer.inputMode='decimal';buffer.placeholder='Imprévu exceptionnel €';buffer.value='300';
  form.insertBefore(buffer,form.querySelector('button[type=submit]'));
  const result=document.querySelector('#simulationResult');if(result){result.innerHTML='';result.classList.remove('muted');result.insertAdjacentHTML('afterend','<div id="decisionScenarios" class="scenario-grid"></div>')}
}

function verdictLabel(v){return {yes:'Compatible',caution:'Possible mais tendu',no:'Non recommandé'}[v]||v}

async function runDecisionScenario(){
  ensureDecisionUi();
  const form=document.querySelector('#simulationForm'),root=document.querySelector('#decisionScenarios');if(!form||!root)return;
  const f=new FormData(form),amount=Math.abs(cents(f.get('amount'))),date=f.get('date');if(!amount||!date)return;
  root.innerHTML='<div class="empty">Analyse des scénarios…</div>';
  try{
    const d=await api('/api/decisions/evaluate',{method:'POST',body:JSON.stringify({amount_cents:amount,due_date:date,label:f.get('label')||'Dépense envisagée',exceptional_buffer_cents:Math.max(0,cents(f.get('exceptionalBuffer')||300))})});
    document.querySelector('#simulationResult').textContent=d.summary;
    root.innerHTML=d.scenarios.map(s=>`<article class="scenario-card" data-verdict="${s.verdict}"><div class="section-title"><strong>${esc(s.name)}</strong><span>${verdictLabel(s.verdict)}</span></div><div class="scenario-safe">${euro(s.safe_to_spend_cents)}<small> disponible restant</small></div><div class="import-counts"><span>point bas ${euro(s.low_point.balance_cents)}</span><span>${shortDate(s.low_point.date)}</span><span>impact ${euro(s.impact_safe_cents)}</span></div><ul>${s.assumptions.map(a=>`<li>${esc(a)}</li>`).join('')}</ul></article>`).join('');
  }catch(err){root.innerHTML=`<div class="empty">Analyse impossible : ${esc(err.message||'erreur')}</div>`}
}

ensureDecisionUi();
const decisionForm=document.querySelector('#simulationForm');
decisionForm?.addEventListener('submit',async e=>{e.preventDefault();e.stopImmediatePropagation();await runDecisionScenario()},true);
