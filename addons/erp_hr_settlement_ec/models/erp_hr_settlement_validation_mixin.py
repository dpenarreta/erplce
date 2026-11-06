from contextlib import contextmanager

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError

from .const import (
    PAYROLL_MANAGER_GROUP,
    VALIDATION_STATE_SELECTION,
    VALIDATION_TRANSITION_KEY,
)


class ErpHrSettlementValidationMixin(models.AbstractModel):
    """Marca «A validar» / «Validado» de la configuración legal de la
    liquidación (causas de salida, tramos de indemnización), con el mismo
    criterio que ``erp.payroll.parameter`` (US-013, CA-12): los valores de
    partida se cargan «A validar» y solo el responsable de nómina los marca
    como validados."""

    _name = "erp.hr.settlement.validation.mixin"
    _description = "Configuración de liquidación a validar"

    state = fields.Selection(
        VALIDATION_STATE_SELECTION,
        string="Estado",
        required=True,
        default="to_validate",
        tracking=True,
        copy=False,
        help="«A validar»: valor de partida pendiente de confirmación por el "
        "responsable de nómina o el asesor laboral. «Validado»: confirmado.",
    )

    # Campos que definen el valor legal: si cambian en un registro
    # «Validado», vuelve a «A validar» (lo define cada modelo).
    _erp_revalidate_fields = ()

    @contextmanager
    def _erp_validation_transition(self):
        """Marca en ``cr.cache`` (no en el contexto, que controla el cliente
        RPC) que una acción de validación está en curso: solo entonces se
        escribe ``state``. Se retira en ``finally``."""
        cache = self.env.cr.cache
        cache[VALIDATION_TRANSITION_KEY] = cache.get(VALIDATION_TRANSITION_KEY, 0) + 1
        try:
            yield
        finally:
            cache[VALIDATION_TRANSITION_KEY] -= 1
            if not cache[VALIDATION_TRANSITION_KEY]:
                cache.pop(VALIDATION_TRANSITION_KEY)

    def write(self, vals):
        """El estado solo cambia con Validar / Volver a «A validar» (también
        para el responsable: ``UserError``), salvo ``env.su`` (carga de
        datos, migraciones). Cambiar un valor legal de un registro «Validado»
        lo devuelve a «A validar» (mismo criterio que los parámetros de
        nómina, US-017 CA-10)."""
        in_transition = self.env.su or bool(
            self.env.cr.cache.get(VALIDATION_TRANSITION_KEY)
        )
        if "state" in vals and not in_transition:
            raise UserError(
                _(
                    "El estado «A validar» / «Validado» solo cambia con los "
                    "botones Validar y Volver a «A validar» del responsable de "
                    "nómina."
                )
            )
        revalidate = self.browse()
        if not in_transition and set(self._erp_revalidate_fields).intersection(vals):
            revalidate = self.filtered(lambda record: record.state == "validated")
        res = super().write(vals)
        if revalidate:
            with self._erp_validation_transition():
                revalidate.write({"state": "to_validate"})
        return res

    def _erp_set_validation_state(self, state):
        if not self.env.su and not self.env.user.has_group(PAYROLL_MANAGER_GROUP):
            raise AccessError(
                _(
                    "Solo el responsable de nómina puede validar la "
                    "configuración de las liquidaciones. Pida a su responsable "
                    "que la revise."
                )
            )
        # Idempotente: los que ya están en el estado destino no cambian.
        with self._erp_validation_transition():
            self.filtered(lambda record: record.state != state).write({"state": state})
        return True

    def action_validate(self):
        """Marca como «Validado» (solo el responsable de nómina)."""
        return self._erp_set_validation_state("validated")

    def action_set_to_validate(self):
        """Devuelve a «A validar» (solo el responsable de nómina)."""
        return self._erp_set_validation_state("to_validate")
