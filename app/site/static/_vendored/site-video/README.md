# `site-video` — video on tap

A video is a re-hosted thumbnail with a play mark until it is tapped; only then does `site-video.js` swap in the YouTube player from `youtube-nocookie.com`, with autoplay. Nothing loads from YouTube before the tap, which is most of a video page's weight. Without the script the link opens the video on YouTube.

## Markup

```html
<div class="video" data-yt="VIDEO_ID" data-title="What the video is">
<a href="https://www.youtube.com/watch?v=VIDEO_ID"><img src="/img/thumb.webp" alt="What the video is"></a>
</div>
<script type="module" src="/_vendored/site-video/site-video.js"></script>
```

Needs [`site-tokens`](../site-tokens/).

## Files

| File | Role |
| --- | --- |
| `site-video.css` | Styles |
| `site-video.js` | Behaviour (an ES module; the page works without it) |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-video/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-video`, never by hand. Do not edit the files per site: the brand is token values in the site's own stylesheet (see [`site-tokens`](../site-tokens/)). Load order and the whole set: [`../README.md`](../README.md).
