"""Canvas-drawn controls used by the Apple-inspired TubeGrab interface.

Tkinter widgets are rectangular, so the main surfaces and controls are painted
on Canvas objects.  A few small classes expose the subset of the ttk widget API
that the application uses (``configure(text=...)``, ``cget("state")``,
``grid_remove``) to keep the UI code readable.
"""

from __future__ import annotations

import math
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable, Sequence

from .theme import current_fonts, current_palette

ASSETS = Path(__file__).resolve().parent / "assets"


def load_icon(name: str) -> tk.PhotoImage:
    """Load a bundled PNG icon, caching it per Tk interpreter."""

    path = ASSETS / "icons" / f"{name}.png"
    root = tk._default_root  # type: ignore[attr-defined]
    cache = getattr(root, "_tubegrab_icon_cache", None) if root is not None else None
    if cache is None:
        cache = {}
        if root is not None:
            root._tubegrab_icon_cache = cache  # type: ignore[attr-defined]
    key = str(path)
    image = cache.get(key)
    if image is None:
        image = tk.PhotoImage(file=key)
        cache[key] = image
    return image


def _color(value: str) -> str:
    return value if value.startswith("#") else getattr(current_palette(), value)


def _mix(first: str, second: str, amount: float) -> str:
    amount = max(0.0, min(1.0, amount))
    start = tuple(int(first[index : index + 2], 16) for index in (1, 3, 5))
    end = tuple(int(second[index : index + 2], 16) for index in (1, 3, 5))
    values = tuple(round(a + (b - a) * amount) for a, b in zip(start, end))
    return "#{:02x}{:02x}{:02x}".format(*values)


def _tile_cache() -> dict[tuple[int, str, str, str], dict[str, tk.PhotoImage]]:
    root = tk._default_root  # type: ignore[attr-defined]
    cache = getattr(root, "_tubegrab_tile_cache", None) if root is not None else None
    if cache is None:
        cache = {}
        if root is not None:
            root._tubegrab_tile_cache = cache  # type: ignore[attr-defined]
    return cache


def _corner_tiles(
    radius: int,
    fill: str,
    border: str,
    background: str,
    border_width: int = 1,
) -> dict[str, tk.PhotoImage]:
    """Render four opaque, antialiased corner tiles for a rounded surface.

    Tk's Canvas has no antialiasing, so corners are pre-blended against the
    known background colour and drawn as images.  This keeps edges smooth
    without adding Pillow or Cairo as a dependency.
    """

    radius = max(2, int(radius))
    border_width = max(1, min(int(border_width), radius - 1))
    fill = _color(fill)
    border = _color(border) if border else fill
    background = _color(background)
    key = (radius, fill, border, background, border_width)
    cache = _tile_cache()
    cached = cache.get(key)
    if cached is not None:
        return cached

    centers = {
        "nw": (radius, radius),
        "ne": (0, radius),
        "sw": (radius, 0),
        "se": (0, 0),
    }
    samples = 6
    total = samples * samples
    tiles: dict[str, tk.PhotoImage] = {}
    for name, (center_x, center_y) in centers.items():
        image = tk.PhotoImage(width=radius, height=radius)
        for y in range(radius):
            row: list[str] = []
            for x in range(radius):
                fill_coverage = 0
                border_coverage = 0
                if radius <= 2:
                    fill_coverage = total
                else:
                    for sy in range(samples):
                        py = y + (sy + 0.5) / samples
                        for sx in range(samples):
                            px = x + (sx + 0.5) / samples
                            distance = math.hypot(px - center_x, py - center_y)
                            if distance <= radius - border_width:
                                fill_coverage += 1
                            elif distance <= radius:
                                border_coverage += 1
                inside = (fill_coverage + border_coverage) / total
                if inside <= 0:
                    color = background
                else:
                    color = _mix(background, fill, inside)
                    if border_coverage:
                        color = _mix(color, border, border_coverage / (fill_coverage + border_coverage))
                row.append(color)
            image.put("{" + " ".join(row) + "}", to=(0, y))
        tiles[name] = image
    cache[key] = tiles
    return tiles


