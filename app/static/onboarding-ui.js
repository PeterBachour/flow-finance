async function loadOnboarding(){
  const status=await api('/api/onboarding/status');
  let card=document.querySelector('#onboardingCard');
  if(status.ready){card?.remove();return status}
  if(!card){
    card=document.createElement('section');card.id='onboardingCard';card.className='card section onboarding-card';
    const hero=document.querySelector('[data-page="home"] .hero');hero?.insertAdjacentElement('afterend',card);
  }
  const steps=(status.steps||[]).map(s=>`<div class="onboarding-step ${s.done?'done':''}"><span>${s.done?'✓':'○'}</span><strong>${esc(s.label)}</strong></div>`).join('');
  const blockers=(status.blockers||[]).map(x=>`<div class="prep-message blocker">${esc(x)}</div>`).join('');
  const warnings=(status.warnings||[]).map(x=>`<div class="prep-message warning">${esc(x)}</div>`).join('');
  const accountForm=status.liquid_account_count===0?`<form id="onboardingAccountForm" class="form-grid onboarding-form"><input name="name" placeholder="Nom du compte" value="Compte courant" required><select name="kind"><option value="checking">Compte courant</option><option value="cash">Espèces</option></select><input name="balance" inputmode="decimal" placeholder="Solde réel €" required><input name="date" type="date" value="${new Date().toISOString().slice(0,10)}" required><button type="submit" class="primary">Créer le compte</button></form>`:'';
  card.innerHTML=`<div class="section-title"><h2>Configurer Flow</h2><span>${status.steps.filter(s=>s.done).length}/${status.steps.length}</span></div><p class="muted">Flow ne calcule pas un disponible fiable tant que les données de base ne sont pas complètes.</p><div class="onboarding-steps">${steps}</div>${blockers}${warnings}${accountForm}`;
  const form=card.querySelector('#onboardingAccountForm');
  form?.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(form);await api('/api/onboarding/accounts',{method:'POST',body:JSON.stringify({name:f.get('name'),kind:f.get('kind'),current_balance_cents:cents(f.get('balance')),balance_as_of:f.get('date')})});await loadBase();await loadOnboarding()});
  return status
}

const previousLoadBaseOnboarding=loadBase;
loadBase=async function(){const result=await previousLoadBaseOnboarding();await loadOnboarding().catch(()=>{});return result};
loadOnboarding().catch(()=>{});
document.querySelector('#refresh')?.addEventListener('click',()=>loadOnboarding().catch(()=>{}));
