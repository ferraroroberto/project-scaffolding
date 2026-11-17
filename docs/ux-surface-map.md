# UX surface map

Every fleet web app keeps one map of everything a person can see and do in it: each screen, tab, drill-in, menu and kebab, sheet, dialog, popover, Settings row, empty, error and loading state, gesture and keyboard path, with how it is reached, what is on it, what each control does and the decision behind it. This page is the convention; [templates/ux-surfaces.yaml](templates/ux-surfaces.yaml) is the file an app copies to start its own.

## Why a map

A layout change (a wider measure, a new band, a moved nav) has to be checked surface by surface, and a design review only measures the surfaces its walk happens to open. Prose about the main views is not enough: when one fleet app's surfaces were walked by hand, the walk found 74 surfaces, the app's own view docs described 53 of them, 17 more were described only in unrelated docs, 4 were not described anywhere and 3 were described wrongly. A complete map turns "check every surface" from memory into a list, and gives each surface a name that code, tests and reviews can share.

## Where it lives

Two files per web app, in the app's own repo:

- `docs/ux-surfaces.yaml`, the **map**: the single source, structured so a script and an agent read an entry without parsing prose. People and agents edit this file.
- `docs/ux-surface-map.md`, the **page**: generated from the map by `scripts/ux_surface_map.py` (vendored beside the ratchet). It groups the entries by area, draws one Mermaid diagram per area and ends with a link index. It opens with a "generated, do not edit" line; the ratchet fails a page that is not byte for byte what the generator makes from the map.

A repo serving two apps keeps one map and one page per app, naming them in its `[ux_surface_ratchet]` `map` and `page` settings. Streamlit spikes and public static sites are exempt.

## What counts as a surface

Anything a person can land on, open or perform as a unit:

