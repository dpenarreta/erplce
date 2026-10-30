"""Campos de apoyo a las vistas de nómina (US-008, CA-6 / CA-7): conceptos
del empleado, régimen de décimo cuarto en el rol, concepto de las entradas
variables y limpieza al cambiar el tipo de concepto. Valores ficticios."""

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import new_test_user, tagged

from .common import PayrollEcCase


@tagged("post_install", "-at_install")
class TestPayrollEcUiFields(PayrollEcCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls._employee("Begoña Ñúñez Peña")
        cls.contract = cls._contract(cls.employee)
        cls.employee_sierra = cls._employee("Íñigo Cañar", establishment=cls.est_sierra)
        cls._contract(cls.employee_sierra)
        cls.hr_user = new_test_user(
            cls.env,
            login="rrhh_sin_nomina_us008",
            groups="base.group_user,hr.group_hr_user",
        )
        cls.internal = new_test_user(
            cls.env, login="interno_sin_nomina_us008", groups="base.group_user"
        )
        # Con su propia ficha, como un empleado real (sin ella el directorio
        # evalúa dominios child_of con un empleado vacío).
        cls._employee("Interno Ñ", user_id=cls.internal.id)

    def _input(self, payslip, **vals):
        return self.env["hr.payslip.input"].create(
            {"payslip_id": payslip.id, "contract_id": self.contract.id, **vals}
        )

    # ------------------------------------------------------------------
    # hr.employee.erp_payroll_concept_ids
    # ------------------------------------------------------------------
    def test_employee_concepts_visible_to_payroll(self):
        bonus = self._concept("TEST_BONO_FIJO", name="Bono de función – Ñandú")
        assignment = self._assign(self.employee, bonus, 120.0)
        field = self.env["hr.employee"]._fields["erp_payroll_concept_ids"]
        self.assertEqual(field.groups, "payroll.group_payroll_user")
        self.assertNotIn(
            "erp_payroll_concept_ids", self.env["hr.employee.public"]._fields
        )
        for user in (self.payroll_user, self.payroll_manager):
            with self.subTest(user=user.login):
                employee = self.employee.with_user(user)
                self.assertEqual(employee.erp_payroll_concept_ids, assignment)
                self.assertIn("erp_payroll_concept_ids", employee.fields_get())
        # El responsable crea asignaciones desde la ficha del empleado.
        other = self._concept("TEST_MOVILIZACION")
        self.employee.with_user(self.payroll_manager).write(
            {
                "erp_payroll_concept_ids": [
                    (
                        0,
                        0,
                        {
                            "concept_id": other.id,
                            "amount": 45.5,
                            "date_from": "2026-01-01",
                        },
                    )
                ]
            }
        )
        self.assertEqual(len(self.employee.erp_payroll_concept_ids), 2)
        # El usuario de nómina solo lee las asignaciones.
        with self.assertRaises(AccessError):
            self.employee.with_user(self.payroll_user).write(
                {"erp_payroll_concept_ids": [(2, assignment.id)]}
            )

    def test_employee_concepts_hidden_without_payroll(self):
        """RRHH sin nómina: lee la ficha completa sin AccessError (el campo no
        aparece) y no puede leer el campo explícitamente."""
        self._assign(self.employee, self._concept("TEST_BONO"), 100.0)
        employee = self.employee.with_user(self.hr_user)
        self.assertNotIn("erp_payroll_concept_ids", employee.fields_get())
        # Campos que carga el cliente web para la ficha y la lista del empleado.
        result = employee.get_views([(False, "form"), (False, "list")])
        form_fields = list(result["models"]["hr.employee"]["fields"])
        self.assertNotIn("erp_payroll_concept_ids", form_fields)
        values = employee.read(form_fields)[0]
        self.assertEqual(values["name"], "Begoña Ñúñez Peña")
        with self.assertRaises(AccessError):
            employee.read(["erp_payroll_concept_ids"])

    def test_public_profile_internal_user(self):
        """Usuario interno sin nómina ni RRHH: el directorio y la lectura de
        campos públicos del empleado siguen funcionando (prefetch)."""
        self._assign(self.employee, self._concept("TEST_BONO"), 100.0)
        public = self.env["hr.employee.public"].with_user(self.internal)
        rows = public.search_read([("id", "=", self.employee.id)])
        self.assertEqual(rows[0]["name"], "Begoña Ñúñez Peña")
        self.assertEqual(public.browse(self.employee.id).name, "Begoña Ñúñez Peña")
        self.assertEqual(
            self.employee.with_user(self.internal).name, "Begoña Ñúñez Peña"
        )
        self.assertTrue(
            public.get_views([(False, "form"), (False, "kanban")])["views"]["form"]
        )

    # ------------------------------------------------------------------
    # hr.payslip.erp_decimo_cuarto_regime
    # ------------------------------------------------------------------
    def test_payslip_fourteenth_regime(self):
        field = self.env["hr.payslip"]._fields["erp_decimo_cuarto_regime"]
        self.assertFalse(field.store)
        self.assertTrue(field.compute_sudo)
        self.assertEqual(field.groups, "payroll.group_payroll_user")
        costa = self._payslip(self.employee).with_user(self.payroll_user)
        sierra = self._payslip(self.employee_sierra).with_user(self.payroll_user)
        self.assertEqual(costa.erp_decimo_cuarto_regime, "costa_galapagos")
        self.assertEqual(sierra.erp_decimo_cuarto_regime, "sierra_amazonia")
        # Refleja el establecimiento actual del empleado.
        self.employee.erp_establishment_id = self.est_sierra
        self.env.invalidate_all()
        self.assertEqual(costa.erp_decimo_cuarto_regime, "sierra_amazonia")
        # Sin establecimiento: vacío, sin error.
        self.employee.erp_establishment_id = False
        self.env.invalidate_all()
        self.assertFalse(costa.erp_decimo_cuarto_regime)

    def test_payslip_fourteenth_regime_without_hr_group(self):
        """Un usuario de nómina al que se le quitara RRHH (hoy lo implica el
        grupo de nómina) ve el régimen en el rol sin AccessError, aunque no
        pueda leer el campo del empleado."""
        payslip = self._payslip(self.employee)
        user = self.payroll_user
        hr_group = self.env.ref("hr.group_hr_user")
        self.assertTrue(user.has_group("hr.group_hr_user"))
        # El ORM vuelve a añadir los grupos implicados: se quita el vínculo en
        # la tabla para simular el caso.
        self.env.cr.execute(
            "DELETE FROM res_groups_users_rel WHERE uid = %s AND gid = %s",
            (user.id, hr_group.id),
        )
        self.env.invalidate_all()
        self.env.registry.clear_cache()
        self.assertFalse(user.has_group("hr.group_hr_user"))
        self.assertTrue(user.has_group("payroll.group_payroll_user"))
        with self.assertRaises(AccessError):
            self.employee.with_user(user).read(["erp_decimo_cuarto_regime"])
        self.assertEqual(
            payslip.with_user(user).erp_decimo_cuarto_regime, "costa_galapagos"
        )
        self.assertEqual(
            payslip.with_user(user).read(["erp_decimo_cuarto_regime"])[0][
                "erp_decimo_cuarto_regime"
            ],
            "costa_galapagos",
        )

    def test_payslip_fourteenth_regime_searchable(self):
        costa = self._payslip(self.employee)
        sierra = self._payslip(self.employee_sierra)
        found = (
            self.env["hr.payslip"]
            .with_user(self.payroll_user)
            .search([("erp_decimo_cuarto_regime", "=", "sierra_amazonia")])
        )
        self.assertIn(sierra, found)
        self.assertNotIn(costa, found)

    # ------------------------------------------------------------------
    # hr.payslip.input.erp_concept_id
    # ------------------------------------------------------------------
    def test_input_onchange_fills_code_and_name(self):
        concept = self._concept(
            "TEST_COMISION", amount_kind="variable", name="Comisión de ventas – año"
        )
        line = self.env["hr.payslip.input"].new({"name": "x", "code": "OTRO"})
        line.erp_concept_id = concept
        line._onchange_erp_concept_id()
        self.assertEqual(line.code, "TEST_COMISION")
        self.assertEqual(line.name, "Comisión de ventas – año")

    def test_input_create_from_concept(self):
        concept = self._concept(
            "TEST_COMISION", amount_kind="variable", name="Comisión de ventas"
        )
        payslip = self._payslip(self.employee)
        Input = self.env["hr.payslip.input"].with_user(self.payroll_user)
        line = Input.create(
            {
                "payslip_id": payslip.id,
                "contract_id": self.contract.id,
                "erp_concept_id": concept.id,
                "amount": 80.0,
            }
        )
        self.assertEqual(
            (line.code, line.name), ("TEST_COMISION", "Comisión de ventas")
        )
        self.assertEqual(line.company_id, self.company)
        # El código lo manda el concepto; la descripción propia se respeta.
        line2 = Input.create(
            {
                "payslip_id": payslip.id,
                "contract_id": self.contract.id,
                "erp_concept_id": concept.id,
                "code": "CUALQUIERA",
                "name": "Comisión – enero (Ñ)",
                "amount": 20.0,
            }
        )
        self.assertEqual(
            (line2.code, line2.name), ("TEST_COMISION", "Comisión – enero (Ñ)")
        )
        payslip.with_user(self.payroll_user).compute_sheet()
        self.assertAlmostEqual(self._lines(payslip)["INC_OTHER"], 100.0)

    def test_input_create_with_code_links_variable_concept(self):
        variable = self._concept("TEST_VAR", amount_kind="variable")
        self._concept("TEST_FIJO")
        payslip = self._payslip(
            self.employee,
            inputs={"TEST_VAR": 10.0, "TEST_FIJO": 5.0, "TEST_NO_EXISTE": 1.0},
        )
        by_code = {line.code: line for line in payslip.input_line_ids}
        self.assertEqual(by_code["TEST_VAR"].erp_concept_id, variable)
        self.assertEqual(by_code["TEST_VAR"].name, "Entrada TEST_VAR")
        self.assertFalse(by_code["TEST_FIJO"].erp_concept_id)
        self.assertFalse(by_code["TEST_NO_EXISTE"].erp_concept_id)

    def test_input_create_with_code_ignores_archived_and_other_company(self):
        other_company = self.env["res.company"].create({"name": "Otra Ñ (prueba)"})
        self._concept("TEST_OTRA", amount_kind="variable", company_id=other_company.id)
        archived = self._concept("TEST_ARCH", amount_kind="variable")
        archived.active = False
        payslip = self._payslip(
            self.employee, inputs={"TEST_OTRA": 1.0, "TEST_ARCH": 2.0}
        )
        self.assertFalse(payslip.input_line_ids.erp_concept_id)

    def test_input_write_keeps_code_and_concept_consistent(self):
        bonus = self._concept("TEST_BONO_VAR", amount_kind="variable")
        mobility = self._concept(
            "TEST_MOVIL", amount_kind="variable", name="Movilización"
        )
        payslip = self._payslip(self.employee)
        line = self._input(
            payslip, name="Bono de enero", code="TEST_BONO_VAR", amount=10.0
        ).with_user(self.payroll_user)
        self.assertEqual(line.erp_concept_id, bonus)
        # Cambiar el concepto actualiza código y descripción.
        line.write({"erp_concept_id": mobility.id})
        self.assertEqual((line.code, line.name), ("TEST_MOVIL", "Movilización"))
        # Cambiar el código vuelve a enlazar (sin tocar la descripción)...
        line.write({"code": "TEST_BONO_VAR"})
        self.assertEqual(line.erp_concept_id, bonus)
        self.assertEqual(line.name, "Movilización")
        # ... o deja la entrada sin concepto si el código no es de uno variable.
        line.write({"code": "TEST_DESCONOCIDO"})
        self.assertFalse(line.erp_concept_id)
        # Quitar el concepto conserva el código.
        line.write({"erp_concept_id": mobility.id})
        line.write({"erp_concept_id": False})
        self.assertEqual(line.code, "TEST_MOVIL")

    def test_input_concept_constraints(self):
        fixed = self._concept("TEST_FIJO")
        other_company = self.env["res.company"].create({"name": "Otra Ñ (prueba)"})
        foreign = self._concept(
            "TEST_AJENO", amount_kind="variable", company_id=other_company.id
        )
        variable = self._concept("TEST_VAR", amount_kind="variable")
        payslip = self._payslip(self.employee)
        for concept, text in ((fixed, "es fijo"), (foreign, "otra empresa")):
            with self.subTest(concept=concept.code):
                with self.assertRaises(ValidationError) as error:
                    self._input(payslip, erp_concept_id=concept.id, amount=1.0)
                self.assertIn(text, str(error.exception))
        line = self._input(payslip, erp_concept_id=variable.id, amount=1.0)
        # El concepto manda: el código se corrige, no hay incoherencia.
        line.write({"code": "TEST_OTRO", "erp_concept_id": variable.id})
        self.assertEqual(line.code, "TEST_VAR")
        # Garantía final si el código se alterara por otra vía.
        self.env.cr.execute(
            "UPDATE hr_payslip_input SET code = 'TEST_OTRO' WHERE id = %s",
            (line.id,),
        )
        line.invalidate_recordset(["code"])
        with self.assertRaises(ValidationError) as error:
            line._check_erp_concept()
        self.assertIn("TEST_OTRO", str(error.exception))

    def test_input_concept_domain_check_company(self):
        field = self.env["hr.payslip.input"]._fields["erp_concept_id"]
        domain = field._description_domain(self.env)
        self.assertIn("amount_kind", domain)
        self.assertIn("company_id", domain)

    # ------------------------------------------------------------------
    # erp.payroll.concept: cambio de tipo
    # ------------------------------------------------------------------
    def test_concept_type_onchange_clears_fields(self):
        debit = self.accounts["expense_bonus"]
        credit = self.accounts["deduction_payable"]
        concept = self.Concept.new(
            {
                "name": "Bono Ñ",
                "code": "TEST_BONO",
                "concept_type": "income",
                "iess_base": True,
                "thirteenth_base": True,
                "account_debit_id": debit.id,
            }
        )
        concept.concept_type = "deduction"
        concept._onchange_concept_type()
        self.assertFalse(concept.iess_base)
        self.assertFalse(concept.thirteenth_base)
        self.assertFalse(concept.account_debit_id)
        concept.account_credit_id = credit
        concept.concept_type = "income"
        concept._onchange_concept_type()
        self.assertFalse(concept.account_credit_id)
        # Un ingreso conserva sus bases y su cuenta deudora.
        concept.update({"iess_base": True, "account_debit_id": debit.id})
        concept._onchange_concept_type()
        self.assertTrue(concept.iess_base)
        self.assertEqual(concept.account_debit_id, debit)
