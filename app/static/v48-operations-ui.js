(()=>{
  const ID='v48QualityWorkbench';
  let busy=false;
  let activeHistoryBatch=null;
  let activeHistoryPreflight=null;
  let lastHistoryQuality=null;
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML.replaceAll('"','&quot;').replaceAll("'",'&#39;');};
  const api=async(url,options={})=>{const headers=options.body instanceof FormData?{}:{'Content-Type':'application/json'};const r=await fetch(url,{cache:'no-store',...options,headers:{...headers,...(options.headers||{})}});if(!r.ok)throw new Error((await r.text())||`HTTP ${r.status}`);return r.json();};

  function dialog(){return document.getElementById('editDialog');}
  function body(){return document.getElementById('editBody');}

  async function openBulk(pattern='',suggestedCategory=''){
    const d=dialog(),b=body();if(!d||!b)return;d.showModal();b.innerHTML='<div class="skeleton tall"></div>';
    try{
      const [categories,accounts]=await Promise.all([api('/api/categories'),api('/api/accounts')]);
      b.innerHTML=`<form id="v48BulkForm" class="stack"><p class="eyebrow">Traitement groupé</p><h3>Catégoriser plusieurs mouvements</h3><p class="subtle">Flow affiche d’abord un aperçu. Rien n’est modifié avant ta confirmation.</p><label class="form-label">Motif à rechercher<input class="field" name="pattern" minlength="2" required placeholder="ex. MONOPRIX" value="${esc(pattern)}"></label><label class="form-label">Catégorie<select class="field" name="category" required><option value="">Choisir</option>${categories.map(c=>`<option ${c.name===suggestedCategory?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label><label class="form-label">Compte<select class="field" name="account_id"><option value="">Tous les comptes</option>${accounts.map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select></label><label class="toggle-row"><span><strong>Seulement les non catégorisés</strong><small>Évite d’écraser des corrections déjà faites.</small></span><input type="checkbox" name="only_uncategorized" checked></label><label class="toggle-row"><span><strong>Créer une règle</strong><small>Les prochains mouvements correspondants seront classés automatiquement.</small></span><input type="checkbox" name="create_rule" checked></label><button class="btn primary">Prévisualiser</button><div id="v48Preview"></div></form>`;
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

  const priorityLabel=value=>({critical:'Critique',high:'Haute',medium:'Moyenne',low:'Faible'})[value]||'À vérifier';

  function openHistoryQuality(){
    const d=dialog(),b=body(),data=lastHistoryQuality;if(!d||!b||!data)return;
    d.showModal();
    const rows=(data.actions||[]).map((action,index)=>`<article class="v48-history-action"><span class="v48-history-rank">${index+1}</span><div><div class="v48-history-title"><strong>${esc(action.title)}</strong><span class="chip ${action.priority==='critical'||action.priority==='high'?'warning':''}">${esc(priorityLabel(action.priority))}</span></div><p>${esc(action.detail)}</p><small>Preuve : ${esc(action.evidence||'Indisponible')}</small>${action.expected_document?`<small>Document attendu : ${esc(action.expected_document)}</small>`:''}<small>${esc(action.impact)}</small></div></article>`).join('');
    const canImport=(data.actions||[]).some(action=>action.target==='bulk_import');
    b.innerHTML=`<div class="stack"><p class="eyebrow">Historique</p><h3>Plan de fiabilisation</h3><p class="subtle">${data.open_count||0} action(s), dont ${data.blocking_count||0} bloquante(s). Ordre calculé depuis la couverture documentaire. Aucune correction n'est exécutée automatiquement.</p><div class="v48-history-summary"><div><span>Score</span><strong>${data.score??'—'}/100</strong></div><div><span>Critiques</span><strong>${data.counts?.critical||0}</strong></div><div><span>Hautes</span><strong>${data.counts?.high||0}</strong></div><div><span>Autres</span><strong>${(data.counts?.medium||0)+(data.counts?.low||0)}</strong></div></div><div class="v48-history-list">${rows||'<div class="empty-state">Aucune action historique prioritaire.</div>'}</div>${canImport?'<button class="btn primary" id="v48HistoryImport">Analyser les documents manquants</button>':''}<p class="subtle">Lecture seule jusqu'à la prévisualisation et à la validation explicite d'un lot.</p></div>`;
    document.getElementById('v48HistoryImport')?.addEventListener('click',openHistoryImport);
  }

  async function openHistoryImport(){
    const b=body();if(!b)return;b.innerHTML='<div class="skeleton tall"></div>';
    try{
      const accounts=await api('/api/accounts'),preferred=accounts.filter(account=>account.kind==='checking'),choices=preferred.length?preferred:accounts;
      b.innerHTML=`<form id="v48HistoryImportForm" class="stack"><p class="eyebrow">Import historique</p><h3>Analyser les documents manquants</h3><p class="subtle">Les PDF et CSV restent en staging. Rien n'est écrit avant la validation explicite du lot.</p><label class="form-label">Compte<select class="field" name="account_id" required>${choices.map(account=>`<option value="${account.id}">${esc(account.name)}</option>`).join('')}</select></label><label class="form-label">Documents<input class="field" name="files" type="file" accept=".pdf,.csv,application/pdf,text/csv" multiple required></label><button class="btn primary">Analyser le lot</button><div id="v48HistoryImportStatus" class="notice">Aucune écriture avant validation.</div><div id="v48HistoryImportReview"></div></form>`;
      document.getElementById('v48HistoryImportForm')?.addEventListener('submit',analyzeHistoryImport);
    }catch(error){b.innerHTML=`<div class="notice">Import indisponible : ${esc(error.message)}</div>`;}
  }

  async function analyzeHistoryImport(event){
    event.preventDefault();const form=event.currentTarget,status=document.getElementById('v48HistoryImportStatus'),review=document.getElementById('v48HistoryImportReview');
    const files=[...form.elements.files.files];if(!files.length)return;
    const payload=new FormData();payload.append('account_id',form.elements.account_id.value);files.forEach(file=>payload.append('files',file));
    status.textContent=`Analyse de ${files.length} fichier(s)…`;review.innerHTML='<div class="skeleton"></div>';
    try{const data=await api('/api/imports/bulk/analyze',{method:'POST',body:payload});activeHistoryBatch=data.batch_id;renderHistoryBatch(data);status.textContent='Analyse terminée. Vérifie les alertes avant validation.';}catch(error){status.textContent=`Analyse impossible : ${error.message}`;review.innerHTML='';}
  }

  function historyPreflightLabel(issue){
    if(issue.type==='period_gap')return `Période manquante du ${issue.missing_start} au ${issue.missing_end}`;
    if(issue.type==='period_overlap')return `Chevauchement entre ${issue.after_file} et ${issue.before_file}`;
    if(issue.type==='balance_discontinuity')return `Écart de solde entre ${issue.after_file} et ${issue.before_file} : ${euro(issue.difference_cents)}`;
    if(issue.type==='parse_error')return `${issue.file} : ${issue.detail}`;
    return issue.type||'Contrôle à vérifier';
  }

  function renderHistoryPreflight(preflight){
    if(!preflight)return '<div class="v48-history-preflight blocked">Contrôle de continuité indisponible. Validation bloquée.</div>';
    const title=preflight.can_commit?(preflight.requires_confirmation?'Historique incomplet à confirmer':'Continuité des relevés validée'):'Validation bloquée';
    const issues=(preflight.issues||[]).map(issue=>`<li><strong>${issue.severity==='blocking'?'Bloquant':'Attention'}</strong> · ${esc(historyPreflightLabel(issue))}</li>`).join('');
    return `<section class="v48-history-preflight ${preflight.can_commit?(preflight.requires_confirmation?'warning':'ready'):'blocked'}"><strong>${title}</strong><small>${preflight.statement_count||0} relevé(s) · ${preflight.coverage_start||'début inconnu'} au ${preflight.coverage_end||'fin inconnue'}</small>${issues?`<ul class="bulk-warning">${issues}</ul>`:''}</section>`;
  }

  function renderHistoryBatch(data){
    const review=document.getElementById('v48HistoryImportReview');if(!review)return;
    const documents=data.documents||[],preflight=data.preflight||null;activeHistoryPreflight=preflight;
    const canCommit=Boolean(preflight?.can_commit)&&documents.some(document=>document.document_type==='statement'||(document.document_type==='payroll'&&document.status==='ready'));
    const commitLabel=preflight?.requires_confirmation?'Confirmer et importer':'Valider le lot';
    review.innerHTML=`${renderHistoryPreflight(preflight)}<div class="v48-history-documents">${documents.map(document=>`<div class="v48-history-document"><div><strong>${esc(document.filename)}</strong><small>${esc(document.period||'Période non détectée')}${document.warning?` · ${esc(document.warning)}`:''}</small></div><span class="chip ${document.warning?'warning':'active'}">${esc(document.document_type||'inconnu')}</span></div>`).join('')}</div><div class="toolbar"><button class="btn secondary" type="button" id="v48HistoryDiscard">Abandonner</button><button class="btn primary" type="button" id="v48HistoryCommit" ${canCommit?'':'disabled'}>${commitLabel}</button></div>`;
    document.getElementById('v48HistoryDiscard')?.addEventListener('click',discardHistoryBatch);
    document.getElementById('v48HistoryCommit')?.addEventListener('click',commitHistoryBatch);
  }

  async function commitHistoryBatch(){
    if(!activeHistoryBatch)return;const status=document.getElementById('v48HistoryImportStatus');
    try{const confirmation=activeHistoryPreflight?.requires_confirmation?'?confirm_warnings=true':'';const result=await api(`/api/imports/bulk/${activeHistoryBatch}/commit${confirmation}`,{method:'POST'});status.textContent=`Import terminé : ${result.statements||0} relevé(s), ${result.payrolls||0} fiche(s), ${result.transactions||0} mouvement(s).`;activeHistoryBatch=null;activeHistoryPreflight=null;setTimeout(()=>{dialog()?.close();refresh();},900);}catch(error){status.textContent=`Validation impossible : ${error.message}`;}
  }

  async function discardHistoryBatch(){
    if(!activeHistoryBatch)return;const status=document.getElementById('v48HistoryImportStatus');
    try{await api(`/api/imports/bulk/${activeHistoryBatch}`,{method:'DELETE'});activeHistoryBatch=null;activeHistoryPreflight=null;status.textContent='Lot abandonné. Aucune donnée importée.';document.getElementById('v48HistoryImportReview').innerHTML='';}catch(error){status.textContent=`Abandon impossible : ${error.message}`;}
  }

  async function refresh(){
    if(busy)return;const root=document.querySelector('[data-screen="movements"]');if(!root||!root.classList.contains('active'))return;const toolbar=root.querySelector('.movement-controls-v7');if(!toolbar)return;
    busy=true;
    try{
      const results=await Promise.allSettled([api('/api/v4.8/quality-workbench'),api('/api/v4.8/recurring-review'),api('/api/v3.7/data-intelligence?limit=250'),api('/api/v5.7/data-quality-actions?months=24')]);
      const quality=results[0].status==='fulfilled'?results[0].value:{uncategorized:'?',unmatched_transfers:'?'};
      const recurring=results[1].status==='fulfilled'?results[1].value:{count:'?'};
      const suggestions=(results[2].status==='fulfilled'?(results[2].value.merchant_suggestions||[]):[]).filter(item=>!item.confirmed).slice(0,3);
      lastHistoryQuality=results[3].status==='fulfilled'?results[3].value:null;
      if(!toolbar.isConnected||!root.classList.contains('active'))return;
      document.getElementById(ID)?.remove();
      toolbar.insertAdjacentHTML('afterend',`<section id="${ID}" class="v48-workbench"><div class="v48-quality-summary"><div><strong>Qualité des données</strong><small>${quality.uncategorized} à catégoriser · ${quality.unmatched_transfers} transfert(s) non apparié(s) · ${recurring.count} récurrence(s) à valider · ${lastHistoryQuality?.open_count??'?'} action(s) historique(s)</small></div><span>${results[0].status==='fulfilled'&&results[1].status==='fulfilled'?quality.uncategorized+quality.unmatched_transfers+recurring.count:'Indisponible'}</span></div>${suggestions.length?`<div class="v48-merchant-suggestions"><small>Groupes repérés</small>${suggestions.map(item=>`<button type="button" class="chip" data-v48-pattern="${esc(item.normalized_key)}" data-v48-category="${esc(item.suggested_category||'')}">${esc(item.canonical_name)} · ${item.occurrences}${item.suggested_category?` · ${esc(item.suggested_category)}`:''}</button>`).join('')}</div>`:''}<div class="v48-workbench-actions"><button class="btn secondary" id="v48UncategorizedBtn">Afficher à classer</button><button class="btn secondary" id="v48BulkBtn">Catégoriser en masse</button><button class="btn secondary" id="v48RecurringBtn">Revoir les récurrences</button><button class="btn secondary" id="v48HistoryBtn" ${lastHistoryQuality?'':'disabled'}>Fiabiliser l'historique${lastHistoryQuality?` (${lastHistoryQuality.open_count||0})`:''}</button></div></section>`);
      document.getElementById('v48UncategorizedBtn')?.addEventListener('click',()=>root.querySelector('[data-filter="uncategorized"]')?.click());
      document.getElementById('v48BulkBtn')?.addEventListener('click',()=>openBulk());
      document.getElementById('v48RecurringBtn')?.addEventListener('click',openRecurring);
      document.getElementById('v48HistoryBtn')?.addEventListener('click',openHistoryQuality);
      root.querySelectorAll('[data-v48-pattern]').forEach(button=>button.addEventListener('click',()=>openBulk(button.dataset.v48Pattern,button.dataset.v48Category)));
    }catch(_){/* keep movements usable */}
    finally{busy=false;if(!toolbar.isConnected)queueMicrotask(refresh);}
  }

  const observer=new MutationObserver(records=>{if(records.some(record=>[...record.addedNodes,...record.removedNodes].some(node=>node.id!==ID)))queueMicrotask(refresh);});
  const start=()=>{const root=document.querySelector('[data-screen="movements"]');if(root)observer.observe(root,{childList:true,subtree:false});document.querySelectorAll('[data-nav="movements"]').forEach(b=>b.addEventListener('click',()=>setTimeout(refresh,80)));refresh();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
