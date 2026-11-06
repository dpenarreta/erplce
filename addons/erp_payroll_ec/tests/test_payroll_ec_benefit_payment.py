"""Pago de décimos acumulados (US-013, CA-1 a CA-4): periodo y fecha de pago
por parámetros, asistente de generación del lote, marca de provisiones
pagadas al confirmar, contabilidad sin gasto, anulación y reembolso, y
bloqueo de los roles mensuales cuyas provisiones ya se pagaron.

Valores FICTICIOS de prueba (ver ``common.py``): sueldo 1.000, divisor del
décimo tercero 12 (provisión mensual 83,33) y SBU 400 entre 12 meses
(provisión mensual de décimo cuarto 33,33).
"""

from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged

from ..models.const import BENEFIT_PERIOD_PARAM_PREFIX
from .common import PayrollEcCase

# Periodos y fechas de pago de prueba (prefijo -> mes/día de inicio y pago).
TEST_PERIODS = {
    "THIRTEENTH": (12, 1, 12, 24),
    "FOURTEENTH_COSTA": (3, 1, 3, 15),
    "FOURTEENTH_SIERRA": (8, 1, 8, 15),
}


@tagged("post_install", "-at_install")
class TestPayrollEcBenefitPayment(PayrollEcCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "payroll.allow_cancel_payslips", True
        )
        cls.Parameter.create(
            [
                {
                    "code": f"{prefix}_{suffix}",
                    "name": f"{prefix}_{suffix} (prueba)",
                    "value_type": "number",
                    "value": value,
                    # Antes de los valores cargados (archivados por common).
                    "date_from": date(2010, 1, 1),
                    "norm": "Valor ficticio de prueba",
                }
                for prefix, values in TEST_PERIODS.items()
                for suffix, value in zip(
                    (
                        "PERIOD_START_MONTH",
                        "PERIOD_START_DAY",
                        "PAYMENT_MONTH",
                        "PAYMENT_DAY",
                    ),
                    values,
                    strict=True,
                )
            ]
        )
        cls.benefit_structure = cls.env.ref("erp_payroll_ec.structure_ec_benefit_pay")
        benefit_rules = {rule.code: rule for rule in cls.benefit_structure.rule_ids}
        for code, account in (
            ("D13_ACC_PAY", "d13_provision"),
            ("D14_ACC_PAY_COSTA", "d14_costa"),
            ("D14_ACC_PAY_SIERRA", "d14_sierra"),
        ):
            benefit_rules[code].with_company(cls.company).write(
                {"account_debit": cls.accounts[account].id, "account_credit": False}
            )
        cls.Wizard = cls.env["erp.payroll.benefit.payment.wizard"]
        cls.Payment = cls.env["erp.payroll.provision.payment"]
        cls.PayslipLine = cls.env["hr.payslip.line"]
        cls.ana = cls._employee("Ana Peñafiel Núñez")
        cls._contract(cls.ana)
        cls.jose = cls._employee("José Íñiguez Ávila")
        cls._contract(cls.jose)
        cls.monthly = cls._employee("Martín Cañar (mensualiza)")
        cls._contract(cls.monthly)
        cls._election(cls.monthly, "thirteenth", "monthly")
        cls._election(cls.monthly, "fourteenth", "monthly")
        cls.serrano = cls._employee("Begoña Sarmiento (Sierra)", cls.est_sierra)
        cls._contract(cls.serrano)

    # ------------------------------------------------------------------
    # Ayudas
    # ------------------------------------------------------------------
    def _confirmed_month(self, employee, year, month):
        date_from = date(year, month, 1)
        payslip = self._payslip(
            employee,
            date_from=date_from,
            date_to=date_from + relativedelta(day=31),
        )
        payslip.compute_sheet()
        payslip.action_payslip_done()
        return payslip

    def _provision(self, payslip, code="D13_PROV"):
        return payslip.line_ids.filtered(lambda line: line.code == code)

    def _wizard(self, user=None, **vals):
        Wizard = self.Wizard.with_user(user) if user else self.Wizard
        return Wizard.create({"benefit": "thirteenth", "year": 2026, **vals})

    def _generate(self, user=None, **vals):
        wizard = self._wizard(user, **vals)
        action = wizard.action_generate()
        return wizard, action

    def _pending(self, employee, codes=("D13_PROV",)):
        return self.PayslipLine._erp_get_pending_provision_lines(
            codes, employees=employee
        )

    # ------------------------------------------------------------------
    # Periodo y fecha de pago (CA-1, CA-2)
    # ------------------------------------------------------------------
    def test_benefit_period_from_parameters(self):
        Payslip = self.env["hr.payslip"]
        self.assertEqual(
            Payslip._erp_get_benefit_period("D13_ACC_PAY", 2026),
            (date(2025, 12, 1), date(2026, 11, 30), date(2026, 12, 24)),
        )
        self.assertEqual(
            Payslip._erp_get_benefit_period("D14_ACC_PAY_COSTA", 2026),
            (date(2025, 3, 1), date(2026, 2, 28), date(2026, 3, 15)),
        )
        # Año bisiesto: el periodo de la Costa termina el 29 de febrero.
        self.assertEqual(
            Payslip._erp_get_benefit_period("D14_ACC_PAY_COSTA", 2028)[1],
            date(2028, 2, 29),
        )
        self.assertEqual(
            Payslip._erp_get_benefit_period("D14_ACC_PAY_SIERRA", 2026),
            (date(2025, 8, 1), date(2026, 7, 31), date(2026, 8, 15)),
        )
        self.assertEqual(set(BENEFIT_PERIOD_PARAM_PREFIX.values()), set(TEST_PERIODS))
        # Parámetro con un mes imposible y año fuera de rango.
        self.Parameter.create(
            {
                "code": "THIRTEENTH_PAYMENT_MONTH",
                "name": "Mes de pago erróneo (prueba)",
                "value_type": "number",
                "value": 13,
                "date_from": date(2027, 1, 1),
                "norm": "Valor ficticio de prueba",
            }
        )
        with self.assertRaisesRegex(UserError, "THIRTEENTH_PAYMENT_MONTH"):
            Payslip._erp_get_benefit_period("D13_ACC_PAY", 2027)
        with self.assertRaises(UserError):
            Payslip._erp_get_benefit_period("D13_ACC_PAY", 26)

    def test_wizard_defaults_and_period(self):
        wizard = self._wizard()
        self.assertEqual(wizard.pay_code, "D13_ACC_PAY")
        self.assertEqual(
            (wizard.date_start, wizard.date_end),
            (date(2025, 12, 1), date(2026, 11, 30)),
        )
        self.assertEqual(wizard.payment_date, date(2026, 12, 24))
        fourteenth = self._wizard(benefit="fourteenth")
        self.assertFalse(fourteenth.pay_code)
        self.assertIn("régimen", fourteenth.period_message)
        with self.assertRaisesRegex(UserError, "régimen"):
            fourteenth.action_generate()
        with Form(self.Wizard) as form:
            form.benefit = "fourteenth"
            form.regime = "sierra_amazonia"
            form.year = 2026
            self.assertEqual(form.payment_date, date(2026, 8, 15))

    # ------------------------------------------------------------------
    # Generación del lote (CA-1, CA-2, CA-3)
    # ------------------------------------------------------------------
    def test_generate_thirteenth_payment(self):
        for employee in (self.ana, self.jose, self.monthly):
            self._confirmed_month(employee, 2026, 1)
            self._confirmed_month(employee, 2026, 2)
        # Provisión fuera del periodo (diciembre de 2026 es del pago 2027).
        self._confirmed_month(self.ana, 2026, 12)
        wizard, action = self._generate(
            self.payroll_manager, payment_date=date(2026, 12, 20)
        )
        run = wizard.payslip_run_id
        self.assertEqual(action["params"]["next"]["res_id"], run.id)
        self.assertEqual(run.struct_id, self.benefit_structure)
        self.assertEqual(
            (run.date_start, run.date_end), (date(2025, 12, 1), date(2026, 11, 30))
        )
        self.assertEqual(run.slip_ids.employee_id, self.ana | self.jose)
        self.assertEqual((wizard.created_count, wizard.skipped_count), (2, 0))
        self.assertIn("2 roles creados", wizard.summary)
        for slip in run.slip_ids:
            self.assertEqual(slip.state, "verify")
            self.assertEqual(slip.erp_benefit_pay_code, "D13_ACC_PAY")
            self.assertEqual(slip.date, date(2026, 12, 20))
            # Solo el décimo tercero, aunque haya provisiones de décimo
            # cuarto en el periodo: 2 × 83,33.
            self._assert_lines(
                slip, {"D13_ACC_PAY": 166.66, "GROSS": 166.66, "NET": 166.66}
            )
        # Nada pendiente para otro lote del mismo periodo mientras exista el
        # anterior: todos omitidos y ningún lote vacío.
        runs_before = self.env["hr.payslip.run"].search_count([])
        with self.assertRaisesRegex(UserError, "ya tiene el rol de pago"):
            self._generate(self.payroll_manager)
        self.assertEqual(self.env["hr.payslip.run"].search_count([]), runs_before)

    def test_generate_without_pending_provisions(self):
        self._confirmed_month(self.monthly, 2026, 1)
        with self.assertRaisesRegex(UserError, "No hay provisiones"):
            self._generate(self.payroll_manager)

    def test_generate_fourteenth_by_regime(self):
        self._confirmed_month(self.ana, 2026, 1)
        self._confirmed_month(self.serrano, 2026, 1)
        wizard, _action = self._generate(
            self.payroll_manager, benefit="fourteenth", regime="sierra_amazonia"
        )
        slip = wizard.payslip_run_id.slip_ids
        self.assertEqual(slip.employee_id, self.serrano)
        self._assert_lines(
            slip,
            {"D14_ACC_PAY_SIERRA": 33.33, "GROSS": 33.33, "NET": 33.33},
        )
        # La Costa paga en marzo: el periodo 2026 termina en febrero e incluye
        # enero de 2026 solo para Ana.
        wizard, _action = self._generate(
            self.payroll_manager, benefit="fourteenth", regime="costa_galapagos"
        )
        self.assertEqual(wizard.payslip_run_id.slip_ids.employee_id, self.ana)

    def test_generate_skips_employee_without_contract(self):
        self._confirmed_month(self.ana, 2026, 1)
        self._confirmed_month(self.jose, 2026, 1)
        # El contrato de José se anula después: sin contrato en el periodo.
        self.jose.contract_ids.write({"state": "cancel"})
        wizard, action = self._generate(self.payroll_manager)
        self.assertEqual(wizard.payslip_run_id.slip_ids.employee_id, self.ana)
        self.assertEqual(wizard.skipped_count, 1)
        self.assertIn("José Íñiguez Ávila: sin contrato", wizard.summary)
        self.assertEqual(action["params"]["type"], "warning")

    def test_access_only_payroll_manager(self):
        Access = self.env["ir.model.access"]
        model = "erp.payroll.benefit.payment.wizard"
        self.assertFalse(
            Access.with_user(self.payroll_user).check(model, "create", False)
        )
        self.assertTrue(
            Access.with_user(self.payroll_manager).check(model, "create", False)
        )
        wizard = self._wizard()
        with self.assertRaises(AccessError):
            wizard.with_user(self.payroll_user).action_generate()

    def test_wizard_company_limited_to_allowed_companies(self):
        other = self.env["res.company"].create({"name": "Otra empresa (prueba)"})
        Wizard = self.Wizard.with_user(self.payroll_manager)
        domain = Wizard._fields["company_id"].domain(Wizard)
        self.assertEqual(
            self.env["res.company"].search(domain), self.payroll_manager.company_ids
        )
        self.assertNotIn(other, self.env["res.company"].search(domain))
        self._confirmed_month(self.ana, 2026, 1)
        wizard = self._wizard(self.payroll_manager, company_id=other.id)
        with self.assertRaisesRegex(AccessError, "selector de empresas"):
            wizard.action_generate()

    # ------------------------------------------------------------------
    # Confirmación, contabilidad y anulación (CA-3, CA-4)
    # ------------------------------------------------------------------
    def test_confirm_marks_provisions_and_posts_without_expense(self):
        january = self._confirmed_month(self.ana, 2026, 1)
        february = self._confirmed_month(self.ana, 2026, 2)
        wizard, _action = self._generate(self.payroll_manager)
        slip = wizard.payslip_run_id.slip_ids
        slip.with_user(self.payroll_manager).action_payslip_done()
        self.assertEqual(slip.state, "done")
        provisions = self._provision(january) | self._provision(february)
        self.assertEqual(slip.erp_paid_provision_ids.payslip_line_id, provisions)
        self.assertEqual(
            set(slip.erp_paid_provision_ids.mapped("document_type")), {"payslip"}
        )
        self.assertFalse(self._pending(self.ana))
        # Asiento (CA-4): debe del pasivo de la provisión, haber de «Sueldos
        # por pagar»; sin gasto y cuadrado.
        move = slip.sudo().move_id
        self.assertEqual(move.state, "posted")
        self.assertEqual(move.date, date(2026, 12, 24))
        by_account = {
            line.account_id: (line.debit, line.credit) for line in move.line_ids
        }
        self.assertEqual(
            set(by_account),
            {self.accounts["d13_provision"], self.accounts["net_payable"]},
        )
        self.assertAlmostEqual(by_account[self.accounts["d13_provision"]][0], 166.66)
        self.assertAlmostEqual(by_account[self.accounts["net_payable"]][1], 166.66)
        self.assertFalse(
            move.line_ids.filtered(
                lambda line: line.account_id.account_type == "expense"
            )
        )
        self.assertAlmostEqual(
            sum(move.line_ids.mapped("debit")), sum(move.line_ids.mapped("credit"))
        )
        self.assertEqual(move.line_ids.partner_id, self.ana.work_contact_id)
        # El rol mensual con provisiones pagadas no se anula ni se reembolsa
        # (mensaje que nombra el documento que las pagó).
        with self.assertRaisesRegex(UserError, slip.number):
            january.with_user(self.payroll_manager).action_payslip_cancel()
        with self.assertRaisesRegex(UserError, "reembolsar"):
            january.with_user(self.payroll_manager).refund_sheet()
        # Anular el pago revierte el asiento y deja las provisiones
        # pendientes otra vez (CA-3).
        slip.with_user(self.payroll_manager).action_payslip_cancel()
        self.assertEqual(slip.state, "cancel")
        self.assertFalse(slip.erp_paid_provision_ids)
        self.assertEqual(self._pending(self.ana), provisions)
        self.assertTrue(move.reversal_move_ids)
        # Y el rol mensual ya se puede anular.
        january.with_user(self.payroll_manager).action_payslip_cancel()
        self.assertEqual(january.state, "cancel")

    def test_confirm_detects_changed_provisions(self):
        self._confirmed_month(self.ana, 2026, 1)
        wizard, _action = self._generate(self.payroll_manager)
        slip = wizard.payslip_run_id.slip_ids
        # Se confirma otro mes del periodo después del cálculo y la
        # confirmación no recalcula: el rol ya no cuadra con lo pendiente.
        self._confirmed_month(self.ana, 2026, 2)
        self.env["ir.config_parameter"].sudo().set_param(
            "payroll.prevent_compute_on_confirm", True
        )
        with self.assertRaisesRegex(UserError, "Recalcule"):
            slip.with_user(self.payroll_manager).action_payslip_done()
        self.env["ir.config_parameter"].sudo().set_param(
            "payroll.prevent_compute_on_confirm", False
        )
        # Por defecto la confirmación recalcula: paga los dos meses.
        slip.with_user(self.payroll_manager).action_payslip_done()
        self.assertEqual(len(slip.erp_paid_provision_ids), 2)

    def test_refund_releases_and_cancelled_refund_restores(self):
        self._confirmed_month(self.ana, 2026, 1)
        wizard, _action = self._generate(self.payroll_manager)
        slip = wizard.payslip_run_id.slip_ids
        slip.action_payslip_done()
        slip.with_user(self.payroll_manager).refund_sheet()
        refund = slip.refunded_id
        self.assertTrue(refund.credit_note)
        self.assertEqual(refund.state, "done")
        self.assertFalse(slip.erp_paid_provision_ids)
        self.assertFalse(refund.erp_paid_provision_ids)
        self.assertTrue(self._pending(self.ana))
        # Anular el reembolso: el pago original vuelve a cubrir sus
        # provisiones.
        refund.with_user(self.payroll_manager).action_payslip_cancel()
        self.assertEqual(len(slip.erp_paid_provision_ids), 1)
        self.assertFalse(self._pending(self.ana))

    def test_benefit_payslip_requires_benefit_code(self):
        self._confirmed_month(self.ana, 2026, 1)
        slip = self.env["hr.payslip"].create(
            {
                "employee_id": self.ana.id,
                "contract_id": self.ana.contract_ids.id,
                "struct_id": self.benefit_structure.id,
                "date_from": date(2025, 12, 1),
                "date_to": date(2026, 11, 30),
            }
        )
        with self.assertRaisesRegex(UserError, "Pago de décimos"):
            slip.compute_sheet()
        # El décimo que paga el rol no se cambia a mano.
        with self.assertRaises(UserError):
            slip.with_user(self.payroll_manager).write(
                {"erp_benefit_pay_code": "D13_ACC_PAY"}
            )
