(function () {
  const WORKFLOW_PAGES = ['workflow.html', 'hello-scrum.html', 'hello-scrum-aidlc.html', 'ai-dlc.html', 'jeff.html', 'chad.html', 'items.html', 'docs.html'];
  const path = window.location.pathname;
  if (WORKFLOW_PAGES.some(p => path.endsWith(p))) {
    const nav = document.createElement('div');
    nav.className = 'wf-nav';
    nav.innerHTML =
      '<a href="hello-scrum.html">Hello Scrum</a>' +
      '<a href="hello-scrum-aidlc.html">Hello Scrum AI-DLC</a>' +
      '<a href="ai-dlc.html">AWS AI-DLC</a>' +
      '<a href="docs.html">AI-DLC Docs</a>' +
      '<a href="jeff.html">Jeff</a>' +
      '<a href="chad.html">Chad</a>' +
      '<a href="items.html">Items</a>';
    nav.querySelectorAll('a').forEach(a => {
      if (path.endsWith(a.getAttribute('href'))) a.classList.add('active');
    });
    document.body.appendChild(nav);
  }
})();

(function () {
  const path = window.location.pathname;

  const nav = document.createElement('div');
  nav.className = 'phase-nav';
  [
    { label: 'Inception',    href: 'inception.html'    },
    { label: 'Construction', href: 'construction.html' },
    { label: 'Operations',   href: 'operations.html'   },
  ].forEach(({ label, href }) => {
    const a = document.createElement('a');
    a.href = '/' + href;
    a.textContent = label;
    if (path.endsWith(href)) a.classList.add('active');
    nav.appendChild(a);
  });
  document.body.appendChild(nav);

  document.querySelectorAll('.top-nav a').forEach(link => {
    const lp = new URL(link.href, location.href).pathname;
    if (lp === path || (path === '/' && lp === '/') || (path.endsWith(lp) && lp !== '/'))
      link.classList.add('active');
  });
  document.querySelectorAll('.nav-ref-btn').forEach(btn => {
    const menu = btn.nextElementSibling;
    if (!menu) return;
    const links = [...menu.querySelectorAll('a')];
    const pages = links.map(a => new URL(a.href, location.href).pathname);
    if (pages.some(p => path.endsWith(p.split('/').pop()))) btn.classList.add('active');
  });
})();

(async function () {
  try {
    const res  = await fetch('/health/score');
    const data = await res.json();
    const color = data.status === 'healthy'  ? '#00ff99'
                : data.status === 'warning'  ? '#ffcc00'
                : data.status === 'critical' ? '#ff4444'
                : null;
    if (!color) return;
    const borderColor = data.status === 'healthy'  ? '#00ff9940'
                      : data.status === 'warning'  ? '#ffcc0040'
                      : '#ff444440';
    const link = document.querySelector('a[href="health.html"]');
    if (link) { link.style.color = color; link.style.borderColor = borderColor; }
  } catch (e) {}
})();
