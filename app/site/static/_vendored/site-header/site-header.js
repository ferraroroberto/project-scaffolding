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
window.matchMedia('(min-width: 1024px)').addEventListener('change', (e) => e.matches && setMenu(false));
