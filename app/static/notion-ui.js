(() => {
  const $ = (id) => document.getElementById(id);
  const fmtDate = (value) => value ? new Date(value).toLocaleString('fr-FR') : 'Jamais';

  function setText(id, value) {
    const el = $(id);
    if (el) el.textContent = value;
  }

  async function request(url, options) {
    const response = await fetch(url, options);
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  }

  function renderStats(data) {
    const stats = data.stats || data.last_import_stats || data;
    const keys = [
      ['accounts', 'Comptes'],
      ['balances', 'Soldes'],
      ['monthly_history', 'Historiques mensuels'],
      ['transactions', 'Transactions'],
      ['recurrences', 'Récurrences'],
      ['goals', 'Objectifs'],
      ['rules', 'Règles'],
      ['decisions', 'Décisions'],
      ['conflicts', 'Conflits'],
      ['ignored', 'Ignorés'],
    ];
    const target = $('notionStats');
    if (!target) return;
    target.innerHTML = keys
      .filter(([key]) => stats[key] !== undefined)
      .map(([key, label]) => `<div class="notion-stat"><span>${label}</span><strong>${stats[key]}</strong></div>`)
      .join('');
  }

  async function loadStatus() {
    try {
      const data = await request('/api/notion/status');
      setText('notionConnection', data.connected ? 'Référentiel Notion disponible' : 'Non connecté');
      setText('notionLastSync', `Dernière synchronisation : ${fmtDate(data.last_sync_at)}`);
      setText('notionRevision', data.source_revision || 'Aucun import');
      setText('notionConflicts', `${data.open_conflicts || 0} conflit(s) à vérifier`);
      if (data.last_run?.stats_json) {
        try { renderStats(JSON.parse(data.last_run.stats_json)); } catch (_) {}
      }
    } catch (error) {
      setText('notionConnection', 'État indisponible');
      setText('notionLastSync', error.message);
    }
  }

  async function preview() {
    setText('notionActionStatus', 'Analyse du mapping…');
    try {
      const data = await request('/api/notion/preview');
      renderStats({
        accounts: data.accounts,
        balances: data.balance_history,
        monthly_history: data.monthly_history,
        transactions: data.confirmed_transactions,
        recurrences: data.recurrences,
        goals: data.goals,
        rules: data.rules,
        decisions: data.decisions,
        conflicts: data.open_conflicts,
      });
      setText('notionActionStatus', `Prévisualisation prête. Politique : ${data.policy}.`);
    } catch (error) {
      setText('notionActionStatus', error.message);
    }
  }

  async function run(action) {
    setText('notionActionStatus', action === 'sync' ? 'Synchronisation…' : 'Import…');
    try {
      const data = await request(`/api/notion/${action}`, { method: 'POST' });
      renderStats(data);
      setText('notionActionStatus', `Terminé. Révision ${data.source_revision}.`);
      await loadStatus();
      if (typeof window.loadAll === 'function') await window.loadAll();
    } catch (error) {
      setText('notionActionStatus', error.message);
    }
  }

  $('notionAnalyze')?.addEventListener('click', preview);
  $('notionImport')?.addEventListener('click', () => run('import'));
  $('notionSync')?.addEventListener('click', () => run('sync'));
  $('settingsBtn')?.addEventListener('click', loadStatus);
  document.addEventListener('DOMContentLoaded', loadStatus);
})();
