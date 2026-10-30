"""Prueba de humo del motor de nómina OCA y error sin contrato (US-006, CA-4).

Las categorías, reglas, estructura, cuentas y diario se crean aquí, con valores
ficticios de prueba (no normativos): sueldo básico = ``contract.wage`` y una
deducción de prueba del 10 % del básico, en negativo según la convención del
motor (las deducciones restan en la categoría NET).
"""

from datetime import date

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import format_date


@tagged("post_install", "-at_install")
class TestPayslipComputeSheet(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        # Periodo de prueba: un mes completo.
        cls.date_from = date(2026, 1, 1)
        cls.date_to = date(2026, 1, 31)

        # Contabilidad de prueba (cuentas ficticias, no del plan l10n_ec).
        Account = cls.env["account.account"]
        cls.account_expense = Account.create(
            {"code": "5999901", "name": "Sueldos (prueba)", "account_type": "expense"}
        )
        cls.account_deduction = Account.create(
            {
                "code": "2999901",
                "name": "Retención de prueba por pagar",
                "account_type": "liability_current",
            }
        )
        cls.account_net = Account.create(
            {
                "code": "2999902",
                "name": "Sueldos por pagar (prueba)",
                "account_type": "liability_current",
            }
        )
        cls.journal = cls.env["account.journal"].create(
            {
                "name": "Nómina de prueba",
                "code": "NOMTS",
                "type": "general",
                "default_account_id": cls.account_expense.id,
            }
        )

        # Categorías y reglas de prueba.
        Category = cls.env["hr.salary.rule.category"]
        cls.categ_basic = Category.create({"name": "Básico", "code": "TBASIC"})
        cls.categ_ded = Category.create({"name": "Deducción", "code": "TDED"})
        cls.categ_net = Category.create({"name": "Neto", "code": "TNET"})
        Rule = cls.env["hr.salary.rule"]
        cls.rule_basic = Rule.create(
            {
                "name": "Sueldo básico",
                "code": "TBASIC",
                "sequence": 1,
                "category_id": cls.categ_basic.id,
                "condition_select": "none",
                "amount_select": "code",
                "amount_python_compute": "result = contract.wage",
                "account_debit": cls.account_expense.id,
            }
        )
        cls.rule_ded = Rule.create(
            {
                "name": "Deducción de prueba (10 %)",
                "code": "TDED10",
                "sequence": 50,
                "category_id": cls.categ_ded.id,
                "condition_select": "none",
                "amount_select": "percentage",
                "amount_percentage_base": "TBASIC",
                "amount_percentage": -10.0,
                # Importe negativo en la cuenta de débito → apunte al haber.
                "account_debit": cls.account_deduction.id,
            }
        )
        cls.rule_net = Rule.create(
            {
                "name": "Neto a recibir",
                "code": "TNET",
                "sequence": 200,
                "category_id": cls.categ_net.id,
                "condition_select": "none",
                "amount_select": "code",
                "amount_python_compute": "result = categories.TBASIC + categories.TDED",
                "account_credit": cls.account_net.id,
            }
        )
        cls.structure = cls.env["hr.payroll.structure"].create(
            {
                "name": "Estructura de prueba US-006",
                "code": "TEST-US006",
                "parent_id": False,
                "rule_ids": [
                    (6, 0, (cls.rule_basic | cls.rule_ded | cls.rule_net).ids)
                ],
            }
        )

        # Tipo de contrato estándar (hr_contract): erp_hr_ec (US-007) exige
        # tipo en los contratos en curso cuando está instalado en la misma BD.
        cls.contract_type = cls.env["hr.contract.type"].create(
            {"name": "Indefinido (prueba US-006)"}
        )
        Employee = cls.env["hr.employee"]
        cls.employee = Employee.create({"name": "José Ñúñez Peña"})
        cls.employee_2 = Employee.create({"name": "María Fernanda Muñoz"})
        cls.employee_no_contract = Employee.create({"name": "Ángel Ibáñez Cañizares"})
        cls.contract = cls._create_contract(cls.employee, 1000.0, date(2025, 1, 1))
        cls.contract_2 = cls._create_contract(cls.employee_2, 1234.56, date(2025, 6, 1))

    @classmethod
    def _create_contract(cls, employee, wage, date_start, date_end=False, state="open"):
        return cls.env["hr.contract"].create(
            {
                "name": f"Contrato de {employee.name}",
                "employee_id": employee.id,
                "wage": wage,
                "date_start": date_start,
                "date_end": date_end,
                "state": state,
                "contract_type_id": cls.contract_type.id,
                "struct_id": cls.structure.id,
                "journal_id": cls.journal.id,
            }
        )

    def _create_payslip(self, employee, contract=None, date_from=None, date_to=None):
        return self.env["hr.payslip"].create(
            {
                "employee_id": employee.id,
                "contract_id": contract.id if contract else False,
                "struct_id": self.structure.id,
                "date_from": date_from or self.date_from,
                "date_to": date_to or self.date_to,
            }
        )

    def _line_total(self, payslip, code):
        line = payslip.line_ids.filtered(lambda line: line.code == code)
        self.assertEqual(len(line), 1, f"Debe haber una línea {code}")
        return line.total

    def _assert_amount(self, amount, expected):
        """El importe guardado ya está redondeado a la moneda y es el esperado."""
        self.assertEqual(
            amount,
            self.currency.round(amount),
            f"{amount} no está redondeado a {self.currency.decimal_places} decimales",
        )
        self.assertAlmostEqual(amount, expected, places=self.currency.decimal_places)

    def _expected_period_text(self, payslip):
        return (
            f"{payslip.employee_id.name}: del "
            f"{format_date(self.env, payslip.date_from)} al "
            f"{format_date(self.env, payslip.date_to)}"
        )

    # ------------------------------------------------------------------
    # Camino feliz
    # ------------------------------------------------------------------
    def test_compute_full_month_amounts(self):
        """Mes completo con 1.000,00 USD: básico, deducción del 10 % y neto."""
        self.assertEqual(self.currency.name, "USD")
        payslip = self._create_payslip(self.employee, self.contract)
        payslip.compute_sheet()

        self.assertEqual(payslip.state, "verify")
        self.assertTrue(payslip.number)
        self.assertEqual(len(payslip.line_ids), 3)
        self._assert_amount(self._line_total(payslip, "TBASIC"), 1000.00)
        self._assert_amount(self._line_total(payslip, "TDED10"), -100.00)
        self._assert_amount(self._line_total(payslip, "TNET"), 900.00)
        self._assert_amount(payslip.get_salary_line_total("TNET"), 900.00)

    def test_compute_without_explicit_contract_uses_open_contract(self):
        """Sin contrato asignado, el motor usa el contrato en curso del periodo."""
        payslip = self._create_payslip(self.employee)
        payslip.compute_sheet()
        self.assertEqual(payslip.state, "verify")
        self._assert_amount(self._line_total(payslip, "TNET"), 900.00)

    def test_compute_rounding_cents(self):
        """Importes con céntimos: 10 % de 1.234,56 = 123,456 → 123,46 USD."""
        payslip = self._create_payslip(self.employee_2, self.contract_2)
        payslip.compute_sheet()
        self._assert_amount(self._line_total(payslip, "TBASIC"), 1234.56)
        self._assert_amount(self._line_total(payslip, "TDED10"), -123.46)
        self._assert_amount(self._line_total(payslip, "TNET"), 1111.10)

    def test_confirm_payslip_creates_balanced_move(self):
        """Confirmar (action_payslip_done) deja el rol en 'done' con su asiento."""
        payslip = self._create_payslip(self.employee, self.contract)
        payslip.compute_sheet()
        payslip.action_payslip_done()

        self.assertEqual(payslip.state, "done")
        move = payslip.move_id
        self.assertTrue(move)
        self.assertEqual(move.state, "posted")
        self.assertEqual(move.journal_id, self.journal)
        self.assertEqual(move.date, self.date_to)
        self._assert_amount(sum(move.line_ids.mapped("debit")), 1000.00)
        self._assert_amount(sum(move.line_ids.mapped("credit")), 1000.00)

        def balance(account):
            lines = move.line_ids.filtered(lambda ml: ml.account_id == account)
            return sum(lines.mapped("balance"))

        self._assert_amount(balance(self.account_expense), 1000.00)
        self._assert_amount(balance(self.account_deduction), -100.00)
        self._assert_amount(balance(self.account_net), -900.00)
        net_line = move.line_ids.filtered(lambda ml: ml.account_id == self.account_net)
        self.assertEqual(net_line.partner_id, self.employee.work_contact_id)

    def test_contract_ending_on_first_day_is_valid(self):
        """Límite: un contrato que termina el primer día del periodo es vigente."""
        employee = self.env["hr.employee"].create({"name": "Begoña Núñez"})
        contract = self._create_contract(
            employee, 1000.0, date(2025, 1, 1), date_end=self.date_from, state="close"
        )
        payslip = self._create_payslip(employee, contract)
        payslip.compute_sheet()
        self.assertEqual(payslip.state, "verify")
        self._assert_amount(self._line_total(payslip, "TBASIC"), 1000.00)

    # ------------------------------------------------------------------
    # Sin contrato vigente
    # ------------------------------------------------------------------
    def test_no_contract_at_all(self):
        payslip = self._create_payslip(self.employee_no_contract)
        with self.assertRaises(UserError) as error:
            payslip.compute_sheet()
        message = str(error.exception)
        self.assertIn("No se puede calcular ni confirmar el rol de pagos", message)
        self.assertIn("no tienen un contrato vigente en el periodo del rol", message)
        self.assertIn(self._expected_period_text(payslip), message)

    def test_explicit_expired_contract(self):
        """Contrato vencido asignado al rol → error controlado."""
        employee = self.env["hr.employee"].create({"name": "Íñigo Ordóñez"})
        contract = self._create_contract(
            employee,
            1000.0,
            date(2024, 1, 1),
            date_end=date(2025, 12, 31),
            state="close",
        )
        payslip = self._create_payslip(employee, contract)
        with self.assertRaises(UserError) as error:
            payslip.compute_sheet()
        self.assertIn(self._expected_period_text(payslip), str(error.exception))
        self.assertFalse(payslip.line_ids)

    def test_future_contract_without_explicit_contract(self):
        """Solo hay un contrato que empieza después del periodo → error."""
        employee = self.env["hr.employee"].create({"name": "Sofía Zúñiga"})
        self._create_contract(employee, 1000.0, date(2026, 3, 1))
        payslip = self._create_payslip(employee)
        with self.assertRaises(UserError) as error:
            payslip.compute_sheet()
        self.assertIn(self._expected_period_text(payslip), str(error.exception))

    def test_explicit_cancelled_contract(self):
        """Contrato cancelado que cubre las fechas no es vigente."""
        employee = self.env["hr.employee"].create({"name": "Raúl Muñoz"})
        contract = self._create_contract(
            employee, 1000.0, date(2025, 1, 1), state="cancel"
        )
        payslip = self._create_payslip(employee, contract)
        with self.assertRaises(UserError):
            payslip.compute_sheet()

    def test_confirm_without_contract_fails(self):
        """Confirmar recalcula el rol: también lanza el error controlado."""
        payslip = self._create_payslip(self.employee_no_contract)
        with self.assertRaises(UserError):
            payslip.action_payslip_done()

    def test_batch_with_one_payslip_without_contract(self):
        """Lote: falla todo y el mensaje nombra solo al empleado sin contrato."""
        payslips = (
            self._create_payslip(self.employee, self.contract)
            | self._create_payslip(self.employee_2)
            | self._create_payslip(self.employee_no_contract)
        )
        with self.assertRaises(UserError) as error:
            payslips.compute_sheet()
        message = str(error.exception)
        self.assertIn("Ángel Ibáñez Cañizares", message)
        self.assertNotIn("José Ñúñez Peña", message)
        self.assertNotIn("María Fernanda Muñoz", message)

    def test_batch_lists_every_invalid_payslip(self):
        employee = self.env["hr.employee"].create({"name": "Nuria Peñafiel"})
        payslips = self._create_payslip(
            self.employee_no_contract
        ) | self._create_payslip(employee)
        with self.assertRaises(UserError) as error:
            payslips.compute_sheet()
        message = str(error.exception)
        for payslip in payslips:
            self.assertIn(self._expected_period_text(payslip), message)

    def test_batch_period_checked_per_payslip(self):
        """Mismo empleado, dos periodos: solo falla el anterior al contrato."""
        employee = self.env["hr.employee"].create({"name": "Tomás Ñaupari"})
        self._create_contract(employee, 1000.0, date(2026, 1, 1))
        valid = self._create_payslip(employee)
        before = self._create_payslip(
            employee, date_from=date(2025, 12, 1), date_to=date(2025, 12, 31)
        )
        with self.assertRaises(UserError) as error:
            (valid | before).compute_sheet()
        message = str(error.exception)
        self.assertIn(self._expected_period_text(before), message)
        self.assertNotIn(self._expected_period_text(valid), message)
        valid.compute_sheet()
        self.assertEqual(valid.state, "verify")

    def _create_valid_batch(self, size):
        """Lote de ``size`` roles válidos: la mitad con contrato asignado y la
        otra mitad sin él (el motor lo busca)."""
        payslips = self.env["hr.payslip"]
        for index in range(size):
            employee = self.env["hr.employee"].create(
                {"name": f"Empleado Ñandú {size}-{index}"}
            )
            contract = self._create_contract(employee, 1000.0, date(2025, 1, 1))
            payslips |= self._create_payslip(employee, contract if index % 2 else None)
        return payslips

    def _count_validation_queries(self, payslips):
        payslips.env.invalidate_all()
        before = self.env.cr.sql_log_count
        payslips._check_contract_in_period()
        return self.env.cr.sql_log_count - before

    def test_batch_validation_queries_do_not_scale(self):
        """La validación hace el mismo número de consultas con 2 que con 6
        roles (sin búsquedas por rol)."""
        small = self._count_validation_queries(self._create_valid_batch(2))
        large = self._count_validation_queries(self._create_valid_batch(6))
        self.assertGreater(small, 0)
        self.assertEqual(small, large)

    # ------------------------------------------------------------------
    # Permisos
    # ------------------------------------------------------------------
    def _create_user(self, login, groups):
        return (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": f"Usuario {login}",
                    "login": login,
                    "email": f"{login}@example.com",
                    "groups_id": [(6, 0, groups.ids)],
                }
            )
        )

    def test_user_without_payroll_group_cannot_compute(self):
        user = self._create_user("sin_nomina", self.env.ref("base.group_user"))
        self.assertFalse(user.has_group("payroll.group_payroll_user"))
        payslip = self._create_payslip(self.employee, self.contract)
        with self.assertRaises(AccessError):
            payslip.with_user(user).compute_sheet()
        self.assertEqual(payslip.state, "draft")

    def test_payroll_manager_can_compute(self):
        user = self._create_user(
            "gestor_nomina", self.env.ref("payroll.group_payroll_manager")
        )
        payslip = self._create_payslip(self.employee, self.contract)
        payslip.with_user(user).compute_sheet()
        self.assertEqual(payslip.state, "verify")
        self._assert_amount(self._line_total(payslip, "TNET"), 900.00)

    def test_payroll_manager_gets_controlled_error(self):
        user = self._create_user(
            "gestor_nomina2", self.env.ref("payroll.group_payroll_manager")
        )
        payslip = self._create_payslip(self.employee_no_contract)
        with self.assertRaises(UserError) as error:
            payslip.with_user(user).compute_sheet()
        self.assertIn("Ángel Ibáñez Cañizares", str(error.exception))

    # ------------------------------------------------------------------
    # Más casos de contrato (ronda QA 1)
    # ------------------------------------------------------------------
    def test_explicit_draft_contract(self):
        """Un contrato en borrador asignado al rol no es vigente."""
        employee = self.env["hr.employee"].create({"name": "Agustín Peña"})
        contract = self._create_contract(
            employee, 1000.0, date(2025, 1, 1), state="draft"
        )
        payslip = self._create_payslip(employee, contract)
        with self.assertRaises(UserError) as error:
            payslip.compute_sheet()
        self.assertIn(self._expected_period_text(payslip), str(error.exception))

    def test_contract_starting_on_last_day_is_valid(self):
        """Límite: un contrato que empieza el último día del periodo es vigente."""
        employee = self.env["hr.employee"].create({"name": "Lucía Cañar"})
        contract = self._create_contract(employee, 1000.0, self.date_to)
        payslip = self._create_payslip(employee, contract)
        payslip.compute_sheet()
        self.assertEqual(payslip.state, "verify")

    def test_contract_of_another_employee(self):
        """El rol de A no se calcula con el contrato de B."""
        payslip = self._create_payslip(self.employee_no_contract, self.contract)
        with self.assertRaises(UserError) as error:
            payslip.compute_sheet()
        message = str(error.exception)
        self.assertIn("el contrato asignado no pertenece al empleado del rol", message)
        self.assertIn(
            "Rol de Ángel Ibáñez Cañizares: el contrato «Contrato de José Ñúñez "
            "Peña» pertenece a José Ñúñez Peña",
            message,
        )
        self.assertFalse(payslip.line_ids)

    # ------------------------------------------------------------------
    # Confirmación sin recálculo (ronda QA 1)
    # ------------------------------------------------------------------
    def _set_prevent_compute_on_confirm(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "payroll.prevent_compute_on_confirm", "True"
        )

    def test_confirm_with_prevent_compute_without_contract(self):
        self._set_prevent_compute_on_confirm()
        payslip = self._create_payslip(self.employee_no_contract)
        with self.assertRaises(UserError) as error:
            payslip.action_payslip_done()
        self.assertIn(self._expected_period_text(payslip), str(error.exception))
        self.assertEqual(payslip.state, "draft")
        self.assertFalse(payslip.move_id)

    def test_confirm_with_prevent_compute_valid_contract(self):
        """Con el ajuste activo, un rol válido calculado se confirma igual."""
        self._set_prevent_compute_on_confirm()
        payslips = self._create_payslip(
            self.employee, self.contract
        ) | self._create_payslip(self.employee_2, self.contract_2)
        payslips.compute_sheet()
        payslips.with_context(without_compute_sheet=True).action_payslip_done()
        self.assertEqual(set(payslips.mapped("state")), {"done"})

    def test_confirm_without_compute_sheet_context_without_contract(self):
        payslip = self._create_payslip(self.employee_no_contract)
        with self.assertRaises(UserError):
            payslip.with_context(without_compute_sheet=True).action_payslip_done()
        self.assertEqual(payslip.state, "draft")

    def test_change_state_wizard_confirm_without_contract(self):
        """Asistente «Cambiar estado» → Confirmar, con el ajuste activo."""
        self._set_prevent_compute_on_confirm()
        payslip = self._create_payslip(self.employee_no_contract)
        wizard = (
            self.env["hr.payslip.change.state"]
            .with_context(active_ids=payslip.ids)
            .create({"state": "done"})
        )
        with self.assertRaises(UserError) as error:
            wizard.change_state_confirm()
        self.assertIn("Ángel Ibáñez Cañizares", str(error.exception))
        self.assertEqual(payslip.state, "draft")

    def test_refund_is_not_revalidated(self):
        """El reembolso de un rol confirmado se confirma aunque el contrato ya
        no esté vigente (copia de un rol validado)."""
        payslip = self._create_payslip(self.employee, self.contract)
        payslip.action_payslip_done()
        self.contract.state = "cancel"
        payslip.refund_sheet()
        refund = payslip.refunded_id
        self.assertTrue(refund.credit_note)
        self.assertEqual(refund.state, "done")
        self._assert_amount(refund.get_salary_line_total("TNET"), 900.00)

    # ------------------------------------------------------------------
    # Asistente de lotes (ronda QA 1)
    # ------------------------------------------------------------------
    def test_batch_wizard_with_employee_without_contract(self):
        run = self.env["hr.payslip.run"].create(
            {
                "name": "Lote enero 2026 (prueba)",
                "date_start": self.date_from,
                "date_end": self.date_to,
                "struct_id": self.structure.id,
            }
        )
        wizard = (
            self.env["hr.payslip.employees"]
            .with_context(active_id=run.id)
            .create(
                {
                    "employee_ids": [
                        (6, 0, (self.employee | self.employee_no_contract).ids)
                    ]
                }
            )
        )
        # US-008: el lote ya no es «todo o nada»; el empleado sin contrato se
        # omite y se informa, y el resto se calcula.
        action = wizard.compute_sheet()
        message = action["params"]["message"]
        self.assertIn("Ángel Ibáñez Cañizares", message)
        self.assertNotIn("José Ñúñez Peña", message)
        payslips = self.env["hr.payslip"].search([("payslip_run_id", "=", run.id)])
        self.assertEqual(payslips.employee_id, self.employee)
        self.assertEqual(payslips.state, "verify")
