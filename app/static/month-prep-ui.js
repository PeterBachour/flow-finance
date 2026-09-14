async function loadMonthPreparation(){
  const root=document.querySelector('#prepStatus');if(!root)return;
  try{
    const d=await api('/api/month-prep');
    document.querySelector('#prepMonth').textContent=d.month;
    root.textContent=d.status_label;
    root.dataset.status=d.status;
    const issueCount=(d.blockers?.length||0)+(d.warnings?.length||0);
    document.querySelector('#prepSubtitle').textContent=issueCount?`${issueCount} point${issueCount>1?'s':''} à traiter`:'Préparation complète';
    document.querySelector('#prepIncome').textContent=euro(d.effective_income_cents??d.recurring_income_cents);
    document.querySelector('#prepOutflows').textContent=euro((d.recurring_outflows_cents||0)+(d.rule_reserved_outflows_cents||0));
    document.querySelector('#prepNet').textContent=euro(d.net_recurring_cents);
    document.querySelector('#prepPending').textContent=String(d.pending_recurring_suggestions?.length||0);
    document.querySelector('#prepSalary').textContent=d.structural_income?`revenu structurant ${d.structural_income.date?shortDate(d.structural_income.date):'fin de mois, date à confirmer'} · ${euro(d.structural_income.amount_cents)}`:'revenu structurant manquant';
    const msgs=[...(d.blockers||[]).map(x=>({kind:'blocker',text:x})),...(d.warnings||[]).map(x=>({kind:'warning',text:x}))];
    document.querySelector('#prepMessages').innerHTML=msgs.length?msgs.map(m=>`<div class="prep-message ${m.kind}">${esc(m.text)}</div>`).join(''):'<div class="prep-message ok">Tous les éléments structurants sont identifiés.</div>';
    const dated=[...(d.expected_events||[]),...(d.planned_events||[])].sort((a,b)=>(a.due_date||'').localeCompare(b.due_date||''));
    const rendered=dated.map(e=>({date:e.due_date,amount_cents:e.amount_cents,label:e.label,certainty:e.source==='recurring'?'récurrent':(e.certainty||'prévu')}));
    renderEvents('#prepEvents',rendered);
    const rules=d.undated_financial_rules||[];
    if(rules.length){
      const container=document.querySelector('#prepEvents');
      container.insertAdjacentHTML('beforeend',rules.map(r=>`<div class="event"><time>date à confirmer</time><div><div class="label">${esc(r.name)}</div><div class="certainty">règle financière · ${r.satisfied?'déjà couverte':'à réserver'}</div></div><div class="value">${euro(-(r.value_cents||0))}</div></div>`).join(''));
    }
  }catch(err){root.textContent='Analyse indisponible';document.querySelector('#prepSubtitle').textContent=err.message||''}
}

function ensureAlertsPanel(){
  if(document.querySelector('#financeAlerts'))return;
  const metrics=document.querySelector('[data-page="home"] .metrics');if(!metrics)return;
  const section=document.createElement('section');section.className='card section';section.id='financeAlerts';
  section.innerHTML='<div class="section-title"><h2>À surveiller</h2><span id="alertCount">—</span></div><div id="alertList" class="review-list"><div class="empty">Analyse…</div></div>';
  metrics.insertAdjacentElement('afterend',section);
}

function ensureAlertPreferences(){
  if(document.querySelector('#alertPreferences'))return;
  const sheet=document.querySelector('#settings .sheet');if(!sheet)return;
  const block=document.createElement('div');block.className='settings-block';block.id='alertPreferences';
  block.innerHTML='<div class="section-title"><h3>Alertes</h3><span>seuils</span></div><label>Solde considéré ancien après</label><div class="inline"><input id="snapshotAlertDays" type="number" min="1" max="30" inputmode="numeric"><span>jours</span></div><label>Fenêtre des charges imminentes</label><div class="inline"><input id="upcomingAlertDays" type="number" min="1" max="31" inputmode="numeric"><span>jours</span></div><button id="saveAlertPreferences">Enregistrer les seuils</button>';
  sheet.insertBefore(block,sheet.lastElementChild);
  block.querySelector('#saveAlertPreferences').addEventListener('click',saveAlertPreferences);
}

async function loadAlertPreferences(){
  ensureAlertPreferences();
  try{
    const p=await api('/api/alerts/preferences');
    document.querySelector('#snapshotAlertDays').value=p.snapshot_max_age_days;
    document.querySelector('#upcomingAlertDays').value=p.upcoming_window_days;
  }catch{}
}

async function saveAlertPreferences(){
  const snapshot=Math.max(1,Number(document.querySelector('#snapshotAlertDays').value||3));
  const upcoming=Math.max(1,Number(document.querySelector('#upcomingAlertDays').value||7));
  await api('/api/alerts/preferences',{method:'PUT',body:JSON.stringify({snapshot_max_age_days:snapshot,upcoming_window_days:upcoming})});
  await loadFinanceAlerts();
}

async function snoozeFinanceAlert(code,days){
  await api(`/api/alerts/${encodeURIComponent(code)}/snooze`,{method:'POST',body:JSON.stringify({days})});
  await loadFinanceAlerts();
}

async function loadFinanceAlerts(){
  ensureAlertsPanel();const root=document.querySelector('#alertList');if(!root)return;
  try{
    const data=await api('/api/alerts');
    const hidden=data.hidden_count?` · ${data.hidden_count} masquée${data.hidden_count>1?'s':''}`:'';
    document.querySelector('#alertCount').textContent=data.count?`${data.count} alerte${data.count>1?'s':''}${hidden}`:`Rien à signaler${hidden}`;
    root.innerHTML=data.alerts.length?data.alerts.map(a=>`<article class="review-card alert-card" data-severity="${esc(a.severity)}" data-alert-code="${esc(a.code)}"><div class="review-head"><div><strong>${esc(a.title)}</strong><small>${esc(a.message)}</small></div><span class="alert-level">${a.severity==='critical'?'Critique':a.severity==='warning'?'Attention':'Info'}</span></div>${a.action?`<div class="prep-message ${a.severity==='critical'?'blocker':'warning'}">${esc(a.action)}</div>`:''}<div class="alert-actions"><button class="ghost alert-snooze" data-days="1">Masquer 24 h</button><button class="ghost alert-snooze" data-days="7">7 jours</button></div></article>`).join(''):'<div class="empty">Aucune action financière urgente.</div>';
  }catch(err){root.innerHTML=`<div class="empty">Alertes indisponibles : ${esc(err.message||'erreur')}</div>`}
}

const previousLoadMonth=loadMonth;
loadMonth=async function(){await previousLoadMonth();await loadMonthPreparation()};
loadMonthPreparation().catch(()=>{});
loadFinanceAlerts().catch(()=>{});
ensureAlertPreferences();
document.querySelector('#financeAlerts')?.addEventListener('click',async e=>{const button=e.target.closest('.alert-snooze');if(!button)return;const card=button.closest('[data-alert-code]');button.disabled=true;try{await snoozeFinanceAlert(card.dataset.alertCode,Number(button.dataset.days))}catch(err){alert(`Impossible de masquer l'alerte : ${err.message}`);button.disabled=false}});
document.querySelector('#refresh')?.addEventListener('click',()=>loadFinanceAlerts().catch(()=>{}));
document.querySelector('.nav button[data-tab="home"]')?.addEventListener('click',()=>loadFinanceAlerts().catch(()=>{}));
document.querySelector('#settingsBtn')?.addEventListener('click',()=>loadAlertPreferences().catch(()=>{}));
