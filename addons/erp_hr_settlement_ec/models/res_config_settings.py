from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Ajustes de nómina: cuentas del asiento de la liquidación (US-013)."""

    _inherit = "res.config.settings"

    erp_settlement_vacation_account_id = fields.Many2one(
        related="company_id.erp_settlement_vacation_account_id",
        readonly=False,
    )
    erp_settlement_severance_account_id = fields.Many2one(
        related="company_id.erp_settlement_severance_account_id",
        readonly=False,
    )
    erp_settlement_indemnity_account_id = fields.Many2one(
        related="company_id.erp_settlement_indemnity_account_id",
        readonly=False,
    )
    erp_settlement_payable_account_id = fields.Many2one(
        related="company_id.erp_settlement_payable_account_id",
        readonly=False,
    )
