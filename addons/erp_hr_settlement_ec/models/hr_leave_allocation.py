from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .const import SETTLEMENT_TRANSITION_KEY

# Campos de la marca de liquidación: solo los escriben las acciones de la
# liquidación (confirmar / anular).
SETTLEMENT_MARK_FIELDS = frozenset({"erp_settlement_id", "erp_settled_days"})


class HrLeaveAllocation(models.Model):
    """Periodo de vacaciones liquidado (US-013, CA-9, CA-10).

    Al confirmar una liquidación, la capa de negocio deja sin saldo los
    periodos de vacaciones pagados y los marca con la liquidación y los días
    que se le quitaron (``erp_settled_days``), para restituirlos exactamente
    si la liquidación se anula. Un reingreso empieza de cero (US-012).
    """

    _inherit = "hr.leave.allocation"

    erp_settlement_id = fields.Many2one(
        "erp.hr.settlement",
        string="Liquidado en",
        readonly=True,
        copy=False,
        index="btree_not_null",
        # Una liquidación con periodos marcados está confirmada y no se puede
        # eliminar; la anulación quita la marca antes.
        ondelete="restrict",
        groups="payroll.group_payroll_user",
        help="Liquidación de haberes que pagó el saldo de este periodo.",
    )
    erp_settled_days = fields.Float(
        string="Días liquidados",
        readonly=True,
        copy=False,
        digits=(16, 2),
        groups="payroll.group_payroll_user",
        help="Días del saldo de este periodo pagados en la liquidación; se "
        "devuelven al saldo si la liquidación se anula.",
    )

    _sql_constraints = [
        (
            # Redefine la restricción (mismo nombre) de hr_holidays, ya
            # redefinida por erp_hr_holidays_ec: además de sus casos, un
            # periodo liquidado puede quedar con saldo 0 (US-013, CA-9).
            "duration_check",
            "CHECK ((number_of_days > 0 AND allocation_type = 'regular') "
            "OR (allocation_type != 'regular') "
            "OR ((COALESCE(erp_history_days, 0) > 0 "
            "OR erp_settlement_id IS NOT NULL) AND number_of_days >= 0))",
            "Los días del saldo deben ser mayores que cero.",
        ),
        (
            "erp_settled_days_positive_check",
            "CHECK (erp_settled_days IS NULL OR erp_settled_days >= 0)",
            "Los días liquidados de un periodo de vacaciones no pueden ser "
            "negativos.",
        ),
        (
            "erp_settled_requires_settlement_check",
            "CHECK (erp_settlement_id IS NOT NULL "
            "OR COALESCE(erp_settled_days, 0) = 0)",
            "Un periodo de vacaciones con días liquidados debe indicar la "
            "liquidación que los pagó.",
        ),
    ]

    # ------------------------------------------------------------------
    # Marca de liquidación protegida (US-013, CA-9, CA-10)
    # ------------------------------------------------------------------
    @api.model
    def _erp_check_settlement_mark(self, field_names):
        """``erp_settlement_id`` y ``erp_settled_days`` solo cambian dentro de
        las acciones de la liquidación (confirmar / anular, indicador
        ``SETTLEMENT_TRANSITION_KEY`` en ``cr.cache``) o con ``env.su``
        (carga de datos, migraciones): editarlos a mano rompería la
        restitución exacta del saldo al anular."""
        if (
            self.env.su
            or self.env.cr.cache.get(SETTLEMENT_TRANSITION_KEY)
            or not SETTLEMENT_MARK_FIELDS.intersection(field_names)
        ):
            return
        raise UserError(
            _(
                "La marca de periodo de vacaciones liquidado («Liquidado en» y "
                "«Días liquidados») no se modifica a mano: la ponen la "
                "confirmación de la liquidación y la quita su anulación."
            )
        )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if any(vals.get(name) for name in SETTLEMENT_MARK_FIELDS):
                self._erp_check_settlement_mark(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._erp_check_settlement_mark(vals)
        return super().write(vals)
