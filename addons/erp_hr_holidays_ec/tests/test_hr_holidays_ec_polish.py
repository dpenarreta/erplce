"""Ronda de pulido de US-012 (observaciones de los auditores, sin
bloqueantes):

- O-A: un adelanto de la fecha de ingreso con el contrato abierto no es un
  reingreso.
- O-B: re-comprobación del cruce de caducidad al liberar saldo.
- QA-UX: mensajes de «Calcular vacaciones».
- QA-TECH P3: unicidad de la carga histórica en la BD.
- O-C: nombre de la tarea programada sin «asignación».

Parámetros FICTICIOS de ``HolidaysEcCase`` (12 días base, adicionales desde
el año 3 a 2 por año con tope 5, vigencia de 3 años).
"""

import re
from datetime import date
from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests import new_test_user, tagged
from odoo.tools import format_date, mute_logger

from odoo.addons.erp_hr_holidays_ec.models.hr_leave_allocation import (
    HrLeaveAllocation,
)

from .test_hr_holidays_ec_business import GENERATOR_LOGGER, RUN_DATE, HolidaysEcCase

OFFICER_GROUPS = "base.group_user,hr.group_hr_user,hr_holidays.group_hr_holidays_user"


@tagged("post_install", "-at_install")
class TestRehireCriterion(HolidaysEcCase):
    """O-A: reingreso solo con un contrato cerrado que termina antes de la
    nueva fecha."""

    def test_advance_with_open_contract_blocked(self):
        employee = self._employee("Adelanto Abierto Ñúñez", date(2022, 1, 3))
        employee._erp_generate_vacation_allocations(RUN_DATE)
        self.assertEqual(self._years(employee), [2, 3, 4])
        # Posterior a todos sus periodos (el año 4 nació el 2026-01-03), pero
        # el contrato sigue abierto: no es un reingreso.
        with self.assertRaisesMessage(UserError, "Rechace y elimine"):
            employee.erp_company_entry_date = date(2026, 2, 1)
        self.assertFalse(employee.erp_company_entry_date)

    def test_generation_with_open_contract_blocked(self):
        """Mismo criterio en la generación: periodos con otra fecha de
        ingreso y ningún contrato cerrado antes de la fecha actual."""
        employee = self._employee("Generación Abierta Peña", date(2022, 1, 3))
        employee._erp_generate_vacation_allocations(RUN_DATE)
        # Cambio directo en la BD de la fecha de ingreso registrada (sin el
        # control de write), como si viniera de una importación antigua.
        employee.sudo()._write({"erp_company_entry_date": date(2026, 2, 1)})
        employee.invalidate_recordset(["erp_company_entry_date"])
        with self.assertRaisesMessage(UserError, "cambió del"):
            employee._erp_generate_vacation_allocations(RUN_DATE)
        self.assertEqual(self._years(employee), [2, 3, 4])

    def test_conflicts_helper(self):
        employee = self._employee("Ayudante Conflictos Ávila", date(2022, 1, 3))
        periods = employee._erp_generate_vacation_allocations(RUN_DATE)
        conflicts = employee._erp_entry_date_conflicts
        new_entry = date(2026, 2, 1)
        # Sin contrato cerrado: todos chocan.
        self.assertEqual(len(conflicts(new_entry, list(periods), [])), 3)
        # Contrato cerrado antes de la nueva fecha: solo los nacidos después.
        self.assertEqual(conflicts(new_entry, list(periods), [date(2026, 1, 20)]), [])
        self.assertEqual(
            len(conflicts(date(2025, 6, 1), list(periods), [date(2025, 5, 30)])), 1
        )
        # Contrato cerrado que termina después de la nueva fecha: no cuenta.
        self.assertEqual(
            len(conflicts(new_entry, list(periods), [date(2026, 3, 1)])), 3
        )
        # Misma fecha con la que se calcularon: sin conflicto.
        self.assertEqual(conflicts(date(2022, 1, 3), list(periods), []), [])

    def test_blocked_message_plural(self):
        first = self._employee("Plural Uno Íñiguez", date(2022, 1, 3))
        second = self._employee("Plural Dos Cañar", date(2022, 1, 3))
        (first | second)._erp_generate_vacation_allocations(RUN_DATE)
        with self.assertRaisesMessage(
            UserError,
            "de Plural Uno Íñiguez y Plural Dos Cañar: ya tienen periodos",
        ):
            (first | second).write({"erp_company_entry_date": date(2021, 1, 4)})
        with self.assertRaisesMessage(
            UserError, "de Plural Uno Íñiguez: ya tiene periodos"
        ):
            first.erp_company_entry_date = date(2021, 1, 4)


