(()=>{
  const CARD_ID='manualReviewCard';
  const DIALOG_ID='manualReviewDialog';
  let injecting=false;

  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const esc=value=>{const d=document.createElement('div');d.textContent=value??'';return d.innerHTML;};
  const dateLabel=value=>{if(!value)return '—';const d=new Date(`${String(value).slice(0,10)}T12:00:00`);return Number.isNaN(d.getTime())?value:new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short',year:'2-digit'}).format(d);};
  const api=async(url,options={})=>{const r=await fetch(url,{cache:'no-store',...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});if(!r.ok)throw new Error((await r.text())||`HTTP ${r.status}`);return r.status===204?null:r.json();};

  const merchantKey=label=>String(label||'')
    .toUpperCase().replace(/^CB\s+/,'')
    .replace(/\s+\d{2}\/\d{2}\/\d{2}$/,'')
    .replace(/\s+/g,' ').trim();

  const load=async()=>{
    const [rows,categories]=await Promise.all([
      api('/api/v3.1/movements?limit=500'),
      api('/api/categories')
    ]);
    const unknown=(rows||[]).filter(item=>Number(item.amount_cents)<0&&!item.is_internal_transfer&&!String(item.category||'').trim());
    const groups=new Map();
    for(const item of unknown){
      const key=merchantKey(item.label)||`#${item.id}`;
      const group=groups.get(key)||{key,rows:[],amount_cents:0};
      group.rows.push(item);
      group.amount_cents+=Math.abs(Number(item.amount_cents)||0);
      groups.set(key,group);
    }
    return {unknown,categories,groups:[...groups.values()].sort((a,b)=>b.amount_cents-a.amount_cents||b.rows.length-a.rows.length)};
  };

  const ensureDialog=()=>{
    let dialog=document.getElementById(DIALOG_ID);
    if(dialog)return dialog;
    document.body.insertAdjacentHTML('beforeend',`<dialog id="${DIALOG_ID}" class="mr-dialog"><form method="dialog" class="mr-panel" data-mr-form><div class="mr-head"><div><p class="eyebrow">Revue manuelle</p><h2>Catégoriser</h2></div><button type="button" class="mr-close" aria-label="Fermer">×</button></div><div data-mr-content></div></form></dialog>`);
    dialog=document.getElementById(DIALOG_ID);
    dialog.querySelector('.mr-close').addEventListener('click',()=>dialog.close());
    dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});
    return dialog;
  };

  const openGroup=async key=>{
    const data=await load();
    const group=data.groups.find(item=>item.key===key);
    if(!group)return;
    const dialog=ensureDialog();
    const content=dialog.querySelector('[data-mr-content]');
    const first=group.rows[0];
    content.innerHTML=`<div class="mr-summary"><strong>${esc(group.key)}</strong><span>${group.rows.length} opération(s) · ${euro(group.amount_cents)}</span></div>
      <div class="mr-samples">${group.rows.slice(0,5).map(row=>`<div><span>${dateLabel(row.booking_date)}</span><strong>${euro(Math.abs(row.amount_cents))}</strong><small>${esc(row.label)}</small></div>`).join('')}</div>
      <label class="mr-field"><span>Catégorie</span><select name="category" required><option value="">Choisir…</option>${data.categories.map(c=>`<option value="${esc(c.name)}">${esc(c.name)}</option>`).join('')}</select></label>
      <label class="mr-toggle"><input type="checkbox" name="all_matches" ${group.rows.length>1?'checked':''}><span><strong>Appliquer aux ${group.rows.length} opérations de ce marchand</strong><small>Action explicite. Aucune règle future n’est créée automatiquement.</small></span></label>
      <p class="mr-status" aria-live="polite"></p><button type="submit" class="btn primary mr-save">Enregistrer</button>`;
    const form=dialog.querySelector('[data-mr-form]');
    form.onsubmit=async e=>{
      e.preventDefault();
      const category=form.category.value;
      if(!category)return;
      const targets=form.all_matches.checked?group.rows:[first];
      const status=form.querySelector('.mr-status');
      const save=form.querySelector('.mr-save');
      save.disabled=true;status.textContent='Enregistrement…';
      try{
        for(const row of targets){
          await api(`/api/v3.1/movements/${row.id}`,{method:'PATCH',body:JSON.stringify({
            user_label:row.user_label||null,
            category,
            is_internal_transfer:Boolean(row.is_internal_transfer),
            is_exceptional:Boolean(row.is_exceptional),
            exclude_from_analytics:Boolean(row.exclude_from_analytics)
          })});
        }
        status.textContent=`${targets.length} opération(s) catégorisée(s).`;
        await refresh();
        setTimeout(()=>dialog.close(),500);
      }catch(err){status.textContent=`Échec : ${err.message}`;}finally{save.disabled=false;}
    };
    dialog.showModal();
  };

  const render=async()=>{
    const root=document.querySelector('[data-screen="movements"]');
    if(!root||!root.classList.contains('active'))return;
    const existing=document.getElementById(CARD_ID);
    if(existing)existing.remove();
    const anchor=root.querySelector('.metric-grid');
    if(!anchor)return;
    try{
      const data=await load();
      const total=data.unknown.reduce((sum,row)=>sum+Math.abs(Number(row.amount_cents)||0),0);
      const html=`<section class="card mr-card" id="${CARD_ID}"><div class="section-head"><div><p class="eyebrow">Qualité des données</p><h2>À catégoriser</h2></div><span class="mr-count">${data.unknown.length}</span></div><p class="subtle">${euro(total)} restent à qualifier. Les groupes sont triés par impact ; aucun classement n’est appliqué sans validation.</p><div class="mr-groups">${data.groups.slice(0,8).map(group=>`<button type="button" class="row list-button mr-row" data-mr-key="${encodeURIComponent(group.key)}"><div><strong>${esc(group.key)}</strong><small>${group.rows.length} opération(s) · dernière ${dateLabel(group.rows.at(-1)?.booking_date)}</small></div><div class="money negative">${euro(group.amount_cents)}</div></button>`).join('')||'<div class="empty-state">Aucune opération non catégorisée.</div>'}</div></section>`;
      anchor.insertAdjacentHTML('afterend',html);
      document.getElementById(CARD_ID)?.querySelectorAll('[data-mr-key]').forEach(btn=>btn.addEventListener('click',()=>openGroup(decodeURIComponent(btn.dataset.mrKey))));
    }catch(err){anchor.insertAdjacentHTML('afterend',`<section class="card mr-card" id="${CARD_ID}"><p class="subtle">Revue des catégories indisponible : ${esc(err.message)}</p></section>`);}
  };

  const refresh=async()=>{await render();};
  const observer=new MutationObserver(()=>{if(!injecting){injecting=true;queueMicrotask(async()=>{try{await render();}finally{injecting=false;}});}});
  const start=()=>{const root=document.querySelector('[data-screen="movements"]');if(root)observer.observe(root,{childList:true});document.querySelectorAll('[data-nav="movements"]').forEach(btn=>btn.addEventListener('click',()=>setTimeout(render,50)));setTimeout(render,100);};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
