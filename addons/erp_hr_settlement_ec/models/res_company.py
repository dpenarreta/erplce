from odoo import fields, models


class ResCompany(models.Model):
    """Cuentas contables del asiento de la liquidación (US-013, CA-9).

    Vacías: se usa la cuenta del plan ``l10n_ec`` con el código por defecto
    (``const.DEFAULT_ACCOUNT_CODES``, a validar por el contador) o, para el
    neto, la cuenta acreedora de la regla «Neto» del rol mensual.
    """

    _inherit = "res.company"

    erp_settlement_vacation_account_id = fields.Many2one(
        "account.account",
        string="Gasto de vacaciones (liquidación)",
        ondelete="restrict",
        check_company=True,
        help="Cuenta de gasto de las vacaciones no gozadas y proporcionales "
        "de la liquidación. Vacía: 52020303 «Vacaciones» del plan de cuentas.",
    )
    erp_settlement_severance_account_id = fields.Many2one(
        "account.account",
        string="Gasto de bonificación por desahucio",
        ondelete="restrict",
        check_company=True,
        help="Cuenta de gasto de la bonificación por desahucio. Vacía: "
        "52020305 «Desahucio» del plan de cuentas.",
    )
    erp_settlement_indemnity_account_id = fields.Many2one(
        "account.account",
        string="Gasto de indemnización por despido",
        ondelete="restrict",
        check_company=True,
        help="Cuenta de gasto de la indemnización por despido intempestivo. "
        "Vacía: 52020304 «Despido intempestivo» del plan de cuentas.",
    )
    erp_settlement_payable_account_id = fields.Many2one(
        "account.account",
        string="Liquidaciones por pagar",
        ondelete="restrict",
        check_company=True,
        help="Cuenta por pagar del neto de la liquidación al empleado. Vacía: "
        "la cuenta acreedora de la regla «Neto» del rol mensual (Sueldos por "
        "pagar).",
    )
