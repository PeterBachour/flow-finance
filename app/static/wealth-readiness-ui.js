(()=>{
  const ID='wealthReadinessPanel';
  let busy=false;
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML;};
  const dateLabel=v=>{if(!v)return 'Sans échéance';const d=new Date(`${String(v).slice(0,10)}T12:00:00`);return Number.isNaN(d.getTime())?String(v):new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short',year:'numeric'}).format(d);};
  const statusLabel=s=>({achieved:'Atteint',on_track:'Dans les temps',at_risk:'À surveiller',off_track:'En retard',late:'Échéance dépassée',no_deadline:'Sans échéance'})[s]||'À vérifier';
  const api=async(url,options={})=>{const r=await fetch(url,{cache:'no-store',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});if(!r.ok)throw new Error((await r.text())||`HTTP ${r.status}`);return r.json();};

  function accountSummary(data){
    const s=data.summary||{};
    const issues=[...(data.accounts?.stale||[]),...(data.accounts?.undated||[])];
    return `<section class="wr-status ${issues.length?'warning':'ok'}">
      <div><strong>${issues.length?`${issues.length} valeur(s) à actualiser`:'Patrimoine à jour'}</strong><small>${s.fresh_accounts||0}/${s.wealth_accounts||0} compte(s) valorisé(s) depuis moins de ${data.freshness_rule_days||31} jours.</small></div>
      ${issues.length?`<details><summary>Voir les comptes concernés</summary><div class="wr-account-issues">${issues.map(a=>`<div><span>${esc(a.name)}</span><strong>${a.freshness==='undated'?'Date manquante':`${a.age_days} j`}</strong></div>`).join('')}</div></details>`:''}
    </section>`;
  }

  function goalCard(g){
    const progress=Math.max(0,Math.min(100,Number(g.progress_pct||0)));
    const current=Number(g.effective_current_cents??g.current_cents??0);
    const history=(g.history||[]).slice(0,4);
    return `<article class="wr-goal" data-goal="${g.id}">
      <div class="wr-goal-head"><div><strong>${esc(g.name)}</strong><small>${statusLabel(g.status)} · ${g.target_date?`cible ${dateLabel(g.target_date)}`:'sans date cible'}</small></div><span class="wr-goal-pct">${Math.round(progress)} %</span></div>
      <div class="wr-track"><i style="width:${progress}%"></i></div>
      <div class="wr-goal-values"><span><b>${euro(current)}</b> constitués</span><span><b>${euro(g.remaining_cents)}</b> restants</span><span><b>${g.required_monthly_cents==null?'—':euro(g.required_monthly_cents)}</b>/mois requis</span></div>
      <div class="wr-goal-actions"><button class="btn secondary" data-goal-edit="${g.id}">Actualiser</button>${history.length?`<details><summary>Historique (${g.history_count||history.length})</summary><div class="wr-history">${history.map(h=>`<div><span>${dateLabel(h.observed_on)}</span><strong>${euro(h.current_cents)}</strong></div>`).join('')}</div></details>`:''}</div>
    </article>`;
  }

  function html(data){
    return `<section id="${ID}" class="wr-stack">
      ${accountSummary(data)}
      <section class="card wr-goals-card"><div class="section-head"><div><p class="eyebrow">Objectifs</p><h2>Trajectoire financière</h2></div><span class="wr-attention">${data.summary?.goals_needing_attention||0} à surveiller</span></div>
        <p class="subtle">Chaque actualisation est datée et historisée. Flow ne remplace pas silencieusement la situation précédente.</p>
        <div class="wr-goals">${(data.goals||[]).map(goalCard).join('')||'<div class="empty-state">Aucun objectif actif.</div>'}</div>
      </section>
    </section>`;
  }

  async function openGoal(id,data){
    const goal=(data.goals||[]).find(g=>Number(g.id)===Number(id));if(!goal)return;
    const dialog=document.getElementById('editDialog'),body=document.getElementById('editBody');if(!dialog||!body)return;
    dialog.showModal();
    body.innerHTML=`<form id="wrGoalForm" class="stack"><p class="eyebrow">Objectif</p><h3>${esc(goal.name)}</h3>
      <label class="form-label">Montant constitué (€)<input class="field" name="current" inputmode="decimal" value="${(Number(goal.current_cents||0)/100).toFixed(2)}"></label>
      <label class="form-label">Contribution mensuelle (€)<input class="field" name="monthly" inputmode="decimal" value="${(Number(goal.monthly_contribution_cents||0)/100).toFixed(2)}"></label>
      <label class="form-label">Date cible<input class="field" type="date" name="target" value="${goal.target_date||''}"></label>
      <div class="notice">La mise à jour crée un snapshot daté de l’objectif. Elle ne crée aucun mouvement bancaire.</div>
      <button class="btn primary">Enregistrer la progression</button></form>`;
    body.querySelector('#wrGoalForm').addEventListener('submit',async e=>{
      e.preventDefault();const f=e.currentTarget.elements;
      await api(`/api/v4.10/goals/${id}/progress`,{method:'POST',body:JSON.stringify({current_cents:Math.round(Number(String(f.current.value).replace(',','.'))*100),monthly_contribution_cents:Math.round(Number(String(f.monthly.value).replace(',','.'))*100),target_date:f.target.value||null,confirmation:'METTRE_A_JOUR'})});
      dialog.close();document.getElementById(ID)?.remove();enhance(true);
    });
  }

  async function enhance(force=false){
    if(busy)return;
    const root=document.querySelector('[data-screen="wealth"]');
    const host=document.getElementById('wealthDecisionView');
    if(!root?.classList.contains('active')||!host)return;
    if(!force&&document.getElementById(ID))return;
    busy=true;
    try{
      const data=await api('/api/v4.10/wealth-readiness');
      document.getElementById(ID)?.remove();
      host.insertAdjacentHTML('beforeend',html(data));
      [...host.querySelectorAll('.card')].forEach(card=>{const h=card.querySelector('h2')?.textContent?.trim();if(h==='Progression et effort requis')card.hidden=true;});
      document.getElementById(ID)?.querySelectorAll('[data-goal-edit]').forEach(b=>b.addEventListener('click',()=>openGoal(b.dataset.goalEdit,data)));
    }catch(error){console.warn('Flow wealth readiness unavailable',error);}finally{busy=false;}
  }

  const observer=new MutationObserver(()=>queueMicrotask(()=>enhance(false)));
  const start=()=>{const root=document.querySelector('[data-screen="wealth"]');if(root)observer.observe(root,{childList:true,subtree:false});document.querySelector('[data-nav="wealth"]')?.addEventListener('click',()=>setTimeout(()=>enhance(true),120));enhance();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();