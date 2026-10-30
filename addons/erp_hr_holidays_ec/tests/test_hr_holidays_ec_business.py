"""Reglas de negocio de ausencias de Ecuador (US-012, CA-3, CA-5, CA-6, CA-8,
CA-9, CA-10, CA-12).

Todos los parámetros son FICTICIOS de prueba: los cargados por el módulo se
archivan y se crean otros con cifras que no son las legales (12 días base,
días adicionales desde el año 3, 2 días por año, tope de 5; vigencia de cada
periodo 3 años; corte de la tarea automática 2025-12-01; paternidad 4 días;
lactancia 2 horas por día; calamidad 2 días; conteo en días calendario).
"""

import base64
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

from dateutil.relativedelta import MO, relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.erp_hr_holidays_ec.models import const
from odoo.addons.erp_hr_holidays_ec.models.hr_employee import VACATION_LOCK_KEY
from odoo.addons.erp_hr_holidays_ec.models.hr_leave_allocation import (
    HrLeaveAllocation,
)

TEST_PARAMETERS = {
    const.VACATION_BASE_DAYS: 12.0,
    const.VACATION_EXTRA_FROM_YEAR: 3.0,
    const.VACATION_EXTRA_DAYS_PER_YEAR: 2.0,
    const.VACATION_EXTRA_MAX_DAYS: 5.0,
    const.VACATION_VALIDITY_YEARS: 3.0,
    const.VACATION_GENERATION_START: 1.0,
    const.VACATION_COUNT_CALENDAR_DAYS: 1.0,
    const.LEAVE_COUNT_CALENDAR_DAYS: 1.0,
    const.LEAVE_MATERNITY_MAX_DAYS: 10.0,
    const.LEAVE_PATERNITY_MAX_DAYS: 4.0,
    const.LEAVE_CALAMITY_MAX_DAYS: 2.0,
    const.LEAVE_NURSING_HOURS_PER_DAY: 2.0,
    const.LEAVE_NURSING_MONTHS: 6.0,
}
PARAMETERS_FROM = date(2015, 1, 1)
# Corte ficticio (distinto del de los datos del módulo, que queda archivado).
GENERATION_START = date(2025, 12, 1)
RUN_DATE = date(2026, 10, 30)
GENERATOR_LOGGER = "odoo.addons.erp_hr_holidays_ec.models.hr_employee"
SIMULATED_ERROR = "Fallo simulado al validar"


def day_lines(days, hour_from, hour_to):
    """Asistencias de lunes (0) a ``days - 1`` de ``hour_from`` a ``hour_to``."""
    return [
        {
            "name": f"Día {day}",
            "dayofweek": str(day),
            "hour_from": hour_from,
            "hour_to": hour_to,
            "day_period": "morning",
        }
        for day in range(days)
    ]


class HolidaysEcCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.erp_max_weekly_hours = 40.0
        cls.Parameter = cls.env["erp.payroll.parameter"]
        cls.Parameter.search([("code", "in", const.ALL_PARAMETER_CODES)]).write(
            {"active": False}
        )
        cls.parameters = {
            code: cls.Parameter.create(
                {
                    "code": code,
                    "name": f"{code} (prueba)",
                    "value_type": "number",
                    "value": value,
                    "date_from": (
                        GENERATION_START
                        if code == const.VACATION_GENERATION_START
                        else PARAMETERS_FROM
                    ),
                    "norm": "Valor ficticio de prueba",
                }
            )
            for code, value in TEST_PARAMETERS.items()
        }
        Calendar = cls.env["resource.calendar"]
        cls.cal_40 = Calendar.create(
            {
                "name": "Jornada 40 h (prueba US-012)",
                "full_time_required_hours": 40.0,
                "attendance_ids": [(0, 0, vals) for vals in day_lines(5, 8, 16)],
            }
        )
        cls.cal_20 = Calendar.create(
            {
                "name": "Medio tiempo 20 h (prueba US-012)",
                "full_time_required_hours": 40.0,
                "attendance_ids": [(0, 0, vals) for vals in day_lines(5, 8, 12)],
            }
        )
        # 5 × 5,2 h = 26 h / 40 h = 0,65 de jornada.
        cls.cal_26 = Calendar.create(
            {
                "name": "Jornada 26 h (prueba US-012)",
                "full_time_required_hours": 40.0,
                "attendance_ids": [(0, 0, vals) for vals in day_lines(5, 8, 13.2)],
            }
        )
        ContractType = cls.env["hr.contract.type"]
        cls.type_labor = ContractType.create(
            {"name": "Indefinido (prueba US-012)", "erp_labor_relationship": True}
        )
        cls.type_no_labor = ContractType.create(
            {
                "name": "Servicios profesionales (prueba)",
                "erp_labor_relationship": False,
            }
        )
        cls.vacation = cls.env.ref("erp_hr_holidays_ec.leave_type_annual_vacation")
        cls.Allocation = cls.env["hr.leave.allocation"]

    @classmethod
    def _contract(cls, employee, date_start, calendar=None, contract_type=None, **vals):
        return cls.env["hr.contract"].create(
            {
                "name": f"Contrato de {employee.name} ({date_start})",
                "employee_id": employee.id,
                "wage": 1000.0,
                "date_start": date_start,
                "state": "open",
                "contract_type_id": (contract_type or cls.type_labor).id,
                "resource_calendar_id": (calendar or cls.cal_40).id,
                **vals,
            }
        )

    @classmethod
    def _employee(
        cls, name, date_start=None, calendar=None, contract_type=None, **vals
    ):
        calendar = calendar or cls.cal_40
        employee = cls.env["hr.employee"].create(
            {"name": name, "resource_calendar_id": calendar.id, **vals}
        )
        if date_start:
            cls._contract(employee, date_start, calendar, contract_type)
        return employee

    @contextmanager
    def assertRaisesMessage(self, exception, regex):
        """``assertRaisesRegex`` con savepoint (el ``assertRaises`` de Odoo lo
        abre; el ``assertRaisesRegex`` de unittest no): lo creado antes del
        error no queda en la BD."""
        with self.assertRaisesRegex(exception, regex), self.env.cr.savepoint():
            yield

    def _auto_allocations(self, employee):
        return self.Allocation.search(
            [("employee_id", "in", employee.ids), ("erp_auto_generated", "=", True)],
            order="erp_entry_date, erp_service_year",
        )

    def _years(self, employee):
        return self._auto_allocations(employee).mapped("erp_service_year")


