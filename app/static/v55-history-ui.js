(()=>{
  const ID='v55HistoryCoverage';
  let activeBatch=null;
  let refreshing=false;
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML;};
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const api=async(url,options={})=>{const headers=options.body instanceof FormData?{}:{'Content-Type':'application/json'};const r=await fetch(url,{cache:'no-store',...options,headers:{...headers,...(options.headers||{})}});if(!r.ok)throw new Error((await r.text())||`HTTP ${r.status}`);return r.status===204?null:r.json();};

  function editDialog(){return document.getElementById('editDialog');}
  function editBody(){return document.getElementById('editBody');}
  function periodPills(periods,klass='warn'){return (periods||[]).slice(-12).map(p=>`<span class="v55-period ${klass}">${esc(p)}</span>`).join('');}
  const readinessLabel=status=>({ready:'Fiable',usable:'Exploitable',limited:'Partiel',insufficient:'Insuffisant'})[status]||'À vérifier';

  async function refresh(){
    if(refreshing)return;
    const root=document.querySelector('[data-screen="movements"]');
    if(!root||!root.classList.contains('active'))return;
    const anchor=document.getElementById('v48QualityWorkbench')||root.querySelector('.toolbar');
    if(!anchor)return;
    refreshing=true;
    try{
      const [data,readiness]=await Promise.all([api('/api/v5.5/history-coverage?months=24'),api('/api/v5.5/history-readiness?months=24')]);
      document.getElementById(ID)?.remove();
      const s=data.summary||{},gates=readiness.gates||{},action=readiness.primary_action;
      anchor.insertAdjacentHTML('afterend',`<section id="${ID}" class="card v55-history"><div class="v55-history-head"><div><p class="eyebrow">Historique</p><h2>Couverture des données</h2><p class="subtle">${esc(data.period_start)} → ${esc(data.period_end)} · lecture seule</p></div><div class="v55-history-actions"><button class="btn secondary" id="v55ImportBtn">Importer plusieurs fichiers</button><button class="btn secondary" id="v55DetailsBtn">Voir les périodes</button></div></div><div class="v55-coverage-grid"><div class="v55-coverage-stat"><span>Relevés</span><strong>${s.statement_coverage_pct??0} %</strong><small>${s.missing_statement_months||0} mois manquant(s)</small></div><div class="v55-coverage-stat"><span>Fiches de paie</span><strong>${s.payroll_coverage_pct??0} %</strong><small>${s.missing_payroll_months||0} mois manquant(s)</small></div><div class="v55-coverage-stat"><span>Mois complets</span><strong>${s.complete_months||0}</strong><small>relevé + paie</small></div><div class="v55-coverage-stat"><span>À revoir</span><strong>${(s.review_months||0)+(s.duplicate_months||0)}</strong><small>revues ou doublons</small></div></div><div class="row"><div><p class="eyebrow">Readiness V5.6</p><strong>${esc(readiness.label)} · ${readiness.score}/100</strong><small>Tendances : ${gates.trends?.ready?'prêtes':'à fiabiliser'} · revenus : ${gates.income_analysis?.ready?'prêts':'partiels'} · prévisions : ${gates.predictive_models?.ready?'prêtes':'prudence'}</small></div><span class="chip ${readiness.status==='ready'||readiness.status==='usable'?'active':'warning'}">${readinessLabel(readiness.status)}</span></div>${action?`<div class="decision-row"><div><strong>Prochaine action : ${esc(action.title)}</strong><small>${esc(action.why||'')} · ${action.count||0} période(s)</small></div></div>`:''}${(data.actions||[]).length?`<div class="stack">${data.actions.slice(0,3).map(a=>`<div class="row"><div><strong>${esc(a.title)}</strong><small>${a.count} période(s)</small></div><span class="chip ${a.priority==='high'?'warning':''}">${esc(a.priority)}</span></div>`).join('')}</div>`:'<div class="empty-state">Historique complet sur la fenêtre analysée.</div>'}<p class="subtle">${esc(readiness.method)}</p></section>`);
      document.getElementById('v55ImportBtn')?.addEventListener('click',openImport);
      document.getElementById('v55DetailsBtn')?.addEventListener('click',()=>openDetails(data,readiness));
    }catch(_){/* keep Movements usable */}
    finally{refreshing=false;}
  }

  function openDetails(data,readiness){
    const d=editDialog(),b=editBody();if(!d||!b)return;d.showModal();
    b.innerHTML=`<div class="stack"><p class="eyebrow">Couverture historique</p><h3>${esc(data.period_start)} → ${esc(data.period_end)}</h3><div><strong>Relevés manquants</strong><div class="v55-periods">${periodPills(data.gaps?.statements)||'<span class="subtle">Aucun</span>'}</div></div><div><strong>Fiches de paie manquantes</strong><div class="v55-periods">${periodPills(data.gaps?.payrolls)||'<span class="subtle">Aucun</span>'}</div></div><div><strong>Périodes à revoir</strong><div class="v55-periods">${periodPills(data.review_periods)||'<span class="subtle">Aucune</span>'}</div></div><div><strong>Périodes complètes</strong><div class="v55-periods">${periodPills(data.complete_periods,'ok')||'<span class="subtle">Aucune</span>'}</div></div><div><strong>Bloqueurs readiness</strong>${(readiness.blockers||[]).map(item=>`<div class="row"><div><strong>${esc(item.title)}</strong><small>${esc(item.detail)}</small></div></div>`).join('')||'<p class="subtle">Aucun bloqueur.</p>'}</div></div>`;
  }

  async function openImport(){
    const d=editDialog(),b=editBody();if(!d||!b)return;d.showModal();b.innerHTML='<div class="skeleton tall"></div>';
    try{
      const accounts=await api('/api/accounts');
      const preferred=accounts.filter(a=>a.kind==='checking');
      const choices=preferred.length?preferred:accounts;
      b.innerHTML=`<form id="v55ImportForm" class="stack"><p class="eyebrow">Import historique</p><h3>Relevés et fiches de paie</h3><p class="subtle">Jusqu'à 100 PDF/CSV. L'analyse reste en staging jusqu'à validation explicite.</p><label class="form-label">Compte<select class="field" name="account_id" required>${choices.map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select></label><label class="form-label">Documents<input class="field" name="files" type="file" accept=".pdf,.csv,application/pdf,text/csv" multiple required></label><button class="btn primary" type="submit">Analyser le lot</button><div id="v55BulkStatus" class="v55-bulk-status">Aucune écriture avant validation.</div><div id="v55BulkReview"></div></form>`;
      document.getElementById('v55ImportForm')?.addEventListener('submit',analyze);
    }catch(e){b.innerHTML=`<div class="notice">Import indisponible : ${esc(e.message)}</div>`;}
  }

  async function analyze(event){
    event.preventDefault();const form=event.currentTarget,status=document.getElementById('v55BulkStatus'),review=document.getElementById('v55BulkReview');
    const files=[...form.elements.files.files];if(!files.length)return;
    const body=new FormData();body.append('account_id',form.elements.account_id.value);files.forEach(file=>body.append('files',file));
    status.textContent=`Analyse de ${files.length} fichier(s)…`;review.innerHTML='<div class="skeleton"></div>';
    try{const data=await api('/api/imports/bulk/analyze',{method:'POST',body});activeBatch=data.batch_id;renderBatch(data);status.textContent='Analyse terminée. Vérifie les alertes avant validation.';}catch(e){status.textContent=`Analyse impossible : ${e.message}`;review.innerHTML='';}
  }

  function renderBatch(data){
    const review=document.getElementById('v55BulkReview');if(!review)return;
    const docs=data.documents||[];review.innerHTML=`<div class="v55-bulk-list">${docs.map(doc=>{const s=doc.summary||{};const detail=doc.document_type==='statement'?`${s.transactions||0} opérations`:doc.document_type==='payroll'?`Net ${s.net_paid_cents==null?'non détecté':euro(s.net_paid_cents)}`:'Document non reconnu';return `<div class="v55-bulk-row"><div><strong>${esc(doc.filename)}</strong><small>${esc(doc.period||'Période non détectée')} · ${esc(detail)}${doc.warning?` · ${esc(doc.warning)}`:''}</small></div><span class="chip ${doc.warning?'warning':'active'}">${esc(doc.document_type)}</span></div>`;}).join('')}</div><div class="toolbar"><button class="btn secondary" type="button" id="v55Discard">Abandonner</button><button class="btn primary" type="button" id="v55Commit">Valider le lot</button></div>`;
    document.getElementById('v55Discard')?.addEventListener('click',discard);
    document.getElementById('v55Commit')?.addEventListener('click',commit);
  }

  async function commit(){if(!activeBatch)return;const status=document.getElementById('v55BulkStatus');status.textContent='Validation du lot…';try{const result=await api(`/api/imports/bulk/${activeBatch}/commit`,{method:'POST'});status.textContent=`Import terminé · ${result.statements||0} relevé(s) · ${result.payrolls||0} fiche(s) · ${result.transactions||0} transaction(s).`;activeBatch=null;setTimeout(()=>{editDialog()?.close();refresh();},900);}catch(e){status.textContent=`Validation impossible : ${e.message}`;}}
  async function discard(){if(!activeBatch)return;const status=document.getElementById('v55BulkStatus');try{await api(`/api/imports/bulk/${activeBatch}`,{method:'DELETE'});activeBatch=null;status.textContent='Lot abandonné. Aucune donnée importée.';document.getElementById('v55BulkReview').innerHTML='';}catch(e){status.textContent=`Abandon impossible : ${e.message}`;}}

  const observer=new MutationObserver(()=>queueMicrotask(refresh));
  const start=()=>{const root=document.querySelector('[data-screen="movements"]');if(root)observer.observe(root,{childList:true,subtree:false});document.querySelectorAll('[data-nav="movements"]').forEach(btn=>btn.addEventListener('click',()=>setTimeout(refresh,100)));refresh();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
