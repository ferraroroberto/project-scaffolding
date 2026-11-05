// site-theme: the light/dark switch. The page follows the system setting until the visitor presses
// the switch; that choice is saved in localStorage under `theme` and wins from then on.
//
// VENDORED VERBATIM from project-scaffolding (app/site/static/_vendored/). Do NOT edit
// this file per-site. Load it as a module; the system setting applies without it, and
// theme-boot.js applies a saved choice before the first paint. Contract: README.md.

const THEME_KEY = 'theme';
const themeRoot = document.documentElement;
const themeButton = document.querySelector('.theme-toggle');
const systemDark = window.matchMedia('(prefers-color-scheme: dark)');

function activeTheme() {
  return themeRoot.dataset.theme || (systemDark.matches ? 'dark' : 'light');
}

function showTheme() {
  themeButton?.setAttribute('aria-pressed', String(activeTheme() === 'dark'));
}

themeButton?.addEventListener('click', () => {
  const next = activeTheme() === 'dark' ? 'light' : 'dark';
  themeRoot.dataset.theme = next;
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch {
    // Storage blocked (private mode, site data off): the choice lasts for this page only.
  }
  showTheme();
});
systemDark.addEventListener('change', showTheme);
showTheme();
