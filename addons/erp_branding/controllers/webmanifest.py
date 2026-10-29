from odoo.http import request

from odoo.addons.web.controllers.webmanifest import WebManifest

BRAND_BACKGROUND_COLOR = "#000000"
BRAND_ICON_SIZES = ("192x192", "512x512")


class ErpBrandingWebManifest(WebManifest):
    def _get_webmanifest(self):
        manifest = super()._get_webmanifest()
        # Respect an explicit "web.web_app_name"; otherwise use the brand name.
        # sudo: same read the core method does for the public manifest route.
        icp = request.env["ir.config_parameter"].sudo()
        if not icp.get_param("web.web_app_name"):
            manifest["name"] = request.env["ir.http"].get_erp_brand_name()
        manifest["background_color"] = BRAND_BACKGROUND_COLOR
        manifest["theme_color"] = BRAND_BACKGROUND_COLOR
        manifest["icons"] = [
            {
                "src": f"/erp_branding/static/img/icon-{size.split('x')[0]}.png",
                "sizes": size,
                "type": "image/png",
            }
            for size in BRAND_ICON_SIZES
        ]
        return manifest
