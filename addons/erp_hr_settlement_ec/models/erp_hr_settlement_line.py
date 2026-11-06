from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .const import (
    DEDUCTION_LINE_CODES,
    LINE_TYPE_SELECTION,
    SETTLEMENT_LINE_CODE_SELECTION,
    SETTLEMENT_TRANSITION_KEY,
)

# Estados de la liquidación en los que sus rubros no cambian.
LOCKED_SETTLEMENT_STATES = ("done", "cancel")
# Tipos de cuenta que no admite un rubro manual: el dinero se mueve con el
# pago de la liquidación (caja, bancos, tarjetas), no en el asiento de la
# liquidación, y las cuentas de orden no son del balance.
EXCLUDED_ACCOUNT_TYPES = ("asset_cash", "liability_credit_card", "off_balance")


class ErpHrSettlementLine(models.Model):
    """Rubro de una liquidación (US-013, CA-6, CA-7).

    ``amount`` es siempre positivo; ``line_type`` (derivado del código) dice si
    suma (ingreso) o resta (descuento). Las líneas que genera «Calcular»
    llevan ``is_manual = False`` y se reemplazan al recalcular; las manuales
    (otros ingresos y descuentos) se conservan.
    """

    _name = "erp.hr.settlement.line"
    _description = "Rubro de liquidación de haberes"
    _order = "settlement_id, sequence, id"
    _check_company_auto = True

    settlement_id = fields.Many2one(
        "erp.hr.settlement",
        string="Liquidación",
        required=True,
        index=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        related="settlement_id.company_id",
        store=True,
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        related="settlement_id.currency_id",
    )
    sequence = fields.Integer(string="Secuencia", default=10)
    code = fields.Selection(
        SETTLEMENT_LINE_CODE_SELECTION,
        string="Rubro",
        required=True,
    )
    name = fields.Char(string="Descripción", required=True)
    line_type = fields.Selection(
        LINE_TYPE_SELECTION,
        string="Tipo",
        compute="_compute_line_type",
        store=True,
        precompute=True,
        help="Ingreso: suma al neto. Descuento: resta del neto.",
    )
    base = fields.Monetary(
        currency_field="currency_id",
        help="Importe base del cálculo (p. ej. remuneración o valor del día).",
    )
    quantity = fields.Float(
        string="Cantidad",
        digits=(16, 4),
        default=1.0,
        help="Días, años, meses o porcentaje aplicado a la base, según el " "rubro.",
    )
    amount = fields.Monetary(
        string="Importe",
        required=True,
        currency_field="currency_id",
        help="Importe del rubro, siempre positivo (el tipo indica si suma o " "resta).",
    )
    explanation = fields.Text(
        string="Explicación",
        help="Cómo se obtuvo el importe, en lenguaje claro (aparece en el PDF).",
    )
    is_manual = fields.Boolean(
        string="Manual",
        help="Rubro registrado a mano por RRHH: se conserva al recalcular.",
    )
    account_id = fields.Many2one(
        "account.account",
        string="Cuenta contable",
        ondelete="restrict",
        check_company=True,
        domain=[
            ("deprecated", "=", False),
            ("account_type", "not in", EXCLUDED_ACCOUNT_TYPES),
        ],
        help="Solo rubros manuales: cuenta del asiento para este valor. "
        "Vacía: la cuenta por defecto del tipo de rubro.",
    )
    provision_line_ids = fields.Many2many(
        "hr.payslip.line",
        "erp_hr_settlement_line_provision_rel",
        "settlement_line_id",
        "payslip_line_id",
        string="Provisiones incluidas",
        copy=False,
        help="Provisiones mensuales de décimos que suma este rubro; al "
        "confirmar la liquidación quedan marcadas como pagadas.",
    )

    _sql_constraints = [
        (
            "amount_positive_check",
            "CHECK (amount >= 0)",
            "El importe de un rubro de liquidación no puede ser negativo: use "
            "un rubro de descuento.",
        ),
        (
            "quantity_positive_check",
            "CHECK (quantity >= 0)",
            "La cantidad de un rubro de liquidación no puede ser negativa.",
        ),
        (
            "manual_code_check",
            "CHECK (is_manual IS NOT TRUE "
            "OR code IN ('OTHER_INCOME', 'OTHER_DEDUCTION'))",
            "Un rubro manual solo puede ser «Otro ingreso» u «Otro descuento».",
        ),
        (
            "manual_account_check",
            "CHECK (account_id IS NULL OR is_manual IS TRUE)",
            "Solo los rubros manuales llevan cuenta contable propia.",
        ),
    ]

    @api.depends("code")
    def _compute_line_type(self):
        for line in self:
            line.line_type = (
                "deduction" if line.code in DEDUCTION_LINE_CODES else "income"
            )

    # ------------------------------------------------------------------
    # Integridad (US-013, CA-7, CA-9)
    # ------------------------------------------------------------------
    @api.constrains("account_id")
    def _check_account(self):
        """La cuenta de un rubro manual no puede estar obsoleta ni ser de
        caja, bancos, tarjeta de crédito o de orden (mismo criterio que el
        dominio del campo, comprobado en el servidor)."""
        for line in self.filtered("account_id"):
            account = line.account_id
            if account.deprecated or account.account_type in EXCLUDED_ACCOUNT_TYPES:
                raise ValidationError(
                    _(
                        "La cuenta «%(account)s» no se puede usar en el rubro "
                        "«%(line)s»: está obsoleta o es de caja, bancos, tarjeta "
                        "de crédito o de orden. Elija una cuenta de gasto, "
                        "pasivo o por cobrar.",
                        account=account.display_name,
                        line=line.name,
                    )
                )

    def _erp_check_settlement_editable(self, settlements):
        """Los rubros de una liquidación confirmada o anulada no se crean,
        modifican ni borran fuera de sus acciones (tampoco el responsable de
        nómina): se anula y vuelve a borrador. Los de una calculada sí
        (rubros manuales, CA-7); si se edita un rubro calculado, confirmar
        exige recalcular."""
        if self.env.su or self.env.cr.cache.get(SETTLEMENT_TRANSITION_KEY):
            return
        locked = settlements.filtered(
            lambda settlement: settlement.state in LOCKED_SETTLEMENT_STATES
        )
        if locked:
            raise UserError(
                _(
                    "No se pueden modificar los rubros de una liquidación "
                    "confirmada o anulada: %(settlements)s.",
                    settlements=", ".join(locked.mapped("display_name")),
                )
            )

    @api.model_create_multi
    def create(self, vals_list):
        self._erp_check_settlement_editable(
            self.env["erp.hr.settlement"].browse(
                {
                    vals["settlement_id"]
                    for vals in vals_list
                    if vals.get("settlement_id")
                }
            )
        )
        return super().create(vals_list)

    def write(self, vals):
        settlements = self.settlement_id
        if vals.get("settlement_id"):
            settlements |= self.env["erp.hr.settlement"].browse(vals["settlement_id"])
        self._erp_check_settlement_editable(settlements)
        return super().write(vals)

    def unlink(self):
        self._erp_check_settlement_editable(self.settlement_id)
        return super().unlink()
