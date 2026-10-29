import re

from odoo.tests import HttpCase, tagged

from odoo.addons.erp_branding.models.ir_http import BRAND_NAME_PARAM

from .css_audit import find_contrast_issues, page_selector_filter


@tagged("post_install", "-at_install")
class TestBrandingHttp(HttpCase):
    def _get_login_html(self):
        response = self.url_open("/web/login")
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_login_page_branding(self):
        html = self._get_login_html()
        self.assertIn("<title>ERP LCE</title>", html)
        self.assertIn("o_erp_branding_name", html)
        self.assertIn("/erp_branding/static/img/logo.svg", html)
        logo = re.search(r"<img[^>]*/erp_branding/static/img/logo\.svg[^>]*>", html)
        self.assertTrue(logo)
        self.assertIn(' alt=""', logo.group(0))
        self.assertIn("/erp_branding/static/img/favicon.ico", html)
        self.assertIn("/erp_branding/static/img/favicon.svg", html)
        self.assertNotIn("Powered by", html)
        self.assertNotIn("<title>Odoo</title>", html)

    def test_login_page_custom_and_empty_name(self):
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param(BRAND_NAME_PARAM, "ERP Pruebas <b>")
        html = self._get_login_html()
        self.assertIn("<title>ERP Pruebas &lt;b&gt;</title>", html)
        self.assertNotIn("ERP Pruebas <b>", html)

        icp.set_param(BRAND_NAME_PARAM, "")
        html = self._get_login_html()
        self.assertIn("<title>ERP LCE</title>", html)

    def test_session_info_includes_brand_name(self):
        self.authenticate("admin", "admin")
        info = self.make_jsonrpc_request("/web/session/get_session_info")
        self.assertEqual(info["erp_brand_name"], "ERP LCE")

    def test_web_client_bootstrap(self):
        self.authenticate("admin", "admin")
        response = self.url_open("/odoo")
        self.assertEqual(response.status_code, 200)
        self.assertIn("<title>ERP LCE</title>", response.text)
        self.assertIn('"erp_brand_name": "ERP LCE"', response.text)
        self.assertIn('content="#000000"', response.text)

    def test_webmanifest_uses_brand(self):
        response = self.url_open("/web/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        manifest = response.json()
        self.assertEqual(manifest["name"], "ERP LCE")
        self.assertTrue(
            all(icon["src"].startswith("/erp_branding/") for icon in manifest["icons"])
        )

    def test_login_css_contrast(self):
        """Frontend CSS rules that apply to the login page: no light
        brand-yellow text and no light text on brand yellow."""
        html = self._get_login_html()
        self.assertIn("o_erp_branding_login", html)
        bundle = self.env["ir.qweb"]._get_asset_bundle(
            "web.assets_frontend", js=False, css=True
        )
        css = bundle.preprocess_css()
        self.assertFalse(bundle.css_errors)
        issues = find_contrast_issues(css, page_selector_filter(html))
        self.assertFalse(
            issues,
            "Login contrast issues:\n"
            + "\n".join(" | ".join(issue) for issue in issues),
        )
