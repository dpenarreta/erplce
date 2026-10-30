"""Periodos de vacaciones: consumo FIFO, carga de vacaciones gozadas antes
del sistema y caducidad (US-012, CA-10, CA-11).

Parámetros ficticios de ``HolidaysEcCase`` (12 días base, adicionales desde
el año 3, vigencia de 3 años). Fechas relativas a hoy: el empleado ingresó
hace 3 años y 10 días, con tres periodos vigentes:

- año 1: nació hace 2 años y 10 días; 12 días; caduca en ~1 año.
- año 2: nació hace 1 año y 10 días; 12 días.
- año 3: nació hace 10 días; 14 días.
"""

from dateutil.relativedelta import MO, relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import new_test_user, tagged
from odoo.tools.misc import file_open

from .test_hr_holidays_ec_business import HolidaysEcCase

TEMPLATE_PATH = "erp_hr_holidays_ec/static/csv/plantilla_vacaciones_gozadas.csv"
IMPORT_OPTIONS = {
    "import_skip_records": [],
    "import_set_empty_fields": [],
    "fallback_values": {},
    "name_create_enabled_fields": {},
    "encoding": "utf-8",
    "separator": ",",
    "quoting": '"',
    "date_format": "",
    "datetime_format": "",
    "float_thousand_separator": ",",
    "float_decimal_separator": ".",
    "advanced": False,
    "has_headers": True,
    "keep_matches": False,
    "limit": 2000,
    "skip": 0,
    "tracking_disable": True,
}


