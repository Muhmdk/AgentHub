(() => {
  const root = document.documentElement;
  let saved;
  try { saved = localStorage.getItem('agenthub-theme'); } catch (_) { /* Optional preference. */ }
  root.dataset.theme = saved === 'dark' ? 'dark' : 'light';
  const routes = [
    ['/registry', 'Registry', 'Inspect the registered version and owner before evaluating changes.'],
    ['/evaluations', 'Evaluations', 'Compare the Inventory FAIL candidate with the Inventory PASS baseline. Failed required gates block release.'],
    ['/governance', 'Governance', 'Filter to Deny to find the seeded admin.delete attempt. Authorization is enforced outside the model.'],
    ['/observability', 'Observability', 'Invoke an agent to generate measurements. No observations means unknown health; trace export requires telemetry to be enabled.'],
    ['/delivery', 'Delivery', 'Inspect stable and candidate traffic. Seeded canary evidence is synthetic; observed runtime cost and rate-card projections are separate.'],
    ['/incidents-console', 'Incidents', 'Inspect the cited evidence before requesting rollback. Execution does not establish recovery; new observations are required.']
  ];
  const current = routes.find(([path]) => path === location.pathname);
  if (current) {
    document.body.classList.add('operator');
    const nav = document.createElement('nav'); nav.className = 'site-nav'; nav.setAttribute('aria-label', 'Operator navigation');
    [['/', 'AgentHub ↗'], ['/console', 'Workspace'], ...routes].forEach(([url, label]) => {
      const link = document.createElement('a'); link.href = url; link.textContent = label;
      if (url === location.pathname) link.setAttribute('aria-current', 'page'); nav.append(link);
    });
    const theme = document.createElement('button'); theme.type = 'button'; theme.className = 'theme-toggle'; theme.textContent = '◐'; theme.setAttribute('aria-label', 'Switch color theme'); nav.append(theme);
    document.body.prepend(nav);
    const context = document.createElement('aside'); context.className = 'operator-context';
    const label = document.createElement('p'); label.textContent = current[2];
    const guide = document.createElement('a'); guide.href = '/demo?mode=live'; guide.textContent = 'Follow the guided lifecycle →';
    context.append(label, guide); document.querySelector('main').prepend(context);
  }
  document.querySelectorAll('.theme-toggle').forEach(button => button.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem('agenthub-theme', root.dataset.theme); } catch (_) { /* Optional preference. */ }
  }));
  document.querySelectorAll('.copy').forEach(button => button.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(button.parentElement.querySelector('code').textContent); button.textContent = 'Copied'; }
    catch (_) { button.textContent = 'Select text to copy'; }
  }));
})();