@tagged("post_install", "-at_install")
class TestExpiryRecheck(HolidaysEcCase):
    """O-B. Ingreso 2019-11-10, cálculo al 2026-11-05 (vigencia ficticia de
    3 años): año 4 caduca 2026-11-09 con 16 días; año 5 desde 2024-11-10."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls._employee("Recheck Yépez Ñauta", date(2019, 11, 10))
        cls.employee._erp_generate_vacation_allocations(date(2026, 11, 5))
        cls.History = cls.env["erp.hr.vacation.history"]

    def _leave(self, date_from, date_to):
        return self.env["hr.leave"].create(
            {
                "employee_id": self.employee.id,
                "holiday_status_id": self.vacation.id,
                "request_date_from": date_from,
                "request_date_to": date_to,
            }
        )

    def _recheck_message(self, action):
        return re.escape(
            f"No se puede {action}: la solicitud de vacaciones de "
            f"{self.employee.name} del {format_date(self.env, date(2026, 11, 5))} "
            f"al {format_date(self.env, date(2026, 11, 14))} cruzaría la "
            "caducidad del periodo del año 4 "
            f"({format_date(self.env, date(2026, 11, 9))})"
        )

    def _crossing_after_history(self):
        line = self.History.create(
            {
                "employee_id": self.employee.id,
                "date": date(2026, 11, 4),
                "number_of_days": 16,
                "service_year": 4,
            }
        )
        crossing = self._leave(date(2026, 11, 5), date(2026, 11, 14))
        return line, crossing

    def _crossing_after_leave(self):
        """Una solicitud anterior (20/10 – 04/11, 16 días calendario) agota
        el año 4; la siguiente cruza su caducidad sin saldo y se admite."""
        earlier = self._leave(date(2026, 10, 20), date(2026, 11, 4))
        self.assertEqual(earlier.number_of_days, 16)
        crossing = self._leave(date(2026, 11, 5), date(2026, 11, 14))
        return earlier, crossing

    def test_history_unlink_rechecked(self):
        line, crossing = self._crossing_after_history()
        with self.assertRaisesMessage(
            ValidationError,
            self._recheck_message("eliminar las vacaciones gozadas antes del sistema"),
        ):
            line.unlink()
        self.env.invalidate_all()
        self.assertTrue(line.exists())
        # Tras anular la solicitud que cruza, sí se puede.
        crossing.action_refuse()
        line.unlink()
        self.assertFalse(line.exists())

    def test_history_reduction_rechecked(self):
        line, _crossing = self._crossing_after_history()
        with self.assertRaisesMessage(
            ValidationError,
            self._recheck_message("cambiar las vacaciones gozadas antes del sistema"),
        ):
            line.number_of_days = 10
        self.env.invalidate_all()
        self.assertEqual(line.number_of_days, 16)
        # Cambiar la observación no reparte ni re-comprueba.
        line.note = "Revisado por Talento Humano"

    def test_refuse_earlier_leave_rechecked(self):
        earlier, crossing = self._crossing_after_leave()
        with self.assertRaisesMessage(
            ValidationError, self._recheck_message("rechazar la solicitud")
        ):
            earlier.action_refuse()
        self.env.invalidate_all()
        self.assertEqual(earlier.state, "confirm")
        # Anulada primero la que cruza, la anterior se rechaza sin problema.
        crossing.action_refuse()
        earlier.action_refuse()
        self.assertEqual(earlier.state, "refuse")

    def test_cancel_earlier_leave_rechecked(self):
        earlier, _crossing = self._crossing_after_leave()
        with self.assertRaisesMessage(
            ValidationError, self._recheck_message("anular la solicitud")
        ):
            earlier.write({"state": "cancel"})

    def test_unlink_earlier_leave_rechecked(self):
        earlier, _crossing = self._crossing_after_leave()
        with self.assertRaisesMessage(
            ValidationError, self._recheck_message("eliminar la solicitud")
        ):
            earlier.unlink()
        self.env.invalidate_all()
        self.assertTrue(earlier.exists())

    def test_no_crossing_no_error(self):
        earlier = self._leave(date(2026, 10, 20), date(2026, 10, 24))
        later = self._leave(date(2026, 11, 10), date(2026, 11, 14))
        earlier.action_refuse()
        later.unlink()
        self.assertEqual(earlier.state, "refuse")


@tagged("post_install", "-at_install")
class TestGenerationMessages(HolidaysEcCase):
    """QA-UX: mensajes de «Calcular vacaciones»."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.officer = new_test_user(
            cls.env, login="encargado_pulido_us012", groups=OFFICER_GROUPS
        )

    def _calculate(self, employees):
        return employees.with_user(
            self.officer
        ).action_erp_generate_vacation_allocations()

    def test_single_business_error_not_wrapped(self):
        employee = self._employee("Sin Envoltorio Ordóñez", date(2024, 3, 4))
        employee._erp_generate_vacation_allocations(RUN_DATE)
        self._contract(
            employee, date(2022, 1, 3), state="close", date_end=date(2024, 3, 3)
        )
        with self.assertRaises(UserError) as ctx:
            self._calculate(employee)
        message = str(ctx.exception)
        self.assertTrue(message.startswith("La fecha de ingreso de"), message)
        self.assertNotIn("No se pudieron generar", message)

    def test_single_technical_error_generic(self):
        employee = self._employee("Error Técnico Cevallos", date(2024, 3, 4))

        def fail(_allocations):
            raise RuntimeError("detalle interno que no debe verse")

        with (
            patch.object(HrLeaveAllocation, "_erp_validate_generated", fail),
            self.assertLogs(GENERATOR_LOGGER, "ERROR") as logs,
            self.assertRaises(UserError) as ctx,
        ):
            self._calculate(employee)
        message = str(ctx.exception)
        self.assertIn("error técnico", message)
        self.assertNotIn("detalle interno", message)
        self.assertNotIn("Traceback", message)
        self.assertIn("detalle interno", "\n".join(logs.output))
        self.assertFalse(self._auto_allocations(employee))

    def test_missing_vacation_type_says_where(self):
        employee = self._employee("Sin Tipo Benítez", date(2024, 3, 4))
        self.vacation.active = False
        with self.assertRaisesMessage(
            UserError, "Ausencias > Configuración > Tipos de ausencia"
        ):
            self._calculate(employee)

    def test_nobody_eligible_single(self):
        employee = self._employee("Sin Contrato Íñiguez")
        action = self._calculate(employee)
        self.assertEqual(
            action["params"]["message"],
            "No se calcularon vacaciones: Sin Contrato Íñiguez no tiene un "
            "contrato en curso con relación laboral. Registre el contrato y "
            "vuelva a calcular.",
        )
        self.assertEqual(action["params"]["type"], "warning")

    def test_nobody_eligible_many(self):
        employees = self.env["hr.employee"]
        for index in range(1, 8):
            employees |= self._employee(f"Sin Contrato {index} Peña")
        no_labor = self._employee(
            "Servicios Sáenz", date(2024, 1, 2), contract_type=self.type_no_labor
        )
        action = self._calculate(employees[:2])
        self.assertIn(
            "Sin Contrato 1 Peña y Sin Contrato 2 Peña no tienen un contrato",
            action["params"]["message"],
        )
        action = self._calculate(employees | no_labor)
        message = action["params"]["message"]
        self.assertIn("Sin Contrato 5 Peña y 3 más no tienen", message)
        self.assertNotIn("ya tienen su periodo", message)


