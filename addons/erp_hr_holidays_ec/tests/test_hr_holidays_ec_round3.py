"""Ronda 3 de correcciones de US-012 (CA-R3-1, CA-R3-2, CA-R3-3).

- CA-R3-1: cambiar la fecha del primer contrato (sin «Fecha de ingreso a la
  empresa») después de calcular no duplica periodos.
- CA-R3-2: una solicitud de vacaciones no puede cruzar la caducidad de un
  periodo con saldo.
- CA-R3-3: nombre del periodo tras la carga histórica, reimportación de la
  plantilla sin duplicar, plural de los textos y sin «asignación».

Parámetros FICTICIOS de ``HolidaysEcCase`` (12 días base, adicionales desde
el año 3 a 2 por año con tope 5, vigencia de 3 años, corte 2025-12-01).
"""

import re
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import new_test_user, tagged
from odoo.tools import format_date
from odoo.tools.misc import file_open

from odoo.addons.erp_hr_holidays_ec.models import text

from .test_hr_holidays_ec_business import (
    GENERATOR_LOGGER,
    RUN_DATE,
    HolidaysEcCase,
)
from .test_hr_holidays_ec_periods import IMPORT_OPTIONS, TEMPLATE_PATH

OFFICER_GROUPS = "base.group_user,hr.group_hr_user,hr_holidays.group_hr_holidays_user"


