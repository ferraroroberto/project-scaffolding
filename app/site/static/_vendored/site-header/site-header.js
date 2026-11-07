// site-header: the header hairline on scroll and the phone menu.
//
// VENDORED VERBATIM from project-scaffolding (app/site/static/_vendored/). Do NOT edit
// this file per-site. Load it as a module; the page works without it. Contract: README.md.

const root = document.documentElement;
const header = document.querySelector('.site-header');

// Header hairline once the page scrolls.
function onScroll() {
  header?.classList.toggle('scrolled', window.scrollY > 4);
}
window.addEventListener('scroll', onScroll, { passive: true });
onScroll();

// Phone menu.
const toggle = document.querySelector('.menu-toggle');
function setMenu(open) {
  root.classList.toggle('menu-open', open);
  toggle?.setAttribute('aria-expanded', String(open));
}
toggle?.addEventListener('click', () => setMenu(!root.classList.contains('menu-open')));
document.querySelectorAll('.site-nav a').forEach((a) => a.addEventListener('click', () => setMenu(false)));
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && root.classList.contains('menu-open')) {
    setMenu(false);
    toggle?.focus();
  }
});

// The text nav shows from --nav-breakpoint (a px length, never below the 1024px the stylesheet's media query sets).
const FLOOR = 1024;
function navBreakpoint() {
  const match = /^\s*(\d+(?:\.\d+)?)px\s*$/.exec(getComputedStyle(root).getPropertyValue('--nav-breakpoint'));
  return match ? Math.max(FLOOR, Number(match[1])) : FLOOR;
}
const wide = window.matchMedia(`(min-width: ${navBreakpoint()}px)`);
function onNavMode() {
  header?.setAttribute('data-nav', wide.matches ? 'inline' : 'menu');
  if (wide.matches) setMenu(false);
}
wide.addEventListener('change', onNavMode);
onNavMode();
