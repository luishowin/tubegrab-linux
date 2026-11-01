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
from typing import Any, Callable, Iterable, Sequence

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


def _round_points(x1: float, y1: float, x2: float, y2: float, radius: float) -> list[float]:
    radius = max(0.0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [x1 + radius, y1, x2 - radius, y1]
    corners = (
        (x2 - radius, y1 + radius, -90, 0),
        (x2 - radius, y2 - radius, 0, 90),
        (x1 + radius, y2 - radius, 90, 180),
        (x1 + radius, y1 + radius, 180, 270),
    )
    steps = 8
    for center_x, center_y, start, end in corners:
        for index in range(steps + 1):
            angle = math.radians(start + (end - start) * index / steps)
            points.extend(
                [
                    center_x + radius * math.cos(angle),
                    center_y + radius * math.sin(angle),
                ]
            )
    return points


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
) -> int:
    return canvas.create_polygon(
        _round_points(x1, y1, x2, y2, radius),
        smooth=False,
        fill=fill,
        outline=outline,
        width=width,
        tags=tags,
    )


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
        self._corners = {
            name: tk.Canvas(
                self,
                width=radius + 1,
                height=radius + 1,
                background=self._fill,
                borderwidth=0,
                highlightthickness=0,
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
            tags="surface",
        )
        self.tag_lower("surface")
        self._draw_corners(width, height)

    def _draw_corners(self, width: int, height: int) -> None:
        radius = self._radius
        if radius <= 0:
            return
        size = radius + 1
        positions = {
            "nw": (1, 1),
            "ne": (width - size - 1, 1),
            "sw": (1, height - size - 1),
            "se": (width - size - 1, height - size - 1),
        }
        for name, canvas in self._corners.items():
            x, y = positions[name]
            canvas.place(x=x, y=y, width=size, height=size)
            canvas.tk.call("raise", canvas._w)
            self._paint_corner(name, canvas, size)

    def _paint_corner(self, name: str, canvas: tk.Canvas, size: int) -> None:
        canvas.delete("all")
        canvas.configure(background=self._fill)
        radius = size - 1
        centers = {
            "nw": (radius, radius),
            "ne": (0, radius),
            "sw": (radius, 0),
            "se": (0, 0),
        }
        starts = {"nw": -90, "ne": 0, "sw": 90, "se": 90}
        ends = {"nw": -180, "ne": -90, "sw": 180, "se": 0}
        center_x, center_y = centers[name]
        start, end = starts[name], ends[name]
        steps = 8
        points: list[float] = []
        for index in range(steps + 1):
            angle = math.radians(start + (end - start) * index / steps)
            points.extend(
                [
                    center_x + radius * math.cos(angle),
                    center_y + radius * math.sin(angle),
                ]
            )
        if name == "nw":
            polygon = [0, 0, radius, 0] + points
        elif name == "ne":
            polygon = [0, 0, radius, 0, radius, radius] + points
        elif name == "sw":
            polygon = [0, 0, 0, radius, radius, radius] + points
        else:
            polygon = [radius, 0, radius, radius, 0, radius] + points
        canvas.create_polygon(polygon, fill=self._background, outline="")
        bbox = {
            "nw": (0, 0, 2 * radius, 2 * radius),
            "ne": (-radius, 0, radius, 2 * radius),
            "sw": (0, -radius, 2 * radius, radius),
            "se": (-radius, -radius, radius, radius),
        }[name]
        arc_start = {"nw": 90, "ne": 0, "sw": 90, "se": 0}[name]
        canvas.create_arc(
            *bbox,
            start=arc_start,
            extent=90,
            style="arc",
            outline=self._border,
            width=1,
        )

    def _on_configure(self, event: tk.Event) -> None:
        self._draw(event.width, event.height)
        inner_width = max(1, event.width - 2 * self._padding[0])
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
        "foreground_disabled": "#ffffff",
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
            cursor="hand2",
            **kwargs,
        )
        self._measure()
        self._draw()
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
        width = max(self._width, self.winfo_width() or self._width)
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
                fill = _mix(palette.accent, palette.content, 0.55)
            else:
                fill = _color(fill_name)
            border = _color(spec["border"]) if spec["border"] else ""
            if disabled and self._style == "secondary":
                fill = _color("content")
            draw_round_rect(self, 1, 1, width - 1, height - 1, spec["radius"], fill=fill, outline=border)
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

        if self._focused and not style_is_link:
            draw_round_rect(
                self,
                1,
                1,
                width - 1,
                height - 1,
                spec["radius"],
                outline=getattr(palette, "accent"),
                width=2,
            )

    # -- events -------------------------------------------------------------

    def _on_enter(self, _event: tk.Event) -> None:
        self._hovered = True
        self.configure(cursor="hand2")
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
    ) -> None:
        palette = current_palette()
        fonts = current_fonts()
        self._variable = variable
        self._segments = list(options)
        self._command = command
        self._font = font or fonts.small_bold
        self._background = background or palette.card
        self._segment_widths = [
            max(50, self._font.measure(label) + 26) for _, label in self._segments
        ]
        self._height = 30
        total = sum(self._segment_widths) + 4 + 2 * (len(self._segments) - 1)
        super().__init__(
            master,
            width=total,
            height=self._height,
            background=self._background,
            borderwidth=0,
            highlightthickness=0,
            takefocus=1,
            cursor="hand2",
        )
        self._trace = variable.trace_add("write", self._on_variable_changed)
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<Left>", lambda _event: self._move(-1))
        self.bind("<Right>", lambda _event: self._move(1))
        self._draw()

    def _selected_index(self) -> int:
        current = self._variable.get()
        for index, (value, _label) in enumerate(self._segments):
            if value == current:
                return index
        return 0

    def _segment_bounds(self, index: int) -> tuple[float, float]:
        x = 2 + sum(self._segment_widths[:index]) + 2 * index
        return x, x + self._segment_widths[index]

    def _draw(self) -> None:
        palette = current_palette()
        self.delete("all")
        width = max(self.winfo_width() or 0, sum(self._segment_widths) + 4 + 2 * (len(self._segments) - 1))
        height = self._height
        draw_round_rect(self, 1, 1, width - 1, height - 1, 9, fill=palette.seg_track)
        selected = self._selected_index()
        x1, x2 = self._segment_bounds(selected)
        draw_round_rect(self, x1, 3, x2, height - 3, 7, fill=palette.seg_thumb, outline=palette.card_border)
        for index, (_value, label) in enumerate(self._segments):
            left, right = self._segment_bounds(index)
            self.create_text(
                (left + right) / 2,
                height / 2,
                text=label,
                fill=palette.text,
                font=self._font,
            )

    def _on_variable_changed(self, *_args: Any) -> None:
        self._draw()

    def _on_click(self, event: tk.Event) -> None:
        for index, (value, _label) in enumerate(self._segments):
            left, right = self._segment_bounds(index)
            if left <= event.x <= right:
                self._variable.set(value)
                if self._command is not None:
                    self._command()
                return

    def _move(self, direction: int) -> str:
        index = max(0, min(len(self._segments) - 1, self._selected_index() + direction))
        self._variable.set(self._segments[index][0])
        if self._command is not None:
            self._command()
        return "break"


