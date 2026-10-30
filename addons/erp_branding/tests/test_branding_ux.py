"""US-017: login and web client without Odoo colors, measured contrast of the
component states, document language and no sign-up link."""

import re

from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools import file_open

from .css_audit import (
    blend,
    button_state_contrasts,
    contrast,
    custom_property_values,
    find_odoo_colors,
    is_light_brand_yellow,
    parse_any_color,
    parse_color,
    parse_rgba,
    resolve_declarations,
    resolve_value,
    svg_colors,
)

YELLOW = (252, 226, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
# Light backgrounds: white, gray-100 (lists, chatter), gray-200 (hover,
# panels) and the brand gray #e1e1e1 (login page body, 'o-color-3' surface of
# the frontend palette).
BRAND_GRAY = (225, 225, 225)
LIGHT_BACKGROUNDS = ((255, 255, 255), (248, 249, 250), (233, 236, 239), BRAND_GRAY)
LANG = "es_EC"

# Backend rules that may keep an Odoo color: user-selectable record colors
# (color #5 "purple" of kanban/calendar), the editor table picker and the
# onboarding tour pointer. None of them is brand UI.
BACKEND_ODOO_COLOR_ALLOWED = (
    "color_5",
    "hr_mandatory_day_5",
    "o-we-tablepicker",
    "o_tour_pointer",
)


def _bundle_css(env, name):
    bundle = env["ir.qweb"]._get_asset_bundle(name, js=False, css=True)
    css = bundle.preprocess_css()
    assert not bundle.css_errors, bundle.css_errors
    return css


def _html_tag(html):
    match = re.search(r"<html[^>]*>", html)
    return match.group(0) if match else ""


def _login_context(prefix):
    return prefix in ("body.o_erp_branding_login", ".o_erp_branding_login")


@tagged("post_install", "-at_install")
class TestBrandingLoginUx(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang(LANG)
        cls.icp = cls.env["ir.config_parameter"].sudo()
        cls.frontend_css = _bundle_css(cls.env, "web.assets_frontend")

    def test_login_document_language(self):
        """CA-4: <html lang> with the request language (BCP 47)."""
        response = self.url_open(
            "/web/login", headers={"Accept-Language": "es-EC,es;q=0.9"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('lang="es-EC"', _html_tag(response.text))

        tag = _html_tag(self.url_open("/web/login").text)
        self.assertRegex(tag, r'lang="[a-z]{2}(-[A-Z]{2})?"')

    def test_web_client_document_language(self):
        admin = self.env.ref("base.user_admin")
        admin.lang = LANG
        self.authenticate("admin", "admin")
        response = self.url_open("/odoo")
        self.assertEqual(response.status_code, 200)
        self.assertIn('lang="es-EC"', _html_tag(response.text))

    def test_login_without_sign_up_link(self):
        """CA-2: no sign-up link even if invitations are opened again;
        password reset is kept."""
        self.icp.set_param("auth_signup.invitation_scope", "b2c")
        self.icp.set_param("auth_signup.reset_password", "True")
        html = self.url_open("/web/login", headers={"Accept-Language": "es-EC"}).text
        self.assertNotIn("/web/signup", html)
        self.assertNotIn("cuenta?", html)
        self.assertNotIn("have an account", html)
        self.assertIn("/web/reset_password", html)

    def test_reset_password_formal_labels(self):
        self.icp.set_param("auth_signup.reset_password", "True")
        html = self.url_open(
            "/web/reset_password", headers={"Accept-Language": "es-EC"}
        ).text
        self.assertIn("Su correo electrónico", html)
        self.assertNotIn("Tu correo", html)

    def test_login_button_states_contrast(self):
        """CA-1: every state of the login buttons (normal, hover, active,
        disabled while submitting, focus) uses the brand palette with
        measured contrast >= 4.5:1."""
        css = self.frontend_css
        for target in (".btn-primary", ".btn-secondary", ".btn-link"):
            states = button_state_contrasts(css, target, _login_context)
            with self.subTest(button=target):
                self.assertEqual(
                    set(states),
                    {"normal", "hover-", "active-", "disabled-", "focus-shadow"},
                )
                for state, (text, bg, ratio) in states.items():
                    if state == "focus-shadow":
                        self.assertEqual(text, BLACK, f"{target} focus shadow")
                        continue
                    self.assertGreaterEqual(
                        ratio, 4.5, f"{target} {state}: {text} on {bg}"
                    )
        primary = button_state_contrasts(css, ".btn-primary", _login_context)
        for state in ("normal", "disabled-"):
            self.assertEqual(primary[state][:2], (BLACK, YELLOW), state)
        for state in ("hover-", "active-"):
            text, bg, _ratio = primary[state]
            self.assertEqual(text, BLACK)
            self.assertFalse(is_light_brand_yellow(text))
            # Darker shades of the brand yellow (same hue).
            self.assertGreater(bg[0], bg[2])
            self.assertGreater(bg[1], bg[2])

    def test_login_input_borders_and_link_targets(self):
        """M-5: login inputs with a border >= 3:1 (WCAG 1.4.11) and small
        links with a target of at least 24 px high (WCAG 2.5.8)."""
        declarations, _rules = resolve_declarations(
            self.frontend_css, ".form-control", _login_context
        )
        border = parse_color(declarations.get("border-color"))
        self.assertTrue(border, declarations.get("border-color"))
        self.assertGreaterEqual(contrast(border, WHITE), 3)
        for target in ("a:not(.btn)", ".btn-link"):
            with self.subTest(link=target):
                declarations, _rules = resolve_declarations(
                    self.frontend_css, target, _login_context
                )
                height = declarations.get("min-height", "0px")
                self.assertTrue(height.endswith("px"), height)
                self.assertGreaterEqual(float(height[:-2]), 24)

    def test_frontend_without_odoo_colors(self):
        """CA-1: no Odoo purple (#714B67) nor blue-gray (#2D3142) left in the
        frontend bundle (login, reset password), whatever the state."""
        hits = [
            hit
            for hit in find_odoo_colors(self.frontend_css)
            if "o_tour_pointer" not in hit[0]
        ]
        self.assertFalse(hits, "\n".join(" | ".join(hit) for hit in hits))


@tagged("post_install", "-at_install")
class TestBrandingCssUx(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = {
            "backend": _bundle_css(cls.env, "web.assets_backend"),
            "frontend": _bundle_css(cls.env, "web.assets_frontend"),
        }

    def _resolved(self, bundle, target, prop):
        declarations, rules = resolve_declarations(self.css[bundle], target)
        return resolve_value(
            declarations.get(prop, ""), declarations, custom_property_values(rules)
        )

    def test_backend_without_odoo_brand_colors(self):
        hits = [
            hit
            for hit in find_odoo_colors(self.css["backend"])
            if not any(allowed in hit[0] for allowed in BACKEND_ODOO_COLOR_ALLOWED)
        ]
        self.assertFalse(hits, "\n".join(" | ".join(hit) for hit in hits))

    def test_muted_text_contrast(self):
        """CA-3: .text-muted and help texts are solid (no alpha) and >= 4.5:1
        on the light backgrounds, in backend and frontend."""
        for bundle in ("backend", "frontend"):
            for target, prop in (
                (".text-muted", "color"),
                (":root", "--secondary-color"),
            ):
                with self.subTest(bundle=bundle, target=target):
                    value = self._resolved(bundle, target, prop)
                    rgba = parse_rgba(value)
                    self.assertTrue(rgba, value)
                    rgb, alpha = rgba
                    self.assertEqual(alpha, 1.0, f"{target} with alpha: {value}")
                    for bg in LIGHT_BACKGROUNDS:
                        self.assertGreaterEqual(
                            contrast(rgb, bg), 4.5, f"{value} on {bg}"
                        )

    def test_frontend_secondary_color_contrast(self):
        """Regression (QA-UX): the frontend secondary color ('o-color-2') is a
        text color too (language selector of the 404 page, portal): every
        state of the secondary buttons and .text-secondary >= 4.5:1 on the
        light backgrounds, including the brand gray #e1e1e1."""
        css = self.css["frontend"]
        value = self._resolved("frontend", ".text-secondary", "color")
        rgba = parse_rgba(value)
        self.assertTrue(rgba, value)
        self.assertEqual(rgba[1], 1.0, value)
        for bg in LIGHT_BACKGROUNDS:
            self.assertGreaterEqual(contrast(rgba[0], bg), 4.5, f"{value} on {bg}")
        for target in (".btn-outline-secondary", ".btn-secondary"):
            for bg in LIGHT_BACKGROUNDS:
                states = button_state_contrasts(css, target, background=bg)
                with self.subTest(button=target, background=bg):
                    self.assertTrue(
                        {"normal", "hover-", "active-", "disabled-"} <= set(states)
                    )
                    for state, (text, back, ratio) in states.items():
                        if state == "disabled-" or ratio is None:
                            # Disabled controls are exempt (WCAG 1.4.3).
                            continue
                        self.assertGreaterEqual(
                            ratio, 4.5, f"{target} {state}: {text} on {back}"
                        )
        # The brand gray stays a surface: never the secondary text color.
        self.assertNotEqual(rgba[0], BRAND_GRAY)

    def test_placeholder_contrast(self):
        """Placeholders of inputs and textareas solid and >= 4.5:1 on the
        light backgrounds (backend web client and frontend/login)."""
        targets = {
            "backend": (
                "::-webkit-input-placeholder",
                "::-moz-placeholder",
                ".o_web_client input::placeholder",
                ".o_web_client textarea::placeholder",
            ),
            "frontend": (".form-control::placeholder",),
        }
        for bundle, selectors in targets.items():
            for target in selectors:
                with self.subTest(bundle=bundle, target=target):
                    value = self._resolved(bundle, target, "color")
                    rgba = parse_rgba(value)
                    self.assertTrue(rgba, f"{target}: {value!r}")
                    self.assertEqual(rgba[1], 1.0, value)
                    for bg in LIGHT_BACKGROUNDS:
                        self.assertGreaterEqual(
                            contrast(rgba[0], bg), 4.5, f"{value} on {bg}"
                        )
        declarations, _rules = resolve_declarations(
            self.css["backend"], ".o_web_client input::placeholder"
        )
        self.assertEqual(declarations.get("opacity"), "1")

    def test_unchecked_checkbox_border_contrast(self):
        """CA-3: unchecked checkboxes and radios have a border >= 3:1
        (WCAG 1.4.11)."""
        for bundle in ("backend", "frontend"):
            with self.subTest(bundle=bundle):
                border = self._resolved(bundle, ".form-check-input", "border")
                color = parse_color(border.split("solid")[-1])
                self.assertTrue(color, border)
                for bg in LIGHT_BACKGROUNDS:
                    self.assertGreaterEqual(contrast(color, bg), 3, f"{border} on {bg}")

    def test_required_fields_visible_without_focus(self):
        """CA-3: the border of required, editable inputs of forms is shown
        without hover/focus, with >= 3:1."""
        found = []
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", self.css["backend"]):
            selector = " ".join(selector.split())
            if (
                ".o_form_view" in selector
                and ".o_required_modifier" in selector
                and ".o_input:not(:hover):not(:focus)" in selector
                and "--o-input-border-color" in body
            ):
                value = body.split("--o-input-border-color:")[1].split(";")[0]
                found.append(parse_color(value))
        self.assertTrue(found)
        for color in found:
            self.assertGreaterEqual(contrast(color, WHITE), 3)

    def test_empty_state_illustration_without_purple(self):
        """CA-3: the "no content" illustrations use the ERP LCE SVG, whose
        colors are grays and brand ones."""
        target = (
            ".o_view_nocontent .o_nocontent_help .o_view_nocontent_smiling_face:before"
        )
        for face in ("smiling_face", "neutral_face"):
            with self.subTest(face=face):
                value = self._resolved(
                    "backend", target.replace("smiling_face", face), "background-image"
                )
                self.assertIn("/erp_branding/static/img/empty_state.svg", value)
        with file_open("erp_branding/static/img/empty_state.svg") as svg:
            colors = svg_colors(svg.read())
        self.assertTrue(colors)
        self.assertIn(YELLOW, colors)
        for color in colors:
            hue_gray = max(color) - min(color) <= 4
            self.assertTrue(hue_gray or color == YELLOW, color)

    def test_audit_helpers(self):
        """The US-017 audit helpers resolve the cascade and detect colors."""
        css = (
            ":root{--link-color: #6b5d00;}"
            ".btn-link{--btn-color: var(--link-color); --btn-hover-color: #fff;"
            " --btn-focus-shadow-rgb: 113, 75, 103;}"
            ".ctx .btn-link{--btn-hover-color: #000000;}"
            ".x{color: #714B67;} .y{background: #5a3c52;} .z{color: #2D3142;}"
            ".gray{color: #808080;} .pink{color: #e83e8c;}"
        )
        states = button_state_contrasts(css, ".btn-link", lambda p: p == ".ctx")
        self.assertEqual(states["normal"][0], (107, 93, 0))
        self.assertEqual(states["hover-"][0], BLACK)
        self.assertEqual(states["focus-shadow"][0], (113, 75, 103))
        flagged = {hit[0] for hit in find_odoo_colors(css)}
        self.assertEqual(flagged, {".btn-link", ".x", ".y", ".z"})
        self.assertEqual(parse_any_color("45, 49, 66"), (45, 49, 66))
        self.assertEqual(blend((0, 0, 0), 0.5), (128, 128, 128))
        self.assertEqual(parse_rgba("rgba(73, 80, 87, 0.76)"), ((73, 80, 87), 0.76))
