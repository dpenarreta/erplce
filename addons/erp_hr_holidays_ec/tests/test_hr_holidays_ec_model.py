"""Modelo y datos de ausencias de Ecuador (US-012, CA-1, CA-2, CA-3, CA-5)."""

from datetime import date

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.erp_hr_holidays_ec.models import const

ECUADOR_TYPES = {
    # xmlid: (requires_allocation, request_unit, leave_validation_type,
    #         unpaid, support_document, erp_attachment_required,
    #         erp_max_duration_param_code)
    "leave_type_annual_vacation": (
        "yes",
        "half_day",
        "manager",
        False,
        False,
        False,
        False,
    ),
    "leave_type_sick": ("no", "day", "manager", False, True, True, False),
    "leave_type_maternity": (
        "no",
        "day",
        "both",
        False,
        True,
        True,
        const.LEAVE_MATERNITY_MAX_DAYS,
    ),
    "leave_type_paternity": (
        "no",
        "day",
        "both",
        False,
        True,
        True,
        const.LEAVE_PATERNITY_MAX_DAYS,
    ),
    "leave_type_calamity": (
        "no",
        "day",
        "manager",
        False,
        True,
        True,
        const.LEAVE_CALAMITY_MAX_DAYS,
    ),
    "leave_type_nursing": (
        "no",
        "hour",
        "manager",
        False,
        True,
        False,
        const.LEAVE_NURSING_HOURS_PER_DAY,
    ),
    "leave_type_paid_permission": ("no", "hour", "manager", False, True, False, False),
    "leave_type_unpaid_permission": ("no", "hour", "both", True, True, False, False),
}
# «Vigente desde» de cada parámetro: fecha de la norma que introdujo el texto
# citado (los periodos y ausencias históricos los necesitan) o, para el corte
# de la tarea automática, la decisión del usuario (2026-01-01).
CODIFICATION = date(2005, 12, 16)
PARAMETER_DATES = {
    const.VACATION_BASE_DAYS: CODIFICATION,
    const.VACATION_EXTRA_FROM_YEAR: CODIFICATION,
    const.VACATION_EXTRA_DAYS_PER_YEAR: CODIFICATION,
    const.VACATION_EXTRA_MAX_DAYS: CODIFICATION,
    const.VACATION_VALIDITY_YEARS: CODIFICATION,
    const.VACATION_GENERATION_START: date(2026, 1, 1),
    const.VACATION_COUNT_CALENDAR_DAYS: CODIFICATION,
    const.LEAVE_COUNT_CALENDAR_DAYS: CODIFICATION,
    const.LEAVE_MATERNITY_MAX_DAYS: date(2009, 2, 13),
    const.LEAVE_PATERNITY_MAX_DAYS: date(2009, 2, 13),
    const.LEAVE_CALAMITY_MAX_DAYS: CODIFICATION,
    const.LEAVE_NURSING_HOURS_PER_DAY: date(2012, 9, 26),
    const.LEAVE_NURSING_MONTHS: date(2012, 9, 26),
}
NATIVE_TYPES = (
    "hr_holidays.holiday_status_cl",
    "hr_holidays.holiday_status_sl",
    "hr_holidays.holiday_status_comp",
    "hr_holidays.holiday_status_unpaid",
)


