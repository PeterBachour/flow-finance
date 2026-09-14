(()=>{
  let applying=false;

  async function apply(){
    if(applying)return;
    const card=document.getElementById('financialIntelligenceCard');
    if(!card)return;
    applying=true;
    try{
      const response=await fetch('/api/finance/intelligence?history_months=12',{cache:'no-store'});
      if(!response.ok)return;
      const data=await response.json();
      const quality=data.data_quality||{};
      if(quality.cycle_status!=='estimated'&&quality.decision_mode!=='month_estimated')return;

      const freshness=[...card.querySelectorAll('.fi-freshness')];
      if(freshness[1]){
        freshness[1].textContent='Relevé mensuel en attente';
        freshness[1].classList.remove('current');
        freshness[1].classList.add('stale');
      }

      const importBtn=card.querySelector('[data-fi-import-activity]');
      if(importBtn)importBtn.textContent='Importer le relevé';

      const note=card.querySelector('.fi-note');
      if(note)note.innerHTML='<strong>Mode estimé normal.</strong> Pendant le mois, Flow pilote avec le solde courant, les engagements connus et ton historique. Le détail des transactions sera consolidé lorsque le relevé mensuel sera disponible à la clôture.';

      const heading=card.querySelector('.fi-head h2');
      if(heading)heading.textContent='Projection estimée à partir du solde réel';
    }catch(_){
      /* Presentation helper only: never block the finance cockpit. */
    }finally{
      applying=false;
    }
  }

  const observer=new MutationObserver(()=>queueMicrotask(apply));
  const start=()=>{
    const home=document.querySelector('[data-screen="home"]');
    if(home)observer.observe(home,{childList:true,subtree:true});
    document.querySelectorAll('[data-nav="home"]').forEach(btn=>btn.addEventListener('click',()=>setTimeout(apply,0)));
    apply();
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
