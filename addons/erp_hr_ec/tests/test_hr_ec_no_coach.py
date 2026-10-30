"""Opción "Sin instructor" del empleado (US-010, CA-1 a CA-4)."""

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestHrEcNoCoach(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Employee = cls.env["hr.employee"]
        cls.manager = cls.Employee.create({"name": "Begoña Núñez Ordóñez"})
        cls.manager_2 = cls.Employee.create({"name": "Íñigo Cárdenas Peña"})
        cls.coach = cls.Employee.create({"name": "Raúl Muñoz Íñiguez"})
        cls.employee = cls.Employee.create(
            {"name": "José Peñafiel Añazco", "coach_id": cls.coach.id}
        )

    def _count_no_coach_employees(self):
        return self.Employee.with_context(active_test=False).search_count(
            [("name", "ilike", "Sin instructor")]
        )

    # ------------------------------------------------------------------
    # CA-1: marcar "Sin instructor"
    # ------------------------------------------------------------------
    def test_mark_clears_coach_and_persists(self):
        self.employee.write({"erp_no_coach": True})
        self.employee.invalidate_recordset()
        self.assertTrue(self.employee.erp_no_coach)
        self.assertFalse(self.employee.coach_id)

    def test_create_marked_with_manager_keeps_no_coach(self):
        employee = self.Employee.create(
            {
                "name": "Sofía Ñáñez",
                "parent_id": self.manager.id,
                "erp_no_coach": True,
            }
        )
        self.assertTrue(employee.erp_no_coach)
        self.assertFalse(employee.coach_id)
        self.assertEqual(employee.parent_id, self.manager)

    def test_no_fake_employee_created(self):
        before = self._count_no_coach_employees()
        self.employee.write({"erp_no_coach": True})
        self.Employee.create({"name": "Matías Úbeda", "erp_no_coach": True})
        self.assertEqual(self._count_no_coach_employees(), before)
        self.assertEqual(before, 0)

    def test_caller_vals_not_mutated(self):
        vals = {"erp_no_coach": True}
        self.employee.write(vals)
        self.assertEqual(vals, {"erp_no_coach": True})
        vals_list = [{"name": "Lucía Ibáñez", "coach_id": self.coach.id}]
        self.Employee.create(vals_list)
        self.assertEqual(
            vals_list, [{"name": "Lucía Ibáñez", "coach_id": self.coach.id}]
        )

    # ------------------------------------------------------------------
    # CA-2: volver a asignar
    # ------------------------------------------------------------------
    def test_assign_coach_removes_mark(self):
        self.employee.write({"erp_no_coach": True})
        self.employee.write({"coach_id": self.coach.id})
        self.assertFalse(self.employee.erp_no_coach)
        self.assertEqual(self.employee.coach_id, self.coach)

    def test_clear_coach_unmarked_stays_unassigned(self):
        self.employee.write({"erp_no_coach": True})
        # Lo que envía el formulario al borrar el campo: instructor vacío y
        # marca desactivada.
        self.employee.write({"coach_id": False, "erp_no_coach": False})
        self.assertFalse(self.employee.erp_no_coach)
        self.assertFalse(self.employee.coach_id)

    def test_unmark_does_not_fill_with_manager(self):
        employee = self.Employee.create(
            {
                "name": "Andrés Zúñiga",
                "parent_id": self.manager.id,
                "erp_no_coach": True,
            }
        )
        employee.write({"erp_no_coach": False})
        self.assertFalse(employee.coach_id)

    # ------------------------------------------------------------------
    # CA-3: relleno automático Gerente -> Instructor
    # ------------------------------------------------------------------
    def test_manager_change_with_mark_does_not_fill(self):
        self.employee.write({"erp_no_coach": True})
        self.employee.write({"parent_id": self.manager.id})
        self.assertFalse(self.employee.coach_id)
        self.employee.write({"parent_id": self.manager_2.id})
        self.assertFalse(self.employee.coach_id)
        self.assertTrue(self.employee.erp_no_coach)

    def test_manager_change_without_mark_standard(self):
        employee = self.Employee.create({"name": "Martín Vélez"})
        employee.write({"parent_id": self.manager.id})
        self.assertEqual(employee.coach_id, self.manager)
        # Un instructor distinto del Gerente se conserva.
        employee.write({"coach_id": self.coach.id})
        employee.write({"parent_id": self.manager_2.id})
        self.assertEqual(employee.coach_id, self.coach)

    def test_mark_and_manager_same_write(self):
        employee = self.Employee.create({"name": "Nicolás Jaramillo"})
        employee.write({"parent_id": self.manager.id, "erp_no_coach": True})
        self.assertFalse(employee.coach_id)
        self.assertTrue(employee.erp_no_coach)

    def test_unmark_and_manager_same_write_standard(self):
        employee = self.Employee.create({"name": "Inés Benítez", "erp_no_coach": True})
        employee.write({"parent_id": self.manager.id, "erp_no_coach": False})
        self.assertEqual(employee.coach_id, self.manager)

    def test_manager_change_mixed_batch(self):
        marked = self.Employee.create({"name": "Ramón Cañar", "erp_no_coach": True})
        unmarked = self.Employee.create({"name": "Elena Guzmán"})
        (marked | unmarked).write({"parent_id": self.manager.id})
        self.assertFalse(marked.coach_id)
        self.assertEqual(unmarked.coach_id, self.manager)

    def _onchange(self, employee, values, changed):
        """Simula el cliente web: llama a ``onchange`` con los valores del
        formulario y devuelve los valores resultantes (los no devueltos por
        el servidor quedan como estaban)."""
        spec = {"erp_no_coach": {}, "coach_id": {}, "parent_id": {}}
        current = {
            "erp_no_coach": employee.erp_no_coach,
            "coach_id": employee.coach_id.id,
            "parent_id": employee.parent_id.id,
        }
        current.update(values)
        result = employee.onchange(current, [changed], spec)["value"]
        current.update(result)
        return current

    def test_form_onchange_mark_clears_coach(self):
        employee = self.Employee.create(
            {"name": "Tomás Ávila", "parent_id": self.manager.id}
        )
        self.assertEqual(employee.coach_id, self.manager)
        values = self._onchange(employee, {"erp_no_coach": True}, "erp_no_coach")
        self.assertFalse(values["coach_id"])

    def test_form_onchange_manager_with_mark(self):
        employee = self.Employee.create(
            {
                "name": "Ximena Ordóñez",
                "parent_id": self.manager.id,
                "erp_no_coach": True,
            }
        )
        values = self._onchange(employee, {"parent_id": self.manager_2.id}, "parent_id")
        self.assertFalse(values["coach_id"])
        self.assertTrue(values["erp_no_coach"])

    def test_form_onchange_manager_without_mark_standard(self):
        employee = self.Employee.create(
            {"name": "Joaquín Sáenz", "parent_id": self.manager.id}
        )
        values = self._onchange(employee, {"parent_id": self.manager_2.id}, "parent_id")
        self.assertEqual(values["coach_id"], self.manager_2.id)

    def test_form_onchange_coach_removes_mark(self):
        self.employee.write({"erp_no_coach": True})
        values = self._onchange(self.employee, {"coach_id": self.coach.id}, "coach_id")
        self.assertFalse(values["erp_no_coach"])
        self.assertEqual(values["coach_id"], self.coach.id)

    # ------------------------------------------------------------------
    # CA-4: coherencia en servidor (API / importación)
    # ------------------------------------------------------------------
    def test_both_in_write_coach_wins(self):
        self.employee.write({"erp_no_coach": True})
        self.employee.write({"erp_no_coach": True, "coach_id": self.manager.id})
        self.assertEqual(self.employee.coach_id, self.manager)
        self.assertFalse(self.employee.erp_no_coach)

    def test_both_in_create_coach_wins_batch(self):
        employees = self.Employee.create(
            [
                {
                    "name": "Paúl Ortúzar",
                    "erp_no_coach": True,
                    "coach_id": self.coach.id,
                },
                {
                    "name": "Mónica Saá",
                    "erp_no_coach": True,
                    "parent_id": self.manager.id,
                },
                {"name": "Germán Alarcón", "parent_id": self.manager.id},
            ]
        )
        both, marked, standard = employees
        self.assertEqual(both.coach_id, self.coach)
        self.assertFalse(both.erp_no_coach)
        self.assertFalse(marked.coach_id)
        self.assertTrue(marked.erp_no_coach)
        self.assertEqual(standard.coach_id, self.manager)
        self.assertFalse(standard.erp_no_coach)

    def test_batch_write_coach_unmarks_all(self):
        marked = self.Employee.create({"name": "Rocío Páez", "erp_no_coach": True})
        employees = marked | self.employee
        employees.write({"erp_no_coach": True})
        self.assertFalse(employees.coach_id)
        employees.write({"coach_id": self.coach.id})
        self.assertEqual(employees.mapped("coach_id"), self.coach)
        self.assertFalse(any(employees.mapped("erp_no_coach")))

    def test_never_both_after_writes(self):
        self.employee.write({"coach_id": self.coach.id, "erp_no_coach": True})
        self.employee.write({"parent_id": self.manager.id})
        self.employee.write({"erp_no_coach": True, "parent_id": self.manager_2.id})
        all_employees = self.Employee.search([("erp_no_coach", "=", True)])
        self.assertFalse(all_employees.filtered("coach_id"))

    # ------------------------------------------------------------------
    # Perfil público
    # ------------------------------------------------------------------
    def test_public_profile_reads_and_filters(self):
        """Un usuario sin RRHH lee el campo (sin AccessError por prefetch) y
        puede filtrar el directorio por él."""
        self.employee.write({"erp_no_coach": True})
        user = new_test_user(
            self.env, login="erp_no_coach_publico", groups="base.group_user"
        )
        employee = self.employee.with_user(user)
        self.assertTrue(employee.erp_no_coach)
        self.assertFalse(employee.coach_id)
        public = self.env["hr.employee.public"].with_user(user)
        self.assertIn(
            self.employee.id, public.search([("erp_no_coach", "=", True)]).ids
        )


@tagged("post_install", "-at_install")
class TestHrEcParentLabel(TransactionCase):
    """Etiqueta "Jefe inmediato" de parent_id (US-010, CA-7)."""

    LANG = "es_EC"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang(cls.LANG)

    def _field_info(self, model, field_name, lang):
        return (
            self.env[model]
            .with_context(lang=lang)
            .fields_get([field_name], ["string", "help"])[field_name]
        )

    def _assert_parent_label(self):
        for model in ("hr.employee", "hr.employee.public"):
            for lang in (self.LANG, "en_US"):
                info = self._field_info(model, "parent_id", lang)
                self.assertEqual(info["string"], "Jefe inmediato", (model, lang))
                self.assertEqual(
                    info["help"],
                    "Persona a la que reporta directamente el empleado; define "
                    "la línea de supervisión y el organigrama.",
                    (model, lang),
                )

    def test_parent_label(self):
        self._assert_parent_label()

    def test_parent_label_survives_hr_translation_reload(self):
        """Recargar las traducciones de hr (actualización de idioma) no
        devuelve la etiqueta "Gerente": las de erp_hr_ec se cargan después."""
        self.env["ir.module.module"]._load_module_terms(
            ["hr", "erp_hr_ec"], [self.LANG], overwrite=True
        )
        self.env.registry.clear_cache()
        self._assert_parent_label()

    def test_department_manager_unchanged(self):
        self.assertEqual(
            self._field_info("hr.department", "manager_id", "en_US")["string"],
            "Manager",
        )
        self.assertEqual(
            self._field_info("hr.department", "manager_id", self.LANG)[
                "string"
            ].strip(),
            "Gerente",
        )
