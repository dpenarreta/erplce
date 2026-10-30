"""Vistas, menús y formularios de erp_payroll_ec (US-008, DEV-4).

La imagen de Odoo no trae Chrome: no hay tours. Se comprueba que las vistas
nuevas y heredadas cargan (get_views) para el responsable de nómina, el
usuario de nómina y un usuario de RRHH sin nómina, qué botones y menús ve cada
uno, y se usan formularios (odoo.tests.Form) como lo haría el cliente web.
"""

from datetime import date

from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import Form, TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

from .common import PayrollEcCase

PAYROLL_MODELS = (
    "erp.payroll.parameter",
    "erp.payroll.concept",
    "erp.payroll.employee.concept",
)


def _arch(model, view_type):
    result = model.get_views([(False, view_type)])
    return etree.fromstring(result["views"][view_type]["arch"])


def _denied(arch, operation):
    """``True`` si el cliente web deshabilita ``operation`` en la vista (Odoo
    lo marca según la ACL del usuario)."""
    return arch.get(operation) in ("false", "False", "0")


def _buttons(arch, name):
    return arch.xpath(f"//header/button[@name='{name}']")


@tagged("post_install", "-at_install")
class TestPayrollEcViews(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="responsable_nomina_vistas",
            groups="base.group_user,payroll.group_payroll_manager",
        )
        cls.user = new_test_user(
            cls.env,
            login="usuario_nomina_vistas",
            groups="base.group_user,payroll.group_payroll_user",
        )
        cls.hr_user = new_test_user(
            cls.env,
            login="rrhh_sin_nomina_vistas",
            groups="base.group_user,hr.group_hr_user",
        )
        cls.internal = new_test_user(
            cls.env, login="interno_sin_nomina_vistas", groups="base.group_user"
        )
        cls.employee = cls.env["hr.employee"].create({"name": "Empleada Vistas"})
        cls.expense_account = cls.env["account.account"].create(
            {
                "code": "5999901",
                "name": "Bono propio (prueba vistas)",
                "account_type": "expense",
            }
        )
        cls.liability_account = cls.env["account.account"].create(
            {
                "code": "2999901",
                "name": "Descuento propio por pagar (prueba vistas)",
                "account_type": "liability_current",
            }
        )

    # ------------------------------------------------------------------
    # Carga de vistas y solo lectura por ACL
    # ------------------------------------------------------------------
    def test_payroll_views_load_and_access(self):
        for model_name in PAYROLL_MODELS:
            for view_type in ("list", "form", "search"):
                with self.subTest(model=model_name, view=view_type):
                    manager_arch = _arch(
                        self.env[model_name].with_user(self.manager), view_type
                    )
                    user_arch = _arch(
                        self.env[model_name].with_user(self.user), view_type
                    )
                    if view_type == "search":
                        continue
                    # El responsable edita; el usuario de nómina solo lee.
                    for operation in ("edit", "create", "delete"):
                        self.assertFalse(_denied(manager_arch, operation))
                        self.assertTrue(_denied(user_arch, operation))

    def test_parameter_views_content(self):
        Parameter = self.env["erp.payroll.parameter"].with_user(self.manager)
        list_arch = _arch(Parameter, "list")
        state = list_arch.xpath("//field[@name='state']")[0]
        self.assertEqual(state.get("widget"), "badge")
        form_arch = _arch(Parameter, "form")
        # Valor con 2 decimales en lista y formulario.
        for arch in (list_arch, form_arch):
            value = arch.xpath("//field[@name='value']")
            self.assertEqual(len(value), 1)
            self.assertEqual(safe_eval(value[0].get("digits")), [16, 2])
        self.assertTrue(form_arch.xpath("//chatter"))
        search_arch = _arch(Parameter, "search")
        self.assertTrue(search_arch.xpath("//filter[@name='to_validate']"))
        self.assertTrue(search_arch.xpath("//filter[@name='group_by_code']"))
        action = self.env.ref("erp_payroll_ec.erp_payroll_parameter_action")
        self.assertIn("A validar", action.help)
        # Los datos del módulo se ven en la acción y quedan «a validar».
        records = Parameter.search([])
        self.assertTrue(records)
        self.assertEqual(set(records.mapped("state")), {"to_validate"})

    def test_actions_have_empty_state_help(self):
        for xmlid in (
            "erp_payroll_ec.erp_payroll_parameter_action",
            "erp_payroll_ec.erp_payroll_concept_action",
            "erp_payroll_ec.erp_payroll_employee_concept_action",
        ):
            with self.subTest(action=xmlid):
                self.assertIn("o_view_nocontent", self.env.ref(xmlid).help)
        concept_help = self.env.ref("erp_payroll_ec.erp_payroll_concept_action").help
        self.assertIn("vacío", concept_help)

    # ------------------------------------------------------------------
    # Rol de pagos
    # ------------------------------------------------------------------
    def test_payslip_form_buttons_by_group(self):
        manager_arch = _arch(self.env["hr.payslip"].with_user(self.manager), "form")
        user_arch = _arch(self.env["hr.payslip"].with_user(self.user), "form")

        self.assertEqual(len(_buttons(manager_arch, "action_payslip_done")), 1)
        self.assertEqual(len(_buttons(manager_arch, "refund_sheet")), 1)
        self.assertEqual(len(_buttons(manager_arch, "action_payslip_cancel")), 2)
        # Usuario de nómina: calcula y anula borradores, no confirma, no
        # reembolsa ni anula un rol confirmado.
        self.assertFalse(_buttons(user_arch, "action_payslip_done"))
        self.assertFalse(_buttons(user_arch, "refund_sheet"))
        cancel = _buttons(user_arch, "action_payslip_cancel")
        self.assertEqual(len(cancel), 1)
        self.assertNotIn("allow_cancel_payslips", cancel[0].get("invisible"))
        self.assertEqual(len(_buttons(user_arch, "compute_sheet")), 1)

        # Guarda del xpath por contenido de OCA: de los dos «Anular» del
        # responsable, el que lleva grupo y confirmación es exactamente el
        # que se ve en confirmado con el ajuste activo, y el del usuario es
        # el de borrador/verificar (nunca visible en confirmado).
        def visible(button, state, allow=True):
            ctx = {"state": state, "allow_cancel_payslips": allow}
            return not safe_eval(button.get("invisible"), ctx)

        done_cancel = [
            button
            for button in _buttons(manager_arch, "action_payslip_cancel")
            if button.get("confirm")
        ]
        self.assertEqual(len(done_cancel), 1)
        self.assertTrue(visible(done_cancel[0], "done"))
        self.assertFalse(visible(done_cancel[0], "done", allow=False))
        for state in ("draft", "verify", "cancel"):
            self.assertFalse(visible(done_cancel[0], state), state)
        self.assertFalse(visible(cancel[0], "done"))
        self.assertTrue(visible(cancel[0], "draft"))
        self.assertTrue(visible(cancel[0], "verify"))
        self.assertFalse(cancel[0].get("confirm"))
        # «Volver a borrador» oculto en confirmado para todos.
        for arch in (manager_arch, user_arch):
            draft = _buttons(arch, "action_payslip_draft")
            self.assertEqual(len(draft), 1)
            self.assertTrue(safe_eval(draft[0].get("invisible"), {"state": "done"}))
            self.assertFalse(safe_eval(draft[0].get("invisible"), {"state": "verify"}))

    def test_payslip_form_content(self):
        arch = _arch(self.env["hr.payslip"].with_user(self.user), "form")
        regime = arch.xpath(
            "//group[@name='right']/field[@name='erp_decimo_cuarto_regime']"
        )
        self.assertEqual(len(regime), 1)
        self.assertIn(regime[0].get("readonly"), ("1", "True", "true"))
        # Asiento contable: un solo campo en todo el formulario (el de
        # payroll_account, movido a la cabecera junto al régimen).
        moves = arch.xpath("//field[@name='move_id']")
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0].getparent().get("name"), "right")
        self.assertEqual(moves[0].get("string"), "Asiento contable")
        self.assertIn(moves[0].get("readonly"), ("1", "True", "true"))
        self.assertTrue(safe_eval(moves[0].get("invisible"), {"move_id": False}))
        self.assertFalse(safe_eval(moves[0].get("invisible"), {"move_id": 1}))
        self.assertFalse(
            arch.xpath("//page[@name='accounting']//field[@name='move_id']")
        )
        # Rol confirmado: entradas y días trabajados de solo lectura.
        for fname in ("input_line_ids", "worked_days_line_ids"):
            with self.subTest(field=fname):
                node = arch.xpath(f"//field[@name='{fname}']")[0]
                self.assertTrue(safe_eval(node.get("readonly"), {"state": "done"}))
                self.assertFalse(safe_eval(node.get("readonly"), {"state": "draft"}))
        lines = arch.xpath("//field[@name='dynamic_filtered_payslip_lines']")[0]
        self.assertIn(lines.get("readonly"), ("1", "True", "true"))

        # Entradas: concepto antes de la descripción, sin dominio de vista
        # (se usa el del campo, con la empresa) y sin crear conceptos.
        columns = [
            node.get("name")
            for node in arch.xpath("//field[@name='input_line_ids']/list/field")
        ]
        self.assertLess(columns.index("erp_concept_id"), columns.index("name"))
        for subview in ("list/", "form//"):
            with self.subTest(subview=subview):
                base = f"//field[@name='input_line_ids']/{subview}"
                concept = arch.xpath(f"{base}field[@name='erp_concept_id']")[0]
                self.assertIsNone(concept.get("domain"))
                self.assertIn("'no_create': True", concept.get("options"))
                code = arch.xpath(f"{base}field[@name='code']")[0]
                self.assertEqual(code.get("readonly"), "erp_concept_id")
                self.assertEqual(code.get("force_save"), "1")
        alert = arch.xpath("//div[@role='note']")
        self.assertEqual(len(alert), 1)
        help_text = " ".join("".join(alert[0].itertext()).split())
        self.assertIn("bonos y descuentos variables", help_text)
        self.assertIn("«Concepto»", help_text)
        self.assertNotIn("escriba el código", help_text)
        # US-017 (CA-9): aviso fijo (role="note") de como máximo 2 frases, sin
        # clases alert-* (Odoo las reserva a role alert/status).
        self.assertFalse(
            [c for c in alert[0].get("class").split() if c.startswith("alert-")]
        )
        self.assertLessEqual(help_text.rstrip(".").count(". "), 1)

    def test_payslip_regime_hidden_without_payroll(self):
        """El régimen de décimo cuarto (groups de nómina) no existe para quien
        no tiene nómina."""
        fields = self.env["hr.payslip"].with_user(self.hr_user).fields_get()
        self.assertNotIn("erp_decimo_cuarto_regime", fields)

    def test_payslip_line_views_load(self):
        for user in (self.manager, self.user):
            with self.subTest(user=user.login):
                arch = _arch(self.env["hr.payslip.line"].with_user(user), "list")
                name = arch.xpath("//field[@name='name']")[0]
                self.assertEqual(name.get("readonly"), "not allow_edit_payslip_lines")
        user_arch = _arch(self.env["hr.payslip.line"].with_user(self.user), "list")
        self.assertTrue(_denied(user_arch, "edit"))

    # ------------------------------------------------------------------
    # Ficha del empleado
    # ------------------------------------------------------------------
    def test_employee_form_concepts_tab(self):
        # US-017 (CA-5): sección de la pestaña «Nómina» de OCA, no pestaña.
        page_xpath = "//page[@name='payroll_settings']"
        section_xpath = f"{page_xpath}/separator[@name='erp_payroll_concepts']"
        field_xpath = f"{page_xpath}/field[@name='erp_payroll_concept_ids']"
        action = self.env.ref("erp_payroll_ec.erp_payroll_employee_concept_action")
        # Responsable: lista editable; usuario de nómina: la ACL deja la lista
        # embebida sin crear, editar ni borrar.
        for user, denied in ((self.manager, False), (self.user, True)):
            with self.subTest(user=user.login):
                arch = _arch(self.env["hr.employee"].with_user(user), "form")
                self.assertFalse(arch.xpath("//page[@name='erp_payroll_concepts']"))
                section = arch.xpath(section_xpath)
                self.assertEqual(section[0].get("string"), "Bonos y descuentos fijos")
                fields = arch.xpath(field_xpath)
                self.assertEqual(len(fields), 1)
                row = fields[0].xpath("./list")[0]
                for operation in ("create", "edit", "delete"):
                    self.assertEqual(_denied(row, operation), denied, operation)
                self.assertEqual(row.get("editable"), "bottom")
                self.assertEqual(row.get("decoration-muted"), "not active")
                # US-017 (CA-11): por fecha, sin interruptor «Activo».
                self.assertEqual(row.get("default_order"), "date_from desc")
                columns = [node.get("name") for node in row.xpath("./field")]
                for name in ("concept_id", "amount", "date_from", "date_to"):
                    self.assertIn(name, columns)
                active = row.xpath("./field[@name='active']")[0]
                self.assertEqual(active.get("column_invisible"), "1")
                self.assertIsNone(active.get("widget"))
                self.assertIn("note", columns)
                # Dominio del campo (fijos + empresa) sin conceptos archivados.
                concept = row.xpath("./field[@name='concept_id']")[0]
                self.assertIsNone(concept.get("domain"))
                self.assertEqual(
                    safe_eval(concept.get("context")), {"active_test": True}
                )
                # La pestaña sustituye al botón inteligente.
                self.assertFalse(arch.xpath(f"//button[@name='{action.id}']"))

        # RRHH sin nómina: ni pestaña ni campo.
        result = (
            self.env["hr.employee"].with_user(self.hr_user).get_views([(False, "form")])
        )
        arch = etree.fromstring(result["views"]["form"]["arch"])
        self.assertFalse(arch.xpath(page_xpath))
        self.assertFalse(arch.xpath(section_xpath))
        self.assertFalse(arch.xpath("//field[@name='erp_payroll_concept_ids']"))
        self.assertNotIn(
            "erp_payroll_concept_ids", result["models"]["hr.employee"]["fields"]
        )

    def test_employee_form_hr_user_without_payroll(self):
        """Un usuario de RRHH sin nómina abre y guarda la ficha de un empleado
        con asignaciones sin AccessError."""
        concept = self.env["erp.payroll.concept"].create(
            {"name": "Bono ficha RRHH", "code": "BONO_FICHA_RRHH"}
        )
        self.env["erp.payroll.employee.concept"].create(
            {
                "employee_id": self.employee.id,
                "concept_id": concept.id,
                "amount": 30.0,
                "date_from": date(2026, 1, 1),
            }
        )
        with Form(self.employee.with_user(self.hr_user)) as form:
            self.assertEqual(form.name, "Empleada Vistas")
            form.job_title = "Analista (prueba vistas)"
        self.assertEqual(self.employee.job_title, "Analista (prueba vistas)")

    # ------------------------------------------------------------------
    # Ajustes
    # ------------------------------------------------------------------
    def test_settings_allow_cancel_visible(self):
        arch = _arch(self.env["res.config.settings"], "form")
        setting = arch.xpath("//block[@id='allow_cancel_payslips']/setting")
        self.assertTrue(setting)
        self.assertEqual(setting[0].get("string"), "Permitir anular roles")
        self.assertTrue(setting[0].xpath(".//field[@name='allow_cancel_payslips']"))

    # ------------------------------------------------------------------
    # US-017: terminología, ficha del empleado, parámetros y listas
    # ------------------------------------------------------------------
    def test_payslip_form_terminology(self):
        """CA-9: etiquetas de Ecuador en el rol de pagos y título con
        etiqueta y ejemplo."""
        for lang in ("en_US", "es_EC"):
            arch = _arch(
                self.env["hr.payslip"].with_user(self.manager).with_context(lang=lang),
                "form",
            )
            with self.subTest(lang=lang):
                self.assertEqual(
                    _buttons(arch, "compute_sheet")[0].get("string"), "Calcular rol"
                )
                self.assertEqual(
                    {b.get("string") for b in _buttons(arch, "action_payslip_cancel")},
                    {"Anular rol"},
                )
                self.assertEqual(
                    _buttons(arch, "refund_sheet")[0].get("string"), "Rectificar rol"
                )
                stat = arch.xpath("//field[@name='payslip_count']")[0]
                self.assertEqual(stat.get("string"), "Líneas del rol")
                credit = arch.xpath("//field[@name='credit_note']")[0]
                self.assertEqual(credit.get("string"), "Rol rectificativo")
                page = arch.xpath("//page[@name='computation']")[0]
                self.assertEqual(page.get("string"), "Cálculo del rol")
                title = arch.xpath("//div[contains(@class, 'oe_title')]")[0]
                label = title.xpath("./label[@for='name']")[0]
                self.assertEqual(label.get("string"), "Descripción del rol")
                name = title.xpath("./h1/field[@name='name']")[0]
                self.assertTrue(name.get("placeholder", "").startswith("p. ej."))

    def _payroll_names(self):
        es = self.env(context={"lang": "es_EC"})
        return {
            xmlid: es.ref(xmlid).name
            for xmlid in (
                "payroll.hr_payslip_menu",
                "payroll.hr_payslip_run_menu",
                "payroll.hr_payslip_action",
                "payroll.hr_payslip_action_employee",
                "payroll.hr_payslip_run_action",
                "payroll.hr_payslip_line_action_computation_details",
            )
        }

    def test_payroll_menus_terminology(self):
        """CA-9: menús y acciones de OCA en español de Ecuador, también tras
        recargar las traducciones sobrescribiendo (patrón de erp_hr_ec)."""
        expected = {
            "payroll.hr_payslip_menu": "Roles de pagos",
            "payroll.hr_payslip_run_menu": "Lotes de roles",
            "payroll.hr_payslip_action": "Roles de pagos",
            "payroll.hr_payslip_action_employee": "Roles de pagos",
            "payroll.hr_payslip_run_action": "Lotes de roles",
            "payroll.hr_payslip_line_action_computation_details": "Líneas del rol",
        }
        self.assertEqual(self._payroll_names(), expected)
        help_html = (
            self.env(context={"lang": "es_EC"}).ref("payroll.hr_payslip_action").help
        )
        self.assertIn("o_view_nocontent", help_html)
        self.assertIn("Cree el primer rol de pagos", help_html)

        self._assert_payroll_labels()

        self.env["ir.module.module"]._load_module_terms(
            ["payroll", "payroll_account", "erp_payroll_ec"], ["es_EC"], overwrite=True
        )
        self.env.invalidate_all()
        self.assertEqual(self._payroll_names(), expected)
        # M-1 / QA-TECH: también los textos de estado vacío y las etiquetas de
        # campos de OCA sobreviven a la recarga con sobrescritura.
        self._assert_payroll_labels()

    def _assert_payroll_labels(self):
        es = self.env(context={"lang": "es_EC"})
        for xmlid, text in (
            ("payroll.hr_payslip_action", "Cree el primer rol de pagos"),
            ("payroll.hr_payslip_run_action", "Cree el primer lote de roles"),
        ):
            with self.subTest(help=xmlid):
                help_html = es.ref(xmlid).help
                self.assertIn("o_view_nocontent_smiling_face", help_html)
                self.assertIn(text, help_html)
        self.assertEqual(
            es.ref("payroll.action_hr_payslip_by_employees").name, "Generar roles"
        )
        for model, field, label in (
            ("hr.payslip", "credit_note", "Rol rectificativo"),
            ("hr.payslip.run", "credit_note", "Rol rectificativo"),
            ("hr.payslip", "name", "Descripción del rol"),
            ("hr.employee", "payroll_structure_id", "Estructura salarial por defecto"),
            (
                "res.config.settings",
                "payroll_structure_id",
                "Estructura salarial por defecto",
            ),
        ):
            with self.subTest(model=model, field=field):
                string = es[model].fields_get([field], ["string"])[field]["string"]
                self.assertEqual(string, label)

    def test_employee_form_at_most_six_tabs(self):
        """CA-5: perfil RRHH + nómina con como máximo 6 pestañas."""
        user = new_test_user(
            self.env,
            login="rrhh_nomina_vistas",
            groups="base.group_user,hr.group_hr_manager,payroll.group_payroll_manager",
        )
        arch = _arch(self.env["hr.employee"].with_user(user), "form")
        pages = [page.get("name") for page in arch.xpath("//notebook[1]/page")]
        self.assertLessEqual(len(pages), 6, pages)
        self.assertIn("erp_ecuador", pages)
        self.assertIn("payroll_settings", pages)
        for paragraph in arch.xpath(
            "//page[@name='payroll_settings']/p[contains(@class, 'text-muted')]"
        ):
            text = " ".join("".join(paragraph.itertext()).split())
            self.assertLessEqual(len(text), 130, text)

    def test_parameter_validation_is_deliberate(self):
        """CA-10 (parte de vistas): barra de estado no clicable, la acción abre
        sin agrupar y con «A validar», encabezados cortos."""
        Parameter = self.env["erp.payroll.parameter"].with_user(self.manager)
        form_arch = _arch(Parameter, "form")
        status = form_arch.xpath("//header/field[@name='state']")[0]
        self.assertEqual(status.get("widget"), "statusbar")
        self.assertNotIn("clickable", status.get("options") or "")
        validate = _buttons(form_arch, "action_validate")
        self.assertEqual(len(validate), 1)
        self.assertEqual(validate[0].get("string"), "Marcar como validado")
        self.assertIn("btn-primary", validate[0].get("class"))
        self.assertTrue(validate[0].get("confirm"))
        self.assertTrue(safe_eval(validate[0].get("invisible"), {"state": "validated"}))
        self.assertFalse(
            safe_eval(validate[0].get("invisible"), {"state": "to_validate"})
        )
        back = _buttons(form_arch, "action_set_to_validate")
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0].get("string"), "Devolver a revisión")
        # «Activo» como casilla, no como interruptor verde.
        active = form_arch.xpath("//sheet//field[@name='active']")[0]
        self.assertEqual(active.get("widget"), "boolean")
        self.assertFalse(safe_eval(back[0].get("invisible"), {"state": "validated"}))
        # El usuario de nómina no ve los botones (grupo del responsable).
        user_form = _arch(
            self.env["erp.payroll.parameter"].with_user(self.user), "form"
        )
        self.assertFalse(_buttons(user_form, "action_validate"))
        self.assertFalse(_buttons(user_form, "action_set_to_validate"))
        action = self.env.ref("erp_payroll_ec.erp_payroll_parameter_action")
        context = safe_eval(action.context)
        self.assertEqual(context, {"search_default_to_validate": 1})
        list_arch = _arch(Parameter, "list")
        self.assertEqual(
            list_arch.xpath("//field[@name='date_from']")[0].get("string"), "Desde"
        )

    def test_lists_short_headers(self):
        """CA-11: encabezados cortos y «Activo» opcional oculto."""
        concept_list = _arch(
            self.env["erp.payroll.concept"].with_user(self.manager), "list"
        )
        for name, label in (
            ("iess_base", "Base IESS"),
            ("thirteenth_base", "Base 13.º"),
        ):
            node = concept_list.xpath(f"//field[@name='{name}']")[0]
            self.assertEqual(node.get("string"), label)
        assigned_list = _arch(
            self.env["erp.payroll.employee.concept"].with_user(self.manager), "list"
        )
        for name, label in (("date_from", "Desde"), ("date_to", "Hasta")):
            node = assigned_list.xpath(f"//field[@name='{name}']")[0]
            self.assertEqual(node.get("string"), label)
        active = assigned_list.xpath("//field[@name='active']")[0]
        self.assertEqual(active.get("optional"), "hide")

    def test_payslip_and_batch_terminology(self):
        """M-1/M-2/M-4: lista de roles y lote de roles en español de Ecuador,
        un solo botón primario en el lote y encabezados que no se truncan."""
        for lang in ("en_US", "es_EC"):
            with self.subTest(lang=lang):
                slip_list = _arch(
                    self.env["hr.payslip"]
                    .with_user(self.manager)
                    .with_context(lang=lang),
                    "list",
                )
                for name, label in (
                    ("name", "Descripción del rol"),
                    ("date_from", "Desde"),
                    ("date_to", "Hasta"),
                ):
                    node = slip_list.xpath(f"//field[@name='{name}']")[0]
                    self.assertEqual(node.get("string"), label)

                Run = (
                    self.env["hr.payslip.run"]
                    .with_user(self.manager)
                    .with_context(lang=lang)
                )
                run_list = _arch(Run, "list")
                for name, label in (("date_start", "Desde"), ("date_end", "Hasta")):
                    node = run_list.xpath(f"//field[@name='{name}']")[0]
                    self.assertEqual(node.get("string"), label)
                credit = run_list.xpath("//field[@name='credit_note']")[0]
                self.assertEqual(credit.get("string"), "Rol rectificativo")
                self.assertEqual(credit.get("optional"), "hide")

                run_form = _arch(Run, "form")
                draft = [
                    button
                    for button in run_form.xpath("//header/button")
                    if not safe_eval(
                        button.get("invisible") or "False", {"state": "draft"}
                    )
                ]
                primary = [
                    button
                    for button in draft
                    if {"oe_highlight", "btn-primary"}
                    & set((button.get("class") or "").split())
                ]
                self.assertEqual(
                    [button.get("string") for button in primary], ["Generar roles"]
                )
                # El primario va primero.
                self.assertEqual(draft[0].get("string"), "Generar roles")
                close = run_form.xpath("//header/button[@name='close_payslip_run']")
                self.assertFalse(close[0].get("class"))
                separator = run_form.xpath(
                    "//field[@name='slip_ids']/preceding-sibling::separator[1]"
                )[0]
                self.assertEqual(separator.get("string"), "Roles de pagos")
                credit = run_form.xpath("//field[@name='credit_note']")[0]
                self.assertEqual(credit.get("string"), "Rol rectificativo")

    def test_employee_and_settings_terminology(self):
        """M-1: botón inteligente, grupo y campo de OCA en la ficha del
        empleado y en Ajustes."""
        user = new_test_user(
            self.env,
            login="rrhh_nomina_terminologia",
            groups="base.group_user,hr.group_hr_manager,payroll.group_payroll_manager",
        )
        for lang in ("en_US", "es_EC"):
            with self.subTest(lang=lang):
                arch = _arch(
                    self.env["hr.employee"].with_user(user).with_context(lang=lang),
                    "form",
                )
                stat = arch.xpath(
                    "//div[@name='button_box']//field[@name='payslip_count']"
                )[0]
                self.assertEqual(stat.get("string"), "Roles de pagos")
                structure = arch.xpath(
                    "//page[@name='payroll_settings']"
                    "//field[@name='payroll_structure_id']"
                )[0]
                self.assertEqual(
                    structure.get("string"), "Estructura salarial por defecto"
                )
                self.assertEqual(
                    structure.getparent().get("string"),
                    "Valores por defecto del contrato",
                )
                settings = _arch(
                    self.env["res.config.settings"].with_context(lang=lang), "form"
                )
                setting = settings.xpath("//block[@id='payroll_structure']/setting")[0]
                self.assertEqual(
                    setting.get("string"), "Estructura salarial por defecto"
                )

    def test_concept_assignments_without_active_toggle(self):
        """Lista de asignaciones del concepto coherente con la pestaña del
        empleado: «Activo» opcional y oculto, encabezados cortos."""
        arch = _arch(self.env["erp.payroll.concept"].with_user(self.manager), "form")
        assignments = arch.xpath("//field[@name='employee_concept_ids']/list")[0]
        active = assignments.xpath("./field[@name='active']")[0]
        self.assertEqual(active.get("optional"), "hide")
        self.assertNotEqual(active.get("widget"), "boolean_toggle")
        for name, label in (("date_from", "Desde"), ("date_to", "Hasta")):
            node = assignments.xpath(f"./field[@name='{name}']")[0]
            self.assertEqual(node.get("string"), label)

    # ------------------------------------------------------------------
    # Menús
    # ------------------------------------------------------------------
    def test_menus_by_group(self):
        Menu = self.env["ir.ui.menu"]
        root = self.env.ref("payroll.payroll_menu_root")
        parameter = self.env.ref("erp_payroll_ec.erp_payroll_ec_menu_parameter")
        concept = self.env.ref("erp_payroll_ec.erp_payroll_ec_menu_concept")
        assigned = self.env.ref("erp_payroll_ec.erp_payroll_ec_menu_employee_concept")
        self.assertEqual(
            parameter.parent_id, self.env.ref("payroll.payroll_menu_configuration")
        )
        self.assertEqual(concept.parent_id, parameter.parent_id)

        visible = Menu.with_user(self.manager)._visible_menu_ids()
        self.assertTrue({root.id, parameter.id, concept.id, assigned.id} <= visible)

        visible = Menu.with_user(self.user)._visible_menu_ids()
        self.assertIn(root.id, visible)
        self.assertIn(assigned.id, visible)
        self.assertNotIn(parameter.id, visible)
        self.assertNotIn(concept.id, visible)

        for user in (self.hr_user, self.internal):
            with self.subTest(user=user.login):
                menus = Menu.with_user(user).load_menus(debug=False)
                self.assertNotIn(root.id, menus)
                self.assertFalse(
                    {parameter.id, concept.id, assigned.id}
                    & Menu.with_user(user)._visible_menu_ids()
                )

    def test_users_without_payroll_cannot_read(self):
        for model_name in PAYROLL_MODELS:
            with self.subTest(model=model_name), self.assertRaises(AccessError):
                self.env[model_name].with_user(self.hr_user).check_access("read")

    # ------------------------------------------------------------------
    # Formularios
    # ------------------------------------------------------------------
    def test_concept_form_accounts_by_type(self):
        Concept = self.env["erp.payroll.concept"].with_user(self.manager)
        with Form(Concept) as form:
            form.name = "Bono de prueba vistas"
            form.code = "BONO_VISTAS"
            form.concept_type = "income"
            form.amount_kind = "fixed"
            form.iess_base = True
            form.account_debit_id = self.expense_account
            # Ingreso: la cuenta acreedora no se muestra.
            with self.assertRaises(AssertionError):
                form.account_credit_id = self.liability_account
        income = form.record
        self.assertEqual(income.account_debit_id, self.expense_account)

        with Form(Concept) as form:
            form.name = "Descuento de prueba vistas"
            form.code = "DESC_VISTAS"
            form.concept_type = "deduction"
            form.amount_kind = "variable"
            form.account_credit_id = self.liability_account
            # Descuento: ni cuenta deudora ni casillas de base.
            for fname, value in (
                ("account_debit_id", self.expense_account),
                ("iess_base", True),
            ):
                with self.assertRaises(AssertionError):
                    setattr(form, fname, value)
        deduction = form.record
        self.assertEqual(deduction.account_credit_id, self.liability_account)
        self.assertFalse(deduction.iess_base)

    def test_concept_form_type_change_clears_account(self):
        """Si un ingreso con cuenta deudora pasa a descuento, el onchange vacía
        la cuenta deudora (que el servidor no admite en un descuento)."""
        Concept = self.env["erp.payroll.concept"].with_user(self.manager)
        form = Form(Concept)
        form.name = "Concepto cambiante"
        form.code = "CAMBIANTE"
        form.concept_type = "income"
        form.account_debit_id = self.expense_account
        form.concept_type = "deduction"
        self.assertFalse(form.account_debit_id)
        form.account_credit_id = self.liability_account
        concept = form.save()
        self.assertEqual(concept.concept_type, "deduction")

    def test_employee_concept_form(self):
        concept = self.env["erp.payroll.concept"].create(
            {"name": "Bono fijo vistas", "code": "BONO_FIJO_V", "amount_kind": "fixed"}
        )
        Assignment = (
            self.env["erp.payroll.employee.concept"]
            .with_user(self.manager)
            .with_context(default_employee_id=self.employee.id)
        )
        with Form(Assignment) as form:
            self.assertEqual(form.employee_id, self.employee)
            form.concept_id = concept
            form.amount = 50.0
            form.date_from = date(2026, 1, 1)
            form.date_to = date(2026, 12, 31)
        assignment = form.record
        self.assertEqual(assignment.concept_type, "income")
        self.assertEqual(assignment.company_id, self.employee.company_id)

        # Lista editable de Nómina > Bonos y descuentos asignados filtrada por
        # empleado.
        with Form(
            Assignment, view="erp_payroll_ec.erp_payroll_employee_concept_view_list"
        ) as row:
            row.concept_id = concept
            row.amount = 60.0
            row.date_from = date(2027, 1, 1)
        self.assertEqual(row.record.employee_id, self.employee)

        # El usuario de nómina no crea asignaciones.
        with self.assertRaises(AccessError):
            self.env["erp.payroll.employee.concept"].with_user(self.user).check_access(
                "create"
            )


