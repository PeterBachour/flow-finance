const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/v4-ui.js','utf8');
const context={Intl,Date,URLSearchParams,FormData:class FormData{},document:{readyState:'loading',addEventListener(){},createElement(){return {set textContent(value){this.innerHTML=String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');}};}}};
vm.createContext(context);
vm.runInContext(source.replace("  if(document.readyState==='loading')",'  globalThis.categoryBreakdown=monthlyCategoryBreakdown; globalThis.movementSummary=movementSelectionSummary; globalThis.renderRecurringCard=monthlyRecurringCard; globalThis.renderMonthScreen=renderMonth; globalThis.renderHomeScreen=renderHome; globalThis.renderTrajectoryChart=trajectoryChart; globalThis.renderSpendingTrend=monthlySpendingTrend; globalThis.renderFlowComposition=monthlyFlowComposition; globalThis.goalCard=wealthGoalCard; globalThis.renderWealthScreen=renderWealth; globalThis.renderMovementsScreen=renderMovements; globalThis.flowState=state;\n  if(document.readyState===\'loading\')'),context);
const render=context.renderRecurringCard;
test('loading failure differs from an empty month and allows retry',()=>{
 const unavailable=render(null),empty=render({summary:{},items:[]});
 assert.match(unavailable,/Suivi indisponible/);
 assert.match(unavailable,/retryRecurringStatus/);
 assert.doesNotMatch(unavailable,/Aucune échéance/);
 assert.match(empty,/Aucune échéance régulière prévue/);
 assert.doesNotMatch(empty,/Rapproché/);
});
test('monthly occurrences display all statuses, due and matched dates safely',()=>{
 const html=render({summary:{expected_cents:4500,paid_cents:1000,remaining_cents:3500,overdue_cents:2000},items:[
 {label:'<script>charge</script>',amount_cents:-1000,due_date:'2026-10-01',matched_booking_date:'2026-10-02',status:'paid'},
 {label:'Charge passée',amount_cents:-2000,due_date:'2026-10-03',status:'overdue'},
 {label:'Charge future',amount_cents:-1500,due_date:'2026-10-25',status:'upcoming'}]});
 for(const text of ['Prévu ce mois','Rapproché','Restant attendu','Paiement détecté','À venir','À vérifier','Mouvement :','inclus dans le restant attendu','estimatif'])assert.ok(html.includes(text),text);
 assert.match(html,/&lt;script&gt;/);
 assert.doesNotMatch(html,/<script>/);
 assert.equal((html.match(/class="monthly-recurring-row"/g)||[]).length,3);
 for(const amount of [4500,1000,3500])assert.ok(html.includes(new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format(amount/100)));
});

async function monthScreen(closing){
 const root={innerHTML:'',querySelectorAll(){return [];}};
 context.document.querySelector=selector=>selector==='[data-screen="month"]'?root:{addEventListener(){}};
 context.fetch=async url=>({ok:true,status:200,json:async()=>{
  if(url.startsWith('/api/v2.1/months/'))return {current:{projected_close_cents:closing.closing_balance_cents,income_cents:30000,spent_cents:10000},closing_explanation:closing};
  if(url==='/api/recurring')return [];
  if(url.startsWith('/api/recurring/status'))return {summary:{},items:[]};
  return {};
 }});
 await context.renderMonthScreen();
 return root.innerHTML;
}
test('missing projection stays unavailable instead of becoming zero',async()=>{
 const html=await monthScreen({status:'unavailable',reason:'selected_month_not_current',closing_balance_cents:null});
 assert.match(html,/Indisponible/);
 assert.match(html,/uniquement pour le mois en cours/);
 assert.doesNotMatch(html,/Solde réel de départ|Revenus - dépenses constatées|formula-result/);
});
test('month screen uses engine components instead of inferred adjustment',async()=>{
 const html=await monthScreen({status:'available',as_of:'2026-10-04',target_date:'2026-10-31',opening_balance_cents:100000,expected_income_cents:20000,expected_outflows_cents:5000,variable_spending_cents:1000,closing_balance_cents:114000,assumptions:{realistic_daily_cents:37}});
 for(const text of ['Solde de référence','Revenus attendus','Échéances restantes','Dépenses variables estimées','ne sont pas déduits une seconde fois'])assert.ok(html.includes(text),text);
 assert.doesNotMatch(html,/Échéances et prévisions restantes/);
 assert.doesNotMatch(html.match(/<div class="formula">[\s\S]*?<\/div><p class="subtle">/)?.[0]||'',/Indisponible/);
});

test('spending trend compares current, previous and averages without presenting a partial month as final',()=>{
 const activeMonth=new Date().toISOString().slice(0,7);
 const html=context.renderSpendingTrend({current:{spent_cents:80000},previous:{spent_cents:100000},average_3m:{spent_cents:90000},average_6m:{spent_cents:85000}},activeMonth);
 for(const text of ['Dépenses comparées','Mois précédent','Moyenne 3 mois','Moyenne 6 mois','mouvements importés à ce jour','transferts internes sont exclus'])assert.ok(html.includes(text),text);
 assert.match(html,/vs précédent/);
 assert.match(html,/class="trend-delta subtle"/);
 assert.doesNotMatch(html,/NaN|undefined|Infinity/);
});

test('spending trend explains a historical comparison and tolerates missing values',()=>{
 const html=context.renderSpendingTrend({current:{spent_cents:60000},previous:{spent_cents:null},average_3m:{spent_cents:50000}},'2026-08');
 assert.match(html,/Comparaison fondée sur les mouvements importés/);
 assert.doesNotMatch(html,/vs précédent|NaN|undefined|Infinity/);
});

test('month composition separates consumption, savings and exceptional outflows',()=>{
 const html=context.renderFlowComposition({
  current:{fixed_cents:45000,variable_cents:30000,other_classified_cents:5000,saving_cents:12000,exceptional_cents:8000,unknown_cents:2500,semantic_coverage_pct:96.8},
  previous:{fixed_cents:44000,variable_cents:35000,other_classified_cents:0,saving_cents:10000,exceptional_cents:0}
 },new Date().toISOString().slice(0,7));
 for(const text of ['Comment se répartit le mois','Dépenses fixes','Dépenses variables','Autres dépenses courantes','Épargne','Dépenses exceptionnelles','96,8 % classé','sorties restent à qualifier','ne sont pas ajoutées artificiellement','mois en cours ne contient que les mouvements importés'])assert.ok(html.includes(text),text);
 assert.match(html,/class="subtle">-5/);
 assert.match(html,/class="flow-composition-item saving"[\s\S]*class="subtle">\+/);
 assert.doesNotMatch(html,/NaN|undefined|Infinity/);
});

test('month composition stays explicit when optional buckets are empty',()=>{
 const html=context.renderFlowComposition({current:{fixed_cents:0,variable_cents:0,saving_cents:0,semantic_coverage_pct:100},previous:{}},'2026-08');
 for(const text of ['Dépenses fixes','Dépenses variables','Épargne','100 % classé'])assert.ok(html.includes(text),text);
 assert.doesNotMatch(html,/Autres dépenses courantes|Dépenses exceptionnelles|sorties restent à qualifier|NaN|undefined/);
});

async function homeScreen(payload){
 const root={innerHTML:'',querySelectorAll(){return [];}};
 context.document.querySelector=selector=>selector==='[data-screen="home"]'?root:{addEventListener(){}};
 context.fetch=async url=>({ok:true,status:200,json:async()=>url==='/api/v6/safe-to-spend'?payload:url==='/api/recurring'?[]:{}});
 await context.renderHomeScreen();
 return root.innerHTML;
}
test('unavailable certified balance hides amount formula and simulation',async()=>{
 const html=await homeScreen({availability:{available:false,status:'unavailable_stale_balance'},safe_to_spend:{total_cents:null,calculated_cents:null},components:{current_balance_cents:100000}});
 assert.match(html,/<div class="hero-amount">Indisponible<\/div>/);
 assert.match(html,/trop ancien/);
 assert.doesNotMatch(html,/id="simulatePurchase"|Résultat après réserves/);
});
test('certified components and negative result are distinct from spendable zero',async()=>{
 const html=await homeScreen({availability:{available:true},safe_to_spend:{total_cents:0,calculated_cents:-2500},components:{current_balance_cents:10000,confirmed_commitments_cents:5000,probable_recurring_cents:6000,goal_reservations_cents:1000,safety_reserve_cents:500}});
 assert.match(html,/id="simulatePurchase"/);
 assert.match(html,/Résultat après réserves/);
 assert.match(html,/Il manque/);
 const euro=value=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format(value/100);
 for(const amount of [-5000,-6000,-2500])assert.ok(html.includes(euro(amount)));
 assert.ok(html.includes('<div class="hero-amount">'+euro(0)+'</div>'));
});

test('trajectory chart exposes realistic, prudent and uncertainty values without hiding assumptions',()=>{
 const html=context.renderTrajectoryChart({
  availability:{available:true},confidence:{level:'medium'},variable_spending:{confidence:'medium'},
  scenarios:{realistic:{closing_balance_cents:85000,low_point:{date:'2026-10-12',balance_cents:72000}},prudent:{closing_balance_cents:76000}},
  uncertainty_band:[
   {date:'2026-10-04',optimistic_cents:100000,realistic_cents:100000,prudent_cents:100000},
   {date:'2026-10-12',optimistic_cents:90000,realistic_cents:72000,prudent_cents:65000},
   {date:'2026-10-31',optimistic_cents:98000,realistic_cents:85000,prudent_cents:76000}
  ]
 });
 for(const text of ['Solde réaliste à l\'horizon','Scénario prudent','Point bas réaliste','Zone d\'incertitude','Confiance moyenne','ne modifient aucune donnée'])assert.ok(html.includes(text),text);
 assert.match(html,/<svg[^>]+role="img"/);
 assert.match(html,/trajectory-line-realistic/);
 assert.match(html,/trajectory-line-prudent/);
 assert.doesNotMatch(html,/NaN|undefined/);
});

test('trajectory chart keeps an explicit unavailable state',()=>{
 const html=context.renderTrajectoryChart({availability:{available:false},uncertainty_band:[]});
 assert.match(html,/trajectoire reste indisponible/);
 assert.doesNotMatch(html,/<svg/);
});

test('goal progress shows current financing instead of future contributions',()=>{
 const html=context.goalCard({name:'<Épargne>',status:'on_track',progress_pct:20,projected_progress_pct:100,effective_current_cents:20000,target_cents:100000,remaining_cents:80000,monthly_contribution_cents:10000,required_monthly_cents:8000,months_remaining:10,target_date:'2027-08-01',projected_at_target_cents:100000,projected_gap_cents:0});
 assert.match(html,/20 % financé/);
 assert.match(html,/aria-valuenow="20"/);
 assert.doesNotMatch(html,/100 % financé/);
 for(const text of ['Déjà financé','Reste à financer','Versement prévu','Rythme nécessaire','Projection à l','une hypothèse','2027','&lt;Épargne&gt;'])assert.ok(html.includes(text),text);
});
test('goals without a deadline, achieved goals and late goals explain their status',()=>{
 const base={name:'Objectif',progress_pct:0,target_cents:10000,remaining_cents:10000};
 const noDate=context.goalCard({...base,status:'no_deadline',required_monthly_cents:null});
 assert.match(noDate,/Aucun rythme requis/);
 assert.doesNotMatch(noDate,/Projection à l/);
 assert.match(context.goalCard({...base,status:'achieved',required_monthly_cents:null}),/Objectif déjà financé/);
 assert.match(context.goalCard({...base,status:'late',required_monthly_cents:10000,months_remaining:0}),/Échéance dépassée/);
});

async function wealthScreen(failures=[]){
 const root={innerHTML:'',querySelectorAll(){return [];},querySelector(){return {addEventListener(){}};}};
 context.document.querySelector=()=>root;
 context.fetch=async url=>({ok:!failures.includes(url),status:200,text:async()=> 'Service unavailable',json:async()=> url==='/api/v2.2/wealth'?{net_worth_cents:123456,total_assets_cents:133456,total_debt_cents:10000,cash_cents:100000,savings_cents:33456,as_of:'2026-10-04'}:url.includes('goals-forecast')?{goals:[]}:{buckets:[],protected_cents:20000}});
 await context.renderWealthScreen();return root.innerHTML;
}
test('optional wealth failures preserve net worth and distinguish unknown from empty',async()=>{
 const html=await wealthScreen(['/api/v3.3/goals-forecast?months=12','/api/v3.8/strategy?months=3']);
 assert.match(html,/Patrimoine net/);
 assert.match(html,/Suivi des objectifs indisponible/);
 assert.match(html,/Analyse de stratégie indisponible/);
 assert.match(html,/<span>Protégé<\/span><strong>Indisponible/);
 assert.doesNotMatch(html,/Aucun objectif patrimonial|Aucune allocation recommandée/);
 assert.match(html,/data-retry-wealth/);
});
test('successful empty goals stay empty and core wealth errors remain visible',async()=>{
 const empty=await wealthScreen();assert.match(empty,/Aucun objectif patrimonial/);assert.doesNotMatch(empty,/Suivi des objectifs indisponible/);
 const failed=await wealthScreen(['/api/v2.2/wealth']);assert.match(failed,/Service unavailable/);assert.doesNotMatch(failed,/Patrimoine net/);
});

for(const screen of ['month','movements']){
 for(const obsoleteError of [false,true])test(`${screen}: late ${obsoleteError?'error':'success'} cannot overwrite a newer month`,async()=>{
  const root={innerHTML:'',querySelectorAll(){return [];},querySelector(){return {addEventListener(){}};}};
  context.document.querySelector=selector=>selector.startsWith('[data-screen=')?root:{addEventListener(){}};
  let resolveOld;
  const gate=new Promise(resolve=>{resolveOld=resolve;});
  context.fetch=async url=>{
   const primary=screen==='month'?url.includes('/api/v2.1/months/'):url.includes('/api/v3.1/movements?');
   if(primary&&url.includes('2026-09')){await gate;if(obsoleteError)throw Error('Old month failure');}
   return {ok:true,status:200,json:async()=>url==='/api/recurring'||url.includes('/api/v3.1/movements?')?[]:url.includes('/months/')?{current:{},closing_explanation:{status:'unavailable',reason:'selected_month_not_current'}}:{}};
  };
  context.flowState.month='2026-09';context.flowState.query='';context.flowState.filter='all';
  const render=screen==='month'?context.renderMonthScreen:context.renderMovementsScreen;
  const old=render();context.flowState.month='2026-10';await render();
  const current=root.innerHTML;assert.ok(current.includes('octobre 2026'));
  resolveOld();await old;assert.equal(root.innerHTML,current);
 });
}

test('month picker remains visible during loading and supports a direct jump',async()=>{
 const root={innerHTML:'',querySelectorAll(){return [];}};
 const handlers={};
 context.document.querySelector=selector=>selector.startsWith('[data-screen=')?root:{addEventListener(type,handler){handlers[selector+type]=handler;}};
 let resolve;
 const gate=new Promise(r=>{resolve=r;});
 let hold=true;
 context.fetch=async url=>{
  if(hold&&url.includes('/api/v2.1/months/'))await gate;
  return {ok:true,status:200,json:async()=>url==='/api/recurring'?[]:url.includes('/months/')?{current:{},closing_explanation:{status:'unavailable',reason:'selected_month_not_current'}}:{}};
 };
 context.flowState.month='2026-10';const pending=context.renderMonthScreen();
 assert.match(root.innerHTML,/id="monthPicker"/);assert.match(root.innerHTML,/id="prevMonth"/);assert.match(root.innerHTML,/Chargement/);
 hold=false;
 await handlers['#monthPickerchange']({target:{value:'2025-01'}});
 assert.equal(context.flowState.month,'2025-01');assert.match(root.innerHTML,/janvier 2025/);
 resolve();await pending;assert.match(root.innerHTML,/janvier 2025/);
 await handlers['#monthPickerchange']({target:{value:''}});assert.equal(context.flowState.month,'2025-01');
});

test('category spending separates spent, planned and recommended amounts',()=>{
 const html=context.categoryBreakdown([{category:'<Courses>',spent_cents:7500,planned_cents:5000,recommended_remaining_cents:0},{category:'Transport',spent_cents:2500,planned_cents:10000,recommended_remaining_cents:3000}]);
 assert.match(html,/75 % des dépenses/);assert.match(html,/25 % des dépenses/);
 assert.match(html,/Budget prévu/);assert.match(html,/Reste recommandé/);assert.match(html,/Dépassé de/);
 assert.match(html,/hors budget ne sont pas incluses/);assert.match(html,/&lt;Courses&gt;/);
 assert.ok(html.indexOf('&lt;Courses&gt;')<html.indexOf('Transport'));
 assert.match(html,/data-category="&lt;Courses&gt;"/);
});
test('category remainder preserves spending beyond the first six categories',()=>{
 const html=context.categoryBreakdown(Array.from({length:8},(_,i)=>({category:`Cat ${i}`,spent_cents:1000})));
 assert.match(html,/Autres catégories \(2\)/);assert.match(html,/25 % des dépenses/);
 assert.equal((html.match(/class="budget-item budget-category-link"/g)||[]).length,7);
 assert.match(html,/80,00/);assert.match(html,/20,00/);
});
test('empty and invalid category amounts never create invalid shares',()=>{
 for(const lines of [[],[{spent_cents:0}],[{spent_cents:-100},{spent_cents:'invalid'}]]){
  const html=context.categoryBreakdown(lines);assert.match(html,/Aucune dépense/);assert.doesNotMatch(html,/NaN|Infinity|width:/);
 }
 const html=context.categoryBreakdown([{category:'Sans budget',spent_cents:100,planned_cents:null,recommended_remaining_cents:null}]);
 assert.doesNotMatch(html,/Budget prévu|Reste recommandé/);
});

test('movement summary explains the selected scope and net amount',()=>{
 const html=context.movementSummary([{amount_cents:-1200,is_internal_transfer:false},{amount_cents:5000,is_internal_transfer:false},{amount_cents:-300,is_internal_transfer:true},{amount_cents:-200,exclude_from_analytics:true}]);
 assert.match(html,/Dépenses de la sélection/);assert.match(html,/12,00/);assert.match(html,/Revenus de la sélection/);assert.match(html,/50,00/);assert.match(html,/Solde net de la sélection/);assert.match(html,/38,00/);
});
test('movement summary handles zero and negative net deterministically',()=>{
 const html=context.movementSummary([{amount_cents:-4500},{amount_cents:1000}]);
 assert.match(html,/Solde net de la sélection/);assert.match(html,/-35,00/);assert.match(html,/class="negative"/);
});

for(const filter of ['expense','income'])test(`movement ${filter} filter totals match displayed rows`,async()=>{
 const root={innerHTML:'',querySelectorAll(){return [];}};
 context.document.querySelector=selector=>selector.startsWith('[data-screen=')?root:{addEventListener(){}};
 const rows=[{id:1,label:'Salary',amount_cents:5000,booking_date:'2026-10-01'},{id:2,label:'Shop',amount_cents:-1200,booking_date:'2026-10-02'}];
 context.fetch=async url=>({ok:true,status:200,json:async()=>url.includes('/movements?')?rows:{uncategorized:0}});
 Object.assign(context.flowState,{month:'2026-10',query:'',filter,category:null});await context.renderMovementsScreen();
 const expected=context.movementSummary(rows.filter(row=>filter==='expense'?row.amount_cents<0:row.amount_cents>0));
 assert.ok(root.innerHTML.includes(expected));assert.match(root.innerHTML,/<h2>1 mouvement\(s\)<\/h2>/);
 assert.doesNotMatch(root.innerHTML,new RegExp(`data-edit="${filter==='expense'?1:2}"`));
});

test('movement list explains its limit when the response reaches 250',async()=>{
 const root={innerHTML:'',querySelectorAll(){return [];}};
 context.document.querySelector=selector=>selector.startsWith('[data-screen=')?root:{addEventListener(){}};
 context.fetch=async url=>({ok:true,status:200,json:async()=>url.includes('/movements?')?Array.from({length:250},(_,i)=>({id:i,label:'Shop',amount_cents:-100,booking_date:'2026-10-01'})):{}});
 Object.assign(context.flowState,{month:'2026-10',query:'',filter:'all',category:null});await context.renderMovementsScreen();
 assert.match(root.innerHTML,/Affichage limité aux 250 mouvements/);
});

test('missing month composition amounts and coverage remain unavailable',()=>{
 const html=context.renderFlowComposition({current:{semantic_coverage_pct:null},previous:{}},'2026-08');
 assert.match(html,/Indisponible/);
 assert.match(html,/Comparaison indisponible/);
 assert.doesNotMatch(html,/% classé|vs mois précédent|class="positive"|class="danger"|NaN|undefined/);
});
test('completed month comparisons retain direction when both amounts exist',()=>{
 const html=context.renderFlowComposition({current:{fixed_cents:10000,saving_cents:5000},previous:{fixed_cents:20000,saving_cents:4000}},'2025-08');
 assert.match(html,/class="positive">-100/);
 assert.match(html,/class="positive">\+/);
});
