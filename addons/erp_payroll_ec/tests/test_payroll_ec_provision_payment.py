"""Marca de provisión de décimo pagada y estructura «Pago de décimos
acumulados» (US-013, CA-1 a CA-4): modelo, restricciones de BD, datos y
consulta de provisiones pendientes.

Las restricciones de BD se prueban también con SQL parametrizado para que los
tests sigan siendo válidos cuando la capa de negocio añada validaciones
previas. Valores ficticios de prueba (ver ``common.py``).
"""

from datetime import date

from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import SQL, index_exists, mute_logger

from ..models.const import (
    ACCRUED_PAY_RULES,
    BENEFIT_PAY_STRUCTURE_CODE,
    BENEFIT_PERIOD_PARAMETER_CODES,
    PROVISION_RULE_CODES,
    benefit_period_param_code,
)
from ..models.hr_payslip_line import PAYSLIP_LINE_PROVISION_INDEX
from .common import PayrollEcCase


@tagged("post_install", "-at_install")
class TestPayrollEcProvisionPayment(PayrollEcCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Payment = cls.env["erp.payroll.provision.payment"]
        cls.Line = cls.env["hr.payslip.line"]
        cls.benefit_structure = cls.env.ref("erp_payroll_ec.structure_ec_benefit_pay")
        cls.employee = cls._employee("Begoña Ñáñez Ortíz")
        cls.contract = cls._contract(cls.employee)

    def _confirmed_month(self, employee, month):
        payslip = self._payslip(
            employee,
            date_from=date(2026, month, 1),
            date_to=date(2026, month, 28),
        )
        payslip.compute_sheet()
        payslip.action_payslip_done()
        return payslip

    def _benefit_payslip(self, employee, date_from, date_to):
        return self.env["hr.payslip"].create(
            {
                "employee_id": employee.id,
                "contract_id": employee.contract_ids[:1].id,
                "struct_id": self.benefit_structure.id,
                "date_from": date_from,
                "date_to": date_to,
            }
        )

    def _provision(self, payslip, code="D13_PROV"):
        line = payslip.line_ids.filtered(lambda line: line.code == code)
        self.assertEqual(len(line), 1, code)
        return line

    def _pay(self, line, payslip):
        return self.Payment.create(
            {
                "payslip_line_id": line.id,
                "amount": line.total,
                "document_type": "payslip",
                "payslip_id": payslip.id,
            }
        )

    # ------------------------------------------------------------------
    # Datos
    # ------------------------------------------------------------------
    def test_benefit_pay_structure_loaded(self):
        structure = self.benefit_structure
        self.assertEqual(structure.code, BENEFIT_PAY_STRUCTURE_CODE)
        self.assertEqual(structure.name, "Pago de décimos acumulados")
        self.assertFalse(structure.parent_id)
        codes = set(structure.rule_ids.mapped("code"))
        self.assertEqual(codes, {*ACCRUED_PAY_RULES, "GROSS", "NET"})
        # Totales compartidos con el rol mensual (mismas reglas).
        self.assertEqual(
            structure.rule_ids.filtered(lambda r: r.code in ("GROSS", "NET")),
            self.env.ref("erp_payroll_ec.rule_ec_gross")
            | self.env.ref("erp_payroll_ec.rule_ec_net"),
        )
        for rule in structure.rule_ids.filtered(lambda r: r.code in ACCRUED_PAY_RULES):
            self.assertEqual(rule.category_id.code, "ALW", rule.code)
            self.assertIn(
                f'payslip._erp_rule_applies("{rule.code}", contract)',
                rule.condition_python,
            )
            self.assertIn(
                f'payslip._erp_rule_amount("{rule.code}", contract, categories, '
                "result_rules)",
                rule.amount_python_compute,
            )
        # El rol mensual no incluye las reglas de pago acumulado.
        monthly_codes = set(self.structure.rule_ids.mapped("code"))
        self.assertFalse(monthly_codes & set(ACCRUED_PAY_RULES))

    def test_benefit_period_parameters_loaded(self):
        Parameter = self.env["erp.payroll.parameter"].with_context(active_test=False)
        params = Parameter.search([("code", "in", BENEFIT_PERIOD_PARAMETER_CODES)])
        self.assertEqual(
            set(params.mapped("code")), set(BENEFIT_PERIOD_PARAMETER_CODES)
        )
        self.assertEqual(len(BENEFIT_PERIOD_PARAMETER_CODES), 12)
        for param in params:
            self.assertEqual(param.state, "to_validate", param.code)
            self.assertEqual(param.value_type, "number", param.code)
            self.assertIn("a validar", param.note, param.code)
        self.assertEqual(
            benefit_period_param_code("fourteenth", "sierra_amazonia", "PAYMENT_DAY"),
            "FOURTEENTH_SIERRA_PAYMENT_DAY",
        )
        with self.assertRaises(KeyError):
            benefit_period_param_code("thirteenth", None, "PERIOD_END_MONTH")

    def test_provision_index_exists(self):
        self.assertTrue(index_exists(self.env.cr, PAYSLIP_LINE_PROVISION_INDEX))

    # ------------------------------------------------------------------
    # Provisiones pendientes
    # ------------------------------------------------------------------
    def test_pending_provisions_exclude_draft_and_paid(self):
        january = self._confirmed_month(self.employee, 1)
        self._payslip(
            self.employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28)
        ).compute_sheet()  # Rol calculado sin confirmar: no cuenta.
        pending = self.Line._erp_get_pending_provision_lines(
            PROVISION_RULE_CODES, employees=self.employee
        )
        self.assertEqual(pending.slip_id, january)
        self.assertEqual(set(pending.mapped("code")), {"D13_PROV", "D14_PROV_COSTA"})
        d13 = self._provision(january)
        payer = self._benefit_payslip(
            self.employee, date(2025, 12, 1), date(2026, 11, 30)
        )
        self._pay(d13, payer)
        pending = self.Line._erp_get_pending_provision_lines(
            ["D13_PROV"], employees=self.employee
        )
        self.assertFalse(pending)
        # Filtro por periodo (mes de inicio del rol).
        self.assertFalse(
            self.Line._erp_get_pending_provision_lines(
                ["D14_PROV_COSTA"],
                employees=self.employee,
                date_from=date(2026, 2, 1),
            )
        )
        with self.assertRaises(ValueError):
            self.Line._erp_pending_provision_domain(["BASIC"])

    def test_cancelled_and_refunded_payslips_are_not_pending(self):
        january = self._confirmed_month(self.employee, 1)
        self.env["ir.config_parameter"].sudo().set_param(
            "payroll.allow_cancel_payslips", True
        )
        january.action_payslip_cancel()
        self.assertFalse(
            self.Line._erp_get_pending_provision_lines(
                PROVISION_RULE_CODES, employees=self.employee
            )
        )

    # ------------------------------------------------------------------
    # Unicidad y restricciones de la marca de pago (CA-3)
    # ------------------------------------------------------------------
    def test_provision_paid_only_once(self):
        january = self._confirmed_month(self.employee, 1)
        line = self._provision(january)
        payer = self._benefit_payslip(
            self.employee, date(2025, 12, 1), date(2026, 11, 30)
        )
        payment = self._pay(line, payer)
        self.assertEqual(line.erp_provision_payment_ids, payment)
        self.assertEqual(payment.employee_id, self.employee)
        self.assertEqual(payment.provision_code, "D13_PROV")
        self.assertEqual(payment.provision_date, date(2026, 1, 1))
        self.assertEqual(payment.company_id, january.company_id)
        self.assertEqual(payer.erp_paid_provision_ids, payment)
        other_payer = self._benefit_payslip(
            self.employee, date(2026, 1, 1), date(2026, 12, 31)
        )
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._pay(line, other_payer)
        # Anular el pago = eliminar la marca: vuelve a quedar pendiente y se
        # puede pagar en otro documento.
        payment.unlink()
        self.assertIn(
            line,
            self.Line._erp_get_pending_provision_lines(
                ["D13_PROV"], employees=self.employee
            ),
        )
        self.assertTrue(self._pay(line, other_payer))

    def test_document_reference_check(self):
        line = self._provision(self._confirmed_month(self.employee, 1))
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.Payment.create(
                    {
                        "payslip_line_id": line.id,
                        "amount": line.total,
                        "document_type": "payslip",
                    }
                )

    def test_amount_not_negative(self):
        line = self._provision(self._confirmed_month(self.employee, 1))
        payer = self._benefit_payslip(
            self.employee, date(2025, 12, 1), date(2026, 11, 30)
        )
        payment = self._pay(line, payer)
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    SQL(
                        "UPDATE erp_payroll_provision_payment SET amount = %s "
                        "WHERE id = %s",
                        -1,
                        payment.id,
                    )
                )

    def test_paid_provision_line_cannot_be_deleted(self):
        line = self._provision(self._confirmed_month(self.employee, 1))
        payer = self._benefit_payslip(
            self.employee, date(2025, 12, 1), date(2026, 11, 30)
        )
        self._pay(line, payer)
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    SQL("DELETE FROM hr_payslip_line WHERE id = %s", line.id)
                )

    def test_only_provisions_of_confirmed_payslips(self):
        january = self._confirmed_month(self.employee, 1)
        payer = self._benefit_payslip(
            self.employee, date(2025, 12, 1), date(2026, 11, 30)
        )
        basic = january.line_ids.filtered(lambda line: line.code == "BASIC")
        with self.assertRaises(ValidationError):
            self._pay(basic, payer)
        draft = self._computed(
            self.employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28)
        )
        with self.assertRaises(ValidationError):
            self._pay(self._provision(draft), payer)

    def test_access(self):
        line = self._provision(self._confirmed_month(self.employee, 1))
        payer = self._benefit_payslip(
            self.employee, date(2025, 12, 1), date(2026, 11, 30)
        )
        payment = self._pay(line, payer)
        Access = self.env["ir.model.access"]
        model = "erp.payroll.provision.payment"
        self.assertTrue(Access.with_user(self.payroll_user).check(model, "read", False))
        for user in (self.payroll_user, self.payroll_manager):
            self.assertTrue(Access.with_user(user).check(model, "read", False))
            for operation in ("write", "create", "unlink"):
                self.assertFalse(
                    Access.with_user(user).check(model, operation, False),
                    (user.login, operation),
                )
            self.assertEqual(
                self.Payment.with_user(user).search([("id", "=", payment.id)]),
                payment,
            )

    def test_manager_cannot_edit_marks_without_sudo(self):
        """Ni siquiera el responsable de nómina edita, borra o crea marcas
        fuera de los flujos del servidor (``UserError`` antes de la ACL)."""
        line = self._provision(self._confirmed_month(self.employee, 1))
        payer = self._benefit_payslip(
            self.employee, date(2025, 12, 1), date(2026, 11, 30)
        )
        payment = self._pay(line, payer)
        as_manager = payment.with_user(self.payroll_manager)
        with self.assertRaisesRegex(UserError, "no se registran, modifican"):
            as_manager.write({"amount": 1.0})
        with self.assertRaisesRegex(UserError, "no se registran, modifican"):
            as_manager.unlink()
        with self.assertRaisesRegex(UserError, "no se registran, modifican"):
            self.Payment.with_user(self.payroll_manager).create(
                {
                    "payslip_line_id": line.id,
                    "amount": line.total,
                    "document_type": "payslip",
                    "payslip_id": payer.id,
                }
            )
        self.assertTrue(payment.exists())
        self.assertEqual(payment.amount, line.total)
        # Con sudo() (flujos del servidor) sí se eliminan.
        payment.with_user(self.payroll_manager).sudo().unlink()
        self.assertFalse(payment.exists())

    # ------------------------------------------------------------------
    # Cálculo del pago acumulado: un décimo por rol (erp_benefit_pay_code)
    # ------------------------------------------------------------------
    def test_benefit_payslip_pays_pending_provisions(self):
        january = self._confirmed_month(self.employee, 1)
        d13 = self._provision(january)
        d14 = self._provision(january, "D14_PROV_COSTA")
        for code, expected in (("D13_ACC_PAY", d13), ("D14_ACC_PAY_COSTA", d14)):
            with self.subTest(code=code):
                payer = self._benefit_payslip(
                    self.employee, date(2025, 12, 1), date(2026, 11, 30)
                )
                payer.sudo().erp_benefit_pay_code = code
                payer.compute_sheet()
                lines = self._lines(payer)
                self.assertEqual(set(lines), {code, "GROSS", "NET"})
                self.assertAlmostEqual(lines[code], expected.total, places=2)
                self.assertAlmostEqual(lines["NET"], expected.total, places=2)
                payer.action_payslip_cancel()