def draw_round_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float = 10,
    *,
    fill: str = "",
    outline: str = "",
    width: float = 1,
    tags: str | tuple[str, ...] = (),
    background: str | None = None,
    corners: bool = True,
) -> None:
    """Draw an antialiased rounded rectangle on a Canvas."""

    x1, y1, x2, y2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
    if x2 <= x1 or y2 <= y1:
        return
    fill = _color(fill) if fill else ""
    outline = _color(outline) if outline else ""
    background = background or canvas.cget("background")
    radius = max(0, int(round(radius)))
    if radius <= 1:
        canvas.create_rectangle(
            x1, y1, x2, y2, fill=fill, outline=outline, width=width, tags=tags
        )
        return

    canvas.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline="", tags=tags)
    canvas.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline="", tags=tags)
    if outline:
        line_width = max(1, int(round(width)))
        offset = line_width // 2
        for start, end in (
            ((x1 + radius - 1, y1 + offset), (x2 - radius + 1, y1 + offset)),
            ((x1 + radius - 1, y2 - offset), (x2 - radius + 1, y2 - offset)),
            ((x1 + offset, y1 + radius - 1), (x1 + offset, y2 - radius + 1)),
            ((x2 - offset, y1 + radius - 1), (x2 - offset, y2 - radius + 1)),
        ):
            canvas.create_line(*start, *end, fill=outline, width=line_width, tags=tags)
    if corners:
        tiles = _corner_tiles(
            radius,
            fill or background,
            outline or fill or background,
            background,
            max(1, int(round(width))),
        )
        canvas.create_image(x1, y1, anchor="nw", image=tiles["nw"], tags=tags)
        canvas.create_image(x2 - radius, y1, anchor="nw", image=tiles["ne"], tags=tags)
        canvas.create_image(x1, y2 - radius, anchor="nw", image=tiles["sw"], tags=tags)
        canvas.create_image(x2 - radius, y2 - radius, anchor="nw", image=tiles["se"], tags=tags)


