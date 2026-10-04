const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/v48-operations-ui.js','utf8');
function setup(fail=false){
 const handlers={},body={innerHTML:''};let html='',clicked=0,requests=0,observer;
 const toolbar={isConnected:true,insertAdjacentHTML(position,value){html=value;}};
 const root={classList:{contains:()=>true},querySelector:s=>s==='.movement-controls-v7'?toolbar:{click(){clicked++;}},querySelectorAll:()=>[]};
 const context={Intl,queueMicrotask,setTimeout,MutationObserver:class{constructor(cb){observer=cb;}observe(){}},document:{readyState:'loading',addEventListener(){},querySelector:()=>root,querySelectorAll:()=>[],createElement:()=>({set textContent(v){this.innerHTML=String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');}}),getElementById:id=>id==='editBody'?body:id==='editDialog'?{showModal(){}}:id==='v48QualityWorkbench'?null:{addEventListener(event,fn){handlers[id]=fn;}}},fetch:async url=>{requests++;if(fail&&url.includes('quality-workbench'))throw Error('offline');return {ok:true,json:async()=>url==='/api/categories'?[{name:'Courses'}]:url==='/api/accounts'?[]:url.includes('quality-workbench')?{uncategorized:3,unmatched_transfers:2}:url.includes('recurring-review')?{count:1}:{merchant_suggestions:[]}};}};
 vm.createContext(context);vm.runInContext(source.replace('  const observer=', '  globalThis.refresh=refresh;globalThis.openBulk=openBulk;\n  const observer='),context);
 return {context,handlers,body,toolbar,html:()=>html,clicked:()=>clicked,requests:()=>requests,observer:()=>observer};
}
test('shell loads quality script and styles with the active release',()=>{
 const shell=fs.readFileSync('app/static/index.html','utf8');
 for(const file of ['v48-operations-ui.js','v48-operations.css'])assert.match(shell,new RegExp('/static/'+file.replaceAll('.','\\.')+'\\?v=6\\.5\\.13'));
});
test('workbench renders beside actual controls and opens a blank bulk form on click',async()=>{
 const s=setup();await s.context.refresh();assert.match(s.html(),/3 à catégoriser/);assert.match(s.html(),/>6<\/span>/);
 s.handlers.v48UncategorizedBtn();assert.equal(s.clicked(),1);
 await s.handlers.v48BulkBtn({type:'click'});assert.match(s.body.innerHTML,/name="pattern"[^>]*value=""/);assert.doesNotMatch(s.body.innerHTML,/object Object/);
 assert.equal(s.requests(),5);
});
test('failed diagnostics are explicitly unavailable while actions remain usable',async()=>{
 const s=setup(true);await s.context.refresh();assert.match(s.html(),/Indisponible/);assert.match(s.html(),/\? à catégoriser/);assert.ok(s.handlers.v48BulkBtn);
});
test('detached controls never receive stale diagnostics',async()=>{
 const s=setup();s.toolbar.isConnected=false;s.context.queueMicrotask=()=>{};await s.context.refresh();assert.equal(s.html(),'');
});
test('attribute quotes are escaped in suggested patterns',async()=>{
 const s=setup();await s.context.openBulk('SHOP " data-evil="yes','Courses');assert.match(s.body.innerHTML,/SHOP &quot; data-evil=&quot;yes/);assert.match(s.body.innerHTML,/<option selected>Courses/);
});
test('workbench insertion does not trigger another diagnostics fetch',()=>{
 const s=setup();let queued=0;s.context.queueMicrotask=()=>queued++;
 s.observer()([{addedNodes:[{id:'v48QualityWorkbench'}],removedNodes:[]}]);assert.equal(queued,0);
 s.observer()([{addedNodes:[{id:''}],removedNodes:[]}]);assert.equal(queued,1);
});
