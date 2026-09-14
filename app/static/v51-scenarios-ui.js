(()=>{
  let busy=false;
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML;};
  const cents=v=>Math.round((Number(String(v||'').replace(',','.'))||0)*100);
  const api=async(url,options={})=>{const r=await fetch(url,{cache:'no-store',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});if(!r.ok)throw new Error((await r.text())||`HTTP ${r.status}`);return r.status===204?null:r.json();};
  const verdictLabel=v=>({compatible:'Compatible',caution:'À surveiller',not_recommended:'Non recommandé'})[v]||v||'À vérifier';

  function card(data){
    const items=data.items||[];
    return `<section id="v51SavedScenarios" class="card v51-scenarios-card">
      <div class="section-head"><div><p class="eyebrow">V5.1 · Scénarios</p><h2>Comparer avant de décider</h2></div><span class="chip">${items.length} enregistré(s)</span></div>
      <details class="v51-scenario-create"><summary>Enregistrer une hypothèse</summary>
        <form id="v51ScenarioForm" class="v51-scenario-form">
          <label>Nom<input name="name" required maxlength="120" placeholder="Ex. Voyage octobre"></label>
          <label>Type<select name="kind"><option value="one_time_expense">Dépense ponctuelle</option><option value="monthly_expense">Dépense mensuelle</option><option value="monthly_income">Revenu mensuel</option></select></label>
          <label>Montant €<input name="amount" required inputmode="decimal" placeholder="0"></label>
          <label data-date-field>Date<input name="date" type="date"></label>
          <label data-day-field hidden>Jour du mois<input name="day" type="number" min="1" max="31" value="1"></label>
          <label>Horizon<select name="months"><option>3</option><option selected>6</option><option>12</option></select></label>
          <button class="btn primary">Enregistrer</button>
        </form><p id="v51ScenarioStatus" class="subtle"></p>
      </details>
      <div class="v51-scenario-list">${items.map(item=>`<article data-scenario-id="${item.id}"><div><strong>${esc(item.name)}</strong><small>${item.horizon_months} mois · ${(item.events||[]).length} hypothèse(s)</small></div><div class="v51-scenario-actions"><button class="chip" data-compare="${item.id}">Comparer</button><button class="chip" data-delete="${item.id}">Supprimer</button></div><div class="v51-scenario-result" data-result="${item.id}"></div></article>`).join('')||'<div class="empty-state">Aucun scénario enregistré.</div>'}</div>
      <p class="subtle">Les scénarios sont persistés séparément des transactions réelles. Ils n’affectent jamais le ledger bancaire.</p>
    </section>`;
  }

  async function refresh(){
    if(busy)return;
    const root=document.querySelector('[data-screen="month"]');
    if(!root||!root.classList.contains('active'))return;
    busy=true;
    try{
      const data=await api('/api/v5/scenarios');
      root.querySelector('#v51SavedScenarios')?.remove();
      const anchor=root.querySelector('#v5Planning')||root.querySelector('.page-head');
      if(!anchor)return;
      anchor.insertAdjacentHTML('afterend',card(data));
      bind(root);
    }catch(_){/* validated month remains available */}finally{busy=false;}
  }

  function bind(root){
    const form=root.querySelector('#v51ScenarioForm');
    const syncKind=()=>{
      const monthly=form?.kind.value!=='one_time_expense';
      root.querySelector('[data-date-field]')?.toggleAttribute('hidden',monthly);
      root.querySelector('[data-day-field]')?.toggleAttribute('hidden',!monthly);
    };
    form?.kind.addEventListener('change',syncKind);syncKind();
    form?.addEventListener('submit',async e=>{
      e.preventDefault();
      const f=e.currentTarget.elements,status=root.querySelector('#v51ScenarioStatus');
      const amount=Math.abs(cents(f.amount.value));
      if(!amount){status.textContent='Saisis un montant supérieur à 0.';return;}
      const kind=f.kind.value,monthly=kind!=='one_time_expense';
      const event={
        event_type:monthly?'monthly':'one_time',
        label:f.name.value.trim(),
        amount_cents:kind==='monthly_income'?amount:-amount,
        due_date:monthly?null:(f.date.value||new Date().toISOString().slice(0,10)),
        day_of_month:monthly?Number(f.day.value||1):null,
        start_date:monthly?new Date().toISOString().slice(0,10):null,
        end_date:null
      };
      status.textContent='Enregistrement…';
      try{
        await api('/api/v5/scenarios',{method:'POST',body:JSON.stringify({name:f.name.value.trim(),description:null,horizon_months:Number(f.months.value),events:[event]})});
        await refresh();
      }catch(err){status.textContent=`Échec : ${err.message}`;}
    });
    root.querySelectorAll('[data-compare]').forEach(btn=>btn.addEventListener('click',async()=>{
      const id=btn.dataset.compare,out=root.querySelector(`[data-result="${id}"]`);out.innerHTML='<div class="skeleton"></div>';
      try{const data=await api(`/api/v5/scenarios/${id}/compare`);out.innerHTML=`<div class="v51-compare ${data.verdict}"><strong>${verdictLabel(data.verdict)}</strong><span>Solde final ${euro(data.simulated?.closing_balance_cents)} · impact ${euro(data.impact?.closing_balance_delta_cents)}</span><span>Point bas ${euro(data.simulated?.low_point_cents)} · marge min ${euro(data.simulated?.minimum_safe_margin_cents)}</span></div>`;}catch(err){out.textContent=`Comparaison indisponible : ${err.message}`;}
    }));
    root.querySelectorAll('[data-delete]').forEach(btn=>btn.addEventListener('click',async()=>{
      if(!confirm('Supprimer ce scénario enregistré ?'))return;
      try{await api(`/api/v5/scenarios/${btn.dataset.delete}`,{method:'DELETE'});await refresh();}catch(err){alert(`Suppression impossible : ${err.message}`);}
    }));
  }

  const observer=new MutationObserver(()=>queueMicrotask(()=>{const root=document.querySelector('[data-screen="month"]');if(root?.classList.contains('active')&&!root.querySelector('#v51SavedScenarios'))refresh();}));
  const start=()=>{const app=document.getElementById('app');if(app)observer.observe(app,{childList:true,subtree:true});document.querySelectorAll('[data-nav="month"]').forEach(b=>b.addEventListener('click',()=>setTimeout(refresh,120)));setTimeout(refresh,180);};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();

(()=>{
  let busy=false;
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML;};
  const statusLabel=v=>({achieved:'Atteint',on_track:'Dans les temps',at_risk:'À surveiller',off_track:'En retard',late:'Échéance dépassée',no_deadline:'Sans échéance'})[v]||v||'—';
  const api=async(url,options={})=>{const r=await fetch(url,{cache:'no-store',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});if(!r.ok)throw new Error((await r.text())||`HTTP ${r.status}`);return r.json();};
  function goalHtml(goal){const progress=Math.max(0,Math.min(100,Number(goal.progress_pct)||0));const projected=Math.max(0,Math.min(100,Number(goal.projected_progress_pct)||0));return `<article class="v51-goal" data-goal-id="${goal.goal_id}"><div class="v51-goal-head"><div><strong>${esc(goal.name||'Objectif')}</strong><small>${statusLabel(goal.status)}${goal.target_date?` · cible ${esc(goal.target_date)}`:''}</small></div><span class="chip ${['late','off_track','at_risk'].includes(goal.status)?'warning':'active'}">${Math.round(progress)} %</span></div><div class="v51-goal-track"><i style="width:${progress}%"></i><b style="width:${projected}%"></b></div><div class="v51-goal-metrics"><div><span>Restant</span><strong>${euro(goal.remaining_cents)}</strong></div><div><span>Configuré</span><strong>${euro(goal.configured_monthly_cents)}/mois</strong></div><div><span>Requis</span><strong>${goal.required_monthly_cents==null?'—':euro(goal.required_monthly_cents)+'/mois'}</strong></div><div><span>Conseillé</span><strong>${euro(goal.recommended_monthly_cents)}/mois</strong></div></div><form class="v51-goal-sim"><label>Tester une mensualité<input name="amount" inputmode="decimal" placeholder="${(Number(goal.configured_monthly_cents||0)/100).toFixed(0)}"></label><button class="btn secondary" type="submit">Simuler</button></form><div class="v51-goal-result" aria-live="polite"></div></article>`;}
  function render(data){return `<section id="v51GoalControl" class="card v51-goals-card"><div class="section-head"><div><p class="eyebrow">V5.1 · Objectifs</p><h2>Pilotage avancé</h2></div><span class="chip">${euro(data.monthly_capacity_cents)}/mois de capacité</span></div><div class="v51-goal-summary"><div><span>Objectifs</span><strong>${data.summary?.goal_count||0}</strong></div><div><span>À surveiller</span><strong>${data.summary?.goals_needing_attention||0}</strong></div><div><span>Capacité libre</span><strong>${euro(data.unallocated_monthly_capacity_cents)}</strong></div></div><div class="v51-goal-list">${(data.goals||[]).map(goalHtml).join('')||'<div class="empty-state">Aucun objectif actif.</div>'}</div><p class="subtle">${esc(data.principle||'')}</p></section>`;}
  async function enhance(){if(busy)return;const root=document.querySelector('[data-screen="wealth"]');if(!root||!root.classList.contains('active')||root.querySelector('#v51GoalControl'))return;busy=true;try{const data=await api('/api/v5/goals-control?months=12');const target=root.querySelector('#v5GoalArbitration')||root.querySelector('.page-head');if(!target)return;target.insertAdjacentHTML('afterend',render(data));root.querySelectorAll('.v51-goal-sim').forEach(form=>form.addEventListener('submit',async event=>{event.preventDefault();const card=form.closest('[data-goal-id]'),output=card.querySelector('.v51-goal-result'),value=Number(String(form.amount.value||'').replace(',','.'));if(!Number.isFinite(value)||value<0){output.textContent='Saisis une mensualité valide.';return;}output.textContent='Simulation…';try{const result=await api(`/api/v5/goals/${card.dataset.goalId}/simulate-contribution`,{method:'POST',body:JSON.stringify({monthly_contribution_cents:Math.round(value*100),months:12})});const compatible=result.compatible_with_current_capacity,delta=Number(result.impact?.projected_gap_delta_cents||0);output.innerHTML=`<div class="v51-sim-result ${compatible?'positive':'warning'}"><strong>${compatible?'Compatible avec la capacité actuelle':'Dépasse la capacité actuelle'}</strong><span>Progression projetée ${Number(result.simulated?.projected_progress_pct||0).toFixed(0)} % · gap ${euro(result.simulated?.projected_gap_cents)}</span><small>Impact sur le gap : ${delta<=0?'':'+'}${euro(delta)} · aucune modification enregistrée</small></div>`;}catch(err){output.textContent=`Simulation indisponible : ${err.message}`;}}));}catch(_){/* existing wealth remains available */}finally{busy=false;}}
  const observer=new MutationObserver(()=>queueMicrotask(enhance));
  const start=()=>{const app=document.getElementById('app');if(app)observer.observe(app,{childList:true,subtree:true});document.querySelectorAll('[data-nav="wealth"]').forEach(b=>b.addEventListener('click',()=>setTimeout(enhance,100)));enhance();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