- **Screens and tabs:** each nav destination, and each drill-in or pane reached from one (a detail drawer, a split pane, a sub-page).
- **Overlays:** every `<dialog>`, sheet, popover, menu, kebab, picker, toast and banner, whether it sits in the markup or is built in JS.
- **Settings:** each Settings group and each row that opens something or holds a choice.
- **States:** the empty, error, loading and gated renderings of a surface, when they show different controls or copy.
- **Inputs that are not elements:** gestures (swipes, drag and drop) and keyboard paths (shortcuts, the command palette's commands).

A single button is not a surface: it is listed under the surface it sits on, in that surface's `does` list.

## The map file

```yaml
app: task-board
notes: >                      # optional: ground rules, layout bands, where state lives
  Phone first; the nav pill switches views.
walk:                         # the walk the map was checked against
  date: 2026-11-17
  build: 1a2b3c4
  widths: [390, 1280]
  themes: [light, dark]
areas:                        # page order; one section and one diagram each
  - id: today
    title: Today
    notes: The default view.  # optional
surfaces:
  - id: today.row-menu
    area: today
    title: Row menu
    root: data-surface
    reach:
      - the row's kebab
      - a right-click
      - "`.` on a focused row"
    holds:
      - the row actions in their Settings order
    does:
      - each action applies to the row and offers Undo
    states:
      - actions the task does not support are hidden
    why: one table of actions feeds the menu, the keys and the swipes
    links:
      - to: row.date
        via: Due date…
```

| Key | Required | What it says |
|---|---|---|
| `id` | yes | The surface's stable id (see Ids). |
| `area` | yes | The `id` of one of `areas`; the entry is listed and drawn in that area. |
| `title` | yes | The name a person sees. |
| `root` | yes | `data-surface` when an element in the code carries the id; `none:` with a reason when the surface has no element of its own (a gesture, a key, a state drawn inside another surface's root). A `none:` with no reason still counts as an element the code must carry. |
| `reach` | no | Every way to get there: tap paths, keys, deep links, what opens it automatically. |
| `holds` | no | What is on it, in order. |
| `does` | no | What each control does, by its visible label. |
| `states` | no | Empty, error, loading, gated (a feature switched off), signed-out. |
| `why` | no | The decision behind it, when the choice was deliberate. |
| `phone`, `desktop` | no | Where the two renderings differ; without either, an entry holds for both. |
| `links` | no | The ways out of this surface: `to:` the id reached, `via:` the control or path (optional). They draw the diagrams and the link index. |

`reach`, `holds`, `does`, `states` and `links` are lists; the other values are text. An unknown key, a missing required one or an `area` that is not listed is an error naming its line, so a typo never drops a field quietly.

The file is read by a strict YAML subset, so the ratchet stays stdlib-only in every adopter and keeps the line numbers and comments its hits and exemptions need. Everything the subset accepts is plain YAML any editor or YAML tool reads the same way; what it refuses (anchors, aliases, tags, flow mappings, a plain value that spans lines) is an error naming the line. In practice: indent with spaces, keep a value on one line or put long prose in a `>` block, and quote a value that starts with a backtick, quote or bracket, holds `: `, or reads as `yes`, `no`, `true`, `false`, `on`, `off` or `null`. The full subset is in the module's docstring.

## Ids

- An id is lowercase letters and digits in segments joined by `.` or `-` (`^[a-z0-9]+(?:[.-][a-z0-9]+)*$`), the same form the e2e capture hook takes, so one id names the surface in the map, in the markup and in a test's `surface(page, "<id>")` call.
- Prefer `<area>.<surface>`, such as `today.row-menu` or `settings.theme`. Short area-number ids (`rw-4`) work too, but an id is never renumbered when entries are reordered.
- An id is stable for the life of the surface. Renaming a surface's title keeps its id; removing the surface removes its entry and every `data-surface` that carried it, in the same change.
- One id names one surface. A surface drawn two ways (a popover with a mouse, a sheet on a phone) keeps one id and one entry, with `phone` and `desktop` values.

## The page and its diagrams

`python scripts/ux_surface_map.py` writes the page; `--check` writes nothing and exits 1 when the page is not current. The page holds, in order: the app's notes and the walk; an index of areas with their surface counts; one section per area with its notes, its diagram and its entries; and a link index of every `links` edge.

Each area's diagram is a Mermaid `flowchart` with a node per surface in the area and an edge per link, labelled with its `via`. A link that crosses into or out of the area ends at a rounded stub node naming the surface and its area, so each diagram stays small enough to read and still shows the way in and out. A link to an id no entry lists is drawn as a stub saying so, and the ratchet counts it as `dangling-link`. The output is deterministic (map order, no timestamps), so regenerating an unchanged map changes nothing.

## Code carries the id

The surface's root element carries `data-surface="<id>"`, the same id as its entry:

```html
<dialog id="quick-add" data-surface="strip.quick-add" data-track-view="quick-add">
```

A surface built in JS gets its id where it is built, as a constant string:

```js
const menu = document.createElement('div');
menu.setAttribute('role', 'menu');
menu.dataset.surface = 'today.row-menu';
```

- The value is always a string literal, never built from content or state.
- The root is the element that appears and disappears with the surface: the `<dialog>`, the sheet's container, the tab panel, the drill-in's pane. Elements that are surfaces by their markup (a `<dialog>`, an element with `role` `dialog`, `alertdialog`, `menu` or `tabpanel`, an element with a `popover` attribute) always carry one; screens, drill-ins and states carry one where they have a root of their own.
- A surface a vendored component builds is stamped by the app's call site, since the component's code is shared by every app. The exception is a surface that has no call site, because the component builds it internally; that component stamps a fixed id itself, and every adopting app lists that id in its map. The ratchet reads the id from the vendored copy, so the entry needs no `Root: none`.

| Id | Component | Surface |
| --- | --- | --- |
| `app.update-banner` | `build-watch` | The "New version available · Reload" banner. |
| `shared.login` | `sign-in` | The password sign-in sheet. |
- `data-surface` names a surface for the map, the tests and the design walk; it is independent of `data-track-view`, which names a view for the usage log, though the two often hold the same value.

## Keeping it true

A change that adds, removes, renames or reshapes a user-visible surface updates the map in the same PR, including the entry's `why` when the choice was deliberate, adds or removes the matching `data-surface`, and regenerates the page. A surface's entry and its attribute appear and disappear together.

The gate holds this deterministically: the [UX surface ratchet](ux-surface-ratchet.md) fails a change that adds a surface root with no `data-surface`, an id with no entry, an entry no element carries, one id on two surfaces, a link to no entry, or a page not regenerated from the map, beyond the app's committed baseline. It sees what the markup and the JS declare; a screen or state built with no id at all is caught by the design-review and e2e walk, which reports every surface it opened that carries no `data-surface`.

## Starting a map

1. Copy [templates/ux-surfaces.yaml](templates/ux-surfaces.yaml) to the app's `docs/ux-surfaces.yaml`, and vendor `scripts/ux_surface_map.py`.
2. Walk the running app on a phone and a desktop width, light and dark: open every tab, every control that opens something, every Settings row, every gated feature on and off, and the empty and error states. Write one entry per surface as you go.
3. Read the markup and the JS for surfaces the walk did not reach (a dialog only an error opens, a picker only one path uses) and add them.
4. Give each surface root its `data-surface`.
5. Add each entry's `links` last, from the entries, and record the walk (date, build, widths, themes).
6. Run `python scripts/ux_surface_map.py` and commit the map and the page together.

## Moving a Markdown map

A map written as Markdown entries (a bold backticked id with *Root*, *Reach*, *Holds*, *Does*, *States*, *Why* fields and one hand-drawn graph) moves field for field: each entry becomes one item under `surfaces`, each `##` group one item under `areas`, `*Root:* none — <reason>` becomes `root:` with `none: <reason>`, each labelled field a list or text, and each edge of the old graph a `links` item on its source surface. Prose between entries goes in the area's or the map's `notes`. A `<!-- <rule>-exempt: <reason> -->` comment becomes a `# <rule>-exempt: <reason>` line right above the entry. Then drop `map = "docs/ux-surface-map.md"` from `[ux_surface_ratchet]` (the ratchet refuses a Markdown `map`), generate the page over the old file, and re-run the ratchet: the baseline's map counts move from the page's path to the map's.
