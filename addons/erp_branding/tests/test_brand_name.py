from odoo.tests import TransactionCase, tagged

from odoo.addons.erp_branding.models.ir_http import (
    BRAND_NAME_PARAM,
    DEFAULT_BRAND_NAME,
)

from .css_audit import (
    DARK_CONTEXTS,
    find_contrast_issues,
    page_selector_filter,
    parse_rules,
)


@tagged("post_install", "-at_install")
class TestBrandName(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.icp = cls.env["ir.config_parameter"].sudo()
        cls.ir_http = cls.env["ir.http"]

    def test_default_parameter_installed(self):
        self.assertEqual(self.icp.get_param(BRAND_NAME_PARAM), "ERP LCE")
        self.assertEqual(self.ir_http.get_erp_brand_name(), "ERP LCE")

    def test_custom_name(self):
        self.icp.set_param(BRAND_NAME_PARAM, "  Mi ERP  ")
        self.assertEqual(self.ir_http.get_erp_brand_name(), "Mi ERP")

    def test_empty_or_blank_falls_back_to_default(self):
        for value in ("", "   "):
            with self.subTest(value=value):
                self.icp.set_param(BRAND_NAME_PARAM, value)
                self.assertEqual(self.ir_http.get_erp_brand_name(), DEFAULT_BRAND_NAME)

    def test_missing_parameter_falls_back_to_default(self):
        self.icp.search([("key", "=", BRAND_NAME_PARAM)]).unlink()
        self.assertFalse(self.icp.get_param(BRAND_NAME_PARAM))
        self.assertEqual(self.ir_http.get_erp_brand_name(), DEFAULT_BRAND_NAME)

    def test_readable_without_config_parameter_access(self):
        """Anonymous visitors (login page) can get the brand name."""
        public_user = self.env.ref("base.public_user")
        name = self.ir_http.with_user(public_user).get_erp_brand_name()
        self.assertEqual(name, "ERP LCE")

    def test_scss_bundles_compile_with_palette(self):
        for bundle_name in ("web.assets_backend", "web.assets_frontend"):
            with self.subTest(bundle=bundle_name):
                bundle = self.env["ir.qweb"]._get_asset_bundle(
                    bundle_name, js=False, css=True
                )
                css = bundle.preprocess_css().lower()
                self.assertFalse(bundle.css_errors)
                self.assertIn("#fce200", css)

    def test_backend_css_contrast(self):
        """No light brand-yellow text (nor light text on yellow) in the backend."""
        bundle = self.env["ir.qweb"]._get_asset_bundle(
            "web.assets_backend", js=False, css=True
        )
        css = bundle.preprocess_css()
        self.assertFalse(bundle.css_errors)
        issues = find_contrast_issues(css)
        self.assertFalse(
            issues,
            "Brand-yellow contrast issues:\n"
            + "\n".join(" | ".join(issue) for issue in issues),
        )
        # Primary buttons: black text on yellow; outline: black on light bg.
        rules = {
            selector: decls
            for _index, selectors, decls in parse_rules(css)
            for selector in selectors
            if selector in (".btn-primary", ".btn-outline-primary")
            and "--btn-color" in decls
        }
        self.assertEqual(rules[".btn-primary"]["--btn-color"][0].lower(), "#000000")
        self.assertEqual(rules[".btn-primary"]["--btn-bg"][0].lower(), "#fce200")
        self.assertEqual(
            rules[".btn-outline-primary"]["--btn-color"][0].lower(), "#000000"
        )
        # No outline-primary variant with yellow text on light backgrounds
        # (".o_cc*" editor color combinations excluded, see DARK_CONTEXTS).
        yellow_outline = [
            selector
            for _index, selectors, decls in parse_rules(css)
            for selector in selectors
            if selector.endswith(".btn-outline-primary")
            and not any(ctx in selector for ctx in DARK_CONTEXTS)
            and decls.get("--btn-color", ("",))[0].lower() == "#fce200"
        ]
        self.assertFalse(yellow_outline)

    def test_css_audit_detects_issues(self):
        """The audit itself flags the patterns it must catch."""
        css = (
            ".a{color: #fce200;}"
            ".b{--btn-color: #FFFFFF; --btn-bg: #fce200;}"
            ".c{color: #000000; background-color: #fce200;}"
            ".o_main_navbar .d{color: #fce200;}"
            ".e{color: #f3cc00;}"
            ".f{color: #fce200;} .f{color: #6b5d00;}"
            ".g{color: #fff !important; background-color: #fce200;}"
            ".x .g{color: #000;}"
        )
        flagged = {selector for _kind, selector, _decl in find_contrast_issues(css)}
        self.assertEqual(flagged, {".a", ".b", ".g"})

        # Page filter: only rules whose classes/ids exist in the page.
        page = '<body class="a x"><div id="main" class="g"></div></body>'
        flagged = {
            selector
            for _kind, selector, _decl in find_contrast_issues(
                css + "#main .a:not(.zz){color: #fce200;}#other{color: #fce200;}",
                page_selector_filter(page),
            )
        }
        self.assertEqual(flagged, {".a", ".g", "#main .a:not(.zz)"})