@tagged("post_install", "-at_install")
class TestHistoryUniqueAndCron(HolidaysEcCase):
    """QA-TECH P3 (unicidad en la BD) y O-C (nombre de la tarea)."""

    def test_database_unique_constraint(self):
        employee = self._employee("Único BD Ñacato", date(2023, 1, 2))
        employee._erp_generate_vacation_allocations(RUN_DATE)
        line = self.env["erp.hr.vacation.history"].create(
            {"employee_id": employee.id, "date": RUN_DATE, "number_of_days": 1}
        )
        line.flush_recordset()
        # Sin pasar por el ORM (como dos importaciones simultáneas): la BD lo
        # impide; el año vacío cuenta como 0.
        for service_year in (None, 0):
            with (
                mute_logger("odoo.sql_db"),
                self.assertRaises(IntegrityError),
                self.env.cr.savepoint(),
            ):
                self.env.cr.execute(
                    """
                    INSERT INTO erp_hr_vacation_history
                        (employee_id, company_id, date, number_of_days,
                         service_year)
                    SELECT employee_id, company_id, date, 2, %s
                      FROM erp_hr_vacation_history WHERE id = %s
                    """,
                    (service_year, line.id),
                )

    def test_write_into_existing_key_rejected(self):
        employee = self._employee("Clave Escritura Ávila", date(2023, 1, 2))
        employee._erp_generate_vacation_allocations(RUN_DATE)
        History = self.env["erp.hr.vacation.history"]
        History.create(
            {"employee_id": employee.id, "date": RUN_DATE, "number_of_days": 1}
        )
        other = History.create(
            {
                "employee_id": employee.id,
                "date": date(2026, 10, 1),
                "number_of_days": 1,
            }
        )
        with self.assertRaisesMessage(ValidationError, "Ya hay una línea"):
            other.date = RUN_DATE

    def test_cron_name_without_allocation(self):
        cron = self.env.ref("erp_hr_holidays_ec.ir_cron_generate_vacation_allocations")
        self.assertEqual(
            cron.name, "Ausencias Ecuador: generar periodos anuales de vacaciones"
        )
        self.assertNotIn("asignaci", cron.name.lower())
        self.assertFalse(cron.active)

    def test_allocation_field_help_without_allocation_word(self):
        fields_ = self.env["hr.leave.allocation"]._fields
        for name in ("erp_service_year", "erp_auto_generated"):
            self.assertNotIn("asignación", fields_[name].help.lower(), name)
