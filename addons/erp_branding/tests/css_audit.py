"""Contrast audit of compiled CSS for the brand yellow (WCAG 2.1 AA).

Only colors of the brand-yellow family (hue of #FCE200 +/- 1.5 deg, i.e. the
brand color and its lighten()/darken() derivatives) are considered; the core's
own yellows (favourite stars, warning, calendar colors) are not brand colors.

Reported issues:

- ``yellow-text``: a text color (``color`` or a ``--*color`` custom property
  that is not a background/border/shadow one) that is a light brand yellow
  (< 3:1 on white). Light yellow text is unreadable on light backgrounds.
- ``light-on-yellow``: a light text color on a light brand-yellow background
  in the same rule and state (e.g. ``--btn-hover-bg`` + ``--btn-hover-color``).

An issue is considered fixed when the compiled CSS contains an overriding rule
for the same selector and property with an acceptable color: either the same
selector later in the CSS, or the selector prefixed with an ancestor (more
specific, wins regardless of order). ``!important`` declarations can only be
overridden by ``!important`` ones. ``var(--x, <yellow>)`` values are accepted
when ``--x`` is defined in the CSS and none of its values is a light yellow.

Rules that only apply on dark backgrounds are excluded (see DARK_CONTEXTS).
"""

import colorsys
import re

BRAND_HUE = 53.8  # #FCE200
BRAND_HUE_TOLERANCE = 1.5

# Selectors whose text is not on a light web-client background:
# - the black navbar (yellow text is the intended accent there),
# - Bootstrap's dark color mode ([data-bs-theme="dark"], light links),
# - dark utility backgrounds,
# - ".o_cc*" color combinations of the HTML editor content (their palette is
#   configured in the editor itself; reviewed and discarded by QA in US-001).
DARK_CONTEXTS = (
    "o_main_navbar",
    'data-bs-theme="dark"',
    "data-bs-theme=dark",
    "bg-black",
    "bg-dark",
    "text-bg-dark",
    ".o_cc",
)

_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_HEX_RE = re.compile(r"#([0-9a-f]{3}|[0-9a-f]{6})\b", re.I)
_RGB_RE = re.compile(
    r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", re.I
)
_VAR_RE = re.compile(r"^var\(\s*(--[\w-]+)\s*,")
_NOT_RE = re.compile(r":not\([^)]*\)")
_CLASS_RE = re.compile(r"\.(-?[_a-zA-Z][\w-]*)")
_ID_RE = re.compile(r"#(-?[_a-zA-Z][\w-]*)")
_NAMED = {"white": (255, 255, 255), "black": (0, 0, 0)}

# Text property -> background properties of the same state.
_STATE_PAIRS = (
    ("color", ("background-color", "background")),
    ("--btn-color", ("--btn-bg",)),
    ("--btn-hover-color", ("--btn-hover-bg",)),
    ("--btn-active-color", ("--btn-active-bg",)),
    ("--btn-disabled-color", ("--btn-disabled-bg",)),
    ("--progress-bar-color", ("--progress-bar-bg",)),
    ("--nav-pills-link-active-color", ("--nav-pills-link-active-bg",)),
    ("--pagination-active-color", ("--pagination-active-bg",)),
    ("--list-group-active-color", ("--list-group-active-bg",)),
    ("--dropdown-link-active-color", ("--dropdown-link-active-bg",)),
)


def parse_color(value):
    """Return the first opaque-enough (r, g, b) found in a CSS value."""
    value = (value or "").strip()
    match = _HEX_RE.search(value)
    if match:
        hexa = match.group(1)
        if len(hexa) == 3:
            hexa = "".join(ch * 2 for ch in hexa)
        return tuple(int(hexa[i : i + 2], 16) for i in (0, 2, 4))
    match = _RGB_RE.search(value)
    if match:
        alpha = float(match.group(4)) if match.group(4) is not None else 1.0
        if alpha < 0.5:
            return None
        return tuple(int(match.group(i)) for i in (1, 2, 3))
    word = value.split(" ")[0].lower() if value else ""
    return _NAMED.get(word)