@tagged("post_install", "-at_install")
class TestVacationGeneration(HolidaysEcCase):
    """Periodos por antigüedad desde la fecha de ingreso, límite de
    acumulación y corte de la tarea automática (CA-3, CA-9, CA-10, CA-12)."""

    def test_first_year_base_days_validated_with_expiry(self):
        employee = self._employee("José Ñúñez Ávila", date(2025, 3, 15))
        created = employee._erp_generate_vacation_allocations(RUN_DATE)
        self.assertEqual(len(created), 1)
        allocation = self._auto_allocations(employee)
        self.assertEqual(allocation, created)
        self.assertEqual(allocation.erp_service_year, 1)
        self.assertEqual(allocation.number_of_days, 12)
        self.assertEqual(allocation.erp_entitled_days, 12)
        self.assertEqual(allocation.erp_entry_date, date(2025, 3, 15))
        self.assertEqual(allocation.state, "validate")
        self.assertEqual(allocation.holiday_status_id, self.vacation)
        self.assertEqual(allocation.date_from, date(2026, 3, 15))
        # Vigencia ficticia de 3 años: caduca el día anterior a 2029-03-15.
        self.assertEqual(allocation.date_to, date(2029, 3, 14))
        self.assertIn("año de servicio 1", allocation.name)
        self.assertIn("Caduca el", allocation.notes)

    def test_not_completed_year_gets_nothing(self):
        employee = self._employee("Inés Peña Robles", date(2026, 2, 1))
        self.assertFalse(employee._erp_generate_vacation_allocations(RUN_DATE))

    def test_one_four_and_ten_years_with_accumulation_limit(self):
        """1, 4 y 10 años de servicio: solo los periodos no caducados a la
        fecha de cálculo (vigencia ficticia de 3 años)."""
        cases = [
            # (fecha de ingreso, [(año, días, caducidad)])
            (date(2025, 9, 1), [(1, 12, date(2029, 8, 31))]),
            # Año 1 (nace 2023-05-10) caducó el 2026-05-09: no se genera.
            (
                date(2022, 5, 10),
                [
                    (2, 12, date(2027, 5, 9)),
                    (3, 14, date(2028, 5, 9)),
                    (4, 16, date(2029, 5, 9)),
                ],
            ),
            # Años 1 a 7 caducados; adicionales con tope (12 + 5).
            (
                date(2016, 8, 1),
                [
                    (8, 17, date(2027, 7, 31)),
                    (9, 17, date(2028, 7, 31)),
                    (10, 17, date(2029, 7, 31)),
                ],
            ),
        ]
        for entry, expected in cases:
            with self.subTest(entry=entry):
                employee = self._employee(f"Empleada Íñiguez {entry}", entry)
                employee._erp_generate_vacation_allocations(RUN_DATE)
                allocations = self._auto_allocations(employee)
                self.assertEqual(
                    [
                        (a.erp_service_year, a.number_of_days, a.date_to)
                        for a in allocations
                    ],
                    expected,
                )

    def test_company_entry_date_prevails_over_contracts(self):
        # Contrato cargado desde 2025, pero ingresó a la empresa en 2020.
        employee = self._employee("Germán Cañar Mora", date(2025, 1, 6))
        employee.erp_company_entry_date = date(2020, 2, 1)
        employee._erp_generate_vacation_allocations(RUN_DATE)
        # Años 4 (2024-02-01, caduca 2027-01-31) a 6 (2026-02-01).
        self.assertEqual(self._years(employee), [4, 5, 6])
        self.assertEqual(
            set(self._auto_allocations(employee).mapped("erp_entry_date")),
            {date(2020, 2, 1)},
        )

    def test_entry_date_correction_blocked_after_generation(self):
        employee = self._employee("Rosa Ávila Peña", date(2024, 3, 4))
        employee.erp_company_entry_date = date(2023, 3, 4)
        employee._erp_generate_vacation_allocations(RUN_DATE)
        with self.assertRaisesMessage(UserError, "Rechace y elimine"):
            employee.erp_company_entry_date = date(2023, 1, 2)
        # Un reingreso (fecha posterior a todos sus periodos) se admite.
        employee.erp_company_entry_date = date(2026, 9, 1)
        self.assertEqual(employee.erp_company_entry_date, date(2026, 9, 1))

    def test_rehire_after_gap_generates_new_first_year(self):
        """Reingreso tras un hueco de ≥ 4 días: el núcleo reinicia la fecha
        del primer contrato y el año 1 del nuevo ingreso es otro periodo."""
        employee = self._employee("Fabián Ñacato Ruiz", date(2023, 1, 2))
        first = employee._erp_generate_vacation_allocations(date(2024, 3, 1))
        self.assertEqual(first.erp_entry_date, date(2023, 1, 2))
        employee.contract_id.write({"date_end": date(2024, 6, 28), "state": "close"})
        self._contract(employee, date(2024, 7, 15))
        self.assertEqual(employee.first_contract_date, date(2024, 7, 15))
        employee._erp_generate_vacation_allocations(RUN_DATE)
        allocations = self._auto_allocations(employee)
        self.assertEqual(
            [(a.erp_entry_date, a.erp_service_year) for a in allocations],
            [
                (date(2023, 1, 2), 1),
                (date(2024, 7, 15), 1),
                (date(2024, 7, 15), 2),
            ],
        )
        self.assertEqual(allocations[1].date_from, date(2025, 7, 15))

    def test_part_time_proportional_and_rounded_to_half_day(self):
        half = self._employee(
            "Rocío Muñoz (medio tiempo)", date(2025, 1, 10), self.cal_20
        )
        partial = self._employee("Raúl Ordóñez (26 h)", date(2025, 1, 10), self.cal_26)
        (half | partial)._erp_generate_vacation_allocations(RUN_DATE)
        self.assertEqual(self._auto_allocations(half).number_of_days, 6)
        # 12 × 0,65 = 7,8 → 8 (medio día más cercano).
        self.assertEqual(self._auto_allocations(partial).number_of_days, 8)

    def test_no_labor_relationship_or_contract_gets_nothing(self):
        no_labor = self._employee(
            "Andrea Sáenz (factura)", date(2020, 2, 1), contract_type=self.type_no_labor
        )
        no_contract = self._employee("Camilo Yánez (sin contrato)")
        created = (no_labor | no_contract)._erp_generate_vacation_allocations(RUN_DATE)
        self.assertFalse(created)
        self.assertFalse(self._auto_allocations(no_labor | no_contract))

    def test_idempotent(self):
        employee = self._employee("Lucía Benítez", date(2023, 4, 1))
        first = employee._erp_generate_vacation_allocations(RUN_DATE)
        self.assertEqual(len(first), 3)
        second = employee._erp_generate_vacation_allocations(RUN_DATE)
        self.assertFalse(second)
        self.assertEqual(len(self._auto_allocations(employee)), 3)

    def test_cutoff_only_anniversaries_since_generation_start(self):
        """La tarea automática solo genera aniversarios desde el corte
        (VACATION_GENERATION_START), aunque VACATION_BASE_DAYS tenga valores
        históricos anteriores; el cálculo inicial genera los anteriores."""
        self.Parameter.create(
            {
                "code": const.VACATION_BASE_DAYS,
                "name": "Días base históricos (prueba)",
                "value_type": "number",
                "value": 12.0,
                "date_from": date(2000, 1, 1),
                "norm": "Valor ficticio de prueba",
            }
        )
        employee = self._employee("Tomás Íñiguez Mora", date(2012, 1, 20))
        employee._erp_generate_vacation_allocations(RUN_DATE, from_cutoff=True)
        # Solo el aniversario 2026-01-20 (año 14) es posterior al corte.
        self.assertEqual(self._years(employee), [14])
        employee._erp_generate_vacation_allocations(RUN_DATE)
        # Cálculo inicial: años 12 (2024-01-20, caduca 2027-01-19) y 13.
        self.assertEqual(self._years(employee), [12, 13, 14])
        self.assertEqual(
            set(self._auto_allocations(employee).mapped("number_of_days")), {17}
        )

    def test_missing_generation_start_parameter(self):
        employee = self._employee("Óscar Viteri", date(2025, 2, 1))
        self.parameters[const.VACATION_GENERATION_START].active = False
        with self.assertRaisesMessage(UserError, const.VACATION_GENERATION_START):
            employee._erp_generate_vacation_allocations(RUN_DATE, from_cutoff=True)
        # El cálculo inicial no depende del corte.
        self.assertTrue(employee._erp_generate_vacation_allocations(RUN_DATE))

    def test_validity_must_be_positive(self):
        employee = self._employee("Paúl Cevallos", date(2025, 2, 1))
        self.parameters[const.VACATION_VALIDITY_YEARS].value = 0
        with self.assertRaisesMessage(UserError, "mayor que cero"):
            employee._erp_generate_vacation_allocations(RUN_DATE)

    def test_cron_idempotent(self):
        employee = self._employee(
            "Tomás Guzmán", fields.Date.today() - relativedelta(years=1, days=3)
        )
        Allocation = self.Allocation
        Allocation._erp_cron_generate_vacation_allocations()
        self.assertEqual(len(self._auto_allocations(employee)), 1)
        Allocation._erp_cron_generate_vacation_allocations()
        self.assertEqual(len(self._auto_allocations(employee)), 1)

    def test_double_validation_reaches_validate(self):
        self.vacation.allocation_validation_type = "both"
        employee = self._employee("Doble Validación Ñáñez", date(2024, 5, 2))
        created = employee._erp_generate_vacation_allocations(RUN_DATE)
        self.assertEqual(len(created), 2)
        self.assertEqual(set(created.mapped("state")), {"validate"})

    def test_advisory_lock_taken(self):
        employee = self._employee("Candado Peña", date(2025, 2, 1))
        employee._erp_generate_vacation_allocations(RUN_DATE)
        self.env.cr.execute(
            """
            SELECT count(*) FROM pg_locks
             WHERE locktype = 'advisory' AND pid = pg_backend_pid()
               AND classid = %s AND objid = %s
            """,
            (VACATION_LOCK_KEY >> 32, VACATION_LOCK_KEY & 0xFFFFFFFF),
        )
        self.assertEqual(self.env.cr.fetchone()[0], 1)

    def test_refused_not_regenerated_until_deleted(self):
        employee = self._employee("Patricia Llerena", date(2025, 6, 1))
        allocation = employee._erp_generate_vacation_allocations(RUN_DATE)
        allocation.action_refuse()
        self.assertFalse(employee._erp_generate_vacation_allocations(RUN_DATE))
        allocation.unlink()
        regenerated = employee._erp_generate_vacation_allocations(RUN_DATE)
        self.assertEqual(regenerated.erp_service_year, 1)

    def test_missing_parameter_manual_raises(self):
        employee = self._employee("Óscar Viteri Ruiz", date(2024, 2, 1))
        self.parameters[const.VACATION_EXTRA_MAX_DAYS].active = False
        with self.assertRaisesMessage(UserError, const.VACATION_EXTRA_MAX_DAYS):
            employee._erp_generate_vacation_allocations(RUN_DATE)
        self.parameters[const.VACATION_BASE_DAYS].active = False
        with self.assertRaisesMessage(UserError, const.VACATION_BASE_DAYS):
            employee._erp_generate_vacation_allocations(RUN_DATE)

    def test_missing_parameter_logged_and_others_continue(self):
        # VACATION_EXTRA_FROM_YEAR solo desde 2025: el periodo vigente del año
        # 2 (nace 2024-05-10) no tiene valor.
        self.parameters[const.VACATION_EXTRA_FROM_YEAR].date_from = date(2025, 1, 1)
        failing = self._employee("Fabián Ñacato", date(2022, 5, 10))
        ok = self._employee("Gabriela Ríos", date(2025, 3, 1))
        errors = []
        with self.assertLogs(GENERATOR_LOGGER, "WARNING") as logs:
            created = (failing | ok)._erp_generate_vacation_allocations(
                RUN_DATE, raise_on_error=False, errors=errors
            )
        self.assertEqual(created.employee_id, ok)
        self.assertFalse(self._auto_allocations(failing))
        self.assertIn(const.VACATION_EXTRA_FROM_YEAR, "\n".join(logs.output))
        self.assertIn("Fabián Ñacato", "\n".join(logs.output))
        self.assertEqual([employee for employee, _msg in errors], [failing])

    def test_employee_error_rolled_back_others_generated(self):
        """Un error al validar los periodos de un empleado deshace solo los
        suyos (savepoint); los demás se generan."""
        failing = self._employee("Empleado Con Error Ñúñez", date(2024, 3, 1))
        ok = self._employee("Empleada Sin Error Ávila", date(2024, 3, 1))
        original = HrLeaveAllocation._erp_validate_generated

        def validate_or_fail(allocations):
            if failing in allocations.employee_id:
                raise ValidationError(SIMULATED_ERROR)
            return original(allocations)

        with (
            patch.object(
                HrLeaveAllocation, "_erp_validate_generated", validate_or_fail
            ),
            self.assertLogs(GENERATOR_LOGGER, "WARNING") as logs,
        ):
            created = (failing | ok)._erp_generate_vacation_allocations(
                RUN_DATE, raise_on_error=False
            )
        self.assertEqual(created.employee_id, ok)
        self.assertEqual(self._years(ok), [1, 2])
        self.assertFalse(self._auto_allocations(failing))
        self.assertIn("Fallo simulado", "\n".join(logs.output))

    def test_manual_button_requires_leave_officer(self):
        employee = self._employee("Diana Cevallos", date(2025, 1, 2))
        basic = new_test_user(self.env, login="basico_us012", groups="base.group_user")
        with self.assertRaises(AccessError):
            employee.with_user(basic).action_erp_generate_vacation_allocations()
        officer = new_test_user(
            self.env,
            login="encargado_ausencias_us012",
            groups="base.group_user,hr.group_hr_user,hr_holidays.group_hr_holidays_user",
        )
        action = employee.with_user(officer).action_erp_generate_vacation_allocations()
        self.assertEqual(action["params"]["type"], "success")
        self.assertEqual(len(self._auto_allocations(employee)), 1)
        action = employee.with_user(officer).action_erp_generate_vacation_allocations()
        self.assertEqual(action["params"]["type"], "info")

    def test_manual_button_batch_lists_errors(self):
        officer = new_test_user(
            self.env,
            login="encargado_lote_us012",
            groups="base.group_user,hr.group_hr_user,hr_holidays.group_hr_holidays_user",
        )
        self.parameters[const.VACATION_EXTRA_FROM_YEAR].date_from = date(2025, 1, 1)
        failing = self._employee("Lote Con Error Peña", date(2022, 5, 10))
        ok = self._employee("Lote Correcto Muñoz", date(2025, 3, 1))
        with self.assertLogs(GENERATOR_LOGGER, "WARNING"):
            action = (
                (failing | ok)
                .with_user(officer)
                .action_erp_generate_vacation_allocations()
            )
        self.assertEqual(action["params"]["type"], "warning")
        self.assertTrue(action["params"]["sticky"])
        self.assertIn("Lote Con Error Peña", action["params"]["message"])
        self.assertEqual(self._years(ok), [1])

    def test_protected_fields_outside_generator(self):
        employee = self._employee("Elena Zambrano", date(2025, 1, 2))
        officer = new_test_user(
            self.env,
            login="encargado_protegidos_us012",
            groups="base.group_user,hr.group_hr_user,hr_holidays.group_hr_holidays_manager",
        )
        Allocation = self.Allocation.with_user(officer)
        vals = {
            "name": "Asignación manual – días extra",
            "employee_id": employee.id,
            "holiday_status_id": self.vacation.id,
            "number_of_days": 2,
            "date_from": date(2026, 1, 1),
        }
        with self.assertRaises(UserError):
            Allocation.create(
                {**vals, "erp_auto_generated": True, "erp_service_year": 9}
            )
        with self.assertRaises(UserError):
            Allocation.create({**vals, "erp_history_days": 1})
        manual = Allocation.create(vals)
        self.assertFalse(manual.erp_auto_generated)
        with self.assertRaises(UserError):
            manual.write({"erp_service_year": 3})
        auto = employee._erp_generate_vacation_allocations(RUN_DATE).with_user(officer)
        with self.assertRaises(UserError):
            auto.write({"erp_auto_generated": False})
        with self.assertRaises(UserError):
            auto.write({"erp_entitled_days": 30})
        # Reenviar el mismo valor y cambiar los días sí se permite.
        auto.write({"erp_service_year": 1, "number_of_days": 13})
        self.assertEqual(auto.number_of_days, 13)