class PopupSelect(tk.Canvas):
    """Compact pop-up menu control matching the mockup's quality picker."""

    def __init__(
        self,
        master: tk.Widget,
        variable: tk.StringVar,
        values: Iterable[str],
        *,
        command: Callable[[], Any] | None = None,
        background: str | None = None,
        font: tkfont.Font | None = None,
        chevron: tk.PhotoImage | None = None,
    ) -> None:
        palette = current_palette()
        fonts = current_fonts()
        self._variable = variable
        self._values = list(values)
        self._command = command
        self._font = font or fonts.small
        self._background = background or palette.card
        self._chevron = chevron
        self._hovered = False
        self._height = 26
        text_width = max((self._font.measure(item) for item in self._values), default=60)
        self._width = text_width + 46
        super().__init__(
            master,
            width=self._width,
            height=self._height,
            background=self._background,
            borderwidth=0,
            highlightthickness=0,
            takefocus=1,
            cursor="hand2",
        )
        self._menu = tk.Menu(self, tearoff=0)
        for item in self._values:
            self._menu.add_radiobutton(
                label=item,
                variable=self._variable,
                value=item,
                command=self._on_selected,
            )
        self._trace = variable.trace_add("write", lambda *_args: self._draw())
        self.bind("<Enter>", lambda _event: self._set_hover(True))
        self.bind("<Leave>", lambda _event: self._set_hover(False))
        self.bind("<Button-1>", self._open_menu)
        self.bind("<space>", self._open_menu)
        self.bind("<Return>", self._open_menu)
        self._draw()

    def _draw(self) -> None:
        palette = current_palette()
        self.delete("all")
        fill = palette.fill_strong if self._hovered else palette.fill
        draw_round_rect(self, 1, 1, self._width - 1, self._height - 1, 7, fill=fill)
        self.create_text(
            11,
            self._height / 2,
            text=self._variable.get(),
            anchor="w",
            fill=palette.text,
            font=self._font,
        )
        chevron_left = self._width - 23
        draw_round_rect(self, chevron_left, 3, self._width - 3, self._height - 3, 5, fill=palette.accent)
        if self._chevron is not None:
            self.create_image((chevron_left + self._width - 3) / 2, self._height / 2, image=self._chevron)
        else:
            self.create_text(
                (chevron_left + self._width - 3) / 2,
                self._height / 2,
                text="⌄",
                fill="#ffffff",
                font=self._font,
            )

    def _set_hover(self, hovered: bool) -> None:
        self._hovered = hovered
        self._draw()

    def _open_menu(self, event: tk.Event) -> str:
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()
        return "break"

    def _on_selected(self) -> None:
        if self._command is not None:
            self._command()


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
            cursor="xterm",
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
        border = palette.field_focus if self._focused else palette.field_border
        draw_round_rect(
            self,
            1,
            1,
            width - 1,
            height - 1,
            11,
            fill=palette.field,
            outline=border,
            width=2 if self._focused else 1,
            tags="surface",
        )
        if self._focused:
            draw_round_rect(
                self,
                0,
                0,
                width,
                height,
                12,
                outline=palette.accent_soft,
                width=2,
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
                draw_round_rect(self, x1, 0, x2, 4, 2, fill=palette.accent)
        else:
            filled = width * self._value / 100.0
            if filled > 1:
                draw_round_rect(self, 0, 0, filled, 4, 2, fill=palette.accent)

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
        self.create_oval(0, 1, 14, 15, fill=_mix(self._color, self._background, 0.78), outline="")
        self.create_oval(3, 4, 11, 12, fill=self._color, outline="")


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

    def _on_inner_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_scrollbar()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(
            self._window,
            width=max(1, event.width - 2 * self._padding[0]),
        )
        self._update_scrollbar()

    def _update_scrollbar(self) -> None:
        try:
            needed = self.inner.winfo_reqheight() > self.canvas.winfo_height() + 2
        except tk.TclError:
            return
        if needed == self._scrollbar_visible:
            return
        self._scrollbar_visible = needed
        if needed:
            self.scrollbar.grid()
        else:
            self.canvas.yview_moveto(0)
            self.scrollbar.grid_remove()

    def _on_wheel(self, event: tk.Event) -> None:
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


def separator(master: tk.Widget, *, background: str | None = None) -> tk.Frame:
    palette = current_palette()
    line = tk.Frame(master, height=1, background=background or palette.sep)
    line.pack_propagate(False)
    return line
