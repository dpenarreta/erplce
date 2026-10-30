"""Flujo del rol mensual Ecuador (US-008, CA-7 a CA-10): duplicados, estados,
permisos, contabilización, anulación, lotes y validaciones de conceptos.
Valores ficticios de prueba (ver ``common.py``)."""

from datetime import date

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from ..models.hr_salary_rule import ERP_RULE_DEFAULT_ACCOUNTS
from .common import PayrollEcCase

ALLOW_CANCEL = "payroll.allow_cancel_payslips"


@tagged("post_install", "-at_install")
class TestPayrollEcFlow(PayrollEcCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls._employee("José Ñúñez Peña")
        cls.contract = cls._contract(cls.employee)
        cls.employee_2 = cls._employee("María Añazco")
        cls.contract_2 = cls._contract(cls.employee_2, wage=1234.56)

    def _move_balance(self, move, account):
        return sum(
            move.line_ids.filtered(lambda ml: ml.account_id == account).mapped(
                "balance"
            )
        )

    # ------------------------------------------------------------------
    # Rol duplicado (CA-8)
    # ------------------------------------------------------------------
    def test_duplicate_on_create(self):
        self._payslip(self.employee)
        with self.assertRaises(UserError) as error:
            self._payslip(self.employee)
        message = str(error.exception)
        self.assertIn("Ya existe un rol de pagos no anulado", message)
        self.assertIn("José Ñúñez Peña", message)
        self.assertIn("Rol mensual Ecuador", message)

    def test_duplicate_within_batch_create(self):
        vals = {
            "employee_id": self.employee_2.id,
            "contract_id": self.contract_2.id,
            "struct_id": self.structure.id,
            "date_from": date(2026, 3, 1),
            "date_to": date(2026, 3, 31),
        }
        with self.assertRaises(UserError) as error:
            self.env["hr.payslip"].create([vals, dict(vals)])
        self.assertIn("María Añazco", str(error.exception))

    def test_duplicate_on_write(self):
        self._payslip(self.employee)
        february = self._payslip(
            self.employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28)
        )
        with self.assertRaises(UserError):
            february.write(
                {"date_from": date(2026, 1, 1), "date_to": date(2026, 1, 31)}
            )

    def test_duplicate_allowed_after_cancel_and_blocked_on_reset(self):
        first = self._payslip(self.employee)
        first.action_payslip_cancel()
        second = self._payslip(self.employee)
        self.assertTrue(second)
        with self.assertRaises(UserError):
            first.action_payslip_draft()
        self.assertEqual(first.state, "cancel")

    # ------------------------------------------------------------------
    # Estados (CA-8)
    # ------------------------------------------------------------------
    def test_done_payslip_cannot_be_recomputed_nor_confirmed_twice(self):
        payslip = self._computed(self.employee)
        payslip.action_payslip_done()
        move = payslip.move_id
        with self.assertRaises(UserError):
            payslip.compute_sheet()
        with self.assertRaises(UserError) as error:
            payslip.action_payslip_done()
        self.assertIn("ya está confirmado", str(error.exception))
        with self.assertRaises(UserError):
            payslip.with_context(without_compute_sheet=True).action_payslip_done()
        self.assertEqual(payslip.move_id, move)
        self.assertEqual(
            self.env["account.move"].search_count([("ref", "=", payslip.number)]), 1
        )
        with self.assertRaises(UserError):
            payslip.action_payslip_draft()

    def test_cancelled_payslip_cannot_be_recomputed_nor_confirmed(self):
        payslip = self._computed(self.employee)
        payslip.action_payslip_cancel()
        with self.assertRaises(UserError):
            payslip.compute_sheet()
        with self.assertRaises(UserError):
            payslip.with_context(without_compute_sheet=True).action_payslip_done()
        payslip.action_payslip_draft()
        payslip.compute_sheet()
        self.assertEqual(payslip.state, "verify")

    def test_lines_of_done_payslip_are_locked(self):
        payslip = self._computed(self.employee)
        payslip.action_payslip_done()
        line = payslip.line_ids[:1]
        with self.assertRaises(UserError):
            line.with_user(self.payroll_manager).write({"amount": 1.0})
        with self.assertRaises(UserError):
            line.unlink()

    # ------------------------------------------------------------------
    # Permisos (CA-9)
    # ------------------------------------------------------------------
    def test_payroll_user_computes_but_cannot_edit_lines(self):
        payslip = self._payslip(self.employee).with_user(self.payroll_user)
        payslip.compute_sheet()
        self.assertEqual(payslip.state, "verify")
        self.assertAlmostEqual(payslip.get_salary_line_total("NET"), 900.00)
        with self.assertRaises(AccessError):
            payslip.line_ids[:1].write({"amount": 1.0})

    def test_payroll_user_cannot_confirm(self):
        payslip = self._computed(self.employee)
        with self.assertRaises(AccessError) as error:
            payslip.with_user(self.payroll_user).action_payslip_done()
        self.assertIn("responsable de nómina", str(error.exception))
        self.assertEqual(payslip.state, "verify")
        self.assertFalse(payslip.move_id)

    def test_manager_without_accounting_group_confirms(self):
        self.assertFalse(
            self.payroll_manager.has_group("account.group_account_invoice")
        )
        payslip = self._payslip(self.employee).with_user(self.payroll_manager)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self.assertEqual(payslip.state, "done")
        move = payslip.sudo().move_id
        self.assertEqual(move.state, "posted")

    def test_payroll_config_read_only_for_payroll_user(self):
        Access = self.env["ir.model.access"]
        for model in (
            "hr.payroll.structure",
            "hr.salary.rule.category",
            "hr.salary.rule",
        ):
            self.assertTrue(
                Access.with_user(self.payroll_user).check(model, "read", False)
            )
            for operation in ("write", "create", "unlink"):
                self.assertFalse(
                    Access.with_user(self.payroll_user).check(model, operation, False),
                    f"{model} {operation}",
                )
                self.assertTrue(
                    Access.with_user(self.payroll_manager).check(
                        model, operation, False
                    ),
                    f"{model} {operation}",
                )
        with self.assertRaises(AccessError):
            self.structure.with_user(self.payroll_user).write({"note": "Cambio"})
        self.structure.with_user(self.payroll_manager).write({"note": "Cambio"})

    # ------------------------------------------------------------------
    # Contabilización (CA-10)
    # ------------------------------------------------------------------
    def test_move_balanced_with_expected_accounts(self):
        payslip = self._computed(self.employee)
        payslip.action_payslip_done()
        move = payslip.move_id
        self.assertEqual(move.state, "posted")
        self.assertEqual(move.journal_id, self.journal)
        self.assertEqual(move.date, date(2026, 1, 31))
        self.assertFalse(
            move.line_ids.filtered(lambda ml: ml.name == "Adjustment Entry")
        )
        self.assertAlmostEqual(sum(move.line_ids.mapped("balance")), 0.0)
        acc = self.accounts
        expected = {
            "expense_wage": 1000.00,
            "iess_personal": -100.00,
            "net_payable": -900.00,
            "expense_patronal": 120.00,
            "iess_patronal": -120.00,
            "expense_fr": 80.00,
            "fr_payable": -80.00,
            "expense_d13": 83.33,
            "d13_provision": -83.33,
            "expense_d14": 33.33,
            "d14_costa": -33.33,
        }
        for key, balance in expected.items():
            self.assertAlmostEqual(self._move_balance(move, acc[key]), balance, msg=key)
        self.assertEqual(set(move.line_ids.account_id), {acc[key] for key in expected})
        partner = self.employee.work_contact_id
        for key in ("net_payable", "iess_personal", "iess_patronal"):
            lines = move.line_ids.filtered(lambda ml, k=key: ml.account_id == acc[k])
            self.assertEqual(lines.partner_id, partner, key)
        expense = move.line_ids.filtered(
            lambda ml: ml.account_id == acc["expense_wage"]
        )
        self.assertFalse(expense.partner_id)

    def test_move_1000_05_without_adjustment(self):
        employee = self._employee("Rocío Peña")
        self._contract(employee, wage=1000.05)
        payslip = self._computed(employee)
        payslip.action_payslip_done()
        move = payslip.move_id
        self.assertEqual(
            len(move.line_ids.filtered(lambda ml: ml.name == "Adjustment Entry")), 0
        )
        self.assertAlmostEqual(
            sum(move.line_ids.mapped("debit")), sum(move.line_ids.mapped("credit"))
        )
        self.assertAlmostEqual(
            self._move_balance(move, self.accounts["net_payable"]), -900.04
        )
        self.assertAlmostEqual(
            self._move_balance(move, self.accounts["iess_personal"]), -100.01
        )
        self.assertAlmostEqual(
            self._move_balance(move, self.accounts["expense_wage"]), 1000.05
        )

    def test_move_concepts_to_own_accounts(self):
        bonus = self._concept(
            "TEST_BONO", account_debit_id=self.accounts["expense_bonus"].id
        )
        other_bonus = self._concept("TEST_OTRO")
        self._concept(
            "TEST_COMIS",
            concept_type="deduction",
            amount_kind="variable",
            account_credit_id=self.accounts["deduction_payable"].id,
        )
        loan = self._concept("TEST_DESC", concept_type="deduction")
        self._assign(self.employee, bonus, 100.0)
        self._assign(self.employee, other_bonus, 40.0)
        self._assign(self.employee, loan, 25.0)
        payslip = self._computed(self.employee, inputs={"TEST_COMIS": 30.0})
        payslip.action_payslip_done()
        move = payslip.move_id
        acc = self.accounts
        self.assertAlmostEqual(self._move_balance(move, acc["expense_bonus"]), 100.00)
        self.assertAlmostEqual(self._move_balance(move, acc["expense_other"]), 40.00)
        self.assertAlmostEqual(
            self._move_balance(move, acc["deduction_payable"]), -30.00
        )
        self.assertAlmostEqual(
            self._move_balance(move, acc["employee_payable"]), -25.00
        )
        # Neto = 1140 - 100 (IESS sobre 1000: conceptos sin base) - 55.
        self.assertAlmostEqual(self._move_balance(move, acc["net_payable"]), -985.00)
        self.assertAlmostEqual(sum(move.line_ids.mapped("balance")), 0.0)
        bonus_line = move.line_ids.filtered(
            lambda ml: ml.account_id == acc["expense_bonus"]
        )
        self.assertEqual(bonus_line.name, bonus.name)
        store_line = move.line_ids.filtered(
            lambda ml: ml.account_id == acc["deduction_payable"]
        )
        self.assertEqual(store_line.partner_id, self.employee.work_contact_id)

    def test_unbalanced_move_raises_instead_of_adjusting(self):
        self.rules["NET"].with_company(self.company).account_credit = False
        payslip = self._computed(self.employee)
        with self.assertRaises(UserError) as error:
            payslip.action_payslip_done()
        self.assertIn("no cuadra", str(error.exception))
        self.assertFalse(payslip.move_id)

    def test_payslip_without_journal(self):
        employee = self._employee("Sin Diario Ñ")
        contract = self._contract(employee)
        contract.journal_id = False
        payslip = self._computed(employee)
        with self.assertRaises(UserError) as error:
            payslip.action_payslip_done()
        self.assertIn("diario de nómina", str(error.exception))

    def test_refund_reverses_amounts(self):
        payslip = self._computed(self.employee)
        payslip.action_payslip_done()
        payslip.refund_sheet()
        refund = payslip.refunded_id
        self.assertEqual(refund.state, "done")
        self.assertAlmostEqual(
            self._move_balance(refund.move_id, self.accounts["net_payable"]), 900.00
        )
        self.assertAlmostEqual(sum(refund.move_id.line_ids.mapped("balance")), 0.0)

    # ------------------------------------------------------------------
    # Anulación (CA-10)
    # ------------------------------------------------------------------
    def test_cancel_done_payslip_reverses_move(self):
        self.env["ir.config_parameter"].sudo().set_param(ALLOW_CANCEL, "True")
        payslip = self._computed(self.employee)
        payslip.action_payslip_done()
        move = payslip.move_id
        with self.assertRaises(AccessError):
            payslip.with_user(self.payroll_user).action_payslip_cancel()
        payslip.with_user(self.payroll_manager).action_payslip_cancel()
        self.assertEqual(payslip.state, "cancel")
        self.assertTrue(move.exists())
        self.assertEqual(move.state, "posted")
        reversal = move.reversal_move_ids
        self.assertEqual(len(reversal), 1)
        self.assertEqual(reversal.state, "posted")
        self.assertAlmostEqual(
            self._move_balance(reversal, self.accounts["net_payable"]), 900.00
        )
        # Puede volver a borrador, recalcularse y confirmarse con otro asiento.
        payslip.action_payslip_draft()
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self.assertNotEqual(payslip.move_id, move)

    def test_cancel_done_payslip_requires_setting(self):
        payslip = self._computed(self.employee)
        payslip.action_payslip_done()
        with self.assertRaises(UserError) as error:
            payslip.action_payslip_cancel()
        self.assertIn("Permitir anular roles", str(error.exception))
        self.assertEqual(payslip.state, "done")
        self.assertFalse(payslip.move_id.reversal_move_ids)

    # ------------------------------------------------------------------
    # Lotes (CA-8)
    # ------------------------------------------------------------------
    def _run_wizard(
        self, employees, date_from=date(2026, 1, 1), date_to=date(2026, 1, 31)
    ):
        run = self.env["hr.payslip.run"].create(
            {
                "name": "Lote de prueba",
                "date_start": date_from,
                "date_end": date_to,
                "struct_id": self.structure.id,
                "journal_id": self.journal.id,
            }
        )
        wizard = (
            self.env["hr.payslip.employees"]
            .with_context(active_id=run.id)
            .create({"employee_ids": [(6, 0, employees.ids)]})
        )
        return run, wizard

    def test_batch_uses_contract_covering_period(self):
        """Lote atrasado de enero: el contrato vigente en enero terminó y el
        contrato actual empieza en marzo."""
        employee = self._employee("Íñigo Renovado")
        old = self._contract(
            employee,
            date_start=date(2025, 1, 1),
            date_end=date(2026, 2, 28),
            state="close",
        )
        current = self._contract(employee, wage=3000.0, date_start=date(2026, 3, 1))
        self.assertEqual(employee.contract_id, current)
        run, wizard = self._run_wizard(employee)
        wizard.compute_sheet()
        self.assertEqual(run.slip_ids.contract_id, old)
        self.assertAlmostEqual(run.slip_ids.get_salary_line_total("BASIC"), 1000.00)

    def test_batch_skips_and_reports_employees(self):
        without_contract = self._employee("Ángel Sin Contrato")
        self._payslip(self.employee_2)
        run, wizard = self._run_wizard(
            self.employee | self.employee_2 | without_contract
        )
        action = wizard.compute_sheet()
        self.assertEqual(run.slip_ids.employee_id, self.employee)
        self.assertEqual(run.slip_ids.state, "verify")
        self.assertEqual(action["tag"], "display_notification")
        message = action["params"]["message"]
        self.assertIn("Ángel Sin Contrato: sin contrato que cubra el periodo", message)
        self.assertIn("María Añazco: ya tiene un rol del periodo", message)
        self.assertNotIn("José Ñúñez Peña", message)
        self.assertIn("Ángel Sin Contrato", run.message_ids[:1].body)

    def test_batch_with_nobody_to_process(self):
        without_contract = self._employee("Ángel Sin Contrato")
        run, wizard = self._run_wizard(without_contract)
        with self.assertRaises(UserError) as error:
            wizard.compute_sheet()
        self.assertIn("No se generó ningún rol", str(error.exception))
        self.assertFalse(run.slip_ids)

    # ------------------------------------------------------------------
    # Conceptos y asignaciones (CA-7)
    # ------------------------------------------------------------------
    def test_assignment_only_fixed_concepts(self):
        variable = self._concept("TEST_VAR", amount_kind="variable")
        with self.assertRaises(ValidationError):
            self._assign(self.employee, variable, 10.0)

    def test_assignment_overlap(self):
        concept = self._concept("TEST_BONO")
        self._assign(
            self.employee,
            concept,
            10.0,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 3, 31),
        )
        with self.assertRaises(ValidationError) as error:
            self._assign(self.employee, concept, 20.0, date_from=date(2026, 3, 31))
        self.assertIn("se solapa", str(error.exception))
        with self.assertRaises(ValidationError):
            self._assign(self.employee, concept, 20.0, date_from=date(2025, 1, 1))
        # Contiguas, otro empleado u otro concepto: permitido.
        self._assign(self.employee, concept, 20.0, date_from=date(2026, 4, 1))
        self._assign(self.employee_2, concept, 20.0, date_from=date(2026, 1, 1))
        self._assign(self.employee, self._concept("TEST_OTRO"), 5.0)
        # Una asignación archivada no cuenta para el solapamiento.
        archived = self._assign(
            self.employee, self._concept("TEST_TERCERO"), 5.0, active=False
        )
        self._assign(self.employee, archived.concept_id, 7.0)

    def test_concept_account_by_type(self):
        with self.assertRaises(ValidationError):
            self._concept("TEST_A", account_credit_id=self.accounts["net_payable"].id)
        with self.assertRaises(ValidationError):
            self._concept(
                "TEST_B",
                concept_type="deduction",
                account_debit_id=self.accounts["expense_bonus"].id,
            )

    def test_concept_with_assignments_cannot_become_variable(self):
        concept = self._concept("TEST_BONO")
        self._assign(self.employee, concept, 10.0)
        with self.assertRaises(ValidationError):
            concept.amount_kind = "variable"

    # ------------------------------------------------------------------
    # Cuenta por defecto de otros descuentos (plan l10n_ec)
    # ------------------------------------------------------------------
    def test_ded_other_default_account_in_ec_chart(self):
        debit_code, _credit = ERP_RULE_DEFAULT_ACCOUNTS[
            "erp_payroll_ec.rule_ec_ded_other"
        ]
        self.assertEqual(debit_code, "21070402")
        if self.company.chart_template != "ec":
            self.skipTest("La empresa de test no tiene el plan contable 'ec'.")
        account = self.env["account.account"].search(
            [
                *self.env["account.account"]._check_company_domain(self.company),
                ("code", "=", debit_code),
            ]
        )
        self.assertEqual(account.account_type, "liability_payable")
