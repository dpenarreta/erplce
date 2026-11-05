"""Contrast audit of the ERP LCE theme (US-018, CA-8).

Builds on the erp_branding helpers (parse_rules, parse_rgba, contrast...) and
measures, on the compiled backend CSS:

- the sidebar (black surface): every text color against every surface of the
  sidebar (normal, hover, active) >= 4.5:1; outlines (focus) and indicator
  bars (``::before`` backgrounds) >= 3:1;
- the app icons of the sidebar: light plate >= 3:1 on every sidebar
  surface, default icon >= 3:1 on the plate;
- light areas (top bar, popover of the icons-only mode): every text color
  against the area background and its hover background >= 4.5:1 (or against
  the rule's own background, e.g. the yellow badges or the active option);
  the last outline of each selector (focus) >= 3:1 on the background;
- status colors (.text-success/-warning/-danger) of the smart buttons and of
  the chatter top bar >= 4.5:1 on every light surface.
"""

from odoo.addons.erp_branding.tests.css_audit import (
    _is_text_property,
    blend,
    contrast,
    parse_rgba,
    parse_rules,
)

SIDEBAR_MARKER = "o_erp_sidebar"
# Sidebar classes that are not on the sidebar surface: the hamburger button
# lives in the light top bar and the backdrop has no text.
# The popover of the icons-only mode is a light area, and the icon plates are
# audited on their own (audit_sidebar_icons).
SIDEBAR_EXCLUDED = (
    "o_erp_sidebar_toggle",
    "o_erp_sidebar_backdrop",
    "o_erp_sidebar_flyout",
    "o_erp_sidebar_icon",
)
FLYOUT_MARKER = "o_erp_sidebar_flyout"
LIGHT_SURFACES = (
    (255, 255, 255),
    (248, 249, 250),  # #f8f9fa, chatter
    (242, 242, 242),  # #f2f2f2, work area
    (233, 236, 239),  # #e9ecef, hover of secondary buttons
)
STATUS_CONTEXTS = ("o-form-buttonbox", "o-mail-Chatter-topbar")
STATUS_CLASSES = (".text-success", ".text-warning", ".text-danger")
NAVBAR_MARKER = "o_main_navbar"
# Rules under .o_main_navbar that are not drawn on the bar: dropdown menus
# (own background) and print rules.
NAVBAR_EXCLUDED = ("dropdown-menu", "dropdown-item", "o-dropdown--menu", "popover")
_KEYWORDS = ("inherit", "transparent", "currentcolor", "initial", "unset", "none")


def solid(value, background=(255, 255, 255)):
    """Opaque (r, g, b) of a CSS color value (alpha blended), or None."""
    rgba = parse_rgba(value)
    if not rgba:
        return None
    rgb, alpha = rgba
    return blend(rgb, alpha, background) if alpha < 1 else rgb


def _is_keyword(value):
    return (value or "").strip().lower().split(" ")[0] in _KEYWORDS


def _rules_with(css, marker, excluded=()):
    for index, selectors, decls in parse_rules(css):
        selectors = [
            s for s in selectors if marker in s and not any(x in s for x in excluded)
        ]
        if selectors:
            yield index, selectors, decls


def sidebar_surfaces(css):
    """Background colors of the sidebar surfaces (base, hover, active)."""
    surfaces = set()
    for _index, selectors, decls in _rules_with(css, SIDEBAR_MARKER, SIDEBAR_EXCLUDED):
        if any("::before" in s for s in selectors):
            continue
        for prop in ("background-color", "background"):
            value = decls.get(prop, ("", False))[0]
            if value and not _is_keyword(value):
                color = solid(value, (0, 0, 0))
                if color:
                    surfaces.add(color)
    return surfaces