class Card(tk.Canvas):
    """Rounded white surface with a hairline border and soft offset shadow."""

    def __init__(
        self,
        master: tk.Widget,
        *,
        radius: int = 12,
        padding: tuple[int, int] = (0, 0),
        background: str | None = None,
        fill: str | None = None,
        border: str | None = None,
        shadow: bool = True,
        autosize: bool = True,
        min_height: int = 0,
        **kwargs: Any,
    ) -> None:
        palette = current_palette()
        self._background = background or palette.content
        self._fill = fill or palette.card
        self._border = border or palette.card_border
        self._show_shadow = shadow
        self._shadow_color = palette.shadow
        self._radius = radius
        self._padding = padding
        self._autosize = autosize
        self._min_height = min_height
        self._requested_height = -1
        super().__init__(
            master,
            background=self._background,
            borderwidth=0,
            highlightthickness=0,
            **kwargs,
        )
        self.body = tk.Frame(self, background=self._fill)
        self._window = self.create_window(
            padding[0],
            padding[1],
            anchor="nw",
            window=self.body,
        )
        self._corner_labels = {
            name: tk.Label(
                self,
                borderwidth=0,
                highlightthickness=0,
                background=self._background,
            )
            for name in ("nw", "ne", "sw", "se")
        }
        self.bind("<Configure>", self._on_configure)
        self.body.bind("<Configure>", self._on_body_configure)
        self.after_idle(self._refresh_requested_size)

    def _draw(self, width: int, height: int) -> None:
        self.delete("surface")
        if width <= 2 or height <= 2:
            return
        if self._show_shadow:
            draw_round_rect(
                self,
                1,
                2,
                width - 1,
                height,
                self._radius,
                fill=self._shadow_color,
                background=self._background,
                tags="surface",
            )
        draw_round_rect(
            self,
            1,
            1,
            width - 1,
            height - 1,
            self._radius,
            fill=self._fill,
            outline=self._border,
            background=self._background,
            tags="surface",
            corners=False,
        )
        self.tag_lower("surface")
        self._place_corner_labels(width, height)

    def _place_corner_labels(self, width: int, height: int) -> None:
        radius = self._radius
        if radius <= 1 or width <= 2 * radius or height <= 2 * radius:
            return
        tiles = _corner_tiles(radius, self._fill, self._border, self._background)
        positions = {
            "nw": (1, 1),
            "ne": (width - radius - 1, 1),
            "sw": (1, height - radius - 1),
            "se": (width - radius - 1, height - radius - 1),
        }
        for name, label in self._corner_labels.items():
            label.configure(image=tiles[name])
            x, y = positions[name]
            label.place(x=x, y=y, width=radius, height=radius)
            label.lift()

    def _on_configure(self, event: tk.Event) -> None:
        self._draw(event.width, event.height)
        inner_width = max(1, event.width - 2 * self._padding[0])
        if self._autosize:
            # Let the body keep its requested height so content growth and
            # shrinkage trigger a <Configure> event and resize the card.
            self.itemconfigure(self._window, width=inner_width)
        else:
            self.itemconfigure(
                self._window,
                width=inner_width,
                height=max(1, event.height - 2 * self._padding[1]),
            )

    def _on_body_configure(self, _event: tk.Event | None = None) -> None:
        if not self._autosize:
            return
        height = max(self._min_height, self.body.winfo_reqheight() + 2 * self._padding[1])
        if height != self._requested_height and height > 0:
            self._requested_height = height
            self.configure(height=height)

    def _refresh_requested_size(self) -> None:
        self._on_body_configure(None)
        self._draw(max(1, self.winfo_width()), max(1, self.winfo_height()))


_BUTTON_STYLES: dict[str, dict[str, Any]] = {
    "primary": {
        "background": "accent",
        "hover": "accent_hover",
        "pressed": "accent_pressed",
        "foreground": "#ffffff",
        "foreground_disabled": "text2",
        "border": "",
        "height": 44,
        "radius": 11,
        "padx": 18,
        "font": "button",
    },
    "secondary": {
        "background": "card",
        "hover": "fill",
        "pressed": "fill_strong",
        "foreground": "text",
        "foreground_disabled": "text3",
        "border": "field_border",
        "height": 44,
        "radius": 11,
        "padx": 18,
        "font": "button",
    },
    "pill": {
        "background": "fill",
        "hover": "fill_strong",
        "pressed": "fill_strong",
        "foreground": "text",
        "foreground_disabled": "text3",
        "border": "",
        "height": 28,
        "radius": 8,
        "padx": 12,
        "font": "small_bold",
    },
    "small": {
        "background": "fill",
        "hover": "fill_strong",
        "pressed": "fill_strong",
        "foreground": "text",
        "foreground_disabled": "text3",
        "border": "",
        "height": 26,
        "radius": 7,
        "padx": 11,
        "font": "small_bold",
    },
    "ghost": {
        "background": None,
        "hover": "fill",
        "pressed": "fill_strong",
        "foreground": "text2",
        "foreground_disabled": "text3",
        "border": "",
        "height": 30,
        "radius": 7,
        "padx": 6,
        "font": "button",
    },
    "link": {
        "background": None,
        "hover": None,
        "pressed": None,
        "foreground": "accent",
        "foreground_disabled": "text3",
        "border": "",
        "height": 22,
        "radius": 0,
        "padx": 1,
        "font": "small",
    },
}


