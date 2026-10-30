"""Reglas del rol mensual Ecuador con parámetros FICTICIOS (US-008, CA-1 a
CA-7, CA-11). Ver ``common.py``: SBU 400, IESS 10 % / 12 %, fondos de reserva
8 %, divisor 12, 12 meses, mes de 30 días, 12 meses de servicio."""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools.misc import format_date

from ..models.hr_payslip import days_30
from .common import PayrollEcCase


@tagged("post_install", "-at_install")
class TestPayrollEcRules(PayrollEcCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls._employee("José Ñúñez Peña")
        cls.contract = cls._contract(cls.employee)

    # ------------------------------------------------------------------
    # Parámetros (CA-1)
    # ------------------------------------------------------------------
    def _param(self, code, value, date_from, company=None, active=True):
        return self.Parameter.create(
            {
                "code": code,
                "name": f"{code} (prueba)",
                "value_type": "number",
                "value": value,
                "date_from": date_from,
                "norm": "Norma ficticia",
                "company_id": company.id if company else False,
                "active": active,
            }
        )

    def test_parameter_most_recent_in_force(self):
        self._param("TEST_DIAS", 10, date(2026, 1, 1))
        self._param("TEST_DIAS", 20, date(2026, 6, 1))
        self._param("TEST_DIAS", 99, date(2026, 3, 1), active=False)
        get = self.Parameter._get_value
        self.assertEqual(get("TEST_DIAS", date(2026, 1, 1)), 10)
        self.assertEqual(get("TEST_DIAS", date(2026, 5, 31)), 10)
        self.assertEqual(get("TEST_DIAS", "2026-06-01"), 20)
        self.assertEqual(get("TEST_DIAS", date(2027, 1, 1)), 20)

    def test_parameter_company_value_prevails(self):
        other = self.env["res.company"].create({"name": "Empresa Ñ (prueba)"})
        self._param("TEST_DIAS", 10, date(2026, 6, 1))
        self._param("TEST_DIAS", 15, date(2026, 1, 1), company=self.company)
        get = self.Parameter._get_value
        self.assertEqual(get("TEST_DIAS", date(2026, 7, 1), self.company), 15)
        self.assertEqual(get("TEST_DIAS", date(2026, 7, 1), other), 10)
        # Antes del valor de la empresa rige el común... si existe.
        with self.assertRaises(UserError):
            get("TEST_DIAS", date(2025, 12, 31), other)

    def test_parameter_missing_raises_spanish_error(self):
        self._param("TEST_DIAS", 10, date(2026, 6, 1))
        with self.assertRaises(UserError) as error:
            self.Parameter._get_value("TEST_DIAS", date(2026, 5, 31))
        message = str(error.exception)
        self.assertIn("«TEST_DIAS (prueba)» (TEST_DIAS)", message)
        self.assertIn(format_date(self.env, date(2026, 5, 31)), message)
        with self.assertRaises(UserError) as error:
            self.Parameter._get_value("NO_EXISTE", date(2026, 5, 31))
        self.assertIn("NO_EXISTE", str(error.exception))

    def test_missing_parameter_stops_payslip(self):
        self.parameters.filtered(lambda p: p.code == "SBU").active = False
        payslip = self._payslip(self.employee)
        with self.assertRaises(UserError) as error:
            payslip.compute_sheet()
        self.assertIn("(SBU)", str(error.exception))
        self.assertFalse(payslip.line_ids)
        self.assertEqual(payslip.state, "draft")

    def test_parameter_change_by_date(self):
        """Un SBU nuevo vigente desde junio solo afecta a los roles desde
        junio."""
        self._param("SBU", 480.0, date(2026, 6, 1))
        may = self._computed(
            self.employee, date_from=date(2026, 5, 1), date_to=date(2026, 5, 31)
        )
        june = self._computed(
            self.employee, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30)
        )
        self.assertAlmostEqual(self._lines(may)["D14_PROV_COSTA"], 33.33)
        self.assertAlmostEqual(self._lines(june)["D14_PROV_COSTA"], 40.00)

    # ------------------------------------------------------------------
    # Días (convención de 30 días)
    # ------------------------------------------------------------------
    def test_days_30_convention(self):
        cases = [
            (date(2026, 1, 1), date(2026, 1, 31), 30),
            (date(2026, 2, 1), date(2026, 2, 28), 30),
            (date(2024, 2, 1), date(2024, 2, 29), 30),
            (date(2026, 4, 1), date(2026, 4, 30), 30),
            (date(2026, 1, 16), date(2026, 1, 31), 15),
            (date(2026, 1, 1), date(2026, 1, 15), 15),
            (date(2026, 1, 31), date(2026, 1, 31), 1),
            (date(2026, 1, 1), date(2026, 1, 30), 30),
            (date(2026, 2, 15), date(2026, 2, 28), 16),
            (date(2026, 2, 1), date(2026, 2, 27), 27),
            (date(2026, 1, 16), date(2026, 2, 15), 30),
            (date(2026, 2, 1), date(2026, 1, 31), 0),
        ]
        for date_from, date_to, expected in cases:
            self.assertEqual(
                days_30(date_from, date_to, 30), expected, (date_from, date_to)
            )

    # ------------------------------------------------------------------
    # Sueldo, IESS y beneficios (CA-2 a CA-6)
    # ------------------------------------------------------------------
    def test_full_month_accumulated_costa(self):
        payslip = self._computed(self.employee)
        self._assert_lines(
            payslip,
            {
                "BASIC": 1000.00,
                "GROSS": 1000.00,
                "IESS_PERSONAL": -100.00,
                "NET": 900.00,
                "IESS_PATRONAL": 120.00,
                "FR_ACCRUED": 80.00,
                "D13_PROV": 83.33,
                "D14_PROV_COSTA": 33.33,
            },
        )

    def test_full_month_monthly_benefits_paid(self):
        employee = self._employee("María Añazco")
        self._contract(employee)
        self._all_monthly(employee)
        payslip = self._computed(employee)
        # La base IESS no incluye fondos de reserva ni décimos.
        self._assert_lines(
            payslip,
            {
                "BASIC": 1000.00,
                "FR_PAID": 80.00,
                "D13_PAID": 83.33,
                "D14_PAID": 33.33,
                "GROSS": 1196.66,
                "IESS_PERSONAL": -100.00,
                "NET": 1096.66,
                "IESS_PATRONAL": 120.00,
            },
        )

    def test_sierra_fourteenth_provision(self):
        employee = self._employee("Íñigo Cuenca", establishment=self.est_sierra)
        self._contract(employee)
        lines = self._lines(self._computed(employee))
        self.assertAlmostEqual(lines["D14_PROV_SIERRA"], 33.33)
        self.assertNotIn("D14_PROV_COSTA", lines)

    def test_february_full_month_is_full_wage(self):
        payslip = self._computed(
            self.employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28)
        )
        self.assertAlmostEqual(self._lines(payslip)["BASIC"], 1000.00)

    def test_entry_mid_month(self):
        """Ingreso el 16 de enero (mes de 31 días): 15 días; sin fondos de
        reserva (primer año)."""
        employee = self._employee("Lucía Cañar")
        self._contract(employee, date_start=date(2026, 1, 16))
        payslip = self._computed(employee)
        self._assert_lines(
            payslip,
            {
                "BASIC": 500.00,
                "GROSS": 500.00,
                "IESS_PERSONAL": -50.00,
                "NET": 450.00,
                "IESS_PATRONAL": 60.00,
                "D13_PROV": 41.67,
                "D14_PROV_COSTA": 16.67,
            },
        )

    def test_exit_mid_month(self):
        employee = self._employee("Raúl Muñoz")
        contract = self._contract(employee, date_end=date(2026, 2, 27), state="close")
        payslip = self._computed(
            employee,
            contract=contract,
            date_from=date(2026, 2, 1),
            date_to=date(2026, 2, 28),
        )
        lines = self._lines(payslip)
        self.assertAlmostEqual(lines["BASIC"], 900.00)
        self.assertAlmostEqual(lines["FR_ACCRUED"], 72.00)
        self.assertAlmostEqual(lines["D14_PROV_COSTA"], 30.00)

    def test_part_time_wage_as_is_and_fourteenth_by_rate(self):
        employee = self._employee("Sofía Zúñiga")
        self._contract(employee, wage=500.0, calendar=self.cal_20)
        lines = self._lines(self._computed(employee))
        self.assertAlmostEqual(lines["BASIC"], 500.00)
        self.assertAlmostEqual(lines["IESS_PERSONAL"], -50.00)
        self.assertAlmostEqual(lines["D13_PROV"], 41.67)
        self.assertAlmostEqual(lines["D14_PROV_COSTA"], 16.67)

    def test_without_labor_relationship(self):
        """Sin relación laboral: ni IESS, ni fondos, ni décimos; tampoco hace
        falta establecimiento."""
        employee = self._employee("Ángel Ibáñez", establishment=False)
        self._contract(employee, contract_type=self.type_no_labor)
        payslip = self._computed(employee)
        self._assert_lines(
            payslip, {"BASIC": 1000.00, "GROSS": 1000.00, "NET": 1000.00}
        )

    def test_employee_without_establishment(self):
        employee = self._employee("Tomás Ñaupari", establishment=False)
        self._contract(employee)
        payslip = self._payslip(employee)
        with self.assertRaises(UserError) as error:
            payslip.compute_sheet()
        message = str(error.exception)
        self.assertIn("Tomás Ñaupari", message)
        self.assertIn("establecimiento", message)

    # ------------------------------------------------------------------
    # Fondos de reserva (CA-4)
    # ------------------------------------------------------------------
    def test_reserve_fund_less_than_a_year(self):
        employee = self._employee("Nuria Peñafiel")
        self._contract(employee, date_start=date(2025, 2, 1))
        lines = self._lines(self._computed(employee))
        self.assertNotIn("FR_ACCRUED", lines)
        self.assertNotIn("FR_PAID", lines)

    def test_reserve_fund_from_anniversary_day(self):
        """Ingreso el 16/01/2025: derecho desde el 16/01/2026 → 15 de 30 días."""
        employee = self._employee("Begoña Núñez")
        self._contract(employee, date_start=date(2025, 1, 16))
        lines = self._lines(self._computed(employee))
        self.assertAlmostEqual(lines["FR_ACCRUED"], 40.00)
        february = self._computed(
            employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28)
        )
        self.assertAlmostEqual(self._lines(february)["FR_ACCRUED"], 80.00)

    def test_reserve_fund_counts_from_first_contract(self):
        """Renovación: el servicio se cuenta desde el primer contrato."""
        employee = self._employee("Agustín Peña")
        self._contract(
            employee,
            date_start=date(2024, 1, 1),
            date_end=date(2025, 12, 31),
            state="close",
        )
        new_contract = self._contract(employee, date_start=date(2026, 1, 1))
        self.assertEqual(employee.first_contract_date, date(2024, 1, 1))
        payslip = self._computed(employee, contract=new_contract)
        self.assertAlmostEqual(self._lines(payslip)["FR_ACCRUED"], 80.00)

    # ------------------------------------------------------------------
    # Modalidad (CA-4 a CA-6)
    # ------------------------------------------------------------------
    def test_mode_change_mid_year(self):
        employee = self._employee("Inés Cañizares")
        self._contract(employee)
        self._election(employee, "thirteenth", "monthly", date(2026, 1, 1))
        self._election(employee, "thirteenth", "accumulated", date(2026, 7, 1))
        june = self._computed(
            employee, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30)
        )
        july = self._computed(
            employee, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31)
        )
        self.assertIn("D13_PAID", self._lines(june))
        self.assertNotIn("D13_PROV", self._lines(june))
        self.assertIn("D13_PROV", self._lines(july))
        self.assertNotIn("D13_PAID", self._lines(july))

    # ------------------------------------------------------------------
    # Conceptos propios (CA-7)
    # ------------------------------------------------------------------
    def test_concepts_fixed_and_variable_with_bases(self):
        bonus = self._concept("TEST_BONO", iess_base=True, thirteenth_base=True)
        self._concept("TEST_MOVIL", amount_kind="variable")
        store = self._concept("TEST_COMIS", concept_type="deduction")
        self._assign(self.employee, bonus, 100.0)
        self._assign(self.employee, store, 50.0)
        # Fuera del periodo y concepto archivado: no cuentan.
        old_bonus = self._concept("TEST_BONO_VIEJO")
        self._assign(
            self.employee,
            old_bonus,
            999.0,
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
        )
        archived = self._concept("TEST_ARCHIVADO")
        self._assign(self.employee, archived, 999.0)
        archived.active = False
        payslip = self._computed(self.employee, inputs={"TEST_MOVIL": 30.0})
        # Base IESS = 1000 + 100 (el variable no suma a bases).
        self._assert_lines(
            payslip,
            {
                "BASIC": 1000.00,
                "INC_OTHER": 130.00,
                "GROSS": 1130.00,
                "IESS_PERSONAL": -110.00,
                "DED_OTHER": -50.00,
                "NET": 970.00,
                "IESS_PATRONAL": 132.00,
                "FR_ACCRUED": 88.00,
                "D13_PROV": 91.67,
                "D14_PROV_COSTA": 33.33,
            },
        )

    def test_fixed_concept_full_amount_in_partial_month(self):
        """Una asignación vigente algún día del periodo entra completa."""
        bonus = self._concept("TEST_BONO")
        self._assign(self.employee, bonus, 100.0, date_from=date(2026, 1, 20))
        lines = self._lines(self._computed(self.employee))
        self.assertAlmostEqual(lines["INC_OTHER"], 100.00)

    def test_variable_input_validation(self):
        fixed = self._concept("TEST_FIJO")
        for inputs, text in (
            ({"TEST_NO_EXISTE": 10.0}, "TEST_NO_EXISTE"),
            ({"TEST_FIJO": 10.0}, "TEST_FIJO"),
        ):
            payslip = self._payslip(self.employee, inputs=inputs)
            with self.assertRaises(UserError) as error:
                payslip.compute_sheet()
            self.assertIn(text, str(error.exception))
            payslip.unlink()
        self.assertTrue(fixed)
        self._concept("TEST_VAR", amount_kind="variable")
        payslip = self._payslip(self.employee, inputs={"TEST_VAR": -5.0})
        with self.assertRaises(UserError) as error:
            payslip.compute_sheet()
        self.assertIn("importe positivo", str(error.exception))

    def test_negative_net_raises(self):
        self._concept("TEST_DESC", concept_type="deduction", amount_kind="variable")
        payslip = self._payslip(self.employee, inputs={"TEST_DESC": 2000.0})
        with self.assertRaises(UserError) as error:
            payslip.compute_sheet()
        message = str(error.exception)
        self.assertIn("negativo", message)
        self.assertIn("José Ñúñez Peña", message)
        self.assertFalse(payslip.line_ids)

    # ------------------------------------------------------------------
    # Redondeo (heredado de US-006)
    # ------------------------------------------------------------------
    def test_rounding_cascade_1000_05(self):
        """10 % de 1.000,05 = 100,005 → 100,01; neto = suma de líneas."""
        employee = self._employee("Rocío Peña")
        self._contract(employee, wage=1000.05)
        payslip = self._computed(employee)
        lines = self._lines(payslip)
        self.assertAlmostEqual(lines["BASIC"], 1000.05)
        self.assertAlmostEqual(lines["IESS_PERSONAL"], -100.01)
        self.assertAlmostEqual(lines["NET"], 900.04)
        self.assertAlmostEqual(
            lines["NET"], lines["GROSS"] + lines["IESS_PERSONAL"], places=2
        )
        for code, total in lines.items():
            self.assertEqual(total, self.currency.round(total), code)

    # ------------------------------------------------------------------
    # Varios contratos en el mismo rol
    # ------------------------------------------------------------------
    def test_two_contracts_in_period_do_not_accumulate(self):
        """Sin contrato en el rol y dos contratos en el periodo: cada contrato
        tiene sus propias líneas y el neto no suma el del otro."""
        employee = self._employee("Mateo Ñuño")
        self._contract(
            employee,
            date_start=date(2024, 1, 1),
            date_end=date(2026, 1, 15),
            state="open",
        )
        self._contract(employee, wage=2000.0, date_start=date(2026, 1, 16))
        payslip = self.env["hr.payslip"].create(
            {
                "employee_id": employee.id,
                "struct_id": self.structure.id,
                "date_from": date(2026, 1, 1),
                "date_to": date(2026, 1, 31),
            }
        )
        payslip.compute_sheet()
        net_lines = payslip.line_ids.filtered(lambda line: line.code == "NET")
        self.assertEqual(sorted(net_lines.mapped("total")), [450.00, 900.00])
