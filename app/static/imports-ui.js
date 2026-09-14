const importApi=async(url,opts={})=>{const r=await fetch(url,opts);if(!r.ok)throw new Error((await r.text())||r.status);return r.json()};
let importCategories=[];

function attrEsc(value){return String(value??'').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll("'",'&#39;').replaceAll('<','&lt;').replaceAll('>','&gt;')}
function pct(n,d){return d?`${Math.round((n/d)*100)}%`:'—'}
function qualityLabel(v){return {ok:'Cohérent',review:'À vérifier',warning:'Alerte',unverified:'Non contrôlé'}[v]||v||'—'}

async function populateImportUi(){
  const [acc,cats]=await Promise.all([importApi('/api/accounts'),importApi('/api/categories')]);
  importCategories=cats;
  const select=document.querySelector('#importAccount');
  if(select)select.innerHTML=acc.map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('');
  await Promise.all([loadImportInbox(),loadImportHistory(),loadRecurringSuggestions()]);
}

async function loadImportHistory(){
  const root=document.querySelector('#importHistory');if(!root)return;
  const rows=await importApi('/api/imports?limit=5');
  root.innerHTML=rows.length?rows.map(r=>{
    const period=r.period_start&&r.period_end?`${shortDate(r.period_start)} → ${shortDate(r.period_end)}`:'Période inconnue';
    const rate=pct(r.auto_classified_rows,r.imported_rows);
    return `<div class="import-history-row"><div><strong>${esc(r.filename)}</strong><small>${esc(r.account_name)} · ${esc(r.source_type.toUpperCase())} · ${period}</small><small>${qualityLabel(r.quality_status)} · auto ${rate}${r.quality_message?` · ${esc(r.quality_message)}`:''}</small></div><div class="import-counts"><span>${r.imported_rows} importées</span><span>${r.duplicate_rows} doublons</span><span>${r.review_rows} à revoir</span><span>${euro(r.debit_total_cents||0)} débit</span><span>${euro(r.credit_total_cents||0)} crédit</span></div>${r.error_message?`<small class="import-error">${esc(r.error_message)}</small>`:''}</div>`;
  }).join(''):'<div class="empty">Aucun import.</div>';
}

async function loadImportInbox(){
  const root=document.querySelector('#importInbox');if(!root)return;
  const rows=await importApi('/api/imports/inbox?limit=100');
  document.querySelector('#inboxCount').textContent=rows.length?`${rows.length} à revoir`:'À jour';
  root.innerHTML=rows.length?rows.map(r=>{
    const options='<option value="">Choisir une catégorie</option>'+importCategories.map(c=>`<option value="${attrEsc(c.name)}">${esc(c.name)}</option>`).join('');
    return `<article class="review-card" data-review-id="${r.id}" data-normalized="${attrEsc(r.normalized_label)}"><div class="review-head"><div><time>${shortDate(r.booking_date)}</time><strong>${esc(r.label)}</strong><small>${esc(r.account_name)}</small></div><div class="value ${r.amount_cents>0?'positive':''}">${r.amount_cents>0?'+':''}${euro(r.amount_cents)}</div></div><select class="review-category">${options}</select><div class="review-actions"><button class="review-accept">Valider</button><button class="review-rule primary">Valider + règle</button><button class="review-ignore ghost">Ignorer</button></div></article>`;
  }).join(''):'<div class="empty">Aucune opération à vérifier.</div>';
}

async function loadRecurringSuggestions(){
  const root=document.querySelector('#recurringSuggestions');if(!root)return;
  const rows=await importApi('/api/recurring/suggestions');
  document.querySelector('#recurringCount').textContent=rows.length?`${rows.length} suggestion${rows.length>1?'s':''}`:'À jour';
  root.innerHTML=rows.length?rows.map((r,i)=>`<article class="review-card recurring-card" data-recurring-index="${i}" data-recurring='${attrEsc(JSON.stringify(r))}'><div class="review-head"><div><strong>${esc(r.label)}</strong><small>${esc(r.account_name)} · ${r.occurrences} mois · vers le ${r.day_of_month}</small><small>${r.category?esc(r.category)+' · ':''}confiance ${Math.round(r.confidence*100)}%</small></div><div class="value ${r.amount_cents>0?'positive':''}">${r.amount_cents>0?'+':''}${euro(r.amount_cents)}</div></div><div class="import-counts"><span>tolérance ${euro(r.tolerance_cents)}</span><span>${shortDate(r.first_seen)} → ${shortDate(r.last_seen)}</span></div><div class="review-actions recurring-actions"><button class="recurring-accept primary">Ajouter aux prévisions</button></div></article>`).join(''):'<div class="empty">Aucune récurrence suffisamment fiable détectée.</div>';
}

