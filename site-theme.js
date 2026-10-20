(function () {
  const requested = new URLSearchParams(window.location.search).get('scoutTheme');
  const theme = ['light', 'dark'].includes(requested)
    ? requested
    : (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', theme);
})();
