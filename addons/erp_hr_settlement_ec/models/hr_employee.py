from datetime import datetime, time

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round
from odoo.tools.misc import format_date

from odoo.addons.erp_hr_holidays_ec.models.hr_employee import (
    ALLOCATION_PARAMETER_CODES,
    ErpVacationParameterTable,
)

# Días del saldo de vacaciones: centésimas, como los periodos de US-012.
VACATION_DAYS_DIGITS = 2


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def _erp_get_settlement_vacation_balance(self, date_departure):
        """Saldo de vacaciones no gozadas a liquidar a la fecha de salida
        (US-013, CA-6.3, CA-9).

        Periodos considerados: asignaciones validadas de tipos «Vacaciones
        anuales» (``erp_is_annual_vacation``) vigentes a la fecha de salida
        (nacidas y no caducadas), sin liquidar. Días de cada periodo: su saldo
        con las ausencias aprobadas (``remaining_leaves`` del reparto FIFO del
        núcleo, ``_get_consumed_leaves``).

        Antes de calcular se exige un estado limpio, con ``UserError`` en
        español:

        - ninguna solicitud de vacaciones pendiente de aprobación (no se sabe
          si se gozará);
        - ninguna ausencia de vacaciones aprobada que termine después de la
          fecha de salida (consumiría saldo que no se goza);
        - ningún periodo de vacaciones por antigüedad sin generar (tarea
          programada inactiva o fecha de ingreso cargada después): se pide
          «Calcular vacaciones» en la ficha. Solo si el empleado tiene
          derecho a la generación automática (US-012).

        sudo(): la nómina calcula la liquidación sin permisos de ausencias;
        se leen solo saldos y fechas del propio empleado y no se devuelven
        registros al usuario (la vista usa el resumen calculado de la
        liquidación).

        :return: lista de ``(hr.leave.allocation (sudo), días)`` con días > 0,
            del periodo más antiguo al más nuevo
        """
        self.ensure_one()
        employee = self.sudo()
        date_departure = fields.Date.to_date(date_departure)
        vacation_types = (
            self.env["hr.leave.type"]
            .sudo()
            .with_context(active_test=False)
            .search([("erp_is_annual_vacation", "=", True)])
        )
        if not vacation_types:
            return []
        Leave = self.env["hr.leave"].sudo()
        pending = Leave.search(
            [
                ("employee_id", "=", employee.id),
                ("holiday_status_id", "in", vacation_types.ids),
                ("state", "in", ("confirm", "validate1")),
            ]
        )
        if pending:
            raise UserError(
                _(
                    "%(employee)s tiene solicitudes de vacaciones pendientes de "
                    "aprobación (%(leaves)s). Apruébelas o recházelas antes de "
                    "calcular la liquidación.",
                    employee=employee.name,
                    leaves=", ".join(
                        format_date(self.env, leave.request_date_from)
                        for leave in pending
                    ),
                )
            )
        later = Leave.search(
            [
                ("employee_id", "=", employee.id),
                ("holiday_status_id", "in", vacation_types.ids),
                ("state", "=", "validate"),
                ("date_to", ">", datetime.combine(date_departure, time.max)),
            ]
        )
        if later:
            raise UserError(
                _(
                    "%(employee)s tiene vacaciones aprobadas después de la fecha "
                    "de salida (%(departure)s): %(leaves)s. Anule esas ausencias "
                    "(o la parte posterior a la salida) antes de calcular la "
                    "liquidación.",
                    employee=employee.name,
                    departure=format_date(self.env, date_departure),
                    leaves=", ".join(
                        format_date(self.env, leave.request_date_from)
                        for leave in later
                    ),
                )
            )
        employee._erp_check_settlement_vacation_periods(date_departure)
        Allocation = self.env["hr.leave.allocation"].sudo()
        allocations = Allocation.search(
            [
                ("employee_id", "=", employee.id),
                ("holiday_status_id", "in", vacation_types.ids),
                ("state", "=", "validate"),
                ("erp_settlement_id", "=", False),
                ("date_from", "<=", date_departure),
                "|",
                ("date_to", "=", False),
                ("date_to", ">=", date_departure),
            ],
            order="date_to, date_from, id",
        )
        if not allocations:
            return []
        consumed = employee._get_consumed_leaves(
            allocations.holiday_status_id, target_date=date_departure
        )[0]
        result = []
        for allocation in allocations:
            data = consumed[employee][allocation.holiday_status_id].get(allocation, {})
            days = float_round(
                data.get("remaining_leaves", 0.0), precision_digits=VACATION_DAYS_DIGITS
            )
            if float_compare(days, 0.0, precision_digits=VACATION_DAYS_DIGITS) > 0:
                result.append((allocation, days))
        return result

    def _erp_check_settlement_vacation_periods(self, date_departure):
        """Todos los periodos de vacaciones por antigüedad vigentes a la fecha
        de salida existen (generados, en cualquier estado): si falta alguno,
        su saldo no entraría en la liquidación. Solo para empleados con
        derecho a la generación automática (US-012,
        ``_erp_vacation_eligible_domain``).

        :raises UserError: faltan periodos (indica los años de servicio)
        """
        self.ensure_one()
        if not self.filtered_domain(self._erp_vacation_eligible_domain()):
            return
        params = ErpVacationParameterTable(self.env, ALLOCATION_PARAMETER_CODES)
        expected = self._erp_vacation_periods(date_departure, params)
        if not expected:
            return
        entry = self._erp_get_entry_date()
        existing = set(
            self.env["hr.leave.allocation"]
            .sudo()
            .search(
                [
                    ("employee_id", "=", self.id),
                    ("erp_auto_generated", "=", True),
                    ("erp_entry_date", "=", entry),
                ]
            )
            .mapped("erp_service_year")
        )
        missing = [
            year for year, _anniversary, _expiry in expected if year not in existing
        ]
        if missing:
            raise UserError(
                _(
                    "Faltan los periodos de vacaciones de %(employee)s de los "
                    "años de servicio %(years)s (fecha de ingreso %(entry)s). "
                    "Pulse «Calcular vacaciones» en la ficha del empleado antes "
                    "de calcular la liquidación, para que su saldo se incluya.",
                    employee=self.name,
                    years=", ".join(str(year) for year in missing),
                    entry=format_date(self.env, entry),
                )
            )
