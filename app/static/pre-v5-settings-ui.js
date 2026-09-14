(()=>{
  let busy=false;
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML;};
  const euro=c=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(c)||0)/100);

  async function patchSettings(){
    if(busy)return;
    const root=document.getElementById('systemCenter');
    const dialog=document.getElementById('settingsDialog');
    if(!root||!dialog?.open)return;
    const decisionSection=[...root.querySelectorAll('.settings-section')].find(s=>s.querySelector('.eyebrow')?.textContent?.trim()==='Décisions');
    if(!decisionSection)return;
    busy=true;
    try{
      const [dr,gr]=await Promise.all([
        fetch('/api/v4.7/decision-priorities',{cache:'no-store'}),
        fetch('/api/v4.7/system-diagnostic',{cache:'no-store'})
      ]);
      const decisions=dr.ok?await dr.json():null;
      const diagnostic=gr.ok?await gr.json():null;

      if(decisions){
        decisionSection.dataset.preV5='1';
        decisionSection.innerHTML=`<div class="section-head"><div><p class="eyebrow">Décisions financières</p><h3>${decisions.open_count||0} choix à traiter</h3></div></div>
          ${(decisions.items||[]).slice(0,6).map(item=>`<article class="release"><div class="row"><div><strong>${esc(item.title)}</strong><small>${esc(item.detail)}</small></div>${item.amount_cents!=null?`<div class="money">${euro(item.amount_cents)}</div>`:''}</div><div class="toolbar"><button class="chip" data-pre-dismiss="${esc(item.key)}">Ignorer</button><button class="chip active" data-pre-done="${esc(item.key)}">Traité</button></div></article>`).join('')||'<div class="empty-state">Aucune décision financière en attente.</div>'}
          ${Number(decisions.quality_review_count)>0?`<div class="notice"><strong>${decisions.quality_review_count} revue(s) de données</strong><br><small>À traiter dans Mouvements ; elles ne sont pas des décisions financières.</small></div>`:''}`;
        decisionSection.querySelectorAll('[data-pre-dismiss]').forEach(b=>b.addEventListener('click',()=>setStatus(b.dataset.preDismiss,'dismissed')));
        decisionSection.querySelectorAll('[data-pre-done]').forEach(b=>b.addEventListener('click',()=>setStatus(b.dataset.preDone,'done')));
      }

      if(diagnostic){
        const application=[...root.querySelectorAll('.settings-section')].find(s=>s.querySelector('.eyebrow')?.textContent?.trim()==='Application');
        if(application){
          const items=[...application.querySelectorAll('.system-item')];
          const versionItem=items.find(item=>item.querySelector('span')?.textContent?.trim()==='Version installée');
          if(versionItem?.querySelector('strong'))versionItem.querySelector('strong').textContent=diagnostic.version||'—';
          const stateItem=items.find(item=>item.querySelector('span')?.textContent?.trim()==='État');
          if(stateItem?.querySelector('strong')&&diagnostic.commit_status!=='known')stateItem.querySelector('strong').textContent='Commit non injecté';
        }
        const section=[...root.querySelectorAll('.settings-section')].find(s=>s.querySelector('h3')?.textContent?.trim()==='Diagnostic');
        if(section){
          section.innerHTML=`<h3>Diagnostic</h3><div class="system-grid">
            <div class="system-item"><span>Version</span><strong>${esc(diagnostic.version||'—')}</strong></div>
            <div class="system-item"><span>Commit</span><strong>${esc(diagnostic.labels?.commit||'Non injecté')}</strong></div>
            <div class="system-item"><span>Mouvements</span><strong>${diagnostic.database?.counts?.transactions??'—'}</strong></div>
            <div class="system-item"><span>À catégoriser</span><strong>${diagnostic.database?.uncategorized??'—'}</strong></div>
            <div class="system-item"><span>Imports</span><strong>${diagnostic.database?.counts?.imports??'—'}</strong></div>
            <div class="system-item"><span>Base</span><strong>${diagnostic.database?.connected?'Connectée':'À vérifier'}</strong></div>
          </div><p class="subtle">Dernier solde daté : ${esc(diagnostic.latest_balance_as_of||'non renseigné')} · Fiabilité mise à jour : ${esc(diagnostic.labels?.update_reliability||'à vérifier')}.</p>`;
        }
      }
    }catch(_){/* preserve base settings */}finally{busy=false;}
  }

  async function setStatus(key,status){
    await fetch(`/api/v3.6/decision-inbox/${encodeURIComponent(key)}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});
    const section=[...document.querySelectorAll('#systemCenter .settings-section')].find(s=>s.dataset.preV5==='1');
    if(section)section.dataset.preV5='0';
    patchSettings();
  }

  const observer=new MutationObserver(()=>queueMicrotask(patchSettings));
  const start=()=>{const root=document.getElementById('systemCenter');if(root)observer.observe(root,{childList:true,subtree:true});document.getElementById('settingsBtn')?.addEventListener('click',()=>setTimeout(patchSettings,120));};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
