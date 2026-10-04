const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/v4-ui.js','utf8');
const context={Intl,Date,FormData:class FormData{},document:{readyState:'loading',addEventListener(){},createElement(){return {set textContent(value){this.innerHTML=String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');}};}}};
vm.createContext(context);
vm.runInContext(source.replace("  if(document.readyState==='loading')",'  globalThis.renderRecurringCard=monthlyRecurringCard; globalThis.renderMonthScreen=renderMonth; globalThis.renderHomeScreen=renderHome; globalThis.goalCard=wealthGoalCard;\n  if(document.readyState===\'loading\')'),context);
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
 assert.doesNotMatch(html,/Indisponible|Échéances et prévisions restantes/);
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