class RoundedButton(tk.Canvas):
    """A rounded, hover-aware push button drawn on a Canvas."""

    def __init__(
        self,
        master: tk.Widget,
        text: str = "",
        command: Callable[[], Any] | None = None,
        *,
        style: str = "secondary",
        background: str | None = None,
        image: tk.PhotoImage | None = None,
        icon_text_gap: int = 7,
        width: int | None = None,
        height: int | None = None,
        font: tkfont.Font | None = None,
        **kwargs: Any,
    ) -> None:
        palette = current_palette()
        fonts = current_fonts()
        spec = _BUTTON_STYLES.get(style, _BUTTON_STYLES["secondary"])
        self._style = style
        self._spec = spec
        self._text = text
        self._command = command
        self._image = image
        self._state = "normal"
        self._hovered = False
        self._pressed = False
        self._focused = False
        self._font = font or getattr(fonts, spec["font"])
        self._background = background or palette.content
        self._icon_gap = icon_text_gap
        self._fixed_width = width
        self._height = height or spec["height"]
        self._width = width or 10
        self._hover_font: tkfont.Font | None = None
        if style == "link":
            self._hover_font = tkfont.Font(
                root=master,
                family=self._font.actual("family"),
                size=self._font.actual("size"),
                weight=self._font.actual("weight"),
                underline=1,
            )
        super().__init__(
            master,
            background=self._background,
            borderwidth=0,
            highlightthickness=0,
            takefocus=1,
            **kwargs,
        )
        self._measure()
        self._draw()
        self.bind("<Configure>", self._on_configure)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<space>", self._on_key)
        self.bind("<Return>", self._on_key)

    # -- ttk-compatible API -------------------------------------------------

    def cget(self, key: str) -> Any:
        if key == "state":
            return self._state
        if key == "text":
            return self._text
        if key == "command":
            return self._command
        return super().cget(key)

    def configure(self, cnf: dict[str, Any] | None = None, **kwargs: Any) -> None:
        changed = False
        if cnf:
            kwargs = {**cnf, **kwargs}
        if "state" in kwargs:
            self._state = str(kwargs.pop("state"))
            changed = True
        if "text" in kwargs:
            self._text = str(kwargs.pop("text"))
            changed = True
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if "image" in kwargs:
            self._image = kwargs.pop("image")
            changed = True
        if "background" in kwargs:
            self._background = kwargs.pop("background")
            super().configure(background=self._background)
            changed = True
        if kwargs:
            super().configure(**kwargs)
        if changed:
            self._measure()
            self._draw()

    config = configure

    def invoke(self) -> None:
        if self._state == "normal" and self._command is not None:
            self._command()

    # -- geometry and painting ---------------------------------------------

    def _content_size(self) -> tuple[int, int]:
        text_width = self._font.measure(self._text) if self._text else 0
        icon_width = self._image.width() if self._image is not None else 0
        gap = self._icon_gap if text_width and icon_width else 0
        return text_width + icon_width + gap, max(text_width, icon_width)

    def _measure(self) -> None:
        content_width, _ = self._content_size()
        width = self._fixed_width or (content_width + 2 * self._spec["padx"])
        self._width = max(8, int(width))
        super().configure(width=self._width, height=self._height)

    def _draw(self) -> None:
        palette = current_palette()
        spec = self._spec
        self.delete("all")
        actual_width = self.winfo_width()
        width = actual_width if actual_width > 1 else self._width
        height = self._height
        disabled = self._state != "normal"
        background_name = spec["background"]

        if background_name is not None:
            fill_name = background_name
            if not disabled:
                if self._pressed:
                    fill_name = spec["pressed"] or background_name
                elif self._hovered:
                    fill_name = spec["hover"] or background_name
            if disabled and self._style == "primary":
                fill = _color("fill")
            else:
                fill = _color(fill_name)
            border = _color(spec["border"]) if spec["border"] else ""
            if disabled and self._style == "secondary":
                fill = _color("content")
            if self._focused and not disabled and self._style != "link":
                draw_round_rect(
                    self,
                    1,
                    1,
                    width - 1,
                    height - 1,
                    spec["radius"],
                    fill=fill,
                    outline=palette.accent,
                )
            else:
                draw_round_rect(
                    self, 1, 1, width - 1, height - 1, spec["radius"], fill=fill, outline=border
                )
        elif self._focused and not disabled and self._style != "link":
            draw_round_rect(
                self,
                1,
                1,
                width - 1,
                height - 1,
                spec["radius"] or 7,
                fill=palette.accent_soft,
                outline=palette.accent,
            )
        elif self._hovered and not disabled and spec["hover"] is not None:
            draw_round_rect(
                self,
                1,
                1,
                width - 1,
                height - 1,
                spec["radius"] or 6,
                fill=_color(spec["hover"]),
            )

        style_is_link = self._style == "link"
        colour_name = spec["foreground_disabled"] if disabled else spec["foreground"]
        color = _color(colour_name)
        font = self._hover_font if self._style == "link" and self._hovered else self._font

        content_width, _ = self._content_size()
        start = max(2, (width - content_width) // 2)
        text_x = start
        if self._image is not None:
            icon_x = start + self._image.width() / 2
            self.create_image(icon_x, height / 2, image=self._image)
            text_x = start + self._image.width() + self._icon_gap
        if self._text:
            self.create_text(text_x, height / 2, text=self._text, anchor="w", fill=color, font=font)

    # -- events -------------------------------------------------------------

    def _on_configure(self, _event: tk.Event) -> None:
        self._draw()

    def _on_enter(self, _event: tk.Event) -> None:
        self._hovered = True
        self._draw()

    def _on_leave(self, _event: tk.Event) -> None:
        self._hovered = False
        self._pressed = False
        self._draw()

    def _on_press(self, _event: tk.Event) -> None:
        if self._state == "normal":
            self._pressed = True
            self.focus_set()
            self._draw()

    def _on_release(self, _event: tk.Event) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if was_pressed and self._state == "normal":
            self.invoke()

    def _on_key(self, _event: tk.Event) -> str:
        self.invoke()
        return "break"

    def _on_focus_in(self, _event: tk.Event) -> None:
        self._focused = True
        self._draw()

    def _on_focus_out(self, _event: tk.Event) -> None:
        self._focused = False
        self._draw()


class SegmentedControl(tk.Canvas):
    """Apple-style segmented picker bound to a ``StringVar``."""

    def __init__(
        self,
        master: tk.Widget,
        variable: tk.StringVar,
        options: Sequence[tuple[str, str]],
        *,
        command: Callable[[], Any] | None = None,
        background: str | None = None,
        font: tkfont.Font | None = None,
        stretch: bool = False,
    ) -> None:
        palette = current_palette()
        fonts = current_fonts()
        self._variable = variable
        self._segments = list(options)
        self._command = command
        self._font = font or fonts.small_bold
        self._background = background or palette.card
        self._stretch = stretch
        self._focused = False
        self._segment_widths = [
            max(34, self._font.measure(label) + 10) for _, label in self._segments
        ]
        self._height = 30
        total = sum(self._segment_widths) + 4 + 2 * (len(self._segments) - 1)
        self._intrinsic_width = total
        super().__init__(
            master,
            width=total,
            height=self._height,
            background=self._background,
            borderwidth=0,
            highlightthickness=0,
            takefocus=1,
        )
        self._trace = variable.trace_add("write", self._on_variable_changed)
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<Left>", lambda _event: self._move(-1))
        self.bind("<Right>", lambda _event: self._move(1))
        self.bind("<Home>", lambda _event: self._select_index(0))
        self.bind("<End>", lambda _event: self._select_index(len(self._segments) - 1))
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self._draw()

    def _selected_index(self) -> int:
        current = self._variable.get()
        for index, (value, _label) in enumerate(self._segments):
            if value == current:
                return index
        return 0

    def _current_width(self) -> float:
        actual_width = self.winfo_width()
        return float(actual_width if actual_width > 1 else self._intrinsic_width)

    def _layout_widths(self) -> list[float]:
        if not self._segments:
            return []
        if not self._stretch:
            return list(self._segment_widths)
        width = self._current_width()
        available = max(
            float(len(self._segments)),
            width - 4 - 2 * (len(self._segments) - 1),
        )
        preferred = sum(self._segment_widths)
        scale = available / preferred if preferred else 1.0
        return [item * scale for item in self._segment_widths]

    def _segment_bounds(self, index: int) -> tuple[float, float]:
        widths = self._layout_widths()
        x = 2.0
        for item in widths[:index]:
            x += item + 2
        return x, x + widths[index]

    def _draw(self) -> None:
        palette = current_palette()
        self.delete("all")
        width = self._current_width()
        height = self._height
        draw_round_rect(self, 1, 1, width - 1, height - 1, 9, fill=palette.seg_track)
        selected = self._selected_index()
        x1, x2 = self._segment_bounds(selected)
        draw_round_rect(
            self,
            x1,
            3,
            x2,
            height - 3,
            7,
            fill=palette.seg_thumb,
            outline=palette.card_border,
            background=palette.seg_track,
        )
        for index, (_value, label) in enumerate(self._segments):
            left, right = self._segment_bounds(index)
            self.create_text(
                (left + right) / 2,
                height / 2,
                text=label,
                fill=palette.text,
                font=self._font,
            )
        if self._focused:
            draw_round_rect(
                self,
                1,
                1,
                width - 1,
                height - 1,
                9,
                outline=palette.accent,
                background=self._background,
            )

    def _on_variable_changed(self, *_args: Any) -> None:
        self._draw()

    def _on_click(self, event: tk.Event) -> None:
        for index, (value, _label) in enumerate(self._segments):
            left, right = self._segment_bounds(index)
            if left <= event.x <= right:
                self.focus_set()
                self._variable.set(value)
                if self._command is not None:
                    self._command()
                return

    def _select_index(self, index: int) -> str:
        if self._segments:
            self._variable.set(self._segments[max(0, min(len(self._segments) - 1, index))][0])
            if self._command is not None:
                self._command()
        return "break"

    def _move(self, direction: int) -> str:
        return self._select_index(self._selected_index() + direction)

    def _on_focus_in(self, _event: tk.Event) -> None:
        self._focused = True
        self._draw()

    def _on_focus_out(self, _event: tk.Event) -> None:
        self._focused = False
        self._draw()


class SearchField(tk.Canvas):
    """Rounded text field with a leading icon, placeholder, and accessory."""

    def __init__(
        self,
        master: tk.Widget,
        textvariable: tk.StringVar,
        *,
        placeholder: str,
        font: tkfont.Font | None = None,
        icon: tk.PhotoImage | None = None,
        background: str | None = None,
    ) -> None:
        palette = current_palette()
        fonts = current_fonts()
        self._variable = textvariable
        self._font = font or fonts.base
        self._icon = icon
        self._background = background or palette.content
        self._height = 44
        self._focused = False
        self._accessory: tk.Widget | None = None
        self._accessory_window: int | None = None
        super().__init__(
            master,
            height=self._height,
            background=self._background,
            borderwidth=0,
            highlightthickness=0,
        )
        self.entry = tk.Entry(
            self,
            textvariable=textvariable,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            background=palette.field,
            foreground=palette.text,
            insertbackground=palette.text,
            selectbackground=palette.selection,
            selectforeground=palette.selection_text,
            font=self._font,
        )
        self._entry_window = self.create_window(42, self._height / 2, anchor="w", window=self.entry)
        self._placeholder = tk.Label(
            self,
            text=placeholder,
            background=palette.field,
            foreground=palette.text3,
            font=self._font,
        )
        self._placeholder.bind("<Button-1>", lambda _event: self.entry.focus_set())
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self._variable.trace_add("write", lambda *_args: self._update_placeholder())
        self._placeholder_visible = False
        self.bind("<Configure>", self._on_configure)
        self.after_idle(self._layout)

    def set_accessory(self, widget: tk.Widget) -> None:
        self._accessory = widget
        self._accessory_window = self.create_window(0, 0, anchor="e", window=widget)
        self.after_idle(self._layout)

    def _on_configure(self, _event: tk.Event) -> None:
        self._layout()

    def _layout(self) -> None:
        palette = current_palette()
        width = max(40, self.winfo_width())
        height = self._height
        self.delete("surface")
        draw_round_rect(
            self,
            1,
            1,
            width - 1,
            height - 1,
            11,
            fill=palette.field,
            outline=palette.field_focus if self._focused else palette.field_border,
            tags="surface",
        )
        if self._icon is not None:
            self.create_image(24, height / 2, image=self._icon, tags="surface")
        accessory_width = 0
        if self._accessory is not None and self._accessory_window is not None:
            accessory_width = self._accessory.winfo_reqwidth() + 18
            self.coords(self._accessory_window, width - 8, height / 2)
        left = 42
        self.coords(self._entry_window, left, height / 2)
        self.itemconfigure(
            self._entry_window,
            width=max(40, width - left - accessory_width - 8),
            height=height - 12,
        )
        self._update_placeholder()

    def _on_focus_in(self, _event: tk.Event) -> None:
        self._focused = True
        self._layout()

    def _on_focus_out(self, _event: tk.Event) -> None:
        self._focused = False
        self._layout()

    def _update_placeholder(self) -> None:
        should_show = not self._variable.get() and not self._focused
        if should_show and not self._placeholder_visible:
            self._placeholder.place(x=42, rely=0.5, anchor="w")
            self._placeholder_visible = True
        elif not should_show and self._placeholder_visible:
            self._placeholder.place_forget()
            self._placeholder_visible = False


class ThinProgress(tk.Canvas):
    """4 px progress bar used inside queue rows."""

    def __init__(self, master: tk.Widget, *, background: str | None = None) -> None:
        palette = current_palette()
        self._background = background or palette.card
        self._value = 0.0
        self._indeterminate = False
        self._after: str | None = None
        self._offset = 0.0
        super().__init__(
            master,
            height=4,
            background=self._background,
            borderwidth=0,
            highlightthickness=0,
        )
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Destroy>", self._on_destroy)

    def set_value(self, value: float | None) -> None:
        self._indeterminate = value is None
        if value is not None:
            self._value = max(0.0, min(100.0, value))
        self._draw()
        if self._indeterminate and self._after is None:
            self._tick()

    def _tick(self) -> None:
        if not self._indeterminate or not self.winfo_exists():
            self._after = None
            return
        self._offset = (self._offset + 0.035) % 1.0
        self._draw()
        self._after = self.after(45, self._tick)

    def _draw(self) -> None:
        palette = current_palette()
        self.delete("all")
        width = self.winfo_width()
        if width <= 2:
            return
        draw_round_rect(self, 0, 0, width, 4, 2, fill=palette.fill)
        if self._indeterminate:
            segment = width * 0.3
            start = (width + segment) * self._offset - segment
            x1 = max(0, start)
            x2 = min(width, start + segment)
            if x2 > x1:
                draw_round_rect(
                    self,
                    x1,
                    0,
                    x2,
                    4,
                    2,
                    fill=palette.accent,
                    background=palette.fill,
                )
        else:
            filled = width * self._value / 100.0
            if filled > 1:
                draw_round_rect(
                    self,
                    0,
                    0,
                    filled,
                    4,
                    2,
                    fill=palette.accent,
                    background=palette.fill,
                )

    def _on_destroy(self, _event: tk.Event) -> None:
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None


class StatusDot(tk.Canvas):
    def __init__(self, master: tk.Widget, *, color: str | None = None, background: str | None = None) -> None:
        palette = current_palette()
        self._color = color or palette.green
        self._background = background or palette.content
        super().__init__(
            master,
            width=16,
            height=16,
            background=self._background,
            borderwidth=0,
            highlightthickness=0,
        )
        self._image = _dot_image(self._color, self._background)
        self.create_image(8, 8, image=self._image)


class ScrollFrame(tk.Frame):
    """Vertically scrollable page whose scrollbar appears only when needed."""

    def __init__(self, master: tk.Widget, *, background: str | None = None, padding: tuple[int, int] = (0, 0)) -> None:
        palette = current_palette()
        self._background = background or palette.content
        super().__init__(master, background=self._background)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            self,
            background=self._background,
            borderwidth=0,
            highlightthickness=0,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.inner = tk.Frame(self.canvas, background=self._background)
        self.inner.columnconfigure(0, weight=1)
        self._window = self.canvas.create_window(
            padding[0],
            padding[1],
            window=self.inner,
            anchor="nw",
        )
        self._padding = padding
        self._scrollbar_visible = True
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")
        self.canvas.bind_all("<Button-4>", self._on_wheel, add="+")
        self.canvas.bind_all("<Button-5>", self._on_wheel, add="+")

    def _sync_scrollregion(self) -> None:
        bbox = self.canvas.bbox("all")
        if bbox is None:
            return
        # Tk 9 centres a scroll region that is smaller than the viewport, which
        # cancelled out the page padding after the first resize.  Anchor the
        # region at (0, 0) and never let it be smaller than the viewport.
        width = max(self.canvas.winfo_width(), bbox[2])
        height = max(self.canvas.winfo_height(), bbox[3])
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def _on_inner_configure(self, _event: tk.Event) -> None:
        self._sync_scrollregion()
        self._update_scrollbar()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(
            self._window,
            width=max(1, event.width - 2 * self._padding[0]),
        )
        self._sync_scrollregion()
        self._update_scrollbar()

    def _update_scrollbar(self) -> None:
        try:
            needed = self.inner.winfo_reqheight() > self.canvas.winfo_height() + 2
        except tk.TclError:
            return
        if needed == self._scrollbar_visible:
            if not needed:
                self.canvas.yview_moveto(0)
            return
        self._scrollbar_visible = needed
        if needed:
            self.scrollbar.grid()
        else:
            self.canvas.yview_moveto(0)
            self.scrollbar.grid_remove()

    def _on_wheel(self, event: tk.Event) -> None:
        if not self._scrollbar_visible:
            return
        try:
            under_pointer = self.canvas.winfo_containing(event.x_root, event.y_root)
        except tk.TclError:
            return
        if under_pointer is None:
            return
        path = str(under_pointer)
        if not (path == str(self.canvas) or path.startswith(str(self.canvas) + ".")):
            return
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta * 2, "units")


def _dot_image(color: str, background: str, size: int = 16) -> tk.PhotoImage:
    color = _color(color)
    background = _color(background)
    halo = _mix(color, background, 0.78)
    image = tk.PhotoImage(width=size, height=size)
    center = size / 2
    samples = 4
    total = samples * samples
    for y in range(size):
        row: list[str] = []
        for x in range(size):
            halo_count = 0
            dot_count = 0
            for sy in range(samples):
                py = y + (sy + 0.5) / samples
                for sx in range(samples):
                    px = x + (sx + 0.5) / samples
                    distance = math.hypot(px - center, py - center)
                    if distance <= 7:
                        halo_count += 1
                        if distance <= 3.6:
                            dot_count += 1
            if halo_count == 0:
                value = background
            else:
                value = _mix(background, halo, halo_count / total)
                if dot_count:
                    value = _mix(value, color, dot_count / total)
            row.append(value)
        image.put("{" + " ".join(row) + "}", to=(0, y))
    return image


def separator(master: tk.Widget, *, background: str | None = None) -> tk.Frame:
    palette = current_palette()
    line = tk.Frame(master, height=1, background=background or palette.sep)
    line.pack_propagate(False)
    return line