def audit_sidebar(css):
    """Return (surfaces, issues) of the sidebar.

    ``issues`` is a list of (selector, property, value, background, ratio)
    below the threshold (4.5 for text, 3 for outlines and indicators).
    """
    surfaces = sidebar_surfaces(css)
    issues = []
    for _index, selectors, decls in _rules_with(css, SIDEBAR_MARKER, SIDEBAR_EXCLUDED):
        is_indicator = any("::before" in s for s in selectors)
        for prop, (value, _important) in decls.items():
            if _is_keyword(value):
                continue
            if _is_text_property(prop):
                minimum = 4.5
            elif prop.startswith("outline") or (
                is_indicator and prop in ("background-color", "background")
            ):
                minimum = 3
            else:
                continue
            for surface in surfaces:
                color = solid(value, surface)
                if color is None:
                    continue
                ratio = contrast(color, surface)
                if ratio < minimum:
                    issues.append((selectors[0], prop, value, surface, round(ratio, 2)))
    return surfaces, issues


def audit_sidebar_icons(css, surfaces):
    """Issues of the icon plates (>= 3:1 on the sidebar surfaces) and of the
    default icon (>= 3:1 on the plate)."""
    issues = []
    plates = []
    for _index, selectors, decls in _rules_with(css, "o_erp_sidebar_icon"):
        value = decls.get("background-color", ("", False))[0]
        if selectors[0].endswith(".o_erp_sidebar_icon") and value:
            plates.append(solid(value))
    for plate in plates:
        for surface in surfaces:
            if contrast(plate, surface) < 3:
                issues.append(
                    ("plate", plate, surface, round(contrast(plate, surface), 2))
                )
    for _index, _selectors, decls in _rules_with(css, "o_erp_sidebar_icon_default"):
        value = decls.get("color", ("", False))[0]
        color = solid(value) if value else None
        for plate in plates if color else ():
            if contrast(color, plate) < 3:
                issues.append(
                    ("default icon", color, plate, round(contrast(color, plate), 2))
                )
    return plates, issues


def audit_status_colors(css):
    """Return (found, issues): status text colors of the smart buttons and of
    the chatter top bar measured on every light surface (>= 4.5:1)."""
    found = {}
    issues = []
    for _index, selectors, decls in parse_rules(css):
        for selector in selectors:
            if not any(c in selector for c in STATUS_CONTEXTS):
                continue
            status = next((s for s in STATUS_CLASSES if selector.endswith(s)), None)
            if not status or "color" not in decls:
                continue
            color = solid(decls["color"][0])
            found[selector] = (color, decls["color"][1])
            for surface in LIGHT_SURFACES:
                if color and contrast(color, surface) < 4.5:
                    issues.append(
                        (selector, color, surface, round(contrast(color, surface), 2))
                    )
    return found, issues


def audit_navbar(css, background, hover_background):
    """Return the issues of the top bar (same format as audit_sidebar)."""
    return audit_light_area(
        css, NAVBAR_MARKER, NAVBAR_EXCLUDED, background, hover_background
    )


def audit_flyout(css, background=(255, 255, 255), hover_background=(237, 237, 237)):
    """Return the issues of the popover of the icons-only mode."""
    return audit_light_area(css, FLYOUT_MARKER, (), background, hover_background)


def audit_light_area(css, marker, excluded, background, hover_background):
    """Text colors >= 4.5:1 and last focus outline >= 3:1 of the rules with
    ``marker`` drawn on a light ``background``."""
    issues = []
    last_outline = {}
    for index, selectors, decls in _rules_with(css, marker, excluded):
        own_bg = None
        for prop in ("background-color", "background"):
            value = decls.get(prop, ("", False))[0]
            if value and not _is_keyword(value):
                own_bg = solid(value, background) or own_bg
        backgrounds = [own_bg] if own_bg else [background, hover_background]
        for prop, (value, _important) in decls.items():
            if prop.startswith("outline") and "solid" in value:
                for selector in selectors:
                    last_outline[selector] = (index, value)
                continue
            if not _is_text_property(prop) or _is_keyword(value):
                continue
            for bg in backgrounds:
                color = solid(value, bg)
                if color is None:
                    continue
                ratio = contrast(color, bg)
                if ratio < 4.5:
                    issues.append((selectors[0], prop, value, bg, round(ratio, 2)))
    for selector, (_index, value) in last_outline.items():
        color = solid(value.split("solid", 1)[1], background)
        if color and contrast(color, background) < 3:
            issues.append(
                (
                    selector,
                    "outline",
                    value,
                    background,
                    round(contrast(color, background), 2),
                )
            )
    return issues
