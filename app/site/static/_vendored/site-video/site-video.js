// site-video: swaps the thumbnail for the nocookie YouTube player only when tapped.
//
// VENDORED VERBATIM from project-scaffolding (app/site/static/_vendored/). Do NOT edit
// this file per-site. Load it as a module; the page works without it. Contract: README.md.

// Video: swap the thumbnail for the player only when tapped.
document.querySelectorAll('.video[data-yt] a').forEach((link) => {
  link.addEventListener('click', (e) => {
    e.preventDefault();
    const box = link.parentElement;
    const frame = document.createElement('iframe');
    frame.src = `https://www.youtube-nocookie.com/embed/${box.dataset.yt}?autoplay=1&rel=0`;
    frame.title = box.dataset.title || 'Video';
    frame.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
    frame.allowFullscreen = true;
    link.replaceWith(frame);
  });
});
