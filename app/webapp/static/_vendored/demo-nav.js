// demo.html?nav plays an installed app for an on-device check of the phone
// nav: the gallery (a long page) becomes the Home tab of the real nav, the
// other two tabs stay short. The nav is mounted after load, so this page
// shows the scroll fades and the keyboard behaviour, not a cold launch.
// Without ?nav (every harness) nothing here runs.
if (new URLSearchParams(location.search).has('nav')) {
  const css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = 'nav/nav-tabs.css';
  const loaded = new Promise((resolve) => { css.onload = resolve; });
  document.head.append(css);
  const skeleton = await fetch('nav/nav-tabs.html').then((r) => r.text());
  await loaded;
  document.body.insertAdjacentHTML('afterbegin', skeleton);
  document.getElementById('paneHome').append(document.querySelector('.gallery'));
  const { initNavTabs } = await import('./nav/nav-tabs.js');
  initNavTabs({ storageKey: 'gallery.nav-demo.tab' });
  // theme-color paints the status bar, so it follows the gallery's toggle.
  const meta = document.createElement('meta');
  meta.name = 'theme-color';
  document.head.append(meta);
  const syncThemeColor = () => { meta.content = getComputedStyle(document.body).backgroundColor; };
  syncThemeColor();
  new MutationObserver(syncThemeColor)
    .observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  document.body.dataset.navDemoReady = '1';
}
