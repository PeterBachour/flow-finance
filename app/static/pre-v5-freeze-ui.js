(()=>{
  let busy=false;
  const esc=v=>{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML;};
  const labels={ok:'OK',warning:'À traiter',info:'Information'};

  async function enhance(){
    if(busy)return;
    const root=document.getElementById('systemCenter');
    const dialog=document.getElementById('settingsDialog');
    if(!root||!dialog?.open)return;
    if(root.querySelector('#preV5Readiness'))return;
    busy=true;
    try{
      const response=await fetch('/api/v4.11/pre-v5-readiness',{cache:'no-store'});
      if(!response.ok)return;
      const data=await response.json();
      const host=[...root.querySelectorAll('.settings-section')].find(s=>s.querySelector('h3')?.textContent?.trim()==='Diagnostic')||root.lastElementChild;
      if(!host)return;
      const section=document.createElement('section');
      section.id='preV5Readiness';
      section.className='settings-section pre-v5-readiness';
      const gates=data.gates||[];
      const attention=gates.filter(g=>g.status!=='ok');
      section.innerHTML=`
        <div class="section-head"><div><p class="eyebrow">Préparation V5</p><h3>${data.release_status==='ready'?'Socle prêt à figer':'Quelques points à traiter'}</h3></div><span class="chip ${data.release_status==='ready'?'active':'warning'}">${data.blocking_count||0} blocage(s)</span></div>
        <div class="pre-v5-gates">${gates.map(g=>`<div class="pre-v5-gate" data-status="${esc(g.status)}"><span class="pre-v5-dot"></span><div><strong>${esc(g.label)}</strong><small>${esc(g.detail)}</small></div><b>${labels[g.status]||esc(g.status)}</b></div>`).join('')}</div>
        <p class="subtle">${esc(data.principle||'')}</p>`;
      host.insertAdjacentElement('afterend',section);
    }catch(_){/* diagnostic addition is non blocking */}finally{busy=false;}
  }

  const observer=new MutationObserver(()=>queueMicrotask(enhance));
  const start=()=>{
    const root=document.getElementById('systemCenter');
    if(root)observer.observe(root,{childList:true,subtree:true});
    document.getElementById('settingsBtn')?.addEventListener('click',()=>setTimeout(enhance,180));
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
