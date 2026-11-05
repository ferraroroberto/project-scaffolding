// site-theme boot: applies a saved light/dark choice before the first paint.
//
// VENDORED VERBATIM from project-scaffolding (app/site/static/_vendored/). Do NOT edit
// this file per-site. Load it as a plain blocking <script> in <head>, before the stylesheets
// (or paste the one line below inline, byte for byte); never `defer`, `async` or `type="module"`,
// which run after the first paint. Contract: README.md.

try{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}
