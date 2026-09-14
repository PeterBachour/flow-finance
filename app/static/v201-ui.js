(() => {
  const q=(s,r=document)=>r.querySelector(s);
  const qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const labels={home:'Accueil',month:'Mois',movements:'Mouvements',wealth:'Patrimoine'};

  function fixNav(){
    qa('.nav button[data-tab]').forEach(btn=>{
      const label=labels[btn.dataset.tab];
      if(!label)return;
      const span=q('span',btn);
      if(span)span.textContent=label;
      btn.setAttribute('aria-label',label);
    });
  }

  function syncTitle(tab){
    const title=q('#pageTitle');
    if(title&&labels[tab])title.textContent=labels[tab];
  }

  function bind(){
    fixNav();
    qa('.nav button[data-tab]').forEach(btn=>btn.addEventListener('click',()=>syncTitle(btn.dataset.tab)));
    const active=q('.nav button.active[data-tab]');
    if(active)syncTitle(active.dataset.tab);
    requestAnimationFrame(()=>window.scrollTo({left:0,top:window.scrollY,behavior:'instant'}));
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})();
