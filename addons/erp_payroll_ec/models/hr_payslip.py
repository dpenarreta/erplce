from collections import defaultdict

from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date

# Estados de contrato que admiten un rol de pagos cuando el contrato está
# asignado explícitamente al rol: "open" (En curso) y "close" (Expirado; p. ej.
# el último rol de un contrato que terminó dentro del periodo).
PAYSLIP_EXPLICIT_CONTRACT_STATES = ("open", "close")
# Sin contrato asignado, el motor OCA (``_get_employee_contracts`` →
# ``hr.employee._get_contracts``) solo usa contratos "open"; se replica el mismo
# criterio para que la validación coincida con lo que realmente se calcularía.
PAYSLIP_IMPLICIT_CONTRACT_STATES = ("open",)
# Ajuste del motor OCA: si está activo, confirmar no recalcula el rol.
PREVENT_COMPUTE_ON_CONFIRM_PARAM = "payroll.prevent_compute_on_confirm"


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    def compute_sheet(self):
        """Calcula los roles de pagos validando antes, en lote, que todos
        tienen un contrato vigente en su periodo (US-006, CA-4).

        El motor OCA genera un rol vacío cuando no hay contrato; aquí se
        bloquea con un ``UserError`` que nombra a cada empleado afectado y su
        periodo. Si algún rol falla, no se calcula ninguno (no hay escrituras
        previas a la validación). Con contrato vigente se delega en el motor
        sin cambios.

        Acceso: el del motor (ACL de ``hr.payslip``, grupo de nómina).
        """
        self._check_contract_in_period()
        return super().compute_sheet()

    def action_payslip_done(self):
        """Confirma los roles validando el contrato también cuando el motor no
        va a recalcularlos (US-006, CA-4).

        OCA solo llama a ``compute_sheet()`` (y por tanto a la validación) si
        no hay ``without_compute_sheet`` en el contexto y el ajuste
        ``payroll.prevent_compute_on_confirm`` está desactivado. En los demás
        casos se valida aquí, salvo los reembolsos (``credit_note``), que el
        motor confirma con ``without_compute_sheet`` como copia de un rol ya
        confirmado.
        """
        if not self._will_compute_on_confirm():
            # El motor no recalculará; si recalculase, compute_sheet() ya valida.
            self.filtered(lambda slip: not slip.credit_note)._check_contract_in_period()
        return super().action_payslip_done()

    def _will_compute_on_confirm(self):
        """Replica la condición de ``action_payslip_done`` de OCA leyendo el
        parámetro directamente (el campo calculado de OCA exige un solo
        registro)."""
        if self.env.context.get("without_compute_sheet"):
            return False
        # sudo(): solo lectura de un ajuste técnico del motor; los usuarios de
        # nómina no tienen acceso a ir.config_parameter.
        prevent = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(PREVENT_COMPUTE_ON_CONFIRM_PARAM)
        )
        return not prevent

    def _check_contract_in_period(self):
        """Lanza ``UserError`` si algún rol de ``self`` tiene asignado un
        contrato de otro empleado o no tiene contrato vigente en su periodo."""
        foreign = self._get_payslips_with_foreign_contract()
        if foreign:
            details = "\n".join(
                _(
                    "- Rol de %(employee)s: el contrato «%(contract)s» pertenece "
                    "a %(owner)s",
                    employee=slip.employee_id.name,
                    contract=slip.contract_id.name,
                    owner=slip.contract_id.employee_id.name,
                )
                for slip in foreign
            )
            raise UserError(
                _(
                    "No se puede calcular ni confirmar el rol de pagos: el contrato "
                    "asignado no pertenece al empleado del rol:\n%(details)s\n\n"
                    "Asigne a cada rol un contrato del propio empleado.",
                    details=details,
                )
            )
        invalid = self._get_payslips_without_valid_contract()
        if not invalid:
            return
        details = "\n".join(
            _(
                "- %(employee)s: del %(date_from)s al %(date_to)s",
                employee=slip.employee_id.name,
                date_from=format_date(self.env, slip.date_from),
                date_to=format_date(self.env, slip.date_to),
            )
            for slip in invalid
        )
        raise UserError(
            _(
                "No se puede calcular ni confirmar el rol de pagos: estos empleados "
                "no tienen un contrato vigente en el periodo del rol:\n"
                "%(details)s\n\n"
                "Registre un contrato en curso que cubra el periodo, asigne al "
                "rol el contrato correcto o corrija las fechas del rol.",
                details=details,
            )
        )

    def _get_payslips_with_foreign_contract(self):
        """Roles cuyo contrato asignado es de otro empleado."""
        return self.filtered(
            lambda slip: slip.contract_id
            and slip.contract_id.employee_id != slip.employee_id
        )

    def _get_payslips_without_valid_contract(self):
        """Devuelve los roles de ``self`` sin contrato vigente en su periodo.

        - Rol con contrato asignado: el contrato debe estar en un estado de
          ``PAYSLIP_EXPLICIT_CONTRACT_STATES`` y solaparse con el periodo.
        - Rol sin contrato: el empleado debe tener algún contrato de
          ``PAYSLIP_IMPLICIT_CONTRACT_STATES`` que se solape con el periodo
          (mismo criterio que el motor). Se resuelve con una sola búsqueda para
          todo el lote y se filtra en memoria por empleado y periodo.

        :return: recordset ``hr.payslip`` (vacío si todos son válidos).
        """
        with_contract = self.filtered("contract_id")
        valid_with_contract = with_contract.filtered(
            lambda slip: slip.contract_id.state in PAYSLIP_EXPLICIT_CONTRACT_STATES
            and slip._contract_overlaps_period(slip.contract_id)
        )
        invalid = with_contract - valid_with_contract

        without_contract = self - with_contract
        if not without_contract:
            return invalid
        contracts = self.env["hr.contract"].search(
            [
                ("employee_id", "in", without_contract.employee_id.ids),
                ("state", "in", PAYSLIP_IMPLICIT_CONTRACT_STATES),
                ("date_start", "<=", max(without_contract.mapped("date_to"))),
                "|",
                ("date_end", "=", False),
                ("date_end", ">=", min(without_contract.mapped("date_from"))),
            ]
        )
        contracts_by_employee = defaultdict(list)
        for contract in contracts:
            contracts_by_employee[contract.employee_id.id].append(contract)
        for slip in without_contract:
            if not any(
                slip._contract_overlaps_period(contract)
                for contract in contracts_by_employee[slip.employee_id.id]
            ):
                invalid |= slip
        return invalid

    def _contract_overlaps_period(self, contract):
        """``True`` si ``contract`` está vigente en algún día del periodo del
        rol (``date_from``-``date_to``, ambos incluidos)."""
        self.ensure_one()
        return contract.date_start <= self.date_to and (
            not contract.date_end or contract.date_end >= self.date_from
        )