@tagged("post_install", "-at_install")
class TestEntryDateChange(HolidaysEcCase):
    """CA-R3-1 (QA-TECH P2): periodos calculados con una fecha de ingreso y
    luego cambia la fecha del primer contrato."""

    def _periods(self, employee):
        return [
            (a.erp_entry_date, a.erp_service_year)
            for a in self._auto_allocations(employee)
        ]

    def _load_previous_contract(self, employee, date_start, date_end):
        """Contrato anterior cargado después del cálculo (cerrado y sin hueco
        con el actual: el núcleo adelanta la fecha del primer contrato)."""
        self._contract(employee, date_start, state="close", date_end=date_end)

    def test_first_contract_change_blocks_generation(self):
        employee = self._employee("Verónica Peñafiel Ñauta", date(2024, 3, 4))
        employee._erp_generate_vacation_allocations(RUN_DATE)
        before = [(date(2024, 3, 4), 1), (date(2024, 3, 4), 2)]
        self.assertEqual(self._periods(employee), before)
        self._load_previous_contract(employee, date(2022, 1, 3), date(2024, 3, 3))
        self.assertEqual(employee.first_contract_date, date(2022, 1, 3))
        self.assertFalse(employee.erp_company_entry_date)
        expected = re.escape(
            f"La fecha de ingreso de {employee.name} cambió del "
            f"{format_date(self.env, date(2024, 3, 4))} al "
            f"{format_date(self.env, date(2022, 1, 3))} (inicio del primer "
            "contrato)"
        )
        with self.assertRaisesMessage(UserError, expected):
            employee._erp_generate_vacation_allocations(RUN_DATE)
        with self.assertRaisesMessage(UserError, "rechace y elimine"):
            employee._erp_generate_vacation_allocations(RUN_DATE)
        with self.assertRaisesMessage(UserError, "«Fecha de ingreso a la empresa»"):
            employee._erp_generate_vacation_allocations(RUN_DATE)
        # Ningún periodo nuevo (sin el control: años 2 a 4 desde 2022).
        self.assertEqual(self._periods(employee), before)

    def test_fix_by_setting_company_entry_date(self):
        """Fijar la «Fecha de ingreso a la empresa» en la fecha con la que se
        calcularon los periodos resuelve el conflicto sin tocar periodos."""
        employee = self._employee("Hernán Íñiguez Cañar", date(2024, 3, 4))
        employee._erp_generate_vacation_allocations(RUN_DATE)
        self._load_previous_contract(employee, date(2022, 1, 3), date(2024, 3, 3))
        employee.erp_company_entry_date = date(2024, 3, 4)
        self.assertFalse(employee._erp_generate_vacation_allocations(RUN_DATE))
        self.assertEqual(
            self._periods(employee), [(date(2024, 3, 4), 1), (date(2024, 3, 4), 2)]
        )
        # Otra fecha que también chocaría sigue bloqueada al guardar.
        with self.assertRaisesMessage(UserError, "Rechace y elimine"):
            employee.erp_company_entry_date = date(2023, 6, 1)

    def test_fix_by_refusing_and_deleting_periods(self):
        employee = self._employee("Gloria Muñoz Peña", date(2024, 3, 4))
        old = employee._erp_generate_vacation_allocations(RUN_DATE)
        self._load_previous_contract(employee, date(2022, 1, 3), date(2024, 3, 3))
        old.action_refuse()
        old.unlink()
        employee._erp_generate_vacation_allocations(RUN_DATE)
        # Desde 2022-01-03: el año 1 (caduca 2026-01-02) ya caducó.
        self.assertEqual(
            self._periods(employee),
            [(date(2022, 1, 3), 2), (date(2022, 1, 3), 3), (date(2022, 1, 3), 4)],
        )

    def test_refused_periods_do_not_block(self):
        employee = self._employee("Ramiro Ávila Ñúñez", date(2024, 3, 4))
        old = employee._erp_generate_vacation_allocations(RUN_DATE)
        self._load_previous_contract(employee, date(2022, 1, 3), date(2024, 3, 3))
        old.action_refuse()
        created = employee._erp_generate_vacation_allocations(RUN_DATE)
        self.assertEqual(created.mapped("erp_service_year"), [2, 3, 4])

    def test_rehire_still_allowed(self):
        """Un reingreso (nueva fecha posterior a todos los periodos) no es un
        conflicto: los periodos del empleo anterior nacieron antes."""
        employee = self._employee("Fabiola Ñacato Ruiz", date(2023, 1, 2))
        employee._erp_generate_vacation_allocations(date(2024, 3, 1))
        employee.contract_id.write({"date_end": date(2024, 6, 28), "state": "close"})
        self._contract(employee, date(2024, 7, 15))
        created = employee._erp_generate_vacation_allocations(RUN_DATE)
        self.assertEqual(created.mapped("erp_service_year"), [1, 2])

    def test_cron_logs_conflict_and_continues(self):
        today = fields.Date.today()
        start = today - relativedelta(years=1, days=3)
        conflicting = self._employee("Conflicto Fecha Peñaherrera", start)
        conflicting._erp_generate_vacation_allocations(today)
        self.assertEqual(self._periods(conflicting), [(start, 1)])
        self._load_previous_contract(
            conflicting, today - relativedelta(years=3), start - relativedelta(days=1)
        )
        ok = self._employee(
            "Sin Conflicto Benítez", today - relativedelta(years=1, days=5)
        )
        with self.assertLogs(GENERATOR_LOGGER, "WARNING") as logs:
            created = self.Allocation._erp_cron_generate_vacation_allocations()
        output = "\n".join(logs.output)
        self.assertIn("Conflicto Fecha Peñaherrera", output)
        self.assertIn("cambió del", output)
        self.assertEqual(created.employee_id, ok)
        self.assertEqual(self._periods(conflicting), [(start, 1)])

    def test_button_batch_lists_conflict(self):
        officer = new_test_user(
            self.env, login="encargado_conflicto_us012", groups=OFFICER_GROUPS
        )
        conflicting = self._employee("Lote Conflicto Ordóñez", date(2024, 3, 4))
        conflicting._erp_generate_vacation_allocations(RUN_DATE)
        self._load_previous_contract(conflicting, date(2022, 1, 3), date(2024, 3, 3))
        ok = self._employee("Lote Correcto Íñiguez", date(2025, 3, 1))
        with self.assertLogs(GENERATOR_LOGGER, "WARNING"):
            action = (
                (conflicting | ok)
                .with_user(officer)
                .action_erp_generate_vacation_allocations()
            )
        self.assertEqual(action["params"]["type"], "warning")
        self.assertIn("Lote Conflicto Ordóñez", action["params"]["message"])
        self.assertIn("cambió del", action["params"]["message"])
        self.assertEqual(self._years(ok), [1])
        self.assertEqual(self._years(conflicting), [1, 2])


