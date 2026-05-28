(async function () {
  try {
    const res  = await fetch('/health');
    const data = await res.json();
    const color = data.status === 'healthy'  ? '#00ff99'
                : data.status === 'warning'  ? '#ffcc00'
                : data.status === 'critical' ? '#ff4444'
                : null;
    if (!color) return;
    const link = document.querySelector('a[href="health.html"]');
    if (link) link.style.color = color;
  } catch (e) {}
})();
