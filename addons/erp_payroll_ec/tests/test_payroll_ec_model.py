"""Modelos, restricciones de BD, datos y permisos de erp_payroll_ec (US-008).

Las restricciones de BD se prueban con SQL parametrizado (UPDATE sobre
registros válidos) para que los tests sigan siendo válidos cuando la capa de
negocio añada validaciones previas con ValidationError/UserError.

No se prueban cifras legales como verdad (CA-11): de los parámetros cargados se
comprueba su presencia, estado, tipo y norma, no su valor.
"""

from datetime import date

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import SQL, index_exists, mute_logger

from ..models.hr_payslip import PAYSLIP_UNIQUE_PERIOD_INDEX
from ..models.hr_salary_rule import ERP_RULE_DEFAULT_ACCOUNTS

PARAMETER_TYPES = {
    "SBU": "amount",
    "IESS_PERSONAL": "percent",
    "IESS_PATRONAL": "percent",
    "RESERVE_FUND_RATE": "percent",
    "THIRTEENTH_DIVISOR": "number",
    "FOURTEENTH_MONTHS": "number",
    "MONTH_DAYS": "number",
    "RESERVE_FUND_MIN_MONTHS": "number",
}

# código de regla -> (código de categoría, ¿condición Python?)
RULES = {
    "BASIC": ("BASIC", False),
    "INC_OTHER": ("ALW", True),
    "FR_PAID": ("ALW", True),
    "D13_PAID": ("ALW", True),
    "D14_PAID": ("ALW", True),
    "GROSS": ("GROSS", False),
    "IESS_PERSONAL": ("DED", True),
    "DED_OTHER": ("DED", True),
    "NET": ("NET", False),
    "IESS_PATRONAL": ("COMP", True),
    "FR_ACCRUED": ("COMP", True),
    "D13_PROV": ("COMP", True),
    "D14_PROV_COSTA": ("COMP", True),
    "D14_PROV_SIERRA": ("COMP", True),
}


