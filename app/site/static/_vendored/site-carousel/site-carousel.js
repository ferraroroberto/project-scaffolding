// site-carousel: the arrows under each whole-card carousel; one click moves one card.
//
// VENDORED VERBATIM from project-scaffolding (app/site/static/_vendored/). Do NOT edit
// this file per-site. Load it as a module; the page works without it. Contract: README.md.

// Carousels: the arrows the build placed after each swipeable row; one click moves one card.
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
document.querySelectorAll('[data-carousel]').forEach((track) => {
  const nav = track.nextElementSibling;
  if (!nav || !nav.classList.contains('swipe-nav')) return;
  const [prev, next] = nav.querySelectorAll('button');
  const step = () => {
    const first = track.firstElementChild;
    const gap = parseFloat(getComputedStyle(track).columnGap) || 0;
    return first ? first.getBoundingClientRect().width + gap : track.clientWidth;
  };
  const update = () => {
    const max = track.scrollWidth - track.clientWidth - 2;
    prev.disabled = track.scrollLeft <= 2;
    next.disabled = track.scrollLeft >= max;
    nav.hidden = max <= 0;
  };
  const behavior = () => (reduceMotion.matches ? 'auto' : 'smooth');
  prev.addEventListener('click', () => track.scrollBy({ left: -step(), behavior: behavior() }));
  next.addEventListener('click', () => track.scrollBy({ left: step(), behavior: behavior() }));
  track.addEventListener('scroll', update, { passive: true });
  window.addEventListener('resize', update);
  update();
});
