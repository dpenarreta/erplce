from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    erp_default_reserve_fund_mode = fields.Selection(
        related="company_id.erp_default_reserve_fund_mode", readonly=False
    )
    erp_default_thirteenth_mode = fields.Selection(
        related="company_id.erp_default_thirteenth_mode", readonly=False
    )
    erp_default_fourteenth_mode = fields.Selection(
        related="company_id.erp_default_fourteenth_mode", readonly=False
    )
    erp_max_weekly_hours = fields.Float(
        related="company_id.erp_max_weekly_hours", readonly=False
    )