@tagged("post_install", "-at_install")
class TestExpiryCrossing(HolidaysEcCase):
    """CA-R3-2 (QA-FUNC B8). Ingreso 2019-11-10, cálculo al 2026-11-05 con
    vigencia ficticia de 3 años:

    - año 4: nace 2023-11-10, caduca 2026-11-09, 16 días;
    - año 5: nace 2024-11-10, caduca 2027-11-09, 17 días;
    - año 6: nace 2025-11-10, caduca 2028-11-09, 17 días.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls._employee("Marcela Yépez Ñúñez", date(2019, 11, 10))
        cls.employee._erp_generate_vacation_allocations(date(2026, 11, 5))
        cls.expiry = date(2026, 11, 9)

    def _leave(self, date_from, date_to):
        return self.env["hr.leave"].create(
            {
                "employee_id": self.employee.id,
                "holiday_status_id": self.vacation.id,
                "request_date_from": date_from,
                "request_date_to": date_to,
            }
        )

    def _leave_count(self):
        return self.env["hr.leave"].search_count(
            [("employee_id", "=", self.employee.id)]
        )

    def _split_message(self):
        return re.escape(
            "Divida la solicitud: el periodo del año 4 caduca el "
            f"{format_date(self.env, self.expiry)}."
        )

    def _taken(self):
        consumed = self.employee._get_consumed_leaves(self.vacation, date(2026, 11, 5))
        data = consumed[0][self.employee][self.vacation]
        return {
            allocation.erp_service_year: data[allocation]["virtual_leaves_taken"]
            for allocation in self._auto_allocations(self.employee)
        }

    def test_periods_ready(self):
        allocations = self._auto_allocations(self.employee)
        self.assertEqual(
            [(a.erp_service_year, a.number_of_days, a.date_to) for a in allocations],
            [
                (4, 16, self.expiry),
                (5, 17, date(2027, 11, 9)),
                (6, 17, date(2028, 11, 9)),
            ],
        )

    def test_request_crossing_expiry_with_balance_rejected(self):
        with self.assertRaisesMessage(ValidationError, self._split_message()):
            self._leave(date(2026, 11, 5), date(2026, 11, 14))
        self.assertEqual(self._leave_count(), 0)
        self.assertEqual(self._taken(), {4: 0, 5: 0, 6: 0})

    def test_request_starting_on_expiry_rejected(self):
        with self.assertRaisesMessage(ValidationError, self._split_message()):
            self._leave(date(2026, 11, 9), date(2026, 11, 12))

    def test_split_requests_allowed(self):
        """Dividida en la caducidad: cada parte se descuenta entera en días
        calendario del periodo que corresponde."""
        first = self._leave(date(2026, 11, 5), date(2026, 11, 9))
        second = self._leave(date(2026, 11, 10), date(2026, 11, 14))
        self.assertEqual((first.number_of_days, second.number_of_days), (5, 5))
        self.assertEqual(self._taken(), {4: 5, 5: 5, 6: 0})

    def test_crossing_expiry_without_balance_allowed(self):
        """El año 4 ya no tiene saldo (gozado antes del sistema): toda la
        solicitud sale del año 5."""
        self.env["erp.hr.vacation.history"].create(
            {
                "employee_id": self.employee.id,
                "date": date(2026, 11, 4),
                "number_of_days": 16,
                "service_year": 4,
            }
        )
        leave = self._leave(date(2026, 11, 5), date(2026, 11, 14))
        self.assertEqual(leave.number_of_days, 10)
        self.assertEqual(self._taken(), {4: 0, 5: 10, 6: 0})

    def test_extending_request_over_expiry_rejected(self):
        leave = self._leave(date(2026, 11, 5), date(2026, 11, 9))
        with self.assertRaisesMessage(ValidationError, self._split_message()):
            leave.write({"request_date_to": date(2026, 11, 14)})

    def test_other_leave_types_not_affected(self):
        sick = self.env.ref("erp_hr_holidays_ec.leave_type_sick")
        leave = self.env["hr.leave"].create(
            {
                "employee_id": self.employee.id,
                "holiday_status_id": sick.id,
                "request_date_from": date(2026, 11, 5),
                "request_date_to": date(2026, 11, 14),
            }
        )
        self.assertTrue(leave)


@tagged("post_install", "-at_install")
class TestRound3Texts(HolidaysEcCase):
    """CA-R3-3: nombre del periodo tras la carga histórica (O2),
    reimportación sin duplicar (O3), plural y sin «asignación»."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.History = cls.env["erp.hr.vacation.history"]
        cls.employee = cls._employee(
            "María José Peña Ñúñez",
            cls.today - relativedelta(years=3, days=10),
            identification_id="0912345675",
        )
        cls.employee._erp_generate_vacation_allocations(cls.today)

    def _history(self, days, **vals):
        return self.History.create(
            {
                "employee_id": self.employee.id,
                "date": self.today,
                "number_of_days": days,
                **vals,
            }
        )

    def _import_template(self):
        with file_open(TEMPLATE_PATH, "rb") as template:
            content = template.read()
        wizard = self.env["base_import.import"].create(
            {
                "res_model": "erp.hr.vacation.history",
                "file": content,
                "file_name": "plantilla_vacaciones_gozadas.csv",
                "file_type": "text/csv",
            }
        )
        preview = wizard.parse_preview(dict(IMPORT_OPTIONS))
        fields_ = [
            "/".join(preview["matches"].get(index) or []) or False
            for index in range(len(preview["headers"]))
        ]
        return wizard.execute_import(fields_, preview["headers"], dict(IMPORT_OPTIONS))

    def test_period_name_kept_after_history(self):
        """O2: antes quedaba «Vacaciones anuales (0.0 día(s))»."""
        periods = self._auto_allocations(self.employee)
        names = periods.mapped("name")
        self.assertTrue(all("año de servicio" in name for name in names), names)
        self._history(15)
        periods.invalidate_recordset()
        self.assertEqual(periods.mapped("number_of_days"), [0, 9, 14])
        self.assertEqual(periods.mapped("name"), names)
        self.assertNotIn("día(s)", " ".join(periods.mapped("name")))

    def test_duplicate_history_line_rejected(self):
        """O3: misma fecha y año de servicio del mismo empleado."""
        self._history(2)
        with self.assertRaisesMessage(ValidationError, "Ya hay una línea"):
            self._history(3)
        with self.assertRaisesMessage(ValidationError, "año de servicio 2"):
            self._history(1, service_year=2)
            self._history(1, service_year=2)
        # Otro año de servicio u otra fecha no son duplicados.
        self._history(1, service_year=3)
        self._history(1, date=self.today - relativedelta(days=1))
        self.assertEqual(
            self.History.search_count([("employee_id", "=", self.employee.id)]), 3
        )

    def test_duplicate_in_same_batch_rejected(self):
        vals = {"employee_id": self.employee.id, "date": self.today}
        with self.assertRaisesMessage(ValidationError, "Ya hay una línea"):
            self.History.create(
                [{**vals, "number_of_days": 1}, {**vals, "number_of_days": 2}]
            )

    def test_reimport_template_does_not_duplicate(self):
        self._employee(
            "María José Peña (ejemplo)",
            self.today - relativedelta(years=3, days=10),
        )._erp_generate_vacation_allocations(self.today)
        result = self._import_template()
        self.assertFalse(
            [m for m in result["messages"] if m["type"] == "error"], result["messages"]
        )
        self.assertEqual(len(result["ids"]), 2)
        periods = self._auto_allocations(self.employee)
        self.assertEqual(periods.mapped("erp_history_days"), [12, 0, 0])
        again = self._import_template()
        errors = [m for m in again["messages"] if m["type"] == "error"]
        self.assertTrue(errors)
        self.assertIn("Ya hay una línea", errors[0]["message"])
        self.assertFalse(again["ids"])
        self.assertEqual(self.History.search_count([]), 2)
        periods.invalidate_recordset()
        self.assertEqual(periods.mapped("erp_history_days"), [12, 0, 0])

    def test_quantity_texts_singular_and_plural(self):
        self.assertEqual(text.format_days(self.env, 1), "1 día")
        self.assertEqual(text.format_days(self.env, 2), "2 días")
        self.assertEqual(text.format_hours(self.env, 1), "1 hora")
        self.assertEqual(text.format_hours(self.env, 2), "2 horas")

    def test_manual_allocation_name_and_display(self):
        allocation = self.Allocation.create(
            {
                "employee_id": self.employee.id,
                "holiday_status_id": self.vacation.id,
                "allocation_type": "regular",
                "number_of_days": 1,
                "date_from": self.today,
            }
        )
        self.assertEqual(allocation.name, f"{self.vacation.name} (1 día)")
        self.assertEqual(
            allocation.display_name, f"Saldo de {self.vacation.name}: 1 día"
        )
        allocation.number_of_days = 3
        self.assertEqual(allocation.name, f"{self.vacation.name} (3 días)")
        self.assertEqual(
            allocation.display_name, f"Saldo de {self.vacation.name}: 3 días"
        )
        new = self.Allocation.new({})
        new.holiday_status_id = False
        self.assertEqual(new._get_title(), "Nuevo saldo")

    def test_button_message_singular(self):
        officer = new_test_user(
            self.env, login="encargado_singular_us012", groups=OFFICER_GROUPS
        )
        employee = self._employee("Diego Cevallos Ñauta", date(2025, 1, 2))
        no_contract = self._employee("Camila Yánez (sin contrato)")
        action = (
            (employee | no_contract)
            .with_user(officer)
            .action_erp_generate_vacation_allocations()
        )
        message = action["params"]["message"]
        self.assertIn("Se generó 1 periodo de vacaciones.", message)
        self.assertIn(
            "1 empleado sin relación laboral o sin contrato en curso no recibe "
            "vacaciones.",
            message,
        )

    def test_balance_messages_without_allocation_word(self):
        other = self._employee("Sin Saldo Íñiguez")
        monday = self.today + relativedelta(days=21, weekday=0)
        with self.assertRaises(ValidationError) as ctx:
            self.env["hr.leave"].create(
                {
                    "employee_id": other.id,
                    "holiday_status_id": self.vacation.id,
                    "request_date_from": monday,
                    "request_date_to": monday,
                }
            )
        self.assertIn("no tiene saldo", str(ctx.exception))
        self.assertNotIn("asignación", str(ctx.exception))
