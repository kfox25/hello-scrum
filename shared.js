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
