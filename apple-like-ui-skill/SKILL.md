---
name: Apple-like UI style for small utilities
description: Design and implement Apple-inspired desktop interfaces for small Tkinter/Python utilities, including light/dark palettes, rounded antialiased Canvas controls, compact responsive layouts, and Tk-specific QA pitfalls.
---

# Apple-like UI style for small utilities

Use this skill when building or restyling a small desktop utility that should
feel like a native macOS/Apple app but must run in Python/Tkinter on Linux.

The goal is not to fake macOS window chrome. Keep the native window decorations
and make the app content feel calm, compact, rounded, and typographic.

## Design tokens

Start with a palette instead of ad-hoc colours:

- Light: content `#f5f5f7`, card `#ffffff`, text `#1d1d1f`,
  secondary `#6e6e73`, border `#e3e3e6`, fill `#ececef`,
  accent `#007aff`, error `#ff3b30`
- Dark: content `#1c1c1e`, card `#2a2a2c`, text `#f5f5f7`,
  secondary `#a5a5ad`, border `#3a3a3e`, fill `#343437`,
  accent `#0a84ff`, error `#ff453a`
- One gray family plus one blue accent. Reserve red for failures. Avoid green
  success colours unless the product explicitly needs them.
- Fonts: Adwaita Sans -> Cantarell -> Noto Sans; 10pt body, 9pt small,
  11-12pt headings, bold for row titles.
- Radii: cards 12px, buttons 10-11px, fields 11px, segmented track 9px,
  pills 7-8px.
- Spacing: 16-24px page padding, 14-16px card padding, 8-12px between controls.

## Layout recipe

1. Native title bar only. Do not add a second in-app title toolbar.
2. Top section: a large rounded input field with an inline accessory (Paste),
   then secondary and primary actions.
3. Two-column grid: Options card on the left, Preview card on the right.
   Both cards must be the same height. Put explanatory footnotes outside the
   card row so they do not drive one card taller.
4. Queue card below with rows: thumbnail, title, status/format, actions.
5. Bottom status bar: right-aligned actions; show status text only for active
   work or failures. Never show a permanent "Ready" label.
6. Responsive:
   - under ~740px content width: move primary/secondary buttons under the field
   - under ~820px content width: stack Preview below Options
   - keep controls from shrinking below their text width

## Tkinter implementation rules

- Tk Canvas has **no antialiasing**. Do not draw visible rounded corners with
  `create_polygon`, `create_oval`, or `create_arc`.
- Render antialiased corners as small `PhotoImage` tiles with supersampling
  (4x-6x per axis). Pre-blend each tile against the known background colour so
  the image can be opaque. Cache by radius/fill/border/background/border width.
- For each rounded surface, draw fill rectangles and 1px straight edges, then
  place the four corner tiles. For cards with an embedded body widget, use four
  raised corner labels with the same tiles to mask the body's square corners.
- When a rounded surface sits on another surface, pass the underlying colour as
  its background. Otherwise the tile blends to the window colour and creates
  notches. Examples: focus ring, segmented thumb, popup chevron, progress fill.
- Prefer a single 1px accent border for focus over nested 2px rings; nested
  rings show seams where the arc meets straight lines.
- Bind `<Configure>` on every custom Canvas control and repaint using
  `winfo_width()` when > 1. Never draw wider than the allocated widget; that
  clips the right side and makes a rounded button look square.
- A Canvas has a large default requested size. For a card that should fill a
  grid row, set `autosize=False` and `height=1`, then pack with
  `fill="both", expand=True`. Let the other card determine the row height.
- If a card autosizes, set both the embedded body's width and height on every
  Configure event; place-managed empty states otherwise collapse.
- Disable page-wheel scrolling when content fits. Force `yview_moveto(0)` when
  the scrollbar is hidden to prevent a blank overscroll band at the top.
- Prefer a segmented control or discrete slider for small, frequently changed
  option sets (roughly 2-9 choices). It keeps the value visible, removes popup
  dismissal bugs, and matches the rest of a compact settings card.
- For a stretched segmented control, measure each label with the chosen font,
  add modest padding, then distribute any extra width proportionally across the
  segments. Repaint from `winfo_width()` on `<Configure>`; never use a fixed
  intrinsic width when the control is meant to fill a card.
- Keep segmented controls keyboard-operable: Left/Right to step, Home/End for
  the ends, and a single 1px accent focus outline.
- Reserve a custom dropdown `Toplevel` for long menus that cannot fit as a
  segmented track. When you do need one, manage local grab, outside-click
  close, Escape close, focus polling, and screen-edge clamping explicitly.
- Use system cursors only. Do not set hand/xterm cursors on custom controls.
- Keep text antialiasing in mind: confirm the Tk build reports
  `::tk::pkgconfig get fontsystem` = `xft`. A Tk built without Xft falls back
  to pixelated core fonts regardless of font choice.

## Primary button states

- Enabled primary: blue fill, white label and icon.
- Disabled primary: neutral gray fill, muted gray icon, secondary text colour.
- Never leave a disabled primary looking blue.

## QA checklist

- Light and dark at 1040x700, 900x620, 800x620, and 640x600.
- Text smooth (Xft).
- No square seams or fringes on any rounded corner.
- Options/Preview equal height.
- No scrollbar or wheel overscroll when content fits.
- Dropdowns, when used, close on outside click, app focus loss, Escape, and
  selection. Prefer segmented controls so this case rarely applies.
- Segmented sliders fit every label at the narrowest supported window and show
  a focus outline for keyboard users.
- Focus rings and keyboard traversal work; buttons respond to Return/Space.
- Disabled/enabled button states are visually distinct.
- No unintended green; red only for errors.
- Run tests under both the dev interpreter and the system Python.

## Pitfall summary

1. A Python with Tk is not necessarily a Tk with Xft.
2. Canvas curves are aliased; use blended image corners.
3. Nested surfaces need the underlying background colour.
4. Paint to allocated width, not requested width.
5. Canvas default size breaks equal-height card layouts.
6. Prefer segmented controls for short option sets; native menus and popups can
   persist and float, so control dismissal must be explicit when they are used.
7. Wheel scrolling must be disabled when content fits.
8. Keep native window chrome; do not fake traffic lights.
