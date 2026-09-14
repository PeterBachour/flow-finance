(()=>{
  let busy=false;
  const esc=value=>{const node=document.createElement('div');node.textContent=value??'';return node.innerHTML;};
  const euro=cents=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format((Number(cents)||0)/100);
  const label=value=>({critical:'Critique',high:'Prioritaire',medium:'À planifier',watch:'À surveiller',positive:'Stable',info:'Information'})[value]||value||'Info';
  const originLabel=value=>value==='financial_decision'?'Choix financier':'Recommandation';
  const surfaceLabel=value=>({home:'Accueil',month:'Mois',movements:'Mouvements',wealth:'Patrimoine'})[value]||'Accueil';
  const statusLabel=value=>({open:'Ouvert',done:'Traité',dismissed:'Ignoré'})[value]||value||'—';
  const lifecycle=item=>item.status_editable?(item.status!=='done'&&item.status!=='dismissed'?`<div class="toolbar v52-status-actions"><button class="chip active" data-v52-status="done" data-v52-key="${esc(item.key)}">Traité</button><button class="chip" data-v52-status="dismissed" data-v52-key="${esc(item.key)}">Ignorer</button></div>`:''):'';
  const historyHtml=items=>items?.length?`<div class="v52-history"><div class="section-head"><div><p class="eyebrow">Historique récent</p><h3>Décisions clôturées</h3></div></div>${items.map(item=>`<article class="v5-rec-row"><div><strong>${esc(item.title)}</strong><small>${esc(statusLabel(item.status))}${item.status_updated_at?` · ${esc(String(item.status_updated_at).slice(0,16).replace('T',' '))}`:''}</small>${item.note?`<p class="subtle">${esc(item.note)}</p>`:''}<div class="toolbar"><button class="chip" data-v52-status="open" data-v52-key="${esc(item.key)}" data-v52-note="${encodeURIComponent(item.note||'')}">Rouvrir</button></div></div><span class="chip">${esc(statusLabel(item.status))}</span></article>`).join('')}</div>`:'';

  async function setStatus(key,status,note=null){
    const response=await fetch(`/api/v5/decision-center/${encodeURIComponent(key)}`,{
      method:'PATCH',
      cache:'no-store',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({status,note})
    });
    if(!response.ok)throw new Error((await response.text())||`HTTP ${response.status}`);
    return response.json();
  }

  async function refresh(force=false){
    if(busy)return;
    const home=document.querySelector('[data-screen="home"]');
    if(!home||!home.classList.contains('active')||(!force&&home.querySelector('#v5Recommendations')))return;
    busy=true;
    try{
      const snapshot=await window.FlowV5HomeSnapshot.get(force);
      const data=snapshot.decision_center||{};
      const items=data.items||[];
      const recentClosed=data.recent_closed||[];
      const primary=data.primary||{
        title:'Aucune décision prioritaire',priority:'positive',explanation:'Aucune action financière urgente n’est détectée.',
        suggested_action:'Continuer le suivi normal.',source:'decision_center',origin:'recommendation',surface:'home',status_editable:false
      };

      const decisionCard=[...home.querySelectorAll('.card')].find(card=>card.querySelector('.eyebrow')?.textContent?.trim()==='Décision V5.2'||card.querySelector('.eyebrow')?.textContent?.trim()==='Décision V5'||card.querySelector('.eyebrow')?.textContent?.trim()==='Décision');
      if(!decisionCard)return;

      decisionCard.innerHTML=`
        <div class="section-head"><div><p class="eyebrow">Décision V5.2</p><h2>${esc(primary.title)}</h2></div><span class="chip ${primary.priority==='critical'||primary.priority==='high'?'warning':'active'}">${esc(label(primary.priority))}</span></div>
        <p class="subtle">${esc(primary.explanation)}</p>
        ${primary.impact_cents!=null?`<div class="money">${euro(primary.impact_cents)}</div>`:''}
        <div class="toolbar"><span class="chip">${esc(originLabel(primary.origin))}</span><button class="chip active" data-v52-go="${esc(primary.surface||'home')}">Ouvrir ${esc(surfaceLabel(primary.surface))}</button></div>
        ${lifecycle(primary)}
        <details id="v5Recommendations" class="v5-rec-details">
          <summary>${data.actionable_count||0} action(s) prioritaire(s) · ${data.financial_choice_count||0} choix financier(s)</summary>
          <div class="v5-rec-primary"><strong>Action proposée</strong><p>${esc(primary.suggested_action)}</p><small>Source : ${esc(primary.source)} · ${esc(originLabel(primary.origin))}</small></div>
          ${items.slice(1,7).map(item=>`<article class="v5-rec-row"><div><strong>${esc(item.title)}</strong><small>${esc(item.explanation)} · ${esc(originLabel(item.origin))}</small>${lifecycle(item)}</div><span class="chip ${item.priority==='critical'||item.priority==='high'?'warning':''}">${esc(label(item.priority))}</span></article>`).join('')}
          ${historyHtml(recentClosed)}
          ${Number(data.quality_review_count)>0?`<p class="subtle">${Number(data.quality_review_count)} revue(s) de qualité de données restent volontairement séparées dans Mouvements.</p>`:''}
          <p class="subtle">${esc(data.principle||'')}</p>
        </details>`;
      decisionCard.querySelectorAll('[data-v52-go]').forEach(button=>button.addEventListener('click',()=>{
        const target=document.querySelector(`[data-nav="${button.dataset.v52Go}"]`);
        target?.click();
      }));
      decisionCard.querySelectorAll('[data-v52-status]').forEach(button=>button.addEventListener('click',async()=>{
        const previous=button.textContent;
        const status=button.dataset.v52Status;
        let note=null;
        if(status==='done'||status==='dismissed'){
          const entered=prompt(status==='done'?'Note facultative pour cette décision traitée :':'Pourquoi ignorer cette décision ? (facultatif)', '');
          if(entered===null)return;
          note=entered.trim()||null;
        }else if(status==='open'){
          note=decodeURIComponent(button.dataset.v52Note||'')||null;
        }
        button.disabled=true;
        button.textContent=status==='open'?'Réouverture…':'Mise à jour…';
        try{
          await setStatus(button.dataset.v52Key,status,note);
          window.FlowV5HomeSnapshot.invalidate();
          await refresh(true);
        }catch(error){
          button.disabled=false;
          button.textContent=previous;
          alert(`Statut non modifié : ${error.message}`);
        }
      }));
    }catch(_){/* V5 decision center is an enhancement only */}finally{busy=false;}
  }

  const observer=new MutationObserver(()=>queueMicrotask(()=>refresh()));
  const start=()=>{
    const home=document.querySelector('[data-screen="home"]');
    if(home)observer.observe(home,{childList:true,subtree:true});
    document.querySelectorAll('[data-nav="home"]').forEach(button=>button.addEventListener('click',()=>setTimeout(()=>refresh(true),120)));
    window.addEventListener('flow:v5-home-snapshot-invalidated',()=>setTimeout(()=>refresh(true),20));
    setTimeout(()=>refresh(),180);
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
