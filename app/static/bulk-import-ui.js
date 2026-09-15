(()=>{
  let activeBatch=null;
  const euroLocal=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR'}).format((c||0)/100);
  const apiBulk=async(url,opts={})=>{const r=await fetch(url,opts);if(!r.ok)throw new Error((await r.text())||r.status);return r.json()};
  const escBulk=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML};

  function ensureBulkUi(){
    if(document.querySelector('#bulkImportPanel'))return;
    const panel=document.querySelector('.import-panel');
    if(!panel)return;
    const block=document.createElement('section');
    block.id='bulkImportPanel';
    block.className='bulk-import-block';
    block.innerHTML=`
      <div class="bulk-heading"><div><p class="section-kicker">Import en masse</p><h3>Relevés + fiches de paie</h3></div><span class="bulk-safe">Staging sécurisé</span></div>
      <p class="muted bulk-copy">Sélectionne jusqu'à 100 fichiers PDF/CSV. Flow analyse tout le lot sans modifier tes calculs avant validation.</p>
      <form id="bulkImportForm" class="bulk-form">
        <select id="bulkImportAccount" name="account" aria-label="Compte bancaire"></select>
        <label class="bulk-drop"><input id="bulkFiles" type="file" accept=".pdf,.csv,application/pdf,text/csv" multiple required><span>Choisir plusieurs fichiers</span><small id="bulkSelection">Aucun fichier sélectionné</small></label>
        <button type="submit" class="primary">Analyser le lot</button>
      </form>
      <div id="bulkStatus" class="import-status">Aucune donnée ne sera écrite avant validation.</div>
      <div id="bulkReview" class="bulk-review"></div>`;
    const history=panel.querySelector('#importHistory')?.parentElement;
    panel.insertBefore(block,history||panel.firstChild);
    bindBulkUi();
    populateBulkAccounts();
  }

  async function populateBulkAccounts(){
    const select=document.querySelector('#bulkImportAccount');if(!select)return;
    const accounts=await apiBulk('/api/accounts');
    const current=accounts.filter(a=>a.kind==='checking');
    select.innerHTML=(current.length?current:accounts).map(a=>`<option value="${a.id}">${escBulk(a.name)}</option>`).join('');
  }

  function moneySummary(doc){
    const s=doc.summary||{};
    if(doc.document_type==='statement')return `${s.transactions||0} opérations · ${euroLocal(s.debit_total_cents||0)} débit · ${euroLocal(s.credit_total_cents||0)} crédit`;
    if(doc.document_type==='payroll')return `Net payé ${s.net_paid_cents==null?'non détecté':euroLocal(s.net_paid_cents)} · Brut ${s.gross_cents==null?'non détecté':euroLocal(s.gross_cents)}`;
    return 'Document non exploitable automatiquement';
  }

  function docLabel(type){return {statement:'Relevé bancaire',payroll:'Fiche de paie',unknown:'Inconnu',duplicate:'Doublon'}[type]||type}

  function preflightLabel(issue){
    if(issue.type==='period_gap')return `Période manquante du ${issue.missing_start} au ${issue.missing_end}`;
    if(issue.type==='period_overlap')return `Chevauchement entre ${issue.after_file} et ${issue.before_file}`;
    if(issue.type==='balance_discontinuity')return `Écart de solde entre ${issue.after_file} et ${issue.before_file} : ${euroLocal(issue.difference_cents)}`;
    if(issue.type==='parse_error')return `${issue.file} : ${issue.detail}`;
    return issue.type||'Contrôle à vérifier';
  }

  function renderPreflight(preflight){
    if(!preflight)return '';
    const tone=preflight.can_commit?(preflight.requires_confirmation?'has-warning':''):'has-warning';
    const title=preflight.can_commit
      ?(preflight.requires_confirmation?'Continuité à confirmer':'Continuité des relevés validée')
      :'Validation bloquée';
    const issues=(preflight.issues||[]).map(issue=>`<li><strong>${issue.severity==='blocking'?'Bloquant':'Attention'}</strong> · ${escBulk(preflightLabel(issue))}</li>`).join('');
    return `<section class="bulk-doc ${tone}" aria-live="polite"><div class="bulk-doc-main"><span class="bulk-type">Contrôle de continuité</span><strong>${title}</strong><small>${preflight.statement_count||0} relevé(s) · ${preflight.coverage_start||'début inconnu'} au ${preflight.coverage_end||'fin inconnue'}</small>${issues?`<ul class="bulk-warning">${issues}</ul>`:''}</div></section>`;
  }

  function renderBatch(data){
    activeBatch=data.batch_id||data.batch?.id||activeBatch;
    const docs=data.documents||[];
    const counts=data.counts||{
      statement:docs.filter(d=>d.document_type==='statement').length,
      payroll:docs.filter(d=>d.document_type==='payroll').length,
      unknown:docs.filter(d=>d.document_type==='unknown').length,
      warning:docs.filter(d=>d.status==='warning'||d.warning).length,
    };
    const preflight=data.preflight||null;
    const root=document.querySelector('#bulkReview');
    root.innerHTML=`
      <div class="bulk-summary">
        <span><strong>${docs.length}</strong> fichiers</span><span><strong>${counts.statement||0}</strong> relevés</span><span><strong>${counts.payroll||0}</strong> paies</span><span class="${(counts.warning||0)>0?'warn':''}"><strong>${counts.warning||0}</strong> alertes</span>
      </div>
      ${renderPreflight(preflight)}
      <div class="bulk-documents">${docs.map(doc=>`<article class="bulk-doc ${doc.warning?'has-warning':''}"><div class="bulk-doc-main"><span class="bulk-type">${docLabel(doc.document_type)}</span><strong>${escBulk(doc.filename)}</strong><small>${doc.period?escBulk(doc.period):'Période non détectée'} · ${moneySummary(doc)}</small>${doc.warning?`<small class="bulk-warning">${escBulk(doc.warning)}</small>`:''}</div><span class="bulk-state">${doc.status==='ready'?'Prêt':doc.status==='committed'?'Importé':doc.status==='duplicate'?'Doublon':'À vérifier'}</span></article>`).join('')}</div>
      <div class="bulk-actions"><button id="bulkDiscard" class="ghost">Abandonner</button><button id="bulkCommit" class="primary" ${docs.some(d=>d.document_type==='statement'||(d.document_type==='payroll'&&d.status==='ready'))&&preflight?.can_commit!==false?'':'disabled'}>Valider le lot</button></div>`;
    document.querySelector('#bulkCommit')?.addEventListener('click',commitBatch);
    document.querySelector('#bulkDiscard')?.addEventListener('click',discardBatch);
  }

  async function analyzeBatch(e){
    e.preventDefault();
    const form=e.currentTarget,files=form.querySelector('#bulkFiles').files,status=document.querySelector('#bulkStatus'),button=form.querySelector('button[type=submit]');
    if(!files.length)return;
    const body=new FormData();body.append('account_id',form.elements.account.value);[...files].forEach(file=>body.append('files',file));
    button.disabled=true;status.textContent=`Analyse de ${files.length} fichier${files.length>1?'s':''}…`;
    try{const data=await apiBulk('/api/imports/bulk/analyze',{method:'POST',body});activeBatch=data.batch_id;renderBatch(data);status.textContent='Analyse terminée. Vérifie les alertes puis valide le lot.'}
    catch(err){status.textContent=`Analyse impossible : ${err.message}`}
    finally{button.disabled=false}
  }

  async function commitBatch(){
    if(!activeBatch)return;
    const button=document.querySelector('#bulkCommit'),status=document.querySelector('#bulkStatus');button.disabled=true;status.textContent='Validation du lot…';
    try{const result=await apiBulk(`/api/imports/bulk/${activeBatch}/commit`,{method:'POST'});status.textContent=`Import terminé · ${result.statements} relevé(s) · ${result.payrolls} fiche(s) de paie · ${result.transactions} transaction(s) · ${result.duplicates} doublon(s)${result.warnings_skipped?` · ${result.warnings_skipped} document(s) ignoré(s)`:''}`;const data=await apiBulk(`/api/imports/bulk/${activeBatch}`);renderBatch(data);await Promise.allSettled([window.loadAll?.(),window.populateImportUi?.()])}
    catch(err){status.textContent=`Validation impossible : ${err.message}`;button.disabled=false}
  }

  async function discardBatch(){
    if(!activeBatch)return;
    const status=document.querySelector('#bulkStatus');
    try{await apiBulk(`/api/imports/bulk/${activeBatch}`,{method:'DELETE'});activeBatch=null;document.querySelector('#bulkReview').innerHTML='';document.querySelector('#bulkImportForm').reset();document.querySelector('#bulkSelection').textContent='Aucun fichier sélectionné';status.textContent='Lot abandonné. Aucune donnée n’a été importée.'}
    catch(err){status.textContent=`Abandon impossible : ${err.message}`}
  }

  function bindBulkUi(){
    document.querySelector('#bulkImportForm')?.addEventListener('submit',analyzeBatch);
    document.querySelector('#bulkFiles')?.addEventListener('change',e=>{const files=[...e.target.files],label=document.querySelector('#bulkSelection');label.textContent=files.length?`${files.length} fichier${files.length>1?'s':''} · ${files.slice(0,3).map(f=>f.name).join(', ')}${files.length>3?'…':''}`:'Aucun fichier sélectionné'});
  }

  const boot=()=>{ensureBulkUi();setTimeout(ensureBulkUi,500)};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
