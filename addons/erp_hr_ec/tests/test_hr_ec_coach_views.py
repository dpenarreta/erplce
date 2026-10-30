"""Vistas de US-010 (DEV-4): widget "Sin instructor", filtros y etiqueta
"Jefe inmediato".

La imagen de Odoo no trae Chrome: el widget OWL (erp_coach_many2one) se
comprueba por carga de vistas (get_views) y por su registro en el bundle de
assets; su comportamiento en el navegador se revisa a mano.
"""

from lxml import etree

from odoo.tests import Form, TransactionCase, new_test_user, tagged
from odoo.tools.misc import file_open

WIDGET = "erp_coach_many2one"
LANG = "es_EC"
PARENT_LABEL = "Jefe inmediato"
NO_COACH_DOMAIN = "[('erp_no_coach', '=', True)]"
UNASSIGNED_DOMAIN = "[('coach_id', '=', False), ('erp_no_coach', '=', False)]"


def _field_nodes(arch, name):
    return etree.fromstring(arch).xpath(f"//field[@name='{name}']")


def _filters(arch):
    return {node.get("name"): node for node in etree.fromstring(arch).iter("filter")}


@tagged("post_install", "-at_install")
class TestHrEcCoachViews(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang(LANG)
        cls.admin = new_test_user(
            cls.env,
            login="erp_coach_view_admin",
            groups="base.group_user,base.group_system,hr.group_hr_manager",
        )
        cls.hr_user = new_test_user(
            cls.env,
            login="erp_coach_view_hr",
            groups="base.group_user,hr.group_hr_user",
        )
        cls.internal = new_test_user(
            cls.env, login="erp_coach_view_internal", groups="base.group_user"
        )
        Employee = cls.env["hr.employee"]
        cls.manager = Employee.create({"name": "Begoña Núñez Ordóñez"})
        cls.coach = Employee.create({"name": "Raúl Muñoz Íñiguez"})
        cls.with_coach = Employee.create(
            {"name": "José Peñafiel Añazco", "coach_id": cls.coach.id}
        )
        cls.no_coach = Employee.create(
            {
                "name": "Ximena Ordóñez Cárdenas",
                "parent_id": cls.manager.id,
                "erp_no_coach": True,
            }
        )
        cls.unassigned = Employee.create({"name": "Íñigo Sáenz Peña"})

    # ------------------------------------------------------------------
    # Ayudantes
    # ------------------------------------------------------------------
    def _assert_coach_widget(self, arch, view_type):
        coach_nodes = _field_nodes(arch, "coach_id")
        self.assertTrue(coach_nodes, view_type)
        self.assertEqual(coach_nodes[0].get("widget"), WIDGET, view_type)
        flag_nodes = _field_nodes(arch, "erp_no_coach")
        self.assertTrue(flag_nodes, view_type)
        attr = "invisible" if view_type == "form" else "column_invisible"
        self.assertEqual(flag_nodes[0].get(attr), "1", view_type)

    def _assert_search(self, arch):
        filters = _filters(arch)
        self.assertEqual(filters["erp_no_coach"].get("domain"), NO_COACH_DOMAIN)
        self.assertEqual(filters["erp_no_coach"].get("string"), "Sin instructor")
        self.assertEqual(
            filters["erp_coach_unassigned"].get("domain"), UNASSIGNED_DOMAIN
        )
        self.assertEqual(
            filters["erp_coach_unassigned"].get("string"), "Instructor sin asignar"
        )
        # CA-7: textos fijos "Manager" del núcleo referidos a parent_id.
        self.assertEqual(filters["group_manager"].get("string"), PARENT_LABEL)
        self.assertEqual(_field_nodes(arch, "parent_id")[0].get("string"), PARENT_LABEL)

    def _employee_form_view(self):
        """Formulario real de empleado (con todas sus herencias) para
        odoo.tests.Form, con dos ajustes de prueba:

        - sin ``child_ids`` del organigrama (ver ``_employee_form_view`` en
          test_hr_ec_views.py);
        - ``erp_no_coach`` visible: Form no escribe campos invisibles, y en el
          navegador es el widget del Instructor quien lo escribe.
        """
        arch = self.env["hr.employee"].get_view(view_type="form")["arch"]
        xpaths = [
            '<xpath expr="//field[@name=\'erp_no_coach\']" position="attributes">'
            '<attribute name="invisible">0</attribute></xpath>'
        ]
        if _field_nodes(arch, "child_ids"):
            xpaths.append(
                '<xpath expr="//field[@name=\'child_ids\']" position="replace"/>'
            )
        return self.env["ir.ui.view"].create(
            {
                "name": "hr.employee.form.test.erp_hr_ec.coach",
                "model": "hr.employee",
                "inherit_id": self.env.ref("hr.view_employee_form").id,
                "mode": "primary",
                "priority": 1000,
                "arch": "<data>" + "".join(xpaths) + "</data>",
            }
        )

    # ------------------------------------------------------------------
    # Carga de vistas
    # ------------------------------------------------------------------
    def test_employee_views_hr_users(self):
        for user in (self.admin, self.hr_user):
            for lang in ("en_US", LANG):
                with self.subTest(user=user.login, lang=lang):
                    views = (
                        self.env["hr.employee"]
                        .with_user(user)
                        .with_context(lang=lang)
                        .get_views(
                            [(False, "list"), (False, "form"), (False, "search")]
                        )
                    )["views"]
                    self._assert_coach_widget(views["form"]["arch"], "form")
                    self._assert_coach_widget(views["list"]["arch"], "list")
                    self._assert_search(views["search"]["arch"])

    def test_public_views_internal_user(self):
        """Usuario interno sin RRHH: directorio (hr.employee.public)."""
        for lang in ("en_US", LANG):
            with self.subTest(lang=lang):
                views = (
                    self.env["hr.employee.public"]
                    .with_user(self.internal)
                    .with_context(lang=lang)
                    .get_views(
                        [
                            (False, "kanban"),
                            (False, "list"),
                            (False, "form"),
                            (False, "search"),
                        ]
                    )
                )["views"]
                self._assert_coach_widget(views["form"]["arch"], "form")
                self._assert_coach_widget(views["list"]["arch"], "list")
                self._assert_search(views["search"]["arch"])
        public = (
            self.env["hr.employee.public"]
            .with_user(self.internal)
            .browse(self.no_coach.id)
        )
        self.assertTrue(public.erp_no_coach)
        self.assertFalse(public.coach_id)

    def test_user_preferences_view(self):
        """Preferencias del usuario (res.users): cargan y muestran el jefe
        inmediato del empleado vinculado."""
        view = self.env.ref("hr.res_users_view_form_profile")
        for user in (self.internal, self.hr_user):
            with self.subTest(user=user.login):
                arch = (
                    self.env["res.users"]
                    .with_user(user)
                    .get_views([(view.id, "form")])["views"]["form"]["arch"]
                )
                self.assertTrue(_field_nodes(arch, "employee_parent_id"))

    def test_widget_in_assets(self):
        """El JS/XML del widget están en el bundle del cliente web."""
        files = [
            path
            for path, *_rest in self.env["ir.asset"]._get_asset_paths(
                "web.assets_backend", {}
            )
        ]
        for name in (
            "coach_many2one_field.js",
            "coach_no_coach_options.js",
            "coach_many2one_field.xml",
            "coach_many2one_field.scss",
        ):
            self.assertTrue(
                any(
                    path.endswith(f"erp_hr_ec/static/src/fields/coach_many2one/{name}")
                    for path in files
                ),
                name,
            )
        # Tests hoot de la posición de "Sin instructor" (/web/tests).
        unit_files = [
            path
            for path, *_rest in self.env["ir.asset"]._get_asset_paths(
                "web.assets_unit_tests", {}
            )
        ]
        self.assertTrue(
            any(
                path.endswith("erp_hr_ec/static/tests/coach_no_coach_options.test.js")
                for path in unit_files
            )
        )

    def test_widget_source_no_literal_combining_marks(self):
        """La normalización usa unaccent del núcleo, sin caracteres
        combinantes literales en el código (QA-TECH)."""
        for name in ("coach_many2one_field.js", "coach_no_coach_options.js"):
            with file_open(
                f"erp_hr_ec/static/src/fields/coach_many2one/{name}"
            ) as source:
                content = source.read()
            self.assertFalse(any("̀" <= char <= "ͯ" for char in content), name)
        with file_open(
            "erp_hr_ec/static/src/fields/coach_many2one/coach_no_coach_options.js"
        ) as source:
            self.assertIn(
                'import {unaccent} from "@web/core/utils/strings"', source.read()
            )

    # ------------------------------------------------------------------
    # Filtros (CA-5)
    # ------------------------------------------------------------------
    def test_filters_results(self):
        mine = (self.with_coach | self.no_coach | self.unassigned).ids
        for model, user in (
            ("hr.employee", self.hr_user),
            ("hr.employee.public", self.internal),
        ):
            with self.subTest(model=model):
                Model = self.env[model].with_user(user)
                no_coach = Model.search(
                    [("id", "in", mine), ("erp_no_coach", "=", True)]
                )
                self.assertEqual(no_coach.ids, self.no_coach.ids)
                unassigned = Model.search(
                    [
                        ("id", "in", mine),
                        ("coach_id", "=", False),
                        ("erp_no_coach", "=", False),
                    ]
                )
                self.assertEqual(unassigned.ids, self.unassigned.ids)

    # ------------------------------------------------------------------
    # Formulario como lo usa el widget (CA-1, CA-2)
    # ------------------------------------------------------------------
    def test_employee_form_no_coach_as_hr_user(self):
        view = self._employee_form_view()
        form = Form(self.env["hr.employee"].with_user(self.hr_user), view=view)
        form.name = "Lucía Cevallos Ordóñez"
        form.parent_id = self.manager
        self.assertEqual(form.coach_id, self.manager)  # estándar de Odoo
        # Elegir "Sin instructor": {erp_no_coach: true, coach_id: false}.
        form.erp_no_coach = True
        form.coach_id = self.env["hr.employee"]
        self.assertFalse(form.coach_id)
        employee = form.save()
        self.assertTrue(employee.erp_no_coach)
        self.assertFalse(employee.coach_id)

        # Recargar: se mantiene "Sin instructor"; cambiar el jefe no lo rellena.
        form = Form(employee.with_user(self.hr_user), view=view)
        self.assertTrue(form.erp_no_coach)
        form.parent_id = self.coach
        self.assertFalse(form.coach_id)
        employee = form.save()
        self.assertTrue(employee.erp_no_coach)
        self.assertFalse(employee.coach_id)

        # Elegir un empleado: el onchange quita la marca.
        form = Form(employee.with_user(self.hr_user), view=view)
        form.coach_id = self.coach
        self.assertFalse(form.erp_no_coach)
        employee = form.save()
        self.assertEqual(employee.coach_id, self.coach)
        self.assertFalse(employee.erp_no_coach)

        # Marcar otra vez y borrar el campo: el widget envía erp_no_coach false
        # y queda "sin asignar".
        employee.write({"erp_no_coach": True})
        form = Form(employee.with_user(self.hr_user), view=view)
        form.coach_id = self.env["hr.employee"]
        form.erp_no_coach = False
        employee = form.save()
        self.assertFalse(employee.erp_no_coach)
        self.assertFalse(employee.coach_id)

    # ------------------------------------------------------------------
    # CA-7: "Jefe inmediato"
    # ------------------------------------------------------------------
    def test_parent_labels_in_views(self):
        """Ninguna vista de empleados ni las preferencias muestran
        "Gerente"/"Manager" para parent_id."""
        cases = [
            ("hr.employee", self.hr_user, ["list", "form", "search", "kanban"]),
            ("hr.employee.public", self.internal, ["list", "form", "search", "kanban"]),
        ]
        for lang in ("en_US", LANG):
            for model, user, view_types in cases:
                with self.subTest(model=model, lang=lang):
                    Model = self.env[model].with_user(user).with_context(lang=lang)
                    result = Model.get_views([(False, vt) for vt in view_types])
                    for view_type, view in result["views"].items():
                        for node in _field_nodes(view["arch"], "parent_id"):
                            self.assertIn(
                                node.get("string"), (None, PARENT_LABEL), view_type
                            )
                        for node in _filters(view["arch"]).values():
                            if "parent_id" in (node.get("context") or ""):
                                self.assertEqual(node.get("string"), PARENT_LABEL)
                    info = Model.fields_get(["parent_id"], ["string"])["parent_id"]
                    self.assertEqual(info["string"], PARENT_LABEL)

    def test_user_preferences_label(self):
        for lang in ("en_US", LANG):
            with self.subTest(lang=lang):
                info = (
                    self.env["res.users"]
                    .with_context(lang=lang)
                    .fields_get(["employee_parent_id"], ["string", "help"])[
                        "employee_parent_id"
                    ]
                )
                self.assertEqual(info["string"], PARENT_LABEL)
                self.assertIn("reporta directamente", info["help"])

    def test_user_preferences_label_survives_hr_translation_reload(self):
        self.env["ir.module.module"]._load_module_terms(
            ["hr", "erp_hr_ec"], [LANG], overwrite=True
        )
        self.env.registry.clear_cache()
        info = (
            self.env["res.users"]
            .with_context(lang=LANG)
            .fields_get(["employee_parent_id"], ["string"])["employee_parent_id"]
        )
        self.assertEqual(info["string"], PARENT_LABEL)
        # Los filtros de búsqueda siguen con "Jefe inmediato" tras recargar.
        arch = (
            self.env["hr.employee"]
            .with_user(self.hr_user)
            .with_context(lang=LANG)
            .get_views([(False, "search")])["views"]["search"]["arch"]
        )
        self.assertEqual(_filters(arch)["group_manager"].get("string"), PARENT_LABEL)

    def test_department_manager_unchanged(self):
        info = (
            self.env["hr.department"]
            .with_context(lang=LANG)
            .fields_get(["manager_id"], ["string"])["manager_id"]
        )
        self.assertNotEqual(info["string"], PARENT_LABEL)
