"""Contratos: tipo obligatorio en curso y máximo de horas semanales
(US-007, CA-8/CA-9)."""

from contextlib import contextmanager
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


def _day_lines(days, hour_from, hour_to, lunch=None, week_type=False):
    """Líneas de asistencia de lunes (0) a ``days - 1`` con descanso opcional
    ``lunch = (desde, hasta)``."""
    lines = []
    for day in range(days):
        common = {"dayofweek": str(day), "week_type": week_type}
        if lunch:
            lines += [
                {
                    **common,
                    "name": f"Día {day} mañana",
                    "hour_from": hour_from,
                    "hour_to": lunch[0],
                    "day_period": "morning",
                },
                {
                    **common,
                    "name": f"Día {day} almuerzo",
                    "hour_from": lunch[0],
                    "hour_to": lunch[1],
                    "day_period": "lunch",
                },
                {
                    **common,
                    "name": f"Día {day} tarde",
                    "hour_from": lunch[1],
                    "hour_to": hour_to,
                    "day_period": "afternoon",
                },
            ]
        else:
            lines.append(
                {
                    **common,
                    "name": f"Día {day}",
                    "hour_from": hour_from,
                    "hour_to": hour_to,
                    "day_period": "morning",
                }
            )
    return lines


@tagged("post_install", "-at_install")
class TestHrEcContract(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.erp_max_weekly_hours = 40.0
        Calendar = cls.env["resource.calendar"]
        cls.cal_40 = Calendar.create(
            {
                "name": "Jornada completa 40 h",
                "attendance_ids": [
                    (0, 0, vals) for vals in _day_lines(5, 8, 17, lunch=(12, 13))
                ],
            }
        )
        cls.cal_20 = Calendar.create(
            {
                "name": "Medio tiempo 20 h",
                "full_time_required_hours": 40.0,
                "attendance_ids": [(0, 0, vals) for vals in _day_lines(5, 8, 12)],
            }
        )
        cls.cal_45 = Calendar.create(
            {
                "name": "Jornada extendida 45 h",
                "attendance_ids": [
                    (0, 0, vals) for vals in _day_lines(5, 8, 18, lunch=(12, 13))
                ],
            }
        )
        cls.type_indefinido = cls.env.ref("erp_hr_ec.contract_type_ec_indefinido")
        cls.type_parcial = cls.env.ref("erp_hr_ec.contract_type_ec_tiempo_parcial")
        Employee = cls.env["hr.employee"]
        cls.emp_a = Employee.create({"name": "Pedro Íñiguez"})
        cls.emp_b = Employee.create({"name": "Ana Muñoz"})

    @contextmanager
    def _raises(self, exception, text):
        """``assertRaises`` de Odoo (deshace en un savepoint lo escrito por la
        operación que falla, a diferencia de ``assertRaisesRegex``) y comprueba
        que el mensaje contiene ``text``."""
        with self.assertRaises(exception) as ctx:
            yield ctx
        self.assertIn(text, str(ctx.exception))

    def _contract(self, employee, calendar, **vals):
        return self.env["hr.contract"].create(
            {
                "name": f"Contrato {employee.name}",
                "employee_id": employee.id,
                "wage": 482.0,
                "date_start": "2026-01-01",
                "resource_calendar_id": calendar.id if calendar else False,
                **vals,
            }
        )

    # ------------------------------------------------------------------
    # Horas semanales de la jornada
    # ------------------------------------------------------------------
    def test_weekly_hours_ignore_lunch(self):
        self.assertEqual(self.cal_40._erp_get_weekly_hours(), 40.0)
        self.assertEqual(self.cal_20._erp_get_weekly_hours(), 20.0)
        self.assertEqual(self.cal_45._erp_get_weekly_hours(), 45.0)

    def test_weekly_hours_two_weeks_average(self):
        sections = [
            {
                "name": "Semana 1",
                "dayofweek": "0",
                "hour_from": 0,
                "hour_to": 0,
                "day_period": "morning",
                "week_type": "0",
                "display_type": "line_section",
                "sequence": 0,
            },
            {
                "name": "Semana 2",
                "dayofweek": "0",
                "hour_from": 0,
                "hour_to": 0,
                "day_period": "morning",
                "week_type": "1",
                "display_type": "line_section",
                "sequence": 25,
            },
        ]
        week_0 = [
            dict(vals, sequence=1) for vals in _day_lines(5, 8, 17, (12, 13), "0")
        ]
        week_1 = [
            dict(vals, sequence=26) for vals in _day_lines(4, 8, 17, (12, 13), "1")
        ]
        calendar = self.env["resource.calendar"].create(
            {
                "name": "Dos semanas 40/32",
                "two_weeks_calendar": True,
                "attendance_ids": [(0, 0, vals) for vals in sections + week_0 + week_1],
            }
        )
        self.assertEqual(calendar._erp_get_weekly_hours(), 36.0)
        self._contract(self.emp_a, calendar, contract_type_id=self.type_indefinido.id)

    def test_weekly_hours_flexible(self):
        calendar = self.env["resource.calendar"].create(
            {
                "name": "Flexible 44 h",
                "flexible_hours": True,
                "full_time_required_hours": 44.0,
                "hours_per_day": 8.8,
                "attendance_ids": [],
            }
        )
        self.assertEqual(calendar._erp_get_weekly_hours(), 44.0)
        with self.assertRaises(ValidationError):
            self._contract(self.emp_a, calendar)

    def test_work_time_rate(self):
        self.assertEqual(self.cal_20._erp_get_work_time_rate(), 0.5)
        self.cal_40.full_time_required_hours = 0
        self.assertEqual(self.cal_40._erp_get_work_time_rate(), 1.0)

    # ------------------------------------------------------------------
    # Máximo semanal (CA-9)
    # ------------------------------------------------------------------
    def test_contract_40h_accepted(self):
        contract = self._contract(
            self.emp_a,
            self.cal_40,
            contract_type_id=self.type_indefinido.id,
            state="open",
        )
        self.assertEqual(contract.state, "open")

    def test_contract_20h_part_time_accepted(self):
        contract = self._contract(
            self.emp_b,
            self.cal_20,
            contract_type_id=self.type_parcial.id,
            state="open",
        )
        self.assertEqual(contract.resource_calendar_id._erp_get_work_time_rate(), 0.5)

    def test_contract_45h_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self._contract(
                self.emp_a, self.cal_45, contract_type_id=self.type_indefinido.id
            )
        message = str(ctx.exception)
        self.assertIn("Jornada extendida 45 h", message)
        self.assertIn("45", message)
        self.assertIn("40", message)
        contract = self._contract(self.emp_a, self.cal_40)
        with self._raises(ValidationError, "supera el máximo"):
            contract.resource_calendar_id = self.cal_45

    def test_contract_without_calendar_not_checked(self):
        """Sin jornada (totalmente flexible) no hay horas que validar. Con
        nómina OCA instalada la jornada es obligatoria en BD, por eso se
        prueba sobre un registro en memoria."""
        contract = self.env["hr.contract"].new(
            {"name": "Contrato flexible", "resource_calendar_id": False}
        )
        contract._erp_check_max_weekly_hours()
        self.assertFalse(contract.resource_calendar_id)

    def test_lower_company_max_with_running_contract(self):
        self._contract(
            self.emp_a,
            self.cal_40,
            contract_type_id=self.type_indefinido.id,
            state="open",
        )
        with self._raises(ValidationError, "supera el máximo"):
            self.company.erp_max_weekly_hours = 36.0
        # Un máximo mayor o igual se acepta.
        self.company.erp_max_weekly_hours = 44.0
        # Con el contrato en borrador no se bloquea el ajuste.
        self._contract(self.emp_b, self.cal_40)
        self.company.erp_max_weekly_hours = 40.0

    def test_edit_calendar_of_running_contract(self):
        self._contract(
            self.emp_a,
            self.cal_40,
            contract_type_id=self.type_indefinido.id,
            state="open",
        )
        saturday = {
            "name": "Sábado",
            "dayofweek": "5",
            "hour_from": 8,
            "hour_to": 13,
            "day_period": "morning",
        }
        with self._raises(ValidationError, "Jornada completa 40 h"):
            self.cal_40.write({"attendance_ids": [(0, 0, saturday)]})
        # Una jornada sin contratos en curso puede superar el máximo.
        self.cal_45.write({"attendance_ids": [(0, 0, saturday)]})

    # ------------------------------------------------------------------
    # Tipo de contrato (CA-8)
    # ------------------------------------------------------------------
    def test_running_contract_requires_type(self):
        with self._raises(ValidationError, "tipo de contrato"):
            self._contract(self.emp_b, self.cal_40, state="open")
        contract = self._contract(self.emp_a, self.cal_40)
        self.assertEqual(contract.state, "draft")
        with self._raises(ValidationError, "tipo de contrato"):
            contract.state = "open"
        contract.write({"contract_type_id": self.type_indefinido.id, "state": "open"})
        with self._raises(ValidationError, "tipo de contrato"):
            contract.contract_type_id = False

    def test_draft_without_type_allowed(self):
        contract = self._contract(self.emp_b, self.cal_20)
        self.assertFalse(contract.contract_type_id)
        contract.state = "cancel"

    def test_ready_draft_contract_requires_type(self):
        """Un borrador marcado como listo lo pasa a en curso el cron
        ``update_state``: debe tener tipo de contrato."""
        with self._raises(ValidationError, "listo para iniciar"):
            self._contract(self.emp_b, self.cal_40, kanban_state="done")
        contract = self._contract(self.emp_a, self.cal_40)
        with self._raises(ValidationError, "tipo de contrato"):
            contract.kanban_state = "done"
        contract.write({"contract_type_id": self.type_indefinido.id})
        contract.kanban_state = "done"
        # El cron abre el borrador listo (date_start ya pasó).
        self.env["hr.contract"].with_context(from_cron=True).update_state()
        self.assertEqual(contract.state, "open")
        # Un borrador no listo sigue pudiendo guardarse sin tipo.
        draft = self._contract(self.emp_b, self.cal_20, date_start="2027-01-01")
        self.assertEqual(draft.kanban_state, "normal")
        self.assertFalse(draft.contract_type_id)

    # ------------------------------------------------------------------
    # Revalidación al cambiar empleado o jornada flexible (ronda QA 1)
    # ------------------------------------------------------------------
    def test_flexible_calendar_raise_hours_running_contract(self):
        calendar = self.env["resource.calendar"].create(
            {
                "name": "Flexible 40 h",
                "flexible_hours": True,
                "full_time_required_hours": 40.0,
                "hours_per_day": 8.0,
                "attendance_ids": [],
            }
        )
        self._contract(
            self.emp_a,
            calendar,
            contract_type_id=self.type_indefinido.id,
            state="open",
        )
        with self._raises(ValidationError, "supera el máximo"):
            calendar.write({"full_time_required_hours": 60.0, "hours_per_day": 12.0})
        # Bajarlas sigue permitido.
        calendar.write({"full_time_required_hours": 36.0, "hours_per_day": 7.2})

    def test_change_contract_employee_to_45h_calendar(self):
        """La jornada del contrato se recalcula desde el empleado: cambiar el
        empleado por uno con jornada de 45 h debe rechazarse."""
        employee_45 = self.env["hr.employee"].create(
            {"name": "Luis Ñacato", "resource_calendar_id": self.cal_45.id}
        )
        contract = self._contract(
            self.emp_a, self.cal_40, contract_type_id=self.type_indefinido.id
        )
        with self._raises(ValidationError, "Jornada extendida 45 h"):
            contract.write({"employee_id": employee_45.id})
            contract.flush_recordset()

    def test_change_employee_calendar_with_contract(self):
        """Cambiar la jornada del empleado no cambia la del contrato (Odoo no
        la propaga), así que no hay nada que revalidar en el contrato; si se
        cambia la jornada del contrato en curso, sí se valida."""
        contract = self._contract(
            self.emp_b,
            self.cal_40,
            contract_type_id=self.type_indefinido.id,
            state="open",
        )
        self.emp_b.resource_calendar_id = self.cal_45
        self.assertEqual(contract.resource_calendar_id, self.cal_40)
        with self._raises(ValidationError, "supera el máximo"):
            contract.resource_calendar_id = self.cal_45

    def test_max_hours_computed_once_per_calendar(self):
        contracts = self._contract(self.emp_a, self.cal_40) | self._contract(
            self.emp_b, self.cal_40, date_start="2027-01-01"
        )
        Calendar = type(self.env["resource.calendar"])
        with patch.object(
            Calendar,
            "_erp_get_weekly_hours",
            autospec=True,
            side_effect=Calendar._erp_get_weekly_hours,
        ) as weekly_hours:
            contracts._erp_check_max_weekly_hours()
        self.assertEqual(weekly_hours.call_count, 1)
