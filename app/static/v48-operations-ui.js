(()=>{
  const ID='v48QualityWorkbench';
  let busy=false;
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML;};
  const api=async(url,options={})=>{const r=await fetch(url,{cache:'no-store',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});if(!r.ok)throw new Error((await r.text())||`HTTP ${r.status}`);return r.json();};

  function dialog(){return document.getElementById('editDialog');}
  function body(){return document.getElementById('editBody');}

  async function openBulk(){
    const d=dialog(),b=body();if(!d||!b)return;d.showModal();b.innerHTML='<div class="skeleton tall"></div>';
    try{
      const [categories,accounts]=await Promise.all([api('/api/categories'),api('/api/accounts')]);
      b.innerHTML=`<form id="v48BulkForm" class="stack"><p class="eyebrow">Traitement groupé</p><h3>Catégoriser plusieurs mouvements</h3><p class="subtle">Flow affiche d’abord un aperçu. Rien n’est modifié avant ta confirmation.</p><label class="form-label">Motif à rechercher<input class="field" name="pattern" minlength="2" required placeholder="ex. MONOPRIX"></label><label class="form-label">Catégorie<select class="field" name="category" required><option value="">Choisir</option>${categories.map(c=>`<option>${esc(c.name)}</option>`).join('')}</select></label><label class="form-label">Compte<select class="field" name="account_id"><option value="">Tous les comptes</option>${accounts.map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select></label><label class="toggle-row"><span><strong>Seulement les non catégorisés</strong><small>Évite d’écraser des corrections déjà faites.</small></span><input type="checkbox" name="only_uncategorized" checked></label><label class="toggle-row"><span><strong>Créer une règle</strong><small>Les prochains mouvements correspondants seront classés automatiquement.</small></span><input type="checkbox" name="create_rule" checked></label><button class="btn primary">Prévisualiser</button><div id="v48Preview"></div></form>`;
      document.getElementById('v48BulkForm')?.addEventListener('submit',previewBulk);
    }catch(e){b.innerHTML=`<div class="notice">Impossible de charger le traitement groupé : ${esc(e.message)}</div>`;}
  }

  function payloadFrom(form){return {pattern:form.pattern.value.trim(),category:form.category.value,account_id:form.account_id.value?Number(form.account_id.value):null,only_uncategorized:form.only_uncategorized.checked,create_rule:form.create_rule.checked};}

  async function previewBulk(event){
    event.preventDefault();const form=event.currentTarget,preview=document.getElementById('v48Preview');if(!preview)return;
    preview.innerHTML='<div class="skeleton"></div>';
    try{
      const payload=payloadFrom(form),data=await api('/api/v4.8/bulk-category/preview',{method:'POST',body:JSON.stringify(payload)});
      preview.innerHTML=`<section class="v48-preview"><strong>${data.affected_count} mouvement(s) concerné(s)</strong><p class="subtle">${data.affected_count?`Ils seront classés en ${esc(data.category)}.`:'Aucun mouvement ne correspond à ces critères.'}</p>${(data.sample||[]).slice(0,6).map(r=>`<div class="v48-sample"><span>${esc(r.user_label||r.label)}</span><strong>${euro(r.amount_cents)}</strong></div>`).join('')}${data.affected_count?'<button type="button" class="btn primary" id="v48ApplyBulk">Confirmer et appliquer</button>':''}</section>`;
      document.getElementById('v48ApplyBulk')?.addEventListener('click',()=>applyBulk(payload));
    }catch(e){preview.innerHTML=`<div class="notice">Prévisualisation impossible : ${esc(e.message)}</div>`;}
  }

  async function applyBulk(payload){
    const preview=document.getElementById('v48Preview');if(preview)preview.innerHTML='<div class="skeleton"></div>';
    try{
      const result=await api('/api/v4.8/bulk-category/apply',{method:'POST',body:JSON.stringify(payload)});
      if(preview)preview.innerHTML=`<div class="notice"><strong>${result.updated_count} mouvement(s) mis à jour.</strong>${result.rule_id?'<br><small>Règle de catégorisation créée ou réutilisée.</small>':''}</div>`;
      setTimeout(()=>{dialog()?.close();refresh();},850);
    }catch(e){if(preview)preview.innerHTML=`<div class="notice">Application impossible : ${esc(e.message)}</div>`;}
  }

  async function openRecurring(){
    const d=dialog(),b=body();if(!d||!b)return;d.showModal();b.innerHTML='<div class="skeleton tall"></div>';
    try{const data=await api('/api/v4.8/recurring-review');b.innerHTML=`<div class="stack"><p class="eyebrow">Récurrences</p><h3>Suggestions à valider</h3><p class="subtle">Une suggestion n’impacte jamais le Safe avant acceptation explicite.</p>${(data.items||[]).map(item=>`<article class="v48-recurring"><div><strong>${esc(item.label)}</strong><small>${esc(item.account_name)} · ${item.occurrences} occurrence(s) · ${Math.round(Number(item.confidence||0)*100)} % de confiance</small><small>${euro(item.amount_cents)} · vers le ${item.day_of_month} du mois${item.category?` · ${esc(item.category)}`:''}</small></div><div class="v48-actions"><button class="chip" data-recurring-reject="${esc(item.review_key)}">Rejeter</button><button class="chip active" data-recurring-accept="${esc(item.review_key)}">Accepter</button></div></article>`).join('')||'<div class="empty-state">Aucune nouvelle récurrence à valider.</div>'}</div>`;bindRecurring();}catch(e){b.innerHTML=`<div class="notice">Suggestions indisponibles : ${esc(e.message)}</div>`;}
  }

  function bindRecurring(){
    body()?.querySelectorAll('[data-recurring-reject]').forEach(btn=>btn.addEventListener('click',()=>decideRecurring(btn.dataset.recurringReject,'reject')));
    body()?.querySelectorAll('[data-recurring-accept]').forEach(btn=>btn.addEventListener('click',()=>decideRecurring(btn.dataset.recurringAccept,'accept')));
  }

  async function decideRecurring(key,action){
    await api('/api/v4.8/recurring-review/decision',{method:'POST',body:JSON.stringify({key,action})});
    openRecurring();refresh();
  }

  async function refresh(){
    if(busy)return;const root=document.querySelector('[data-screen="movements"]');if(!root||!root.classList.contains('active'))return;const toolbar=root.querySelector('.toolbar');if(!toolbar)return;
    busy=true;try{const [quality,recurring]=await Promise.all([api('/api/v4.8/quality-workbench'),api('/api/v4.8/recurring-review')]);document.getElementById(ID)?.remove();toolbar.insertAdjacentHTML('afterend',`<section id="${ID}" class="v48-workbench"><div class="v48-quality-summary"><div><strong>Qualité des données</strong><small>${quality.uncategorized} à catégoriser · ${quality.unmatched_transfers} transfert(s) non apparié(s) · ${recurring.count} récurrence(s) à valider</small></div><span>${quality.uncategorized+quality.unmatched_transfers+recurring.count}</span></div><div class="v48-workbench-actions"><button class="btn secondary" id="v48BulkBtn">Catégoriser en masse</button><button class="btn secondary" id="v48RecurringBtn">Revoir les récurrences</button></div></section>`);document.getElementById('v48BulkBtn')?.addEventListener('click',openBulk);document.getElementById('v48RecurringBtn')?.addEventListener('click',openRecurring);}catch(_){/* keep movements usable */}finally{busy=false;}
  }

  const observer=new MutationObserver(()=>queueMicrotask(refresh));
  const start=()=>{const root=document.querySelector('[data-screen="movements"]');if(root)observer.observe(root,{childList:true,subtree:false});document.querySelectorAll('[data-nav="movements"]').forEach(b=>b.addEventListener('click',()=>setTimeout(refresh,80)));refresh();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