@tagged("post_install", "-at_install")
class TestVacationPeriods(HolidaysEcCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.monday = cls.today + relativedelta(days=21, weekday=MO)
        cls.History = cls.env["erp.hr.vacation.history"]
        cls.employee = cls._employee(
            "María José Peña Ñúñez",
            cls.today - relativedelta(years=3, days=10),
            identification_id="0912345675",
        )
        cls.employee._erp_generate_vacation_allocations(cls.today)

    def _periods(self, employee=None):
        allocations = self._auto_allocations(employee or self.employee)
        allocations.invalidate_recordset()
        return allocations

    def _leave(self, offset_from, offset_to, approve=True, employee=None):
        leave = self.env["hr.leave"].create(
            {
                "employee_id": (employee or self.employee).id,
                "holiday_status_id": self.vacation.id,
                "request_date_from": self.monday + relativedelta(days=offset_from),
                "request_date_to": self.monday + relativedelta(days=offset_to),
            }
        )
        if approve:
            leave.action_approve()
            self.assertEqual(leave.state, "validate")
        return leave

    def _history(self, days, **vals):
        return self.History.create(
            {
                "employee_id": self.employee.id,
                "date": self.today,
                "number_of_days": days,
                **vals,
            }
        )

    def _detail(self, field):
        return self._periods().mapped(field)

    def test_three_periods_with_expiry(self):
        periods = self._periods()
        self.assertEqual(periods.mapped("erp_service_year"), [1, 2, 3])
        self.assertEqual(periods.mapped("number_of_days"), [12, 12, 14])
        for period in periods:
            self.assertEqual(
                period.date_to,
                period.date_from + relativedelta(years=3, days=-1),
            )
        self.assertEqual(self._detail("erp_days_available"), [12, 12, 14])
        self.assertEqual(self._detail("erp_is_expired"), [False, False, False])

    def test_new_requests_consume_oldest_period_first(self):
        """FIFO del núcleo (``_get_consumed_leaves``): primero la asignación
        con la fecha de caducidad más próxima."""
        self._leave(0, 4)
        self.assertEqual(self._detail("erp_days_used"), [5, 0, 0])
        self.assertEqual(self._detail("erp_days_available"), [7, 12, 14])
        self._leave(7, 16)
        self.assertEqual(self._detail("erp_days_used"), [12, 3, 0])
        self.assertEqual(self._detail("erp_days_available"), [0, 9, 14])

    def test_pending_request_shown_per_period(self):
        self._leave(0, 2, approve=False)
        self.assertEqual(self._detail("erp_days_pending"), [3, 0, 0])
        self.assertEqual(self._detail("erp_days_available"), [9, 12, 14])

    def test_history_consumed_fifo_then_new_requests(self):
        self._history(15, note="Total gozado según hoja de cálculo de RRHH")
        periods = self._periods()
        self.assertEqual(periods.mapped("erp_history_days"), [12, 3, 0])
        self.assertEqual(periods.mapped("number_of_days"), [0, 9, 14])
        self.assertEqual(periods.mapped("erp_entitled_days"), [12, 12, 14])
        self.assertEqual(self._detail("erp_days_used"), [12, 3, 0])
        # La nueva solicitud ya no puede usar el año 1 (agotado).
        self._leave(0, 4)
        self.assertEqual(self._detail("erp_days_used"), [12, 8, 0])
        self.assertEqual(self._detail("erp_days_available"), [0, 4, 14])

    def test_history_specific_service_year(self):
        self._history(4, service_year=3)
        self.assertEqual(self._detail("erp_history_days"), [0, 0, 4])

    def test_history_changes_redistribute(self):
        line = self._history(15)
        line.number_of_days = 5
        self.assertEqual(self._detail("erp_history_days"), [5, 0, 0])
        self.assertEqual(self._detail("number_of_days"), [7, 12, 14])
        line.unlink()
        self.assertEqual(self._detail("erp_history_days"), [0, 0, 0])
        self.assertEqual(self._detail("number_of_days"), [12, 12, 14])

    def test_history_keeps_manual_adjustment(self):
        self._periods()[0].number_of_days = 13
        self._history(2)
        self.assertEqual(self._detail("number_of_days"), [11, 12, 14])

    def test_history_exceeding_periods_rejected(self):
        with self.assertRaisesMessage(UserError, "superan los días"):
            self._history(40)
        # Fecha anterior al nacimiento de los periodos 2 y 3: solo el año 1.
        with self.assertRaisesMessage(UserError, "superan los días"):
            self._history(13, date=self.today - relativedelta(years=1, days=20))

    def test_history_without_periods_asks_to_calculate(self):
        other = self._employee(
            "Empleado Sin Cálculo Íñiguez", self.today - relativedelta(years=2)
        )
        with self.assertRaisesMessage(UserError, "Calcule primero"):
            self.History.create(
                {"employee_id": other.id, "date": self.today, "number_of_days": 3}
            )

    def test_history_reapplied_when_period_regenerated(self):
        """Si RRHH rechaza y elimina un periodo y lo vuelve a calcular, la
        carga histórica se reparte otra vez sobre el periodo nuevo."""
        self._history(10)
        oldest = self._periods()[0]
        self.assertEqual(oldest.erp_history_days, 10)
        oldest.action_refuse()
        oldest.unlink()
        regenerated = self.employee._erp_generate_vacation_allocations(self.today)
        self.assertEqual(regenerated.erp_service_year, 1)
        self.assertEqual(regenerated.erp_history_days, 10)
        self.assertEqual(regenerated.number_of_days, 2)

    def test_history_conflicting_with_approved_leaves(self):
        self._leave(0, 9)
        with self.assertRaisesMessage(ValidationError, "superan su saldo"):
            self._history(30)

    def test_history_by_identification_and_mismatch(self):
        line = self.History.create(
            {"identification": " 0912345675 ", "number_of_days": 2}
        )
        self.assertEqual(line.employee_id, self.employee)
        self.assertEqual(line.identification, "0912345675")
        with self.assertRaisesMessage(UserError, "único empleado"):
            self.History.create({"identification": "1799999999", "number_of_days": 2})
        with self.assertRaisesMessage(ValidationError, "no corresponde"):
            self._history(1, identification="1700000000")

    def test_import_template(self):
        self._employee(
            "María José Peña (ejemplo)",
            self.today - relativedelta(years=3, days=10),
        )._erp_generate_vacation_allocations(self.today)
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
        self.assertFalse(preview.get("error"), preview.get("error"))
        fields_ = [
            "/".join(preview["matches"].get(index) or []) or False
            for index in range(len(preview["headers"]))
        ]
        self.assertEqual(
            fields_,
            [
                "identification",
                "employee_id",
                "date",
                "number_of_days",
                "service_year",
                "note",
            ],
        )
        result = wizard.execute_import(
            fields_, preview["headers"], dict(IMPORT_OPTIONS)
        )
        errors = [m for m in result["messages"] if m["type"] == "error"]
        self.assertFalse(errors, result["messages"])
        lines = self.History.browse(result["ids"])
        self.assertEqual(len(lines), 2)
        self.assertIn(self.employee, lines.employee_id)
        self.assertEqual(self._detail("erp_history_days"), [12, 0, 0])

    def test_import_templates_declared(self):
        templates = self.History.get_import_templates()
        self.assertEqual(
            templates[0]["template"],
            "/erp_hr_holidays_ec/static/csv/plantilla_vacaciones_gozadas.csv",
        )

    def test_expired_period_visible_and_excluded_from_balance(self):
        oldest = self._periods()[0]
        oldest.date_to = self.today - relativedelta(days=1)
        oldest.invalidate_recordset()
        self.assertTrue(oldest.erp_is_expired)
        self.assertEqual(oldest.erp_days_expired, 12)
        self.assertEqual(oldest.erp_days_available, 0)
        data = self.vacation.get_allocation_data(self.employee, self.today)
        info = data[self.employee][0][1]
        self.assertEqual(info["virtual_remaining_leaves"], 26)

    def test_history_access_only_leave_officers(self):
        basic = new_test_user(
            self.env, login="basico_historial_us012", groups="base.group_user"
        )
        with self.assertRaises(AccessError):
            self.History.with_user(basic).search([])
        officer = new_test_user(
            self.env,
            login="encargado_historial_us012",
            groups="base.group_user,hr_holidays.group_hr_holidays_user",
        )
        line = self.History.with_user(officer).create(
            {"employee_id": self.employee.id, "number_of_days": 1}
        )
        self.assertEqual(self._detail("erp_history_days"), [1, 0, 0])
        self.assertEqual(line.company_id, self.employee.company_id)
