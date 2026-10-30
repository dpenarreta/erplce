from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date


class HrPayslipEmployees(models.TransientModel):
    _inherit = "hr.payslip.employees"

    def compute_sheet(self):
        """Genera los roles del lote omitiendo, sin detener el lote, a los
        empleados que no pueden tener rol en el periodo (US-008, CA-8):

        - sin contrato en curso o expirado que cubra el periodo del lote;
        - con un rol no anulado del mismo periodo y estructura.

        Los omitidos se informan en una notificación y en el historial del
        lote. Cualquier otro error del cálculo (parámetro sin vigencia,
        empleado sin establecimiento, neto negativo...) detiene el lote
        completo: es un problema de configuración que hay que corregir antes.
        Si no queda ningún empleado, ``UserError`` con la lista.

        El contrato asignado a cada rol es el que cubre el periodo (el de
        inicio más reciente; ``hr.payslip.get_payslip_vals``), no el contrato
        actual del empleado; los demás contratos del periodo (p. ej. el
        expirado en una renovación a mitad de mes) entran también en el
        cálculo (``hr.payslip._get_employee_contracts``).
        """
        self.ensure_one()
        run = self.env["hr.payslip.run"].browse(self.env.context.get("active_id"))
        if not run or not self.employee_ids:
            return super().compute_sheet()
        Payslip = self.env["hr.payslip"]
        date_from, date_to = run.date_start, run.date_end
        contracts = Payslip._erp_get_period_contracts(
            self.employee_ids, date_from, date_to
        )
        without_contract = self.employee_ids.filtered(
            lambda employee: employee.id not in contracts
        )
        with_payslip = self._erp_get_employees_with_payslip(
            self.employee_ids - without_contract, contracts, run
        )
        to_process = self.employee_ids - without_contract - with_payslip
        period = _(
            "del %(date_from)s al %(date_to)s",
            date_from=format_date(self.env, date_from),
            date_to=format_date(self.env, date_to),
        )
        skipped_lines = [
            self.env._(
                "- %(employee)s: sin contrato que cubra el periodo",
                employee=employee.name,
            )
            for employee in without_contract
        ] + [
            self.env._(
                "- %(employee)s: ya tiene un rol del periodo", employee=employee.name
            )
            for employee in with_payslip
        ]
        if not to_process:
            raise UserError(
                _(
                    "No se generó ningún rol para el periodo %(period)s:\n"
                    "%(details)s",
                    period=period,
                    details="\n".join(skipped_lines),
                )
            )
        self.employee_ids = to_process
        # Mapa empleado -> contrato del periodo ya calculado para todo el lote:
        # hr.payslip.get_payslip_vals lo reutiliza en lugar de buscar el
        # contrato empleado por empleado (y comprueba que sea del empleado).
        result = super(
            HrPayslipEmployees,
            self.with_context(
                erp_period_contract_ids={
                    employee_id: contract.id
                    for employee_id, contract in contracts.items()
                }
            ),
        ).compute_sheet()
        if not skipped_lines:
            return result
        message = _(
            "Se omitieron %(count)s empleados del lote (periodo %(period)s):\n"
            "%(details)s",
            count=len(skipped_lines),
            period=period,
            details="\n".join(skipped_lines),
        )
        run.message_post(body=message)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Roles generados con empleados omitidos"),
                "message": message,
                "type": "warning",
                "sticky": True,
                "next": result,
            },
        }

    def _erp_get_employees_with_payslip(self, employees, contracts, run):
        """Empleados que ya tienen un rol no anulado (ni reembolsado) del
        periodo del lote con la estructura que se usaría (la del lote o la del
        contrato del periodo)."""
        if not employees:
            return employees
        # sudo(): la comprobación debe ver los roles de todo el personal (las
        # reglas de registro del usuario de nómina ocultan los de otros
        # departamentos); solo se leen empleado y estructura.
        existing = (
            self.env["hr.payslip"]
            .sudo()
            .search_fetch(
                [
                    ("employee_id", "in", employees.ids),
                    ("date_from", "=", run.date_start),
                    ("date_to", "=", run.date_end),
                    ("state", "!=", "cancel"),
                    ("credit_note", "!=", True),
                    ("refunded_id", "=", False),
                ],
                ["employee_id", "struct_id"],
            )
        )
        keys = {(slip.employee_id.id, slip.struct_id.id) for slip in existing}
        return employees.filtered(
            lambda employee: (
                employee.id,
                (run.struct_id or contracts[employee.id].struct_id).id,
            )
            in keys
        )
