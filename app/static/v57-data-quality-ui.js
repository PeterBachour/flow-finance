(()=>{
  const ID='v57DataQualityCenter';
  let refreshing=false;
  let lastData=null;
  const esc=value=>{const node=document.createElement('div');node.textContent=value??'';return node.innerHTML;};
  const api=async url=>{const response=await fetch(url,{cache:'no-store'});if(!response.ok)throw new Error((await response.text())||`HTTP ${response.status}`);return response.json();};
  const priorityLabel=value=>({critical:'Critique',high:'Haute',medium:'Moyenne',low:'Faible'})[value]||value;
  const priorityClass=value=>value==='critical'?'danger':value==='high'?'warning':value==='medium'?'':'active';
  const unlockLabel=value=>({trends:'Tendances',predictive_models:'Prévisions',income_analysis:'Revenus',historical_depth:'Profondeur historique'})[value]||value;

  function editDialog(){return document.getElementById('editDialog');}
  function editBody(){return document.getElementById('editBody');}
  function unlocks(action){return (action?.unlocks||[]).map(item=>`<span class="v57-unlock">${esc(unlockLabel(item))}</span>`).join('');}

  function runAction(action){
    if(!action)return;
    if(action.target==='bulk_import'){
      document.getElementById('v55ImportBtn')?.click();
      return;
    }
    document.getElementById('v55DetailsBtn')?.click();
  }

  function renderAll(){
    const data=lastData,d=editDialog(),body=editBody();
    if(!data||!d||!body)return;
    d.showModal();
    body.innerHTML=`<div class="stack"><p class="eyebrow">Qualité des données</p><h3>Plan de fiabilisation</h3><p class="subtle">${data.open_count||0} action(s), dont ${data.blocking_count||0} bloquante(s). Aucune correction n'est exécutée automatiquement.</p><div class="v57-action-list">${(data.actions||[]).map((action,index)=>`<article class="v57-action"><div class="v57-action-rank">${index+1}</div><div><div class="v57-action-title"><strong>${esc(action.title)}</strong><span class="chip ${priorityClass(action.priority)}">${esc(priorityLabel(action.priority))}</span></div><p>${esc(action.detail)}</p><div class="v57-proof"><span>Preuve</span><small>${esc(action.evidence||'—')}</small></div>${action.expected_document?`<div class="v57-proof"><span>Document attendu</span><small>${esc(action.expected_document)}</small></div>`:''}<div class="v57-unlocks"><span>Débloque</span><div>${unlocks(action)}</div></div><small class="v57-impact">${esc(action.impact)}</small></div><button class="btn secondary" data-v57-action="${esc(action.id)}">Ouvrir</button></article>`).join('')||'<div class="empty-state">Aucune action de qualité requise.</div>'}</div><p class="subtle">${esc(data.method)}</p></div>`;
    body.querySelectorAll('[data-v57-action]').forEach(button=>button.addEventListener('click',()=>runAction(data.actions.find(item=>item.id===button.dataset.v57Action))));
  }

  async function refresh(){
    if(refreshing)return;
    const root=document.querySelector('[data-screen="movements"]');
    if(!root||!root.classList.contains('active'))return;
    const anchor=document.getElementById('v55HistoryCoverage');
    if(!anchor)return;
    refreshing=true;
    try{
      const data=await api('/api/v5.7/data-quality-actions?months=24');
      lastData=data;
      document.getElementById(ID)?.remove();
      const primary=data.primary_action;
      anchor.insertAdjacentHTML('afterend',`<section id="${ID}" class="card v57-center"><div class="section-head"><div><p class="eyebrow">Plan de fiabilisation</p><h2>Data Quality Action Center</h2><p class="subtle">${data.open_count||0} action(s) ouverte(s) · ${data.blocking_count||0} bloquante(s) · score ${data.score??'—'}/100</p></div><button class="btn secondary" id="v57AllBtn">Voir toutes</button></div><div class="v57-priority-grid"><div><span>Critiques</span><strong>${data.counts?.critical||0}</strong></div><div><span>Hautes</span><strong>${data.counts?.high||0}</strong></div><div><span>Moyennes</span><strong>${data.counts?.medium||0}</strong></div><div><span>Faibles</span><strong>${data.counts?.low||0}</strong></div></div>${primary?`<div class="v57-primary"><div><p class="eyebrow">À faire maintenant</p><strong>${esc(primary.title)}</strong><small>${esc(primary.evidence||primary.impact)}</small><div class="v57-unlocks compact"><span>Débloque</span><div>${unlocks(primary)}</div></div></div><button class="btn primary" id="v57PrimaryBtn">Corriger</button></div>`:'<div class="empty-state">La file de fiabilisation est vide. Aucun correctif historique prioritaire.</div>'}<div class="v57-action-list compact">${(data.actions||[]).slice(1,4).map(action=>`<div class="v57-action-row"><div><strong>${esc(action.title)}</strong><small>${esc(action.evidence||action.impact)}</small></div><span class="chip ${priorityClass(action.priority)}">${esc(priorityLabel(action.priority))}</span></div>`).join('')}</div><p class="subtle">Lecture seule : chaque action expose sa preuve et nécessite une validation explicite.</p></section>`);
      document.getElementById('v57AllBtn')?.addEventListener('click',renderAll);
      document.getElementById('v57PrimaryBtn')?.addEventListener('click',()=>runAction(primary));
    }catch(_){/* keep Movements usable if diagnostic endpoint is unavailable */}
    finally{refreshing=false;}
  }

  const observer=new MutationObserver(()=>queueMicrotask(refresh));
  const start=()=>{
    const root=document.querySelector('[data-screen="movements"]');
    if(root)observer.observe(root,{childList:true,subtree:true});
    document.querySelectorAll('[data-nav="movements"]').forEach(button=>button.addEventListener('click',()=>setTimeout(refresh,180)));
    refresh();
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