@tagged("post_install", "-at_install")
class TestPayrollEcViewForms(PayrollEcCase):
    """Formularios de la ficha del empleado y del rol como los usa el cliente
    web (US-008, CA-7): pestaña de bonos y descuentos fijos y entradas
    variables por concepto. Valores ficticios."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls._employee("Begoña Vistas Ñ")
        cls.contract = cls._contract(cls.employee)

    # ``odoo.tests.Form`` no sirve para la pestaña: la ficha de empleado
    # incluye subvistas de hr.employee que vuelven a procesar el campo en el
    # último nivel y el arnés lo trata como Many2many. Se reproduce lo que
    # hace el cliente web: web_read / web_save con la especificación de
    # columnas de la lista embebida de la vista.
    def _tab_spec(self, user):
        arch = _arch(self.env["hr.employee"].with_user(user), "form")
        columns = arch.xpath(
            "//page[@name='payroll_settings']"
            "/field[@name='erp_payroll_concept_ids']/list/field/@name"
        )
        return {"erp_payroll_concept_ids": {"fields": {name: {} for name in columns}}}

    def test_employee_tab_manager_adds_assignment(self):
        previous = self._assign(
            self.employee,
            self._concept("TEST_MOVIL_TAB"),
            10.0,
            date_from=date(2025, 1, 1),
        )
        bonus = self._concept("TEST_BONO_TAB", name="Bono de función – Ñ")
        employee = self.employee.with_user(self.payroll_manager)
        spec = self._tab_spec(self.payroll_manager)
        rows = employee.web_read(spec)[0]["erp_payroll_concept_ids"]
        self.assertEqual([row["id"] for row in rows], [previous.id])
        employee.web_save(
            {
                "erp_payroll_concept_ids": [
                    Command.update(previous.id, {"date_to": "2025-12-31"}),
                    Command.create(
                        {
                            "concept_id": bonus.id,
                            "amount": 75.5,
                            "date_from": "2026-01-01",
                            "active": True,
                        }
                    ),
                ]
            },
            spec,
        )
        assignments = self.employee.erp_payroll_concept_ids
        self.assertEqual(len(assignments), 2)
        new = assignments - previous
        self.assertEqual((new.concept_id, new.amount), (bonus, 75.5))
        self.assertEqual(new.concept_type, "income")
        self.assertEqual(new.company_id, self.employee.company_id)
        self.assertEqual(previous.date_to, date(2025, 12, 31))

    def test_employee_tab_payroll_user_reads_only(self):
        """El usuario de nómina ve las asignaciones en la pestaña (la lista le
        llega sin crear/editar/borrar) y el servidor rechaza cambios."""
        assignment = self._assign(self.employee, self._concept("TEST_BONO_RO"), 20.0)
        employee = self.employee.with_user(self.payroll_user)
        spec = self._tab_spec(self.payroll_user)
        rows = employee.web_read(spec)[0]["erp_payroll_concept_ids"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], 20.0)
        for command in (
            Command.create(
                {
                    "concept_id": self._concept("TEST_BONO_RO2").id,
                    "amount": 5.0,
                    "date_from": "2026-01-01",
                }
            ),
            Command.update(assignment.id, {"amount": 1.0}),
            Command.delete(assignment.id),
        ):
            with self.subTest(command=command[0]), self.assertRaises(AccessError):
                employee.web_save({"erp_payroll_concept_ids": [command]}, spec)
        self.assertEqual(assignment.amount, 20.0)

    def test_payslip_input_by_concept(self):
        concept = self._concept(
            "TEST_COMISION_V",
            amount_kind="variable",
            name="Comisión de ventas – Ñ",
        )
        payslip = self._payslip(self.employee)
        with Form(payslip.with_user(self.payroll_user)) as form:
            self.assertEqual(form.erp_decimo_cuarto_regime, "costa_galapagos")
            with form.input_line_ids.new() as line:
                line.erp_concept_id = concept
                self.assertEqual(line.code, "TEST_COMISION_V")
                self.assertEqual(line.name, "Comisión de ventas – Ñ")
                # Con concepto, el código no se edita.
                with self.assertRaises(AssertionError):
                    line.code = "OTRO"
                line.name = "Comisión de enero – Ñ"
                line.amount = 80.0
                line.contract_id = self.contract
            # Sin concepto, el código se escribe a mano (como en OCA).
            with form.input_line_ids.new() as line:
                line.name = "Entrada libre"
                line.code = "TEST_LIBRE"
                line.amount = 1.0
                line.contract_id = self.contract
        lines = {line.code: line for line in payslip.input_line_ids}
        self.assertEqual(lines["TEST_COMISION_V"].erp_concept_id, concept)
        self.assertEqual(lines["TEST_COMISION_V"].name, "Comisión de enero – Ñ")
        self.assertFalse(lines["TEST_LIBRE"].erp_concept_id)
        lines["TEST_LIBRE"].unlink()
        payslip.with_user(self.payroll_user).compute_sheet()
        self.assertAlmostEqual(self._lines(payslip)["INC_OTHER"], 80.0)
