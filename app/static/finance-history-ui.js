(() => {
  const euro = c => new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR'}).format((c||0)/100);
  const esc = v => { const d=document.createElement('div'); d.textContent=v??''; return d.innerHTML; };
  const short = s => s ? new Intl.DateTimeFormat('fr-FR',{month:'short',year:'numeric'}).format(new Date(`${s}-15T12:00:00`)) : '—';
  const api = async url => { const r=await fetch(url); if(!r.ok) throw new Error(await r.text()); return r.json(); };

  async function loadFinancialHistory(){
    const historyRoot=document.querySelector('#financialHistory');
    const rulesRoot=document.querySelector('#financialRules');
    const decisionsRoot=document.querySelector('#financialDecisions');
    if(!historyRoot||!rulesRoot||!decisionsRoot) return;
    try{
      const [history,rules,decisions]=await Promise.all([
        api('/api/finance/history?limit=12'),api('/api/finance/rules'),api('/api/finance/decisions?limit=20')
      ]);
      historyRoot.innerHTML=history.months.length?history.months.map(m=>`<div class="history-row"><div><strong>${short(m.month)}</strong><small>${m.comment?esc(m.comment):''}</small></div><div><span>Clôture ${euro(m.closing_balance_cents)}</span><small>${m.salary_cents==null?'Salaire non confirmé':`Salaire ${euro(m.salary_cents)}`}</small></div></div>`).join(''):'<div class="empty">Aucun historique mensuel.</div>';
      rulesRoot.innerHTML=rules.length?rules.map(r=>`<div class="history-row"><div><strong>${esc(r.name)}</strong><small>${esc(r.rule_type)}${r.end_date?` · jusqu'au ${esc(r.end_date)}`:''}</small></div><div><span>${r.value_cents==null?esc(r.value_text||''):euro(r.value_cents)}</span><small>${esc(r.source_status||'')}</small></div></div>`).join(''):'<div class="empty">Aucune règle active.</div>';
      decisionsRoot.innerHTML=decisions.length?decisions.map(d=>`<div class="history-row"><div><strong>${esc(d.title)}</strong><small>${esc(d.decision_date)}</small></div><div class="decision-detail">${esc(d.details||'')}</div></div>`).join(''):'<div class="empty">Aucune décision historisée.</div>';
    }catch(error){historyRoot.innerHTML=`<div class="empty">Historique indisponible : ${esc(error.message)}</div>`;}
  }

  function addCss(href,key){if(document.querySelector(`link[data-${key}]`))return;const css=document.createElement('link');css.rel='stylesheet';css.href=href;css.dataset[key]='1';document.head.appendChild(css)}
  function addScript(src,key){if(document.querySelector(`script[data-${key}]`))return;const script=document.createElement('script');script.src=src;script.defer=true;script.dataset[key]='1';document.body.appendChild(script)}
  function loadV24(){
    document.querySelectorAll('link[data-flow-v2],link[data-flow-v201],script[data-flow-v2],script[data-flow-v201]').forEach(node=>node.remove());
    document.body.classList.remove('flow-v2','flow-v201');
    document.body.classList.add('flow-v21','flow-v22','flow-v23','flow-v24');
    addCss('/static/v21.css?v=2.4.0','flowV21');
    addCss('/static/v22.css?v=2.4.0','flowV22');
    addCss('/static/v23.css?v=2.4.0','flowV23');
    addCss('/static/v24.css?v=2.4.0','flowV24');
    const version=document.querySelector('#appVersion');if(version)version.textContent='2.4.0';
    const apple=document.querySelector('link[rel="apple-touch-icon"]');if(apple)apple.href='/static/apple-touch-icon.png?v=2.4.0';
    const icon=document.querySelector('link[rel="icon"]');if(icon)icon.href='/static/icon-192.png?v=2.4.0';
    addScript('/static/v21-ui.js?v=2.4.0','flowV21');
    addScript('/static/v21-rules.js?v=2.4.0','flowV21Rules');
    addScript('/static/v22-ui.js?v=2.4.0','flowV22');
    addScript('/static/v23-ui.js?v=2.4.0','flowV23');
    addScript('/static/v24-ui.js?v=2.4.0','flowV24');
  }

  document.querySelectorAll('.nav button[data-tab="wealth"]').forEach(b=>b.addEventListener('click',loadFinancialHistory));
  window.loadFinancialHistory=loadFinancialHistory;
  loadV24();
})();
