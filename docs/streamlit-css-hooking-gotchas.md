# Streamlit custom CSS/JS gotchas (didactic)

Reference for hooking custom CSS or JS into Streamlit's rendered DOM —
`st.markdown(..., unsafe_allow_html=True)` style tags, `st.container(key=...)`
selectors, anything that reaches past Streamlit's public widget API into its
actual HTML. Two gotchas surfaced while building a sticky nav bar for a
fleet Streamlit app; both cost real debugging time because they look like CSS
bugs and are actually Streamlit internals moving under you.

> **Audience.** Me, plus any AI coding agent building custom CSS/JS against a
> Streamlit app.
> **Status.** Living reference, not a changelog. Update in place when the
> shape changes.

---

## TL;DR

- Streamlit's `data-testid` attributes are undocumented frontend internals,
  **not** a versioned public API — they rename between releases (`"column"`
  → `"stColumn"` observed in this fleet). Never trust a selector without
  verifying it live against the installed version.
- `position: sticky` on a `st.container(key=...)` (or any Streamlit element)
  usually does nothing, because Streamlit wraps every element in its own
  `stLayoutWrapper` div sized to just that element's height — there's no
  room to "stick" within a containing block that short. Stick a different
  ancestor instead: the one whose own parent spans the full scrollable page.
- Streamlit's fixed header toolbar sits at a very high z-index (~999990); a
  sticky element with `top: 0` slides invisibly underneath it. Offset `top`
  by the header's actual measured height.
- **Don't guess.** Inspect the real DOM (`getBoundingClientRect()` /
  `getComputedStyle()`) in a live browser session before writing the CSS —
  the wrapper structure isn't documented anywhere and has already changed
  once.

---

## Gotcha 1 — `data-testid`s are not a stable contract

Streamlit's React frontend tags most of its rendered elements with
`data-testid="stSomething"` attributes. It's tempting to hook CSS selectors
onto these directly — `[data-testid="stButton"]`, `[data-testid="stColumn"]`
— since they're the only stable-*looking* handles available. They are not
stable: this fleet has already observed a rename between installed
Streamlit versions, where the column wrapper's testid changed from
`"column"` to `"stColumn"`. A selector written against one version silently
stopped matching anything after an upgrade — no error, no warning, the CSS
rule just applied to zero elements and the intended layout quietly reverted
to Streamlit's default.

**The rule:** before shipping a `data-testid` selector, verify it live —
open the actual running app in a browser and confirm the attribute value via
devtools or a quick `document.querySelector(...)` check — rather than
copying a selector from memory, an old snippet, or another version's
inspection session. After any Streamlit version bump, re-verify every
`data-testid`-based CSS rule the same way; treat it as exactly the kind of
thing that silently breaks and needs an explicit re-check, not an assumption
that it still works.

Prefer `st.container(key="my-key")` (generates a stable `.st-key-my-key`
class — this *is* a documented, versioned public API) over a raw
`data-testid` selector wherever the element supports a `key=`. Reach for a
raw `data-testid` only when there's no `key=`-bearing wrapper available, and
treat that selector as version-pinned debt.

## Gotcha 2 — `position: sticky` needs the right containing block

A `position: sticky` element only has room to "stick" within the vertical
bounds of its own containing block (normally: its immediate parent). Naively
wrapping a nav bar in `st.container(key="nav-bar")` and sticking `.st-key-
nav-bar` directly does nothing useful, because Streamlit renders:

```
stVerticalBlock (spans the whole scrollable page)
  └─ stLayoutWrapper (sized to exactly ONE element's own height)
       └─ your element (e.g. .st-key-nav-bar)
```

`stLayoutWrapper` is Streamlit's per-element wrapper — every element gets
one, sized to fit just that element, not the page. If you stick the element
itself, its containing block (`stLayoutWrapper`) is only as tall as the nav
bar — there's zero room to move, so it "unsticks" and scrolls away the
instant you scroll past that sliver.

**The fix:** stick the *wrapper*, not the element — and make sure the
wrapper's own parent actually spans the full scrollable range. In practice
this means putting the sticky bar and the content that scrolls beneath it
inside one shared outer container, so they're siblings within the same
`stVerticalBlock`:

```python
with st.container():                    # shared containing block
    with st.container(key="nav-bar"):   # the sticky bar
        ...
    # routed page content, same outer container, so it's a sibling
    # of nav-bar inside the SAME stVerticalBlock
    ...
```

```css
/* Stick the wrapper Streamlit generates around .st-key-nav-bar, not the
   element itself — its own parent (the outer container's stVerticalBlock)
   is what actually spans the scrollable page. */
div[data-testid="stLayoutWrapper"]:has(> .st-key-nav-bar) {
    position: sticky;
    top: 60px;   /* Streamlit's fixed header height — see Gotcha 3 */
    z-index: 999;
    background-color: #0E1117;  /* opaque — otherwise scrolled content shows through underneath */
}
```

Verify the fix by checking the *actual* containing chain in a live session
rather than assuming it from reading the CSS:

```js
// In the browser console / a javascript_tool call against the running app
const el = document.querySelector('.st-key-nav-bar');
console.log(el.parentElement.getBoundingClientRect());   // the wrapper
console.log(el.parentElement.parentElement.getBoundingClientRect()); // its containing block
```

## Gotcha 3 — the sticky element can vanish under Streamlit's own header

Streamlit's own header toolbar (`[data-testid="stHeader"]`) is
`position: fixed` at a very high z-index (observed ~999990 — comfortably
above anything an app is likely to set). A sticky element with `top: 0`
slides right up underneath that header once scrolled — it's still there,
just painted behind Streamlit's own chrome, which looks exactly like the
sticky positioning silently failing.

**The fix:** measure the header's real height
(`document.querySelector('[data-testid="stHeader"]').getBoundingClientRect().height`)
and set the sticky element's `top` to that value, not `0`, so it parks
just below the header instead of underneath it.

## Single source of truth

Reference implementation combining all three gotchas: `content-management`'s
`app/app.py` (`ferraroroberto/content-management#207`) — a sticky
`segmented_control` nav bar with an inline theme toggle. That specific
nav/theme *pattern* is not vendored here: this scaffold's own Streamlit
starter (`app/app.py`) uses a structurally different navigation
(`st.navigation` + `st.Page` in the sidebar) and already ships a simpler
theme toggle (a sidebar `st.toggle()` injecting a `light.css` overlay, no
private API needed) — content-management's approach exists specifically to
work around `st.tabs()` losing state on rerun
(`ferraroroberto/content-management#157`) and a locked custom theme in that
repo's `config.toml`, neither of which applies to this scaffold's starter.
The three gotchas above are the generalizable lesson; the nav pattern itself
is not.
