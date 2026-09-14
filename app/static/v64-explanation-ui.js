(()=>{
  const VERSION='6.4.0';
  const q=(selector,root=document)=>root.querySelector(selector);
  const euro=cents=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(cents)||0)/100);
  const esc=value=>{const node=document.createElement('div');node.textContent=value??'';return node.innerHTML;};
  const certainty=value=>({confirmed:'Confirmé',probable:'Probable',estimated:'Estimé',unavailable:'Indisponible'})[value]||'À vérifier';
  function dialog(){
    let node=q('#safeExplanationDialog');if(node)return node;
    node=document.createElement('dialog');node.id='safeExplanationDialog';node.className='sheet-dialog';
    node.innerHTML='<div class="sheet-panel large"><div class="sheet-handle"></div><div class="sheet-head"><div><p class="eyebrow">Traçabilité V6.4</p><h2>Comprendre ce montant</h2></div><button class="icon-btn" data-close-explanation aria-label="Fermer">×</button></div><div data-explanation-body class="stack"></div></div>';
    document.body.appendChild(node);q('[data-close-explanation]',node).addEventListener('click',()=>node.close());node.addEventListener('click',event=>{if(event.target===node)node.close();});return node;
  }
  function line(item){
    const sign=item.operator==='subtract'?'−':'';const sources=(item.sources||[]).slice(0,8);
    return `<details class="explain-line"><summary><div><strong>${esc(item.label)}</strong><small>${certainty(item.certainty)} · ${item.included_source_count}/${item.source_count} source(s) retenue(s)</small></div><b>${sign}${euro(item.amount_cents)}</b></summary><div class="explain-sources">${sources.map(source=>`<div><span>${esc(source.label)}</span><small>${esc(source.date||source.entity)} · ${source.included?'Retenu':esc(source.reason||'Exclu')}</small>${source.amount_cents!=null?`<b>${euro(source.amount_cents)}</b>`:''}</div>`).join('')||'<p class="subtle">Aucun élément individuel : règle de politique financière.</p>'}</div></details>`;
  }
  async function open(){
    const node=dialog(),body=q('[data-explanation-body]',node);node.showModal();body.innerHTML='<div class="skeleton tall"></div>';
    try{
      const response=await fetch('/api/v6/safe-to-spend/explanation',{cache:'no-store'});if(!response.ok)throw new Error(`HTTP ${response.status}`);const data=await response.json(),formula=data.formula||{},comparison=data.comparison||{};
      const comparisonMarkup=comparison.available?`<section class="explain-change"><p class="eyebrow">Évolution estimée</p><strong>${comparison.estimated_change_cents>=0?'+':''}${euro(comparison.estimated_change_cents)}</strong><small>Depuis le solde confirmé du ${esc(comparison.previous_balance_date)}. Comparaison à composantes constantes.</small></section>`:`<section class="notice">Aucun calcul antérieur comparable n'est disponible. Flow n'invente pas d'évolution.</section>`;
      body.innerHTML=`<section class="explain-total"><span>Safe to Spend calculé</span><strong>${data.availability?.available?euro(data.safe_to_spend?.total_cents):'Indisponible'}</strong><small>Référence du solde : ${esc(data.as_of)} · horizon : ${esc(data.horizon?.end)}</small></section><section class="explain-formula">${(formula.lines||[]).map(line).join('')}</section><section class="explain-audit ${formula.reconciled?'ok':'error'}"><div><strong>${formula.reconciled?'Calcul réconcilié':'Écart de calcul détecté'}</strong><small>Différence : ${euro(formula.difference_cents)}</small></div><b>${formula.reconciled?'0 centime d’écart':'Bloqué'}</b></section>${comparisonMarkup}<section class="explain-low"><p class="eyebrow">Point bas prudent</p><strong>${euro(data.low_point?.low_point_cents)}</strong><small>Prévu le ${esc(data.low_point?.low_point_date)}</small></section>`;
    }catch(error){body.innerHTML=`<div class="notice">Explication indisponible : ${esc(error.message)}</div>`;}
  }
  function attach(){
    const hero=q('[data-screen="home"] .card.hero');if(!hero||q('[data-explain-safe]',hero))return;
    const button=document.createElement('button');button.className='hero-explain';button.dataset.explainSafe='true';button.textContent='Comprendre ce montant';button.addEventListener('click',open);hero.appendChild(button);
  }
  const observer=new MutationObserver(()=>queueMicrotask(attach));
  const start=()=>{const home=q('[data-screen="home"]');if(home)observer.observe(home,{childList:true,subtree:true});attach();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();