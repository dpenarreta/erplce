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
# - dark utility backgrounds,
# - ".o_cc*" color combinations of the HTML editor content (their palette is
#   configured in the editor itself; reviewed and discarded by QA in US-001).
DARK_CONTEXTS = (
    "o_main_navbar",
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