def luminance(rgb):
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(rgb1, rgb2):
    l1, l2 = sorted((luminance(rgb1), luminance(rgb2)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def is_light_brand_yellow(rgb):
    """Brand-yellow family color that fails 3:1 against white."""
    if rgb is None:
        return False
    hue, _light, sat = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    return (
        abs(hue * 360 - BRAND_HUE) <= BRAND_HUE_TOLERANCE
        and sat > 0.5
        and contrast(rgb, (255, 255, 255)) < 3
    )


def _is_text_property(prop):
    if prop == "color":
        return True
    if not (prop.startswith("--") and prop.endswith("color")):
        return False
    return not any(k in prop for k in ("bg", "background", "border", "shadow"))


def parse_rules(css):
    """Return [(index, [selector, ...], {prop: (value, important)})]."""
    css = _COMMENT_RE.sub("", css)
    rules = []
    for index, (selector, body) in enumerate(_RULE_RE.findall(css)):
        selector = " ".join(selector.split())
        if selector.startswith("@"):
            continue
        decls = {}
        for decl in body.split(";"):
            if ":" not in decl:
                continue
            prop, value = decl.split(":", 1)
            important = "!important" in value
            value = value.replace("!important", "").strip()
            decls[prop.strip().lower()] = (value, important)
        selectors = [s.strip() for s in selector.split(",") if s.strip()]
        rules.append((index, selectors, decls))
    return rules


def _bad_text_value(value, custom_props):
    """True if the text color value is a light brand yellow."""
    match = _VAR_RE.match(value)
    if match:
        defined = custom_props.get(match.group(1))
        if defined:
            return any(is_light_brand_yellow(parse_color(v)) for v in defined)
    return is_light_brand_yellow(parse_color(value))


def _raw_issues(rules, custom_props, selector_filter=None):
    for index, selectors, decls in rules:
        selectors = [s for s in selectors if not any(c in s for c in DARK_CONTEXTS)]
        if selector_filter:
            selectors = [s for s in selectors if selector_filter(s)]
        if not selectors:
            continue
        for prop, (value, important) in decls.items():
            if _is_text_property(prop) and _bad_text_value(value, custom_props):
                yield index, selectors, prop, important, "yellow-text", value
        for text_prop, bg_props in _STATE_PAIRS:
            text_value, important = decls.get(text_prop, ("", False))
            text = parse_color(text_value)
            if text is None or is_light_brand_yellow(text):
                continue
            for bg_prop in bg_props:
                bg = parse_color(decls.get(bg_prop, ("", False))[0])
                if is_light_brand_yellow(bg) and contrast(text, bg) < 4.5:
                    detail = f"{text_value} on {bg_prop}: {decls[bg_prop][0]}"
                    yield (
                        index,
                        selectors,
                        text_prop,
                        important,
                        "light-on-yellow",
                        (detail),
                    )


def _is_overridden(selector, prop, important, index, rules, custom_props):
    for other_index, other_selectors, decls in rules:
        if other_index == index or prop not in decls:
            continue
        value, other_important = decls[prop]
        if important and not other_important:
            continue
        if _bad_text_value(value, custom_props):
            continue
        for other in other_selectors:
            same_later = other == selector and other_index > index
            prefixed = other.endswith(" " + selector)
            if same_later or prefixed:
                return True
    return False


def page_selector_filter(html):
    """Selector filter keeping only the rules that can match ``html``.

    A selector is kept when every class and id it requires (outside
    ``:not(...)``) is present somewhere in the page. Structure and pseudo
    classes are ignored, so the filter may keep a few extra rules (safe side).
    """
    classes = set()
    for value in re.findall(r'\bclass="([^"]*)"', html):
        classes.update(value.split())
    ids = set(re.findall(r'\bid="([^"]*)"', html))

    def keep(selector):
        selector = _NOT_RE.sub("", selector)
        needed_classes = set(_CLASS_RE.findall(selector))
        needed_ids = set(_ID_RE.findall(selector))
        return needed_classes <= classes and needed_ids <= ids

    return keep


def find_contrast_issues(css, selector_filter=None):
    """Return a list of (kind, selector, declaration) not fixed by overrides.

    ``selector_filter`` (optional callable) limits the audited rules (e.g. to
    those of one page, see page_selector_filter); overriding rules are always
    searched in the whole CSS.
    """
    rules = parse_rules(css)
    custom_props = {}
    for _index, _selectors, decls in rules:
        for prop, (value, _important) in decls.items():
            if prop.startswith("--"):
                custom_props.setdefault(prop, []).append(value)
    issues = []
    for index, selectors, prop, important, kind, detail in _raw_issues(
        rules, custom_props, selector_filter
    ):
        for selector in selectors:
            if not _is_overridden(
                selector, prop, important, index, rules, custom_props
            ):
                issues.append((kind, selector, f"{prop}: {detail}"))
    return issues


# ---------------------------------------------------------------------------
# US-017: Odoo colors, resolved component states and measured contrast.
# ---------------------------------------------------------------------------

# Odoo's own brand colors that must not show up in ERP LCE pages:
# purple (#714B67 enterprise, #71639e community) and the frontend secondary
# blue-gray #2D3142, plus their lighten()/darken()/mix() derivatives.
_RGB_TRIPLE_RE = re.compile(r"^\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*$")
_VAR_ANY_RE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)")
WHITE = (255, 255, 255)


# (hue in degrees, HLS saturation) of each Odoo color; derivatives keep the
# hue and roughly the saturation, so lightness is only bounded loosely.
ODOO_COLORS = {
    "#714B67": (315.5, 0.20),
    "#71639E": (254.2, 0.23),
    "#2D3142": (228.6, 0.19),
}


def is_odoo_color(rgb):
    """Color of the Odoo purple / frontend blue-gray families."""
    if rgb is None:
        return False
    hue, light, sat = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    if not 0.1 < light < 0.62:
        return False
    return any(
        abs(hue * 360 - base_hue) <= 6 and abs(sat - base_sat) <= 0.12
        for base_hue, base_sat in ODOO_COLORS.values()
    )


def parse_any_color(value):
    """Like parse_color, also accepting bare "r, g, b" (--*-rgb props)."""
    match = _RGB_TRIPLE_RE.match(value or "")
    if match:
        return tuple(int(match.group(i)) for i in (1, 2, 3))
    return parse_color(value)


def parse_rgba(value):
    """Return ((r, g, b), alpha) of the first color of a CSS value, or None."""
    value = (value or "").strip()
    match = _RGB_RE.search(value)
    if match:
        alpha = float(match.group(4)) if match.group(4) is not None else 1.0
        return tuple(int(match.group(i)) for i in (1, 2, 3)), alpha
    rgb = parse_color(value)
    return (rgb, 1.0) if rgb else None


def blend(rgb, alpha, background=WHITE):
    """Composite a translucent color over an opaque background."""
    return tuple(
        round(c * alpha + b * (1 - alpha))
        for c, b in zip(rgb, background, strict=False)
    )


def find_odoo_colors(css, selector_filter=None):
    """Return [(selector, prop, value)] declaring an Odoo brand color.

    Rules of DARK_CONTEXTS are kept (an Odoo color is never wanted); the
    ``selector_filter`` limits the audit to the rules of one page.
    """
    hits = []
    for _index, selectors, decls in parse_rules(css):
        if selector_filter:
            selectors = [s for s in selectors if selector_filter(s)]
        if not selectors:
            continue
        for prop, (value, _important) in decls.items():
            colors = [parse_any_color(value)]
            colors += [parse_color(m.group(0)) for m in _HEX_RE.finditer(value)]
            if any(is_odoo_color(color) for color in colors):
                hits.append((selectors[0], prop, value))
    return hits


def custom_property_values(rules):
    """Last value of every custom property declared on :root-like rules."""
    values = {}
    for _index, selectors, decls in rules:
        if not any(
            s in (":root", "html", "body", "[data-bs-theme=light]") for s in selectors
        ):
            continue
        for prop, (value, _important) in decls.items():
            if prop.startswith("--"):
                values[prop] = value
    return values


def resolve_declarations(css, target, context_filter=None):
    """Cascade of the declarations that apply to ``target`` (a selector).

    Takes the rules whose selector is exactly ``target`` or ``<prefix>
    target`` where the prefix is accepted by ``context_filter`` (e.g. the
    login page body class). Later rules win, except over ``!important``.
    Returns ({prop: value}, rules) so values can be resolved with
    resolve_value().
    """
    rules = parse_rules(css)
    result = {}
    important = set()
    for _index, selectors, decls in rules:
        applies = False
        for selector in selectors:
            if selector == target:
                applies = True
            elif selector.endswith(" " + target) and context_filter:
                applies = applies or context_filter(selector[: -len(target)].strip())
        if not applies:
            continue
        for prop, (value, is_important) in decls.items():
            if prop in important and not is_important:
                continue
            result[prop] = value
            if is_important:
                important.add(prop)
    return result, rules


def resolve_value(value, declarations, root_values, depth=0):
    """Replace var(--x[, fallback]) by its value (rule first, then :root)."""
    match = _VAR_ANY_RE.search(value or "")
    if not match or depth > 5:
        return value
    name, fallback = match.group(1), match.group(2)
    replacement = declarations.get(name, root_values.get(name, fallback or ""))
    return resolve_value(
        value[: match.start()] + replacement + value[match.end() :],
        declarations,
        root_values,
        depth + 1,
    )


BUTTON_STATES = ("", "hover-", "active-", "disabled-")


def button_state_contrasts(css, target, context_filter=None, background=WHITE):
    """Measured text/background contrast of each button state.

    Returns {state: (text_rgb, bg_rgb, ratio)}; a transparent background
    (link buttons) is measured against ``background``.
    """
    declarations, rules = resolve_declarations(css, target, context_filter)
    root_values = custom_property_values(rules)
    result = {}
    for state in BUTTON_STATES:
        text = resolve_value(
            declarations.get(f"--btn-{state}color", ""), declarations, root_values
        )
        bg_value = resolve_value(
            declarations.get(f"--btn-{state}bg", "transparent"),
            declarations,
            root_values,
        )
        text_rgba = parse_rgba(text)
        if not text_rgba:
            continue
        bg_rgba = parse_rgba(bg_value)
        bg_rgb = blend(*bg_rgba, background) if bg_rgba else background
        text_rgb = blend(*text_rgba, bg_rgb)
        result[state or "normal"] = (text_rgb, bg_rgb, contrast(text_rgb, bg_rgb))
    focus = declarations.get("--btn-focus-shadow-rgb")
    if focus:
        result["focus-shadow"] = (parse_any_color(focus), None, None)
    return result


def svg_colors(svg_text):
    """All hex colors used in an SVG document."""
    return [parse_color(m.group(0)) for m in _HEX_RE.finditer(svg_text)]