@tagged("post_install", "-at_install")
class TestHrHolidaysEcData(TransactionCase):
    """Datos cargados al instalar: parámetros a validar y tipos de Ecuador."""

    def test_parameters_loaded_to_validate_with_norm(self):
        Parameter = self.env["erp.payroll.parameter"]
        params = Parameter.search([("code", "in", const.ALL_PARAMETER_CODES)])
        self.assertEqual(set(params.mapped("code")), set(const.ALL_PARAMETER_CODES))
        for param in params:
            self.assertEqual(param.state, "to_validate", param.code)
            self.assertEqual(param.value_type, "number", param.code)
            self.assertEqual(param.date_from, PARAMETER_DATES[param.code], param.code)
            self.assertFalse(param.company_id, param.code)
            if param.code == const.VACATION_GENERATION_START:
                # No es un valor legal: decisión del usuario.
                self.assertIn("decisión del usuario", param.norm)
            else:
                self.assertIn("Código del Trabajo", param.norm, param.code)
        validity = params.filtered(lambda p: p.code == const.VACATION_VALIDITY_YEARS)
        self.assertIn("art. 75", validity.norm)
        self.assertIn("cuarto año", validity.norm)

    def test_parameters_values_resolve_by_date(self):
        Parameter = self.env["erp.payroll.parameter"]
        when = date(2026, 6, 15)
        expected = {
            const.VACATION_BASE_DAYS: 15,
            const.VACATION_EXTRA_FROM_YEAR: 6,
            const.VACATION_EXTRA_DAYS_PER_YEAR: 1,
            const.VACATION_EXTRA_MAX_DAYS: 15,
            const.VACATION_VALIDITY_YEARS: 4,
            const.VACATION_GENERATION_START: 1,
            const.VACATION_COUNT_CALENDAR_DAYS: 1,
            const.LEAVE_COUNT_CALENDAR_DAYS: 1,
            const.LEAVE_MATERNITY_MAX_DAYS: 94,
            const.LEAVE_PATERNITY_MAX_DAYS: 25,
            const.LEAVE_CALAMITY_MAX_DAYS: 3,
            const.LEAVE_NURSING_HOURS_PER_DAY: 2,
            const.LEAVE_NURSING_MONTHS: 12,
        }
        for code, value in expected.items():
            self.assertEqual(Parameter._get_value(code, when), value, code)

    def test_ecuador_leave_types_loaded(self):
        for xmlid, expected in ECUADOR_TYPES.items():
            leave_type = self.env.ref(f"erp_hr_holidays_ec.{xmlid}")
            actual = (
                leave_type.requires_allocation,
                leave_type.request_unit,
                leave_type.leave_validation_type,
                leave_type.unpaid,
                leave_type.support_document,
                leave_type.erp_attachment_required,
                leave_type.erp_max_duration_param_code,
            )
            self.assertEqual(actual, expected, xmlid)
            self.assertTrue(leave_type.active, xmlid)
            self.assertFalse(leave_type.company_id, xmlid)
            self.assertNotIn(leave_type.color, (1, 2), xmlid)

    def test_max_duration_codes_have_parameter(self):
        types = self.env["hr.leave.type"].search(
            [("erp_max_duration_param_code", "!=", False)]
        )
        codes = set(types.mapped("erp_max_duration_param_code"))
        self.assertTrue(codes)
        found = self.env["erp.payroll.parameter"].search([("code", "in", list(codes))])
        self.assertEqual(set(found.mapped("code")), codes)

    def test_single_annual_vacation_type(self):
        vacation = self.env["hr.leave.type"].search(
            [("erp_is_annual_vacation", "=", True)]
        )
        self.assertEqual(
            vacation, self.env.ref("erp_hr_holidays_ec.leave_type_annual_vacation")
        )

    def test_native_types_archived_and_ecuador_first(self):
        for xmlid in NATIVE_TYPES:
            self.assertFalse(self.env.ref(xmlid).active, xmlid)
        first = self.env["hr.leave.type"].search([], limit=1)
        self.assertEqual(
            first, self.env.ref("erp_hr_holidays_ec.leave_type_annual_vacation")
        )

    def test_historical_dates_have_parameters(self):
        """Ausencias y periodos anteriores a 2026 (carga inicial) encuentran
        valor vigente, salvo el corte de la tarea automática."""
        Parameter = self.env["erp.payroll.parameter"]
        when = date(2025, 12, 1)
        for code in const.ALL_PARAMETER_CODES:
            if code == const.VACATION_GENERATION_START:
                continue
            self.assertTrue(Parameter._get_value(code, when) > 0, code)

    def test_cron_declared(self):
        cron = self.env.ref("erp_hr_holidays_ec.ir_cron_generate_vacation_allocations")
        self.assertEqual(cron.model_id.model, "hr.leave.allocation")
        self.assertEqual(cron.interval_type, "days")
        self.assertEqual(cron.interval_number, 1)
        self.assertIn("_erp_cron_generate_vacation_allocations", cron.code)
        # Se instala inactiva: RRHH la activa tras validar los parámetros.
        self.assertFalse(cron.active)


