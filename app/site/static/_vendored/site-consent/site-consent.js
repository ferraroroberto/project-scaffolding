// site-consent: a non-modal consent bar. It records the visitor's choice in one cookie and
// announces it as a `consent:change` event; it knows nothing about what the choice gates.
//
// VENDORED VERBATIM from project-scaffolding (app/site/static/_vendored/). Do NOT edit
// this file per-site. Load it as a module; the page works without it. Contract: README.md.

const GRANTED = 'granted';
const DENIED = 'denied';
const DEFAULT_NAME = 'consent';
const DEFAULT_DAYS = 183; // six months, then the bar asks again
const NAME_PATTERN = /^[A-Za-z0-9_-]{1,32}$/;

const bar = document.querySelector('[data-consent]');
const name = bar ? (bar.dataset.consentCookie || DEFAULT_NAME) : DEFAULT_NAME;
const days = bar ? Number(bar.dataset.consentDays || DEFAULT_DAYS) : DEFAULT_DAYS;
const valid = NAME_PATTERN.test(name) && days > 0;

function readChoice() {
  try {
    for (const part of String(document.cookie || '').split(';')) {
      const [key, value] = part.trim().split('=');
      if (key === name) return value === GRANTED ? true : value === DENIED ? false : null;
    }
  } catch (_) { /* cookies blocked */ }
  return null;
}

function writeChoice(granted) {
  const secure = typeof location !== 'undefined' && location.protocol === 'https:' ? '; Secure' : '';
  try {
    document.cookie = `${name}=${granted ? GRANTED : DENIED}; Max-Age=${Math.round(days * 86400)}; Path=/; SameSite=Lax${secure}`;
  } catch (_) { /* cookies blocked: the choice holds for this page only */ }
}

/** The stored choice: `true` accepted, `false` rejected, `null` none yet or expired. */
export function getConsent() {
  return valid ? readChoice() : null;
}

if (bar && !valid) {
  console.warn('site-consent: data-consent-cookie must be a plain cookie name and data-consent-days positive; the bar stays hidden.');
} else if (bar) {
  let current = readChoice();
  let opener = null;

  const reserve = () => {
    // Keep a focused control and the page end clear of the fixed bar (WCAG 2.4.11).
    document.documentElement.style.setProperty('--consent-h', `${bar.offsetHeight || 0}px`);
  };
  const show = () => { bar.hidden = false; reserve(); };
  const hide = () => { bar.hidden = true; document.documentElement.style.removeProperty('--consent-h'); };
  const restoreFocus = () => {
    if (opener && typeof opener.focus === 'function') opener.focus();
    opener = null;
  };

  const choose = (granted) => {
    const changed = current !== granted;
    current = granted;
    writeChoice(granted);
    hide();
    restoreFocus();
    if (changed) document.dispatchEvent(new CustomEvent('consent:change', { detail: { granted } }));
  };

  bar.querySelector('[data-consent-accept]')?.addEventListener('click', () => choose(true));
  bar.querySelector('[data-consent-reject]')?.addEventListener('click', () => choose(false));

  document.querySelectorAll('[data-consent-open]').forEach((link) => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      opener = link;
      show();
      // The bar carries tabindex="-1" in the markup, so a keyboard visitor lands on it.
      if (typeof bar.focus === 'function') bar.focus();
    });
  });

  bar.addEventListener('keydown', (e) => {
    // Escape closes a reopened bar without changing the stored choice.
    if (e.key === 'Escape' && current !== null) { hide(); restoreFocus(); }
  });

  if (current === null) show();
}