async function handleReview(button,withRule=false){
  const card=button.closest('[data-review-id]'),category=card.querySelector('.review-category').value;
  if(!category){alert('Choisis une catégorie.');return}
  let rulePattern=null;
  if(withRule){rulePattern=prompt('Motif à reconnaître automatiquement à l’avenir',card.dataset.normalized||'');if(rulePattern===null)return;rulePattern=rulePattern.trim();if(!rulePattern){alert('Le motif ne peut pas être vide.');return}}
  button.disabled=true;
  try{const result=await importApi(`/api/imports/inbox/${card.dataset.reviewId}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({category,create_rule:withRule,rule_pattern:rulePattern})});const status=document.querySelector('#importStatus');if(withRule&&result.auto_classified>0)status.textContent=`Règle créée · ${result.auto_classified} autre(s) opération(s) classée(s) automatiquement.`;await Promise.all([loadImportInbox(),loadImportHistory(),loadMovements(document.querySelector('#movementSearch').value),loadRecurringSuggestions()])}catch(e){alert(`Validation impossible : ${e.message}`);button.disabled=false}
}

document.querySelector('#importForm')?.addEventListener('submit',async e=>{e.preventDefault();const form=e.currentTarget,file=form.querySelector('input[type=file]').files[0],status=document.querySelector('#importStatus');if(!file){status.textContent='Choisis un fichier PDF ou CSV.';return}const body=new FormData();body.append('account_id',form.elements.account.value);body.append('file',file);status.textContent='Import en cours…';form.querySelector('button[type=submit]').disabled=true;try{const result=await importApi('/api/imports',{method:'POST',body});const m=result.metadata||{},period=m.period_start&&m.period_end?`${shortDate(m.period_start)} → ${shortDate(m.period_end)}`:'période inconnue';status.textContent=`${result.imported} importées · ${result.duplicates} doublons · ${result.review} à revoir · auto ${pct(result.auto_classified,result.imported)} · ${qualityLabel(result.quality?.status)} · ${period}`;form.reset();await Promise.all([populateImportUi(),refreshCurrent()])}catch(err){status.textContent=`Import impossible : ${err.message}`;await loadImportHistory().catch(()=>{})}finally{form.querySelector('button[type=submit]').disabled=false}});

document.querySelector('#importInbox')?.addEventListener('click',async e=>{const accept=e.target.closest('.review-accept'),rule=e.target.closest('.review-rule'),ignore=e.target.closest('.review-ignore');if(accept)return handleReview(accept,false);if(rule)return handleReview(rule,true);if(ignore){const card=ignore.closest('[data-review-id]');ignore.disabled=true;try{await importApi(`/api/imports/inbox/${card.dataset.reviewId}/ignore`,{method:'POST'});await Promise.all([loadImportInbox(),loadImportHistory()])}catch(err){alert(err.message);ignore.disabled=false}}});

document.querySelector('#recurringSuggestions')?.addEventListener('click',async e=>{const button=e.target.closest('.recurring-accept');if(!button)return;const card=button.closest('[data-recurring]');const data=JSON.parse(card.dataset.recurring);button.disabled=true;try{await importApi('/api/recurring/suggestions/accept',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account_id:data.account_id,label:data.label,amount_cents:data.amount_cents,day_of_month:data.day_of_month,category:data.category,tolerance_cents:data.tolerance_cents,certainty:'expected'})});document.querySelector('#importStatus').textContent=`Récurrence ajoutée : ${data.label}`;await Promise.all([loadRecurringSuggestions(),loadV05Dashboard()])}catch(err){alert(`Ajout impossible : ${err.message}`);button.disabled=false}});

const originalTab=tab;
tab=function(name){originalTab(name);if(name==='movements')populateImportUi().catch(()=>{})};
populateImportUi().catch(()=>{});

// V0.5 projection cockpit. The legacy endpoints remain available for compatibility,
// but the UI uses the snapshot-safe ledger and the projection-v2 API.
let v05ProjectionMode='realistic';

function ensureProjectionSwitch(){
  if(document.querySelector('#forecastMode'))return;
  const hero=document.querySelector('.hero');if(!hero)return;
  const select=document.createElement('select');select.id='forecastMode';select.className='forecast-mode';select.innerHTML='<option value="realistic">Projection réaliste</option><option value="committed">Projection engagée</option>';
  select.addEventListener('change',()=>{v05ProjectionMode=select.value;renderV05Home()});
  hero.insertBefore(select,document.querySelector('#why'));
}

function renderV05Why(x){
  const rows=[['Solde actuel',x.current_balance_cents],['Engagements prévus',-x.planned_outflows_cents],['Allocations indisponibles',-(x.allocated_cents||0)],['Réserve de sécurité',-x.reserve_cents],['Point bas avant réserve',x.low_point_before_reserve_cents],['Disponible sans risque',x.available_cents]];
  document.querySelector('#explainRows').innerHTML=rows.map((r,i)=>`<div class="why-row ${i===rows.length-1?'total':''}"><span>${r[0]}</span><strong>${euro(r[1])}</strong></div>`).join('');
}

function renderV05Home(){
  const d=dashboard;if(!d)return;
  const f=d.projections?.[v05ProjectionMode]||d.forecast;if(!f)return;
  ensureProjectionSwitch();
  document.querySelector('#today').textContent=new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'long'}).format(new Date(`${d.as_of}T12:00:00`));
  document.querySelector('#safe').textContent=euro(f.safe_to_spend_cents);
  document.querySelector('#daily').textContent=`${euro(f.daily_budget_cents)} / jour jusqu'au ${shortDate(f.horizon)} · ${v05ProjectionMode==='realistic'?'réaliste':'engagée'}`;
  document.querySelector('#balance').textContent=euro(f.opening_balance_cents);document.querySelector('#low').textContent=euro(f.low_point.balance_cents);document.querySelector('#lowDate').textContent=shortDate(f.low_point.date);document.querySelector('#committed').textContent=euro(f.commitments_cents);document.querySelector('#spent').textContent=euro(d.month.spent_cents);document.querySelector('#horizon').textContent=`jusqu'au ${shortDate(f.horizon)}`;
  renderEvents('#events',f.events);renderChart(f.timeline);renderV05Why(f.explanation);
}

async function loadV05Dashboard(){
  dashboard=await api('/api/dashboard-v2');renderV05Home();return dashboard;
}

loadBase=async function(){[dashboard,accounts,categories]=await Promise.all([api('/api/dashboard-v2'),api('/api/accounts'),api('/api/categories')]);renderV05Home();fillSelects()};
renderHome=renderV05Home;

const txFormV05=document.querySelector('#transactionForm');
txFormV05?.addEventListener('submit',async e=>{e.preventDefault();e.stopImmediatePropagation();const f=new FormData(txFormV05);await api('/api/ledger/transactions',{method:'POST',body:JSON.stringify({account_id:Number(f.get('account')),booking_date:f.get('date'),amount_cents:cents(f.get('amount')),label:f.get('label'),category:f.get('category')||null})});txFormV05.reset();await refreshCurrent()},true);

const simFormV05=document.querySelector('#simulationForm');
simFormV05?.addEventListener('submit',async e=>{e.preventDefault();e.stopImmediatePropagation();const f=new FormData(simFormV05),d=await api('/api/simulations-v2',{method:'POST',body:JSON.stringify({amount_cents:-Math.abs(cents(f.get('amount'))),due_date:f.get('date'),label:f.get('label')||'Simulation'})});document.querySelector('#simulationResult').textContent=`Impact sur le disponible : ${euro(d.impact.safe_to_spend_delta_cents)} · nouveau disponible ${euro(d.simulated.safe_to_spend_cents)}`},true);

loadV05Dashboard().catch(()=>{});