@tagged("post_install", "-at_install")
class TestHrHolidaysEcConstraints(TransactionCase):
    """Restricciones de BD en tipos y asignaciones."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vacation = cls.env.ref("erp_hr_holidays_ec.leave_type_annual_vacation")
        cls.employee = cls.env["hr.employee"].create(
            {"name": "María José Íñiguez Peña"}
        )
        cls.employee_2 = cls.env["hr.employee"].create({"name": "Ñusta Cáceres Muñoz"})

    def _allocation_vals(self, employee=None, service_year=3, auto=True):
        return {
            "name": "Vacaciones – año de servicio con tilde y ñ",
            "employee_id": (employee or self.employee).id,
            "holiday_status_id": self.vacation.id,
            "allocation_type": "regular",
            "number_of_days": 15,
            "date_from": date(2026, 3, 1),
            "date_to": date(2027, 2, 28),
            "erp_service_year": service_year,
            "erp_auto_generated": auto,
        }

    def test_auto_allocation_unique_per_service_year(self):
        Allocation = self.env["hr.leave.allocation"]
        Allocation.create(self._allocation_vals())
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                Allocation.create(self._allocation_vals())

    def test_auto_allocation_other_year_or_employee_allowed(self):
        Allocation = self.env["hr.leave.allocation"]
        Allocation.create(self._allocation_vals(service_year=3))
        Allocation.create(self._allocation_vals(service_year=4))
        Allocation.create(self._allocation_vals(employee=self.employee_2))
        self.assertEqual(
            Allocation.search_count(
                [
                    ("erp_auto_generated", "=", True),
                    ("holiday_status_id", "=", self.vacation.id),
                ]
            ),
            3,
        )

    def test_refused_auto_allocation_can_be_regenerated(self):
        Allocation = self.env["hr.leave.allocation"]
        first = Allocation.create(self._allocation_vals())
        first.action_refuse()
        self.assertEqual(first.state, "refuse")
        second = Allocation.create(self._allocation_vals())
        self.assertTrue(second.erp_auto_generated)

    def test_manual_allocations_not_restricted(self):
        Allocation = self.env["hr.leave.allocation"]
        Allocation.create(self._allocation_vals(service_year=0, auto=False))
        Allocation.create(self._allocation_vals(service_year=0, auto=False))

    def test_auto_allocation_requires_service_year(self):
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env["hr.leave.allocation"].create(
                    self._allocation_vals(service_year=0)
                )

    def test_service_year_not_negative(self):
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env["hr.leave.allocation"].create(
                    self._allocation_vals(service_year=-1, auto=False)
                )

    def test_second_active_annual_vacation_type_rejected(self):
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env["hr.leave.type"].create(
                    {
                        "name": "Vacaciones duplicadas – año 2026",
                        "requires_allocation": "yes",
                        "erp_is_annual_vacation": True,
                        "company_id": False,
                    }
                )

    def test_archived_annual_vacation_type_allows_new_one(self):
        self.vacation.active = False
        self.vacation.flush_recordset()
        new_type = self.env["hr.leave.type"].create(
            {
                "name": "Vacaciones anuales (nueva configuración)",
                "requires_allocation": "yes",
                "erp_is_annual_vacation": True,
                "company_id": False,
            }
        )
        self.assertTrue(new_type.erp_is_annual_vacation)

    def test_annual_vacation_requires_allocation(self):
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.vacation.write({"requires_allocation": "no"})
                self.vacation.flush_recordset()

    def test_attachment_required_needs_support_document(self):
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env["hr.leave.type"].create(
                    {
                        "name": "Tipo con adjunto sin documento",
                        "requires_allocation": "no",
                        "support_document": False,
                        "erp_attachment_required": True,
                    }
                )

    def test_max_duration_code_format(self):
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env["hr.leave.type"].create(
                    {
                        "name": "Tipo con código inválido",
                        "requires_allocation": "no",
                        "erp_max_duration_param_code": "duración_máxima",
                    }
                )


@tagged("post_install", "-at_install")
class TestHrHolidaysEcAccess(TransactionCase):
    """Permisos básicos: un empleado sin grupo de RRHH pide sus ausencias."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env,
            login="empleado_ausencias_ec",
            name="Andrés Núñez Ordóñez",
            groups="base.group_user",
        )
        cls.employee = cls.env["hr.employee"].create(
            {"name": "Andrés Núñez Ordóñez", "user_id": cls.user.id}
        )
        cls.sick = cls.env.ref("erp_hr_holidays_ec.leave_type_sick")

    def test_employee_can_request_own_leave(self):
        leave = (
            self.env["hr.leave"]
            .with_user(self.user)
            .create(
                {
                    "employee_id": self.employee.id,
                    "holiday_status_id": self.sick.id,
                    "request_date_from": date(2026, 11, 2),
                    "request_date_to": date(2026, 11, 3),
                }
            )
        )
        self.assertEqual(leave.employee_id, self.employee)
        self.assertEqual(leave.state, "confirm")

    def test_employee_cannot_request_for_other_employee(self):
        other = self.env["hr.employee"].create({"name": "Otra Persona Ñañez"})
        with self.assertRaises(AccessError):
            self.env["hr.leave"].with_user(self.user).create(
                {
                    "employee_id": other.id,
                    "holiday_status_id": self.sick.id,
                    "request_date_from": date(2026, 11, 2),
                    "request_date_to": date(2026, 11, 3),
                }
            )

    def test_employee_reads_leave_types_but_cannot_edit(self):
        LeaveType = self.env["hr.leave.type"].with_user(self.user)
        sick = LeaveType.browse(self.sick.id)
        self.assertTrue(sick.erp_attachment_required)
        with self.assertRaises(AccessError):
            sick.write({"erp_attachment_required": False})

    def test_historical_calamity_leave(self):
        """Ausencia histórica (2025-12-01) con los parámetros del módulo."""
        calamity = self.env.ref("erp_hr_holidays_ec.leave_type_calamity")
        leave = self.env["hr.leave"].create(
            {
                "employee_id": self.employee.id,
                "holiday_status_id": calamity.id,
                "request_date_from": date(2025, 12, 1),
                "request_date_to": date(2025, 12, 3),
            }
        )
        # Días calendario (lunes a miércoles) = máximo de partida (3).
        self.assertEqual(leave.number_of_days, 3)

    def test_employee_cannot_read_payroll_parameters(self):
        with self.assertRaises(AccessError):
            self.env["erp.payroll.parameter"].with_user(self.user).search([])
