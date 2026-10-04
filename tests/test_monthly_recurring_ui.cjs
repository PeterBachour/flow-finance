const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/v4-ui.js','utf8');
const context={Intl,Date,document:{readyState:'loading',addEventListener(){},createElement(){return {set textContent(value){this.innerHTML=String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');}};}}};
vm.createContext(context);
vm.runInContext(source.replace("  if(document.readyState==='loading')",'  globalThis.renderRecurringCard=monthlyRecurringCard;\n  if(document.readyState===\'loading\')'),context);
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
