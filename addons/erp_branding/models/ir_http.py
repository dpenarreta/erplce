from odoo import api, models

BRAND_NAME_PARAM = "erp_branding.name"
DEFAULT_BRAND_NAME = "ERP LCE"


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @api.model
    def get_erp_brand_name(self):
        """Return the configured brand name, falling back to the default one.

        Public (no leading underscore) because it is called from QWeb templates,
        whose evaluation context forbids private attributes. It only exposes a
        non-sensitive display name.
        """
        # sudo: the brand is shown on public pages (login) to anonymous users,
        # who cannot read ir.config_parameter; only this single key is read.
        value = self.env["ir.config_parameter"].sudo().get_param(BRAND_NAME_PARAM)
        return (value or "").strip() or DEFAULT_BRAND_NAME

    def session_info(self):
        result = super().session_info()
        result["erp_brand_name"] = self.get_erp_brand_name()
        return result