@tagged("post_install", "-at_install")
class TestPayrollEcModel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Parameter = cls.env["erp.payroll.parameter"]
        cls.Concept = cls.env["erp.payroll.concept"]
        cls.EmployeeConcept = cls.env["erp.payroll.employee.concept"]
        cls.structure = cls.env.ref("erp_payroll_ec.structure_ec_monthly")
        cls.employee = cls.env["hr.employee"].create({"name": "José Ñúñez Peña"})
        cls.employee_2 = cls.env["hr.employee"].create({"name": "María Añazco"})
        # Parámetro y conceptos de prueba (valores ficticios, no normativos).
        cls.param = cls.Parameter.create(
            {
                "code": "TEST_PARAM",
                "name": "Parámetro de prueba – Ñandú",
                "value_type": "amount",
                "value": 123.4567,
                "date_from": date(2026, 1, 1),
                "norm": "Norma de prueba, art. 1",
            }
        )
        cls.concept_income = cls.Concept.create(
            {
                "name": "Bono de alimentación (prueba)",
                "code": "TEST_BONO_ALIM",
                "concept_type": "income",
                "amount_kind": "fixed",
                "iess_base": True,
            }
        )
        cls.concept_deduction = cls.Concept.create(
            {
                "name": "Descuento comisariato (prueba)",
                "code": "TEST_DESC_COMIS",
                "concept_type": "deduction",
                "amount_kind": "variable",
            }
        )
        cls.assignment = cls.EmployeeConcept.create(
            {
                "employee_id": cls.employee.id,
                "concept_id": cls.concept_income.id,
                "amount": 50.0,
                "date_from": date(2026, 1, 1),
            }
        )
        cls.payroll_user = new_test_user(
            cls.env,
            login="usuario_nomina_ec",
            groups="base.group_user,payroll.group_payroll_user",
        )
        cls.payroll_manager = new_test_user(
            cls.env,
            login="responsable_nomina_ec",
            groups="base.group_user,payroll.group_payroll_manager",
        )
        cls.plain_user = new_test_user(
            cls.env, login="sin_nomina_ec", groups="base.group_user"
        )

    def _sql_update(self, table, values, record_id):
        """UPDATE parametrizado de varias columnas (identificadores escapados)."""
        self.env.flush_all()
        assignments = SQL(", ").join(
            SQL("%s = %s", SQL.identifier(column), value)
            for column, value in values.items()
        )
        self.env.cr.execute(
            SQL(
                "UPDATE %s SET %s WHERE id = %s",
                SQL.identifier(table),
                assignments,
                record_id,
            )
        )

    def _assert_db_rejects(self, table, values, record_id):
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._sql_update(table, values, record_id)

    # ------------------------------------------------------------------
    # Datos cargados
    # ------------------------------------------------------------------
    def test_parameters_loaded_to_validate_with_norm(self):
        params = self.Parameter.search([("code", "in", list(PARAMETER_TYPES))])
        self.assertEqual(set(params.mapped("code")), set(PARAMETER_TYPES))
        for param in params:
            self.assertEqual(param.state, "to_validate", param.code)
            self.assertEqual(param.value_type, PARAMETER_TYPES[param.code], param.code)
            self.assertTrue(param.norm and param.norm.strip(), param.code)
            self.assertFalse(param.company_id, param.code)
            self.assertTrue(param.date_from, param.code)

    def test_parameter_data_is_noupdate(self):
        data = self.env["ir.model.data"].search(
            [("module", "=", "erp_payroll_ec"), ("model", "=", "erp.payroll.parameter")]
        )
        self.assertEqual(len(data), len(PARAMETER_TYPES))
        self.assertTrue(all(data.mapped("noupdate")))

    def test_concept_catalog_delivered_empty(self):
        data = self.env["ir.model.data"].search_count(
            [("module", "=", "erp_payroll_ec"), ("model", "=", "erp.payroll.concept")]
        )
        self.assertEqual(data, 0)
        others = self.Concept.with_context(active_test=False).search_count(
            [("id", "not in", (self.concept_income | self.concept_deduction).ids)]
        )
        self.assertEqual(others, 0)

    def test_structure_and_rules_loaded(self):
        self.assertEqual(self.structure.code, "EC_MONTHLY")
        self.assertEqual(self.structure.name, "Rol mensual Ecuador")
        self.assertFalse(self.structure.parent_id)
        rules = self.structure.rule_ids
        self.assertEqual(set(rules.mapped("code")), set(RULES))
        for rule in rules:
            category_code, conditional = RULES[rule.code]
            self.assertEqual(rule.category_id.code, category_code, rule.code)
            self.assertEqual(rule.amount_select, "code", rule.code)
            self.assertIn(
                f'payslip._erp_rule_amount("{rule.code}", contract, categories, '
                "result_rules)",
                rule.amount_python_compute,
            )
            if conditional:
                self.assertEqual(rule.condition_select, "python", rule.code)
                self.assertIn(
                    f'payslip._erp_rule_applies("{rule.code}", contract)',
                    rule.condition_python,
                )
            else:
                self.assertEqual(rule.condition_select, "none", rule.code)
        # El neto se calcula después de todos los ingresos y descuentos, y las
        # reglas de la empresa (COMP) después del neto.
        by_code = {rule.code: rule for rule in rules}
        net_sequence = by_code["NET"].sequence
        for code, (category_code, _conditional) in RULES.items():
            if category_code in ("BASIC", "ALW", "GROSS", "DED"):
                self.assertLess(by_code[code].sequence, net_sequence, code)
            elif category_code == "COMP":
                self.assertGreater(by_code[code].sequence, net_sequence, code)

    def test_rule_account_mapping_covers_structure(self):
        mapped = {self.env.ref(xmlid).code for xmlid in ERP_RULE_DEFAULT_ACCOUNTS}
        self.assertEqual(mapped, set(RULES))

    def _require_ec_chart(self):
        if self.company.chart_template != "ec":
            self.skipTest("La empresa de test no tiene el plan contable 'ec'.")

    def test_default_accounts_assigned_from_ec_chart(self):
        self._require_ec_chart()
        for xmlid, (debit_code, credit_code) in ERP_RULE_DEFAULT_ACCOUNTS.items():
            rule = self.env.ref(xmlid).with_company(self.company)
            if debit_code:
                self.assertEqual(rule.account_debit.code, debit_code, xmlid)
            else:
                self.assertFalse(rule.account_debit, xmlid)
            if credit_code:
                self.assertEqual(rule.account_credit.code, credit_code, xmlid)
            else:
                self.assertFalse(rule.account_credit, xmlid)

    def test_default_accounts_idempotent_and_keep_manual_changes(self):
        self._require_ec_chart()
        rule = self.env.ref("erp_payroll_ec.rule_ec_basic").with_company(self.company)
        manual = self.env["account.account"].create(
            {
                "code": "5999911",
                "name": "Sueldos – cuenta manual (prueba)",
                "account_type": "expense",
            }
        )
        rule.account_debit = manual
        Rule = self.env["hr.salary.rule"]
        self.assertEqual(Rule._erp_set_default_accounts(self.company), 0)
        self.assertEqual(rule.account_debit, manual)
        # Una cuenta vaciada se vuelve a rellenar.
        net = self.env.ref("erp_payroll_ec.rule_ec_net").with_company(self.company)
        net.account_credit = False
        self.assertEqual(Rule._erp_set_default_accounts(self.company), 1)
        self.assertEqual(net.account_credit.code, "21070401")

    # ------------------------------------------------------------------
    # Restricciones: parámetros
    # ------------------------------------------------------------------
    def test_parameter_unique_code_date_company_including_global(self):
        other = self.Parameter.create(
            {
                "code": "TEST_PARAM",
                "name": "Parámetro de prueba (otra fecha)",
                "value_type": "amount",
                "value": 1.0,
                "date_from": date(2026, 2, 1),
                "norm": "Norma de prueba",
            }
        )
        # Ambos sin empresa (globales): NULLS NOT DISTINCT impide duplicar.
        self._assert_db_rejects(
            "erp_payroll_parameter", {"date_from": date(2026, 1, 1)}, other.id
        )
        # Con empresa distinta del global sí se admite la misma fecha.
        self._sql_update(
            "erp_payroll_parameter",
            {"date_from": date(2026, 1, 1), "company_id": self.company.id},
            other.id,
        )

    def test_parameter_checks(self):
        table = "erp_payroll_parameter"
        self._assert_db_rejects(table, {"code": "sbu_minusculas"}, self.param.id)
        self._assert_db_rejects(table, {"code": "1SBU"}, self.param.id)
        self._assert_db_rejects(table, {"code": "SBU-2026"}, self.param.id)
        self._assert_db_rejects(table, {"value": -0.0001}, self.param.id)
        self._assert_db_rejects(
            table, {"value_type": "percent", "value": 100.01}, self.param.id
        )
        # Límites válidos.
        self._sql_update(table, {"value_type": "percent", "value": 100}, self.param.id)
        self._sql_update(table, {"value": 0, "code": "A"}, self.param.id)

    def test_parameter_value_keeps_four_decimals(self):
        self.param.invalidate_recordset(["value"])
        self.assertEqual(self.param.value, 123.4567)

    def test_parameter_changes_are_tracked(self):
        param = self.param.with_user(self.payroll_manager)
        param.write({"value": 130.0})
        param.action_validate()
        # El seguimiento se escribe en el precommit (como en los tests de mail).
        self.env.flush_all()
        self.env.cr.precommit.run()
        tracked = self.param.message_ids.tracking_value_ids.field_id.mapped("name")
        self.assertIn("value", tracked)
        self.assertIn("state", tracked)

    # ------------------------------------------------------------------
    # Restricciones: conceptos y asignaciones
    # ------------------------------------------------------------------
    def test_concept_unique_code_per_company_and_format(self):
        table = "erp_payroll_concept"
        self._assert_db_rejects(
            table, {"code": "TEST_BONO_ALIM"}, self.concept_deduction.id
        )
        self._assert_db_rejects(table, {"code": "bono"}, self.concept_deduction.id)
        self._assert_db_rejects(
            table, {"code": "BONO ÑANDÚ"}, self.concept_deduction.id
        )
        self._assert_db_rejects(table, {"code": "B" * 33}, self.concept_deduction.id)
        self._sql_update(table, {"code": "B" * 32}, self.concept_deduction.id)
        # Mismo código en otra empresa: permitido.
        other_company = self.env["res.company"].create({"name": "Empresa Ñ (prueba)"})
        self._sql_update(
            table,
            {"code": "TEST_BONO_ALIM", "company_id": other_company.id},
            self.concept_deduction.id,
        )

    def test_deduction_cannot_add_to_bases(self):
        table = "erp_payroll_concept"
        self._assert_db_rejects(table, {"iess_base": True}, self.concept_deduction.id)
        self._assert_db_rejects(
            table, {"thirteenth_base": True}, self.concept_deduction.id
        )

    def test_employee_concept_checks(self):
        table = "erp_payroll_employee_concept"
        self._assert_db_rejects(table, {"amount": 0}, self.assignment.id)
        self._assert_db_rejects(table, {"amount": -0.01}, self.assignment.id)
        self._assert_db_rejects(
            table, {"date_to": date(2025, 12, 31)}, self.assignment.id
        )
        # Límite: un solo día de vigencia.
        self._sql_update(table, {"date_to": date(2026, 1, 1)}, self.assignment.id)

    def test_employee_concept_company_and_currency(self):
        self.assertEqual(self.assignment.company_id, self.employee.company_id)
        self.assertEqual(self.assignment.currency_id, self.company.currency_id)

    def test_concept_in_use_cannot_be_deleted(self):
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.concept_income.unlink()
                self.env.flush_all()

    def test_employee_deletion_cascades_to_assignments(self):
        employee = self.env["hr.employee"].create({"name": "Ángel Ibáñez"})
        assignment = self.EmployeeConcept.create(
            {
                "employee_id": employee.id,
                "concept_id": self.concept_income.id,
                "amount": 10.0,
                "date_from": date(2026, 1, 1),
            }
        )
        employee.unlink()
        self.assertFalse(assignment.exists())

    # ------------------------------------------------------------------
    # Restricción: rol duplicado
    # ------------------------------------------------------------------
    def _create_payslip(self, employee, date_from, date_to):
        return self.env["hr.payslip"].create(
            {
                "employee_id": employee.id,
                "struct_id": self.structure.id,
                "date_from": date_from,
                "date_to": date_to,
            }
        )

    def test_unique_payslip_index_exists(self):
        self.assertTrue(index_exists(self.env.cr, PAYSLIP_UNIQUE_PERIOD_INDEX))

    def test_duplicate_payslip_rejected(self):
        jan = self._create_payslip(self.employee, date(2026, 1, 1), date(2026, 1, 31))
        feb = self._create_payslip(self.employee, date(2026, 2, 1), date(2026, 2, 28))
        period = {"date_from": jan.date_from, "date_to": jan.date_to}
        self._assert_db_rejects("hr_payslip", period, feb.id)
        # Sin estructura en ambos: también duplicado.
        self._sql_update("hr_payslip", {"struct_id": None}, jan.id)
        self._sql_update("hr_payslip", {"struct_id": None}, feb.id)
        self._assert_db_rejects("hr_payslip", period, feb.id)

    def test_duplicate_allowed_when_cancelled_refund_or_other_employee(self):
        jan = self._create_payslip(self.employee, date(2026, 1, 1), date(2026, 1, 31))
        period = {"date_from": jan.date_from, "date_to": jan.date_to}
        other_employee = self._create_payslip(
            self.employee_2, jan.date_from, jan.date_to
        )
        self.assertTrue(other_employee)
        cancelled = self._create_payslip(
            self.employee, date(2026, 2, 1), date(2026, 2, 28)
        )
        self._sql_update("hr_payslip", {"state": "cancel", **period}, cancelled.id)
        refund = self._create_payslip(
            self.employee, date(2026, 3, 1), date(2026, 3, 31)
        )
        self._sql_update("hr_payslip", {"credit_note": True, **period}, refund.id)
        # Rol corregido tras un reembolso: el original queda con refunded_id.
        self._sql_update("hr_payslip", {"refunded_id": refund.id}, jan.id)
        corrected = self._create_payslip(
            self.employee, date(2026, 4, 1), date(2026, 4, 30)
        )
        self._sql_update("hr_payslip", period, corrected.id)
        # Otra estructura en el mismo periodo: permitido.
        other_structure = self.env["hr.payroll.structure"].create(
            {
                "name": "Estructura de prueba – décimos",
                "code": "TEST_D",
                "parent_id": False,
            }
        )
        extra = self._create_payslip(self.employee, date(2026, 5, 1), date(2026, 5, 31))
        self._sql_update(
            "hr_payslip", {"struct_id": other_structure.id, **period}, extra.id
        )

    # ------------------------------------------------------------------
    # Permisos
    # ------------------------------------------------------------------
    def _check_access(self, user, model, operation):
        return (
            self.env["ir.model.access"].with_user(user).check(model, operation, False)
        )

    def test_acl_matrix(self):
        models_crud_manager = (
            "erp.payroll.parameter",
            "erp.payroll.concept",
            "erp.payroll.employee.concept",
        )
        for model in models_crud_manager:
            self.assertTrue(self._check_access(self.payroll_user, model, "read"), model)
            for operation in ("write", "create", "unlink"):
                self.assertFalse(
                    self._check_access(self.payroll_user, model, operation),
                    f"{model} {operation}",
                )
                self.assertTrue(
                    self._check_access(self.payroll_manager, model, operation),
                    f"{model} {operation}",
                )
            self.assertFalse(self._check_access(self.plain_user, model, "read"), model)

    def test_payroll_user_cannot_edit_parameters(self):
        param = self.param.with_user(self.payroll_user)
        self.assertEqual(param.code, "TEST_PARAM")
        with self.assertRaises(AccessError):
            param.write({"value": 1.0})
        with self.assertRaises(AccessError):
            self.Parameter.with_user(self.payroll_user).create(
                {
                    "code": "TEST_OTRO",
                    "name": "Otro",
                    "value": 1.0,
                    "date_from": date(2026, 1, 1),
                    "norm": "Norma de prueba",
                }
            )
        self.param.with_user(self.payroll_manager).write({"value": 2.0})
        self.assertEqual(self.param.value, 2.0)

    def test_user_without_payroll_group_cannot_read(self):
        with self.assertRaises(AccessError):
            self.param.with_user(self.plain_user).read(["value"])
        with self.assertRaises(AccessError):
            self.concept_income.with_user(self.plain_user).read(["name"])
        with self.assertRaises(AccessError):
            self.assignment.with_user(self.plain_user).read(["amount"])

    def test_payslip_lines_read_only_for_payroll_user(self):
        model = "hr.payslip.line"
        self.assertTrue(self._check_access(self.payroll_user, model, "read"))
        for operation in ("write", "create", "unlink"):
            self.assertFalse(self._check_access(self.payroll_user, model, operation))
            self.assertTrue(self._check_access(self.payroll_manager, model, operation))
        contract_type = self.env["hr.contract.type"].create(
            {"name": "Indefinido (prueba)"}
        )
        contract = self.env["hr.contract"].create(
            {
                "name": "Contrato de prueba",
                "employee_id": self.employee.id,
                "wage": 1000.0,
                "date_start": date(2026, 1, 1),
                "contract_type_id": contract_type.id,
                "struct_id": self.structure.id,
            }
        )
        payslip = self._create_payslip(
            self.employee, date(2026, 1, 1), date(2026, 1, 31)
        )
        rule = self.env.ref("erp_payroll_ec.rule_ec_basic")
        line = self.env["hr.payslip.line"].create(
            {
                "slip_id": payslip.id,
                "salary_rule_id": rule.id,
                "employee_id": self.employee.id,
                "contract_id": contract.id,
                "name": rule.name,
                "code": rule.code,
                "category_id": rule.category_id.id,
                "amount": 1000.0,
            }
        )
        user_line = line.with_user(self.payroll_user)
        self.assertEqual(user_line.amount, 1000.0)
        with self.assertRaises(AccessError):
            user_line.write({"amount": 1.0})
        with self.assertRaises(AccessError):
            user_line.unlink()

    def test_multicompany_concepts_hidden_for_other_company(self):
        other_company = self.env["res.company"].create({"name": "Empresa Ñ 2 (prueba)"})
        concept = self.Concept.create(
            {
                "name": "Bono otra empresa",
                "code": "TEST_BONO_OTRA",
                "concept_type": "income",
                "company_id": other_company.id,
            }
        )
        visible = self.Concept.with_user(self.payroll_manager).search(
            [("code", "=", "TEST_BONO_OTRA")]
        )
        self.assertFalse(visible)
        self.assertTrue(concept.exists())