@tagged("post_install", "-at_install")
class TestLeaveManagerFromParent(HolidaysEcCase):
    """Aprobador de ausencias = usuario del Jefe inmediato (CA-5)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.users = {
            key: new_test_user(
                cls.env, login=f"jefe_{key}_us012", groups="base.group_user"
            )
            for key in ("u1", "u2", "u3", "u4", "u5")
        }
        cls.boss1 = cls._employee("Jefa Uno Ñáñez", user_id=cls.users["u1"].id)
        cls.boss2 = cls._employee("Jefe Dos Ávila", user_id=cls.users["u2"].id)
        cls.boss_no_user = cls._employee("Jefe sin usuario Íñiguez")

    def test_derived_on_create_and_parent_change(self):
        employee = self._employee("Empleada Peña", parent_id=self.boss1.id)
        self.assertEqual(employee.leave_manager_id, self.users["u1"])
        employee.parent_id = self.boss2
        self.assertEqual(employee.leave_manager_id, self.users["u2"])

    def test_manual_approver_kept_on_parent_change(self):
        employee = self._employee("Empleado Muñoz", parent_id=self.boss1.id)
        employee.leave_manager_id = self.users["u3"]
        employee.parent_id = self.boss2
        self.assertEqual(employee.leave_manager_id, self.users["u3"])
        employee.parent_id = self.boss_no_user
        self.assertEqual(employee.leave_manager_id, self.users["u3"])

    def test_parent_without_user_clears_derived_approver(self):
        employee = self._employee("Empleada Cañar", parent_id=self.boss1.id)
        employee.parent_id = self.boss_no_user
        self.assertFalse(employee.leave_manager_id)
        employee.parent_id = self.boss2
        self.assertEqual(employee.leave_manager_id, self.users["u2"])

    def test_parent_user_change_updates_subordinates(self):
        derived = self._employee("Subordinado derivado", parent_id=self.boss1.id)
        manual = self._employee("Subordinado manual", parent_id=self.boss1.id)
        manual.leave_manager_id = self.users["u3"]
        empty = self._employee(
            "Subordinado sin jefe usuario", parent_id=self.boss_no_user.id
        )
        self.assertFalse(empty.leave_manager_id)
        self.boss1.user_id = self.users["u5"]
        self.assertEqual(derived.leave_manager_id, self.users["u5"])
        self.assertEqual(manual.leave_manager_id, self.users["u3"])
        self.boss_no_user.user_id = self.users["u4"]
        self.assertEqual(empty.leave_manager_id, self.users["u4"])


@tagged("post_install", "-at_install")
class TestLeaveRequests(HolidaysEcCase):
    """Solicitudes: saldo, duración máxima, días calendario, adjunto,
    aprobación por el jefe y anulación (CA-5, CA-6)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        today = fields.Date.today()
        # Lunes futuro: las solicitudes no empiezan antes de hoy.
        cls.monday = today + relativedelta(days=21, weekday=MO)
        cls.boss_user = new_test_user(
            cls.env, login="jefe_inmediato_us012", groups="base.group_user"
        )
        cls.employee_user = new_test_user(
            cls.env, login="empleada_us012", groups="base.group_user"
        )
        cls.other_user = new_test_user(
            cls.env, login="otro_usuario_us012", groups="base.group_user"
        )
        cls.boss = cls._employee("Jefa Inmediata Ordóñez", user_id=cls.boss_user.id)
        cls.employee = cls._employee(
            "Empleada Ñusta Peñafiel",
            today - relativedelta(years=1, days=10),
            parent_id=cls.boss.id,
            user_id=cls.employee_user.id,
        )
        cls.other = cls._employee("Otro Empleado Íñiguez", user_id=cls.other_user.id)
        cls.employee._erp_generate_vacation_allocations(today)
        cls.sick = cls.env.ref("erp_hr_holidays_ec.leave_type_sick")
        cls.paternity = cls.env.ref("erp_hr_holidays_ec.leave_type_paternity")
        cls.nursing = cls.env.ref("erp_hr_holidays_ec.leave_type_nursing")

    def _request(
        self, leave_type, date_from, date_to, user=None, employee=None, **vals
    ):
        return (
            self.env["hr.leave"]
            .with_user(user or self.employee_user)
            .create(
                {
                    "employee_id": (employee or self.employee).id,
                    "holiday_status_id": leave_type.id,
                    "request_date_from": date_from,
                    "request_date_to": date_to,
                    **vals,
                }
            )
        )

    def _day(self, offset):
        return self.monday + relativedelta(days=offset)

    def test_allocation_and_approver_ready(self):
        self.assertEqual(self.employee.leave_manager_id, self.boss_user)
        self.assertEqual(self._auto_allocations(self.employee).number_of_days, 12)

    def test_vacation_counts_calendar_days(self):
        # Lunes a domingo: 7 días calendario (5 laborables).
        leave = self._request(self.vacation, self._day(0), self._day(6))
        self.assertEqual(leave.number_of_days, 7)
        self.assertEqual(leave.number_of_hours, 40)

    def test_vacation_counts_working_days_when_parameter_is_zero(self):
        self.parameters[const.VACATION_COUNT_CALENDAR_DAYS].value = 0
        leave = self._request(self.vacation, self._day(0), self._day(6))
        self.assertEqual(leave.number_of_days, 5)

    def test_insufficient_balance_message_shows_available(self):
        with self.assertRaisesMessage(
            ValidationError,
            r"Saldo insuficiente.*disponible 12 días, solicitado 14 días",
        ):
            self._request(self.vacation, self._day(0), self._day(13))
        self._request(self.vacation, self._day(0), self._day(6))
        with self.assertRaisesMessage(
            ValidationError, r"disponible 5 días, solicitado 6 días"
        ):
            self._request(self.vacation, self._day(14), self._day(19))

    def test_no_allocation_message(self):
        with self.assertRaisesMessage(ValidationError, "no tiene saldo"):
            self._request(
                self.vacation,
                self._day(0),
                self._day(1),
                user=self.other_user,
                employee=self.other,
            )

    def test_max_duration_in_calendar_days(self):
        # Viernes a lunes: 4 días calendario (2 laborables) = máximo 4.
        leave = self._request(self.paternity, self._day(4), self._day(7))
        self.assertEqual(leave.number_of_days, 4)
        # Viernes a martes: 5 días calendario (3 laborables) > 4.
        with self.assertRaisesMessage(ValidationError, "duración máxima de 4 días"):
            self._request(self.paternity, self._day(11), self._day(15))

    def test_max_duration_hours_per_day(self):
        ok = self._request(
            self.nursing,
            self._day(0),
            self._day(0),
            request_unit_hours=True,
            request_hour_from=8.0,
            request_hour_to=10.0,
        )
        self.assertEqual(ok.number_of_hours, 2)
        with self.assertRaisesMessage(ValidationError, "máximo de 2 horas por día"):
            self._request(
                self.nursing,
                self._day(1),
                self._day(1),
                request_unit_hours=True,
                request_hour_from=8.0,
                request_hour_to=11.0,
            )
        with self.assertRaisesMessage(ValidationError, "horas por día"):
            self._request(self.nursing, self._day(2), self._day(3))

    def test_overlap_rejected(self):
        self._request(self.sick, self._day(0), self._day(1))
        with self.assertRaises(ValidationError):
            self._request(self.vacation, self._day(1), self._day(2))

    def test_attachment_required_to_approve(self):
        leave = self._request(self.sick, self._day(0), self._day(1))
        self.assertEqual(leave.state, "confirm")
        with self.assertRaisesMessage(UserError, "documento de respaldo"):
            leave.with_user(self.boss_user).action_approve()
        self.env["ir.attachment"].with_user(self.employee_user).create(
            {
                "name": "certificado_médico.pdf",
                "res_model": "hr.leave",
                "res_id": leave.id,
                "datas": base64.b64encode(b"%PDF-1.4 certificado"),
            }
        )
        leave.with_user(self.boss_user).action_approve()
        self.assertEqual(leave.state, "validate")

    def test_boss_approves_vacation_others_cannot(self):
        leave = self._request(self.vacation, self._day(0), self._day(4))
        with self.assertRaises(AccessError):
            leave.with_user(self.other_user).action_approve()
        with self.assertRaises(UserError):
            leave.with_user(self.employee_user).action_approve()
        leave.with_user(self.boss_user).action_approve()
        self.assertEqual(leave.state, "validate")
        self.assertEqual(leave.first_approver_id, self.boss)

    def test_approved_leave_cancelled_only_by_boss_or_hr(self):
        leave = self._request(self.vacation, self._day(0), self._day(4))
        leave.with_user(self.boss_user).action_approve()
        as_employee = leave.with_user(self.employee_user)
        self.assertFalse(as_employee.can_cancel)
        with self.assertRaises(ValidationError):
            as_employee._action_user_cancel("Ya no viajo")
        as_boss = leave.with_user(self.boss_user)
        self.assertTrue(as_boss.can_cancel)
        wizard = (
            self.env["hr.holidays.cancel.leave"]
            .with_user(self.boss_user)
            .create(
                {"leave_id": leave.id, "reason": "Cambio de planificación del área"}
            )
        )
        wizard.action_cancel_leave()
        self.assertEqual(leave.state, "cancel")
        self.assertIn(
            "Cambio de planificación del área",
            "\n".join(leave.message_ids.mapped("body")),
        )

    def test_hr_officer_can_cancel_approved(self):
        officer = new_test_user(
            self.env,
            login="rrhh_ausencias_us012",
            groups="base.group_user,hr_holidays.group_hr_holidays_user",
        )
        leave = self._request(self.vacation, self._day(0), self._day(2))
        leave.with_user(self.boss_user).action_approve()
        self.assertTrue(leave.with_user(officer).can_cancel)

    def test_insufficient_balance_message_only_failing_employee(self):
        """Solicitudes en lote: el mensaje nombra solo al empleado sin saldo
        suficiente, no a los demás del mismo grupo (tipo y fecha)."""
        enough = self._employee(
            "Empleado Con Saldo Cañar",
            fields.Date.today() - relativedelta(years=1, days=10),
        )
        enough._erp_generate_vacation_allocations(fields.Date.today())
        vals = {
            "holiday_status_id": self.vacation.id,
            "request_date_from": self._day(0),
        }
        with self.assertRaises(ValidationError) as ctx:
            self.env["hr.leave"].create(
                [
                    {
                        **vals,
                        "employee_id": self.employee.id,
                        "request_date_to": self._day(13),
                    },
                    {
                        **vals,
                        "employee_id": enough.id,
                        "request_date_to": self._day(2),
                    },
                ]
            )
        message = str(ctx.exception)
        self.assertIn("Saldo insuficiente", message)
        self.assertIn(self.employee.name, message)
        self.assertNotIn(enough.name, message)

    def test_vacation_half_day(self):
        leave = self._request(
            self.vacation, self._day(1), self._day(1), request_unit_half=True
        )
        self.assertEqual(leave.number_of_days, 0.5)

    def test_employee_cannot_delete_after_first_approval(self):
        leave = self._request(self.paternity, self._day(0), self._day(1))
        with self.assertRaisesMessage(UserError, "documento de respaldo"):
            leave.with_user(self.boss_user).action_approve()
        self.env["ir.attachment"].with_user(self.employee_user).create(
            {
                "name": "partida_de_nacimiento.pdf",
                "res_model": "hr.leave",
                "res_id": leave.id,
                "datas": base64.b64encode(b"%PDF-1.4 partida"),
            }
        )
        leave.with_user(self.boss_user).action_approve()
        self.assertEqual(leave.state, "validate1")
        with self.assertRaisesMessage(UserError, "ya tiene la aprobación del jefe"):
            leave.with_user(self.employee_user).unlink()
        self.assertTrue(leave.exists())
        self.assertTrue(leave.with_user(self.boss_user).can_cancel)

    def test_employee_can_delete_pending_request(self):
        leave = self._request(self.sick, self._day(0), self._day(0))
        leave.with_user(self.employee_user).unlink()
        self.assertFalse(leave.exists())

    def test_attachment_required_incompatible_with_no_validation(self):
        with self.assertRaisesMessage(ValidationError, "Adjunto obligatorio"):
            self.sick.leave_validation_type = "no_validation"

    def test_allocation_display_name(self):
        allocation = self.Allocation.search(
            [("employee_id", "=", self.employee.id), ("erp_auto_generated", "=", True)]
        )
        self.assertEqual(
            allocation.display_name, f"Saldo de {self.vacation.name}: 12 días"
        )
        new = self.Allocation.new({})
        new.holiday_status_id = False
        self.assertEqual(new.display_name, "Nuevo saldo")
        self.assertNotIn("False", new.display_name)

    def test_dashboard_action_name(self):
        action = self.employee.action_time_off_dashboard()
        self.assertEqual(action["name"], f"Ausencias de {self.employee.name}")

    def test_max_duration_display(self):
        self.assertEqual(self.paternity.erp_max_duration_display, "4 días (a validar)")
        self.assertEqual(
            self.nursing.erp_max_duration_display, "2 horas por día (a validar)"
        )
        self.parameters[const.LEAVE_PATERNITY_MAX_DAYS].state = "validated"
        self.paternity.invalidate_recordset(["erp_max_duration_display"])
        self.assertEqual(self.paternity.erp_max_duration_display, "4 días")
        self.assertFalse(self.sick.erp_max_duration_display)
        self.parameters[const.LEAVE_CALAMITY_MAX_DAYS].active = False
        calamity = self.env.ref("erp_hr_holidays_ec.leave_type_calamity")
        self.assertEqual(
            calamity.erp_max_duration_display,
            f"Sin valor vigente ({const.LEAVE_CALAMITY_MAX_DAYS})",
        )
