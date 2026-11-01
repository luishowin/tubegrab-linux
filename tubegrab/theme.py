"""Understated dark ttk theme for TubeGrab."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from tkinter import ttk

# Charcoal surfaces with a restrained GNOME-blue accent.
BG = "#252525"
SURFACE = "#2d2d2d"
SURFACE_ALT = "#343434"
INSET = "#222222"
FIELD = "#1f1f1f"
TRACK = "#202020"
STATUS_BG = "#202020"
BORDER = "#3d3d3d"
BORDER_HOVER = "#505050"
TEXT = "#f0f0f0"
MUTED = "#a6a6a6"
FAINT = "#7d7d7d"
ACCENT = "#3584e4"
ACCENT_HOVER = "#4a91e8"
ACCENT_PRESSED = "#2a75c9"
ACCENT_SOFT = "#2e4b68"
ACCENT_SOFT_HOVER = "#365a7d"
ACCENT_BORDER = "#5b8dbf"
ERROR = "#ff7b72"
WARNING = "#f0c674"
WARNING_BG = "#3a3128"
SUCCESS = "#8bd17c"
THUMB_BG = "#1b1b1b"


@dataclass
class Fonts:
    base: tkfont.Font
    base_bold: tkfont.Font
    small: tkfont.Font
    small_bold: tkfont.Font
    section: tkfont.Font
    title: tkfont.Font
    subtitle: tkfont.Font
    mono: tkfont.Font
    button: tkfont.Font
    row_title: tkfont.Font


def _font_family(families: set[str], candidates: tuple[str, ...], fallback: str) -> str:
    for candidate in candidates:
        if candidate in families:
            return candidate
    return fallback


def apply_theme(root: tk.Tk) -> Fonts:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    families = {name.lower(): name for name in tkfont.families(root)}
    base_family = _font_family(
        families,
        ("cantarell", "adwaita sans", "inter", "noto sans", "liberation sans", "dejavu sans"),
        tkfont.nametofont("TkDefaultFont").actual("family"),
    )
    mono_family = _font_family(
        families,
        ("adwaita mono", "jetbrains mono", "noto sans mono", "liberation mono", "dejavu sans mono"),
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
        section=tkfont.Font(root=root, family=base_family, size=10, weight="bold"),
        title=tkfont.Font(root=root, family=base_family, size=20, weight="bold"),
        subtitle=tkfont.Font(root=root, family=base_family, size=9),
        mono=tkfont.Font(root=root, family=mono_family, size=9),
        button=tkfont.Font(root=root, family=base_family, size=10),
        row_title=tkfont.Font(root=root, family=base_family, size=10, weight="bold"),
    )

    root.configure(background=BG)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("Inset.TFrame", background=INSET)
    style.configure("Header.TFrame", background=BG)
    style.configure("Status.TFrame", background=STATUS_BG)
    style.configure("Queue.TFrame", background=SURFACE)
    style.configure("QueueOuter.TFrame", background=BG)

    style.configure("TLabel", background=BG, foreground=TEXT, font=fonts.base)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=fonts.small)
    style.configure("Faint.TLabel", background=BG, foreground=FAINT, font=fonts.small)
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=fonts.title)
    style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=fonts.subtitle)
    style.configure("Section.TLabel", background=BG, foreground=TEXT, font=fonts.section)
    style.configure("Error.TLabel", background=BG, foreground=ERROR, font=fonts.small)
    style.configure(
        "Warning.TLabel",
        background=WARNING_BG,
        foreground=WARNING,
        font=fonts.small,
        padding=(12, 8),
    )

    style.configure("Card.TLabel", background=SURFACE, foreground=TEXT, font=fonts.base)
    style.configure("CardBold.TLabel", background=SURFACE, foreground=TEXT, font=fonts.base_bold)
    style.configure("CardMuted.TLabel", background=SURFACE, foreground=MUTED, font=fonts.small)
    style.configure("CardSection.TLabel", background=SURFACE, foreground=TEXT, font=fonts.section)
    style.configure("CardError.TLabel", background=SURFACE, foreground=ERROR, font=fonts.small)
    style.configure("CardSuccess.TLabel", background=SURFACE, foreground=SUCCESS, font=fonts.small)

    style.configure("Inset.TLabel", background=INSET, foreground=TEXT, font=fonts.base)
    style.configure("InsetTitle.TLabel", background=INSET, foreground=TEXT, font=fonts.base_bold)
    style.configure("InsetMuted.TLabel", background=INSET, foreground=MUTED, font=fonts.small)
    style.configure("InsetError.TLabel", background=INSET, foreground=ERROR, font=fonts.small)
    style.configure("InsetSection.TLabel", background=INSET, foreground=MUTED, font=fonts.small_bold)

    style.configure("Queue.TLabel", background=SURFACE, foreground=TEXT, font=fonts.base)
    style.configure("QueueTitle.TLabel", background=SURFACE, foreground=TEXT, font=fonts.row_title)
    style.configure("QueueMuted.TLabel", background=SURFACE, foreground=MUTED, font=fonts.small)
    style.configure("QueueError.TLabel", background=SURFACE, foreground=ERROR, font=fonts.small)
    style.configure("QueueSuccess.TLabel", background=SURFACE, foreground=SUCCESS, font=fonts.small)

    style.configure("Status.TLabel", background=STATUS_BG, foreground=TEXT, font=fonts.small)
    style.configure("StatusMuted.TLabel", background=STATUS_BG, foreground=MUTED, font=fonts.small)

    button_options = dict(
        font=fonts.button,
        padding=(12, 7),
        anchor="center",
        relief="flat",
        borderwidth=1,
        bordercolor=BORDER,
        lightcolor=SURFACE_ALT,
        darkcolor=SURFACE_ALT,
        background=SURFACE_ALT,
        foreground=TEXT,
        focuscolor=ACCENT,
    )
    style.configure("TButton", **button_options)
    style.map(
        "TButton",
        background=[("pressed", FIELD), ("active", BORDER_HOVER), ("disabled", SURFACE)],
        foreground=[("disabled", FAINT)],
        bordercolor=[("focus", ACCENT), ("active", BORDER_HOVER)],
        lightcolor=[("pressed", FIELD), ("active", BORDER_HOVER)],
        darkcolor=[("pressed", FIELD), ("active", BORDER_HOVER)],
    )

    style.configure(
        "Accent.TButton",
        **{
            **button_options,
            "background": ACCENT,
            "foreground": "#ffffff",
            "bordercolor": ACCENT,
            "lightcolor": ACCENT,
            "darkcolor": ACCENT,
        },
    )
    style.map(
        "Accent.TButton",
        background=[
            ("pressed", ACCENT_PRESSED),
            ("active", ACCENT_HOVER),
            ("disabled", "#3a4654"),
        ],
        foreground=[("disabled", "#9aa4ae")],
        bordercolor=[("pressed", ACCENT_PRESSED), ("active", ACCENT_HOVER), ("focus", "#9cc7ff")],
        lightcolor=[("pressed", ACCENT_PRESSED), ("active", ACCENT_HOVER)],
        darkcolor=[("pressed", ACCENT_PRESSED), ("active", ACCENT_HOVER)],
    )

    style.configure(
        "Ghost.TButton",
        **{**button_options, "background": SURFACE, "bordercolor": SURFACE, "lightcolor": SURFACE, "darkcolor": SURFACE, "foreground": MUTED},
    )
    style.map(
        "Ghost.TButton",
        background=[("pressed", SURFACE_ALT), ("active", SURFACE_ALT)],
        foreground=[("active", TEXT), ("disabled", FAINT)],
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("active", SURFACE_ALT)],
        darkcolor=[("active", SURFACE_ALT)],
    )

    style.configure(
        "Small.TButton",
        **{
            **button_options,
            "padding": (9, 4),
            "font": fonts.small,
            "background": SURFACE_ALT,
            "bordercolor": BORDER,
            "lightcolor": SURFACE_ALT,
            "darkcolor": SURFACE_ALT,
        },
    )
    style.map(
        "Small.TButton",
        background=[("pressed", FIELD), ("active", BORDER_HOVER), ("disabled", SURFACE)],
        foreground=[("disabled", FAINT)],
        bordercolor=[("focus", ACCENT), ("active", BORDER_HOVER)],
        lightcolor=[("pressed", FIELD), ("active", BORDER_HOVER)],
        darkcolor=[("pressed", FIELD), ("active", BORDER_HOVER)],
    )

    style.configure(
        "SmallGhost.TButton",
        **{
            **button_options,
            "padding": (8, 3),
            "font": fonts.small,
            "background": SURFACE,
            "bordercolor": SURFACE,
            "lightcolor": SURFACE,
            "darkcolor": SURFACE,
            "foreground": MUTED,
        },
    )
    style.map(
        "SmallGhost.TButton",
        background=[("pressed", SURFACE_ALT), ("active", SURFACE_ALT)],
        foreground=[("active", TEXT), ("disabled", FAINT)],
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("active", SURFACE_ALT)],
        darkcolor=[("active", SURFACE_ALT)],
    )

    style.configure("StatusSmall.TButton", **{**button_options, "padding": (8, 3), "font": fonts.small, "background": STATUS_BG, "bordercolor": STATUS_BG, "lightcolor": STATUS_BG, "darkcolor": STATUS_BG, "foreground": MUTED})
    style.map(
        "StatusSmall.TButton",
        background=[("pressed", SURFACE_ALT), ("active", SURFACE_ALT)],
        foreground=[("active", TEXT), ("disabled", FAINT)],
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("active", SURFACE_ALT)],
        darkcolor=[("active", SURFACE_ALT)],
    )

    style.configure(
        "Segment.Toolbutton",
        font=fonts.base,
        padding=(12, 7),
        anchor="center",
        relief="flat",
        borderwidth=1,
        background=SURFACE_ALT,
        foreground=MUTED,
        bordercolor=BORDER,
        lightcolor=SURFACE_ALT,
        darkcolor=SURFACE_ALT,
        focuscolor=ACCENT,
    )
    style.map(
        "Segment.Toolbutton",
        background=[
            ("selected", ACCENT_SOFT),
            ("active", "selected", ACCENT_SOFT_HOVER),
            ("pressed", ACCENT_SOFT),
            ("active", BORDER_HOVER),
            ("disabled", SURFACE),
        ],
        foreground=[("selected", TEXT), ("active", TEXT), ("disabled", FAINT)],
        bordercolor=[("selected", ACCENT_BORDER), ("focus", ACCENT)],
        lightcolor=[("selected", ACCENT_SOFT), ("active", BORDER_HOVER)],
        darkcolor=[("selected", ACCENT_SOFT), ("active", BORDER_HOVER)],
    )

    style.configure(
        "TEntry",
        fieldbackground=FIELD,
        foreground=TEXT,
        insertcolor=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=(8, 7),
        relief="flat",
    )
    style.map(
        "TEntry",
        fieldbackground=[("disabled", SURFACE), ("readonly", SURFACE)],
        foreground=[("disabled", MUTED), ("readonly", MUTED)],
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("focus", ACCENT)],
        darkcolor=[("focus", ACCENT)],
    )

    style.configure(
        "TCombobox",
        fieldbackground=FIELD,
        background=SURFACE_ALT,
        foreground=TEXT,
        arrowcolor=MUTED,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=(8, 5),
        relief="flat",
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", FIELD), ("disabled", SURFACE)],
        foreground=[("disabled", MUTED), ("readonly", TEXT)],
        arrowcolor=[("disabled", FAINT)],
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("focus", ACCENT)],
        darkcolor=[("focus", ACCENT)],
    )
    root.option_add("*TCombobox*Listbox.background", SURFACE_ALT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_SOFT)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    root.option_add("*TCombobox*Listbox.font", fonts.base)
    root.option_add("*TCombobox*Listbox.borderWidth", "0")

    style.configure(
        "TG.Horizontal.TProgressbar",
        troughcolor=TRACK,
        background=ACCENT,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
        bordercolor=TRACK,
        thickness=6,
        borderwidth=0,
    )
    style.configure(
        "Queue.Horizontal.TProgressbar",
        troughcolor=FIELD,
        background=ACCENT,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
        bordercolor=FIELD,
        thickness=5,
        borderwidth=0,
    )

    style.configure(
        "Vertical.TScrollbar",
        background=BORDER,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=MUTED,
        lightcolor=BORDER,
        darkcolor=BORDER,
        width=10,
        arrowsize=10,
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("pressed", ACCENT), ("active", BORDER_HOVER)],
        arrowcolor=[("active", TEXT)],
    )
    style.configure("TSeparator", background=BORDER)
    return fonts
