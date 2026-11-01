"""Apple-inspired light/dark theme for TubeGrab.

Tkinter cannot render CSS shadows or backdrop blurs, so the palette, type
scale, and spacing follow the design mockup while rounded surfaces are drawn
on Canvas widgets in :mod:`tubegrab.widgets`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from tkinter import ttk


@dataclass(frozen=True)
class Palette:
    name: str
    window: str
    content: str
    card: str
    card_border: str
    shadow: str
    text: str
    text2: str
    text3: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    green: str
    red: str
    amber: str
    fill: str
    fill_strong: str
    sep: str
    field: str
    field_border: str
    field_focus: str
    seg_track: str
    seg_thumb: str
    thumb_top: str
    thumb_middle: str
    thumb_bottom: str
    notice_bg: str
    notice_text: str
    log_bg: str
    log_text: str
    selection: str
    selection_text: str


LIGHT = Palette(
    name="light",
    window="#ffffff",
    content="#f5f5f7",
    card="#ffffff",
    card_border="#e3e3e6",
    shadow="#ececf0",
    text="#1d1d1f",
    text2="#6e6e73",
    text3="#a1a1a6",
    accent="#007aff",
    accent_hover="#0a84ff",
    accent_pressed="#0063cc",
    accent_soft="#e5f1ff",
    green="#007aff",
    red="#ff3b30",
    amber="#007aff",
    fill="#ececef",
    fill_strong="#dedee3",
    sep="#e6e6ea",
    field="#ffffff",
    field_border="#d8d8dd",
    field_focus="#007aff",
    seg_track="#ececef",
    seg_thumb="#ffffff",
    thumb_top="#d1d1d6",
    thumb_middle="#a1a1a6",
    thumb_bottom="#6e6e73",
    notice_bg="#ececef",
    notice_text="#007aff",
    log_bg="#f5f5f7",
    log_text="#1d1d1f",
    selection="#cfe7ff",
    selection_text="#1d1d1f",
)

DARK = Palette(
    name="dark",
    window="#1e1e1e",
    content="#1c1c1e",
    card="#2a2a2c",
    card_border="#3a3a3e",
    shadow="#151517",
    text="#f5f5f7",
    text2="#a5a5ad",
    text3="#6b6b72",
    accent="#0a84ff",
    accent_hover="#3d9bff",
    accent_pressed="#0063cc",
    accent_soft="#14324f",
    green="#0a84ff",
    red="#ff453a",
    amber="#0a84ff",
    fill="#343437",
    fill_strong="#45454a",
    sep="#333336",
    field="#2a2a2c",
    field_border="#414146",
    field_focus="#0a84ff",
    seg_track="#343437",
    seg_thumb="#636366",
    thumb_top="#49494d",
    thumb_middle="#3a3a3d",
    thumb_bottom="#2b2b2e",
    notice_bg="#343437",
    notice_text="#0a84ff",
    log_bg="#1c1c1e",
    log_text="#e5e5e7",
    selection="#31557a",
    selection_text="#ffffff",
)

_PALETTE = LIGHT
_FONTS: "Fonts | None" = None


def current_palette() -> Palette:
    return _PALETTE


def current_fonts() -> "Fonts":
    assert _FONTS is not None, "apply_theme() must run before creating widgets"
    return _FONTS


def detect_appearance() -> str:
    """Return ``light`` or ``dark`` using the GNOME session preference."""

    override = os.environ.get("TUBEGRAB_THEME", "").strip().lower()
    if override in {"light", "dark"}:
        return override

    if shutil.which("gsettings"):
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if "prefer-dark" in result.stdout:
                return "dark"
            theme = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if "dark" in theme.stdout.lower():
                return "dark"
        except (OSError, subprocess.SubprocessError):
            pass

    gtk_theme = os.environ.get("GTK_THEME", "").lower()
    if "dark" in gtk_theme:
        return "dark"
    return "light"


def _font_family(families: set[str], candidates: tuple[str, ...], fallback: str) -> str:
    for candidate in candidates:
        if candidate.lower() in families:
            return families[candidate.lower()]
    return fallback


@dataclass
class Fonts:
    base: tkfont.Font
    base_bold: tkfont.Font
    small: tkfont.Font
    small_bold: tkfont.Font
    tiny: tkfont.Font
    section: tkfont.Font
    title: tkfont.Font
    subtitle: tkfont.Font
    mono: tkfont.Font
    button: tkfont.Font
    row_title: tkfont.Font


def apply_theme(root: tk.Tk) -> Fonts:
    global _PALETTE, _FONTS

    palette = DARK if detect_appearance() == "dark" else LIGHT
    _PALETTE = palette

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    families = {name.lower(): name for name in tkfont.families(root)}
    base_family = _font_family(
        families,
        (
            "sf pro text",
            "sf pro display",
            "inter",
            "adwaita sans",
            "cantarell",
            "noto sans",
            "liberation sans",
            "dejavu sans",
        ),
        tkfont.nametofont("TkDefaultFont").actual("family"),
    )
    mono_family = _font_family(
        families,
        ("sf mono", "adwaita mono", "jetbrains mono", "noto sans mono", "liberation mono", "dejavu sans mono"),
        tkfont.nametofont("TkFixedFont").actual("family"),
    )

    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name).configure(family=base_family, size=10)
        except tk.TclError:
            pass
    try:
        tkfont.nametofont("TkFixedFont").configure(family=mono_family, size=9)
    except tk.TclError:
        pass

    fonts = Fonts(
        base=tkfont.Font(root=root, family=base_family, size=10),
        base_bold=tkfont.Font(root=root, family=base_family, size=10, weight="bold"),
        small=tkfont.Font(root=root, family=base_family, size=9),
        small_bold=tkfont.Font(root=root, family=base_family, size=9, weight="bold"),
        tiny=tkfont.Font(root=root, family=base_family, size=8),
        section=tkfont.Font(root=root, family=base_family, size=8, weight="bold"),
        title=tkfont.Font(root=root, family=base_family, size=12, weight="bold"),
        subtitle=tkfont.Font(root=root, family=base_family, size=9),
        mono=tkfont.Font(root=root, family=mono_family, size=9),
        button=tkfont.Font(root=root, family=base_family, size=10),
        row_title=tkfont.Font(root=root, family=base_family, size=10, weight="bold"),
    )
    _FONTS = fonts

    root.configure(background=palette.content)
    root.option_add("*Menu.background", palette.card)
    root.option_add("*Menu.foreground", palette.text)
    root.option_add("*Menu.activeBackground", palette.accent)
    root.option_add("*Menu.activeForeground", "#ffffff")
    root.option_add("*Menu.selectColor", palette.accent)
    root.option_add("*Menu.relief", "flat")
    root.option_add("*Menu.borderWidth", "0")
    root.option_add("*Menu.font", fonts.base)
    root.option_add("*TCombobox*Listbox.background", palette.card)
    root.option_add("*TCombobox*Listbox.foreground", palette.text)
    root.option_add("*TCombobox*Listbox.selectBackground", palette.accent)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", fonts.base)

    style.configure("TFrame", background=palette.content)
    style.configure("Card.TFrame", background=palette.card)
    style.configure("Status.TFrame", background=palette.content)

    style.configure("TLabel", background=palette.content, foreground=palette.text, font=fonts.base)
    style.configure("Muted.TLabel", background=palette.content, foreground=palette.text2, font=fonts.small)
    style.configure("Faint.TLabel", background=palette.content, foreground=palette.text3, font=fonts.small)
    style.configure("Title.TLabel", background=palette.content, foreground=palette.text, font=fonts.title)
    style.configure("Subtitle.TLabel", background=palette.content, foreground=palette.text2, font=fonts.subtitle)
    style.configure("Section.TLabel", background=palette.content, foreground=palette.text2, font=fonts.section)
    style.configure("Error.TLabel", background=palette.content, foreground=palette.red, font=fonts.small)
    style.configure(
        "Warning.TLabel",
        background=palette.notice_bg,
        foreground=palette.notice_text,
        font=fonts.small,
        padding=(12, 9),
    )
    style.configure("Card.TLabel", background=palette.card, foreground=palette.text, font=fonts.base)
    style.configure("CardBold.TLabel", background=palette.card, foreground=palette.text, font=fonts.base_bold)
    style.configure("CardMuted.TLabel", background=palette.card, foreground=palette.text2, font=fonts.small)
    style.configure("CardError.TLabel", background=palette.card, foreground=palette.red, font=fonts.small)
    style.configure("CardSuccess.TLabel", background=palette.card, foreground=palette.green, font=fonts.small)
    style.configure("QueueTitle.TLabel", background=palette.card, foreground=palette.text, font=fonts.row_title)
    style.configure("QueueMuted.TLabel", background=palette.card, foreground=palette.text2, font=fonts.small)
    style.configure("QueueError.TLabel", background=palette.card, foreground=palette.red, font=fonts.small)
    style.configure("QueueSuccess.TLabel", background=palette.card, foreground=palette.green, font=fonts.small)
    style.configure("Status.TLabel", background=palette.content, foreground=palette.text2, font=fonts.small)
    style.configure("StatusMuted.TLabel", background=palette.content, foreground=palette.text2, font=fonts.small)

    style.configure(
        "TButton",
        font=fonts.button,
        padding=(12, 7),
        anchor="center",
        relief="flat",
        borderwidth=0,
        background=palette.fill,
        foreground=palette.text,
        focuscolor=palette.accent,
    )
    style.map(
        "TButton",
        background=[("pressed", palette.fill_strong), ("active", palette.fill_strong), ("disabled", palette.content)],
        foreground=[("disabled", palette.text3)],
    )
    style.configure(
        "Accent.TButton",
        background=palette.accent,
        foreground="#ffffff",
        focuscolor=palette.accent,
    )
    style.map(
        "Accent.TButton",
        background=[("pressed", palette.accent_pressed), ("active", palette.accent_hover)],
        foreground=[("disabled", palette.text3)],
    )
    style.configure(
        "Ghost.TButton",
        background=palette.content,
        foreground=palette.text2,
    )
    style.map(
        "Ghost.TButton",
        background=[("pressed", palette.fill), ("active", palette.fill)],
        foreground=[("active", palette.text), ("disabled", palette.text3)],
    )

    style.configure(
        "Vertical.TScrollbar",
        background=palette.fill_strong,
        troughcolor=palette.content,
        bordercolor=palette.content,
        arrowcolor=palette.text3,
        lightcolor=palette.fill_strong,
        darkcolor=palette.fill_strong,
        width=10,
        arrowsize=10,
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("pressed", palette.accent), ("active", palette.text3)],
    )
    style.configure("TSeparator", background=palette.sep)
    style.configure(
        "TEntry",
        fieldbackground=palette.field,
        foreground=palette.text,
        insertcolor=palette.text,
        bordercolor=palette.field_border,
        lightcolor=palette.field_border,
        darkcolor=palette.field_border,
        padding=(8, 7),
        relief="flat",
    )
    return fonts
