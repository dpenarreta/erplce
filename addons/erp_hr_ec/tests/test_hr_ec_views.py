"""Vistas, menús y formularios de erp_hr_ec (US-007, DEV-4).

La imagen de Odoo no trae Chrome: no hay tours. Se comprueba que las vistas
nuevas y heredadas cargan (get_views) para un administrador, un usuario de
RRHH y un usuario interno sin RRHH, y se usan formularios (odoo.tests.Form)
como lo haría el cliente web (onchange, invisibilidad, obligatoriedad).
"""

from lxml import etree

from odoo.exceptions import RedirectWarning
from odoo.tests import Form, TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

ERP_EMPLOYEE_FIELDS = (
    "erp_establishment_id",
    "erp_region",
    "erp_decimo_cuarto_regime",
    "erp_disability",
    "erp_disability_percentage",
    "erp_disability_card",
    "erp_disability_substitute",
    "erp_dependent_ids",
    "erp_benefit_election_ids",
    "erp_extra_value_ids",
)


def _field_names(arch):
    return {node.get("name") for node in etree.fromstring(arch).iter("field")}


@tagged("post_install", "-at_install")
class TestHrEcViews(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = new_test_user(
            cls.env,
            login="erp_hr_view_admin",
            groups="base.group_user,base.group_system,hr.group_hr_manager",
        )
        cls.hr_manager = new_test_user(
            cls.env,
            login="erp_hr_view_manager",
            groups="base.group_user,hr.group_hr_manager",
        )
        cls.hr_user = new_test_user(
            cls.env, login="erp_hr_view_user", groups="base.group_user,hr.group_hr_user"
        )
        cls.internal = new_test_user(
            cls.env, login="erp_hr_view_internal", groups="base.group_user"
        )
        cls.establishment = cls.env["erp.establishment"].create(
            {"code": "201", "name": "Agencia Guayaquil Norte", "region": "costa"}
        )
        cls.establishment_sierra = cls.env["erp.establishment"].create(
            {"code": "202", "name": "Agencia Quito Sur", "region": "sierra"}
        )
        cls.field_text = cls.env["erp.hr.extra.field"].create(
            {"name": "Talla de uniforme", "value_type": "char"}
        )
        cls.field_list = cls.env["erp.hr.extra.field"].create(
            {
                "name": "Grupo sanguíneo",
                "value_type": "selection",
                "option_ids": [(0, 0, {"name": "O+"}), (0, 0, {"name": "A+"})],
            }
        )

    # ------------------------------------------------------------------
    # Carga de vistas
    # ------------------------------------------------------------------
    def test_employee_views_load_for_hr_users(self):
        for user in (self.admin, self.hr_manager, self.hr_user):
            with self.subTest(user=user.login):
                result = (
                    self.env["hr.employee"]
                    .with_user(user)
                    .get_views(
                        [
                            (False, "kanban"),
                            (False, "list"),
                            (False, "form"),
                            (False, "search"),
                        ]
                    )
                )
                views = result["views"]
                form_fields = _field_names(views["form"]["arch"])
                for name in ERP_EMPLOYEE_FIELDS:
                    self.assertIn(name, form_fields)
                form_arch = etree.fromstring(views["form"]["arch"])
                self.assertTrue(form_arch.xpath("//page[@name='erp_ecuador']"))
                # US-017 (CA-5): «Datos adicionales» es una sección de la
                # pestaña Ecuador, no una pestaña propia.
                self.assertFalse(form_arch.xpath("//page[@name='erp_extra_data']"))
                self.assertTrue(
                    form_arch.xpath(
                        "//page[@name='erp_ecuador']"
                        "/separator[@name='erp_extra_data']"
                    )
                )
                self.assertTrue(
                    form_arch.xpath(
                        "//page[@name='erp_ecuador']"
                        "/field[@name='erp_extra_value_ids']"
                    )
                )
                # El establecimiento está en Información de trabajo.
                self.assertTrue(
                    form_arch.xpath(
                        "//page[@name='public']//field[@name='erp_establishment_id']"
                    )
                )
                self.assertIn(
                    "erp_establishment_id", _field_names(views["list"]["arch"])
                )
                search_arch = etree.fromstring(views["search"]["arch"])
                filters = {f.get("name") for f in search_arch.iter("filter")}
                self.assertLessEqual(
                    {
                        "erp_region_costa",
                        "erp_region_sierra",
                        "erp_region_amazonia",
                        "erp_region_galapagos",
                        "erp_group_establishment",
                        "erp_group_region",
                    },
                    filters,
                )

    def test_employee_views_for_user_without_hr(self):
        """Un usuario interno sin RRHH sigue usando las vistas públicas."""
        Employee = self.env["hr.employee"].with_user(self.internal)
        # Comportamiento del núcleo: get_views de hr.employee redirige.
        with self.assertRaises(RedirectWarning):
            Employee.get_views([(False, "form")])
        form = Employee.get_view(view_type="form")
        self.assertFalse(_field_names(form["arch"]) & set(ERP_EMPLOYEE_FIELDS))
        result = (
            self.env["hr.employee.public"]
            .with_user(self.internal)
            .get_views(
                [(False, "kanban"), (False, "list"), (False, "form"), (False, "search")]
            )
        )
        for view in result["views"].values():
            self.assertFalse(_field_names(view["arch"]) & set(ERP_EMPLOYEE_FIELDS))
        # La ficha pública de un empleado se puede leer.
        employee = self.env["hr.employee"].create(
            {"name": "Empleado Público", "erp_establishment_id": self.establishment.id}
        )
        public = (
            self.env["hr.employee.public"].with_user(self.internal).browse(employee.id)
        )
        self.assertEqual(public.name, "Empleado Público")

    def test_configuration_views_load(self):
        cases = [
            (self.hr_manager, "erp.hr.extra.field", ["list", "form", "search"]),
            (self.hr_user, "erp.hr.extra.field", ["list", "form", "search"]),
            (self.hr_user, "hr.contract.type", ["list", "form"]),
            (self.hr_user, "erp.establishment", ["list", "form", "search"]),
        ]
        for user, model, view_types in cases:
            with self.subTest(user=user.login, model=model):
                result = (
                    self.env[model]
                    .with_user(user)
                    .get_views([(False, view_type) for view_type in view_types])
                )
                self.assertEqual(set(result["views"]), set(view_types))
        contract_type_views = (
            self.env["hr.contract.type"]
            .with_user(self.hr_user)
            .get_views([(False, "list"), (False, "form")])["views"]
        )
        for view in contract_type_views.values():
            self.assertIn("erp_labor_relationship", _field_names(view["arch"]))
        field_form = (
            self.env["erp.hr.extra.field"]
            .with_user(self.hr_manager)
            .get_views([(False, "form")])["views"]["form"]["arch"]
        )
        options_group = etree.fromstring(field_form).xpath("//group[@name='options']")
        self.assertEqual(options_group[0].get("invisible"), "value_type != 'selection'")

    def test_settings_view(self):
        arch = (
            self.env["res.config.settings"]
            .with_user(self.admin)
            .get_views([(False, "form")])["views"]["form"]["arch"]
        )
        names = _field_names(arch)
        for name in (
            "erp_default_reserve_fund_mode",
            "erp_default_thirteenth_mode",
            "erp_default_fourteenth_mode",
            "erp_max_weekly_hours",
        ):
            self.assertIn(name, names)
        self.assertIn("a validar con la normativa vigente", arch)

        settings = Form(self.env["res.config.settings"].with_user(self.admin))
        settings.erp_default_thirteenth_mode = "monthly"
        settings.erp_max_weekly_hours = 44.0
        settings.save().execute()
        company = self.env.company
        self.assertEqual(company.erp_default_thirteenth_mode, "monthly")
        self.assertEqual(company.erp_max_weekly_hours, 44.0)

    def test_menus(self):
        Menu = self.env["ir.ui.menu"]
        menu_est = self.env.ref("erp_hr_ec.erp_hr_ec_menu_establishment")
        menu_extra = self.env.ref("erp_hr_ec.erp_hr_ec_menu_extra_field")
        hr_action = self.env.ref("erp_hr_ec.erp_hr_ec_establishment_action")
        settings_action = self.env.ref("erp_establishment.erp_establishment_action")
        self.assertEqual(menu_est.action, hr_action)
        self.assertNotEqual(menu_est.action, settings_action)
        # Acción de solo consulta: misma tabla y vistas, sin crear/editar/borrar
        # ni invitar a importar (RRHH solo tiene lectura del catálogo).
        self.assertEqual(hr_action.res_model, "erp.establishment")
        self.assertEqual(hr_action.search_view_id, settings_action.search_view_id)
        context = safe_eval(hr_action.context)
        for key in ("create", "edit", "delete", "import"):
            self.assertIs(context.get(key), False, key)
        self.assertNotIn("Importar", hr_action.help)
        self.assertIn("Ajustes", hr_action.help)
        self.assertIn("Establecimientos", hr_action.help)
        # El menú de Ajustes conserva la acción original de administración.
        self.assertEqual(
            self.env.ref("erp_establishment.erp_establishment_menu_settings").action,
            settings_action,
        )
        visible = Menu.with_user(self.hr_user)._visible_menu_ids()
        self.assertIn(menu_est.id, visible)
        self.assertNotIn(menu_extra.id, visible)
        visible = Menu.with_user(self.hr_manager)._visible_menu_ids()
        self.assertIn(menu_est.id, visible)
        self.assertIn(menu_extra.id, visible)
        visible = Menu.with_user(self.internal)._visible_menu_ids()
        self.assertNotIn(menu_est.id, visible)
        self.assertNotIn(menu_extra.id, visible)
        self.assertTrue(self.env.ref("erp_hr_ec.erp_hr_extra_field_action").help)

    # ------------------------------------------------------------------
    # Formularios
    # ------------------------------------------------------------------
    def _employee_form_view(self):
        """Formulario de empleado para odoo.tests.Form.

        Limitación de odoo.tests.Form: el organigrama (``child_ids`` de
        hr_org_chart, auto-instalable) es un one2many de hr.employee sin
        subvista; Form carga recursivamente el formulario de hr.employee para
        él y, en el nivel más profundo, convierte los one2many del empleado
        en many2many en su caché compartida, por lo que ``.new()`` deja de
        estar disponible. Se usa una vista primaria que hereda del formulario
        real (con todas sus extensiones, incluida la de erp_hr_ec) y solo
        quita ese campo.
        """
        arch = self.env["hr.employee"].get_view(view_type="form")["arch"]
        if "child_ids" not in _field_names(arch):
            return None
        return self.env["ir.ui.view"].create(
            {
                "name": "hr.employee.form.test.erp_hr_ec",
                "model": "hr.employee",
                "inherit_id": self.env.ref("hr.view_employee_form").id,
                "mode": "primary",
                "priority": 1000,
                "arch": "<xpath expr=\"//field[@name='child_ids']\" "
                'position="replace"/>',
            }
        )

    def test_employee_form_as_hr_user(self):
        form = Form(
            self.env["hr.employee"].with_user(self.hr_user),
            view=self._employee_form_view(),
        )
        arch = form._view["tree"]
        self.assertTrue(arch.xpath("//page[@name='erp_ecuador']"))
        form.name = "Lucía Cevallos Ordóñez"
        form.erp_establishment_id = self.establishment
        self.assertEqual(form.erp_region, "costa")
        self.assertEqual(form.erp_decimo_cuarto_regime, "costa_galapagos")
        form.erp_establishment_id = self.establishment_sierra
        self.assertEqual(form.erp_decimo_cuarto_regime, "sierra_amazonia")
        with self.assertRaises(AssertionError):
            form.erp_region = "costa"  # solo lectura

        # Discapacidad: porcentaje y carné ocultos hasta marcarla.
        with self.assertRaises(AssertionError):
            form.erp_disability_percentage = 40.0
        form.erp_disability = True
        form.erp_disability_percentage = 40.0
        form.erp_disability_card = "MSP-12345"

        with form.erp_dependent_ids.new() as dependent:
            dependent.name = "Mateo Cevallos"
            dependent.relationship = "child"
            dependent.birthdate = "2018-05-10"
        with form.erp_benefit_election_ids.new() as election:
            election.benefit = "reserve_fund"
            election.mode = "accumulated"
            election.date_from = "2026-01-01"
        with form.erp_extra_value_ids.new() as value:
            value.field_id = self.field_text
            self.assertEqual(value.value_type, "char")
            value.value_char = "M"
            with self.assertRaises(AssertionError):
                value.value_integer = 3  # columna oculta para tipo texto
        with form.erp_extra_value_ids.new() as value:
            value.field_id = self.field_list
            value.option_id = self.field_list.option_ids[0]
        employee = form.save()

        self.assertEqual(employee.erp_establishment_id, self.establishment_sierra)
        self.assertEqual(employee.erp_disability_percentage, 40.0)
        self.assertEqual(employee.erp_dependent_ids.name, "Mateo Cevallos")
        self.assertEqual(employee.erp_benefit_election_ids.mode, "accumulated")
        self.assertEqual(
            employee._get_benefit_mode("reserve_fund", "2026-03-01"), "accumulated"
        )
        values = {v.field_id: v for v in employee.erp_extra_value_ids}
        self.assertEqual(values[self.field_text].value_char, "M")
        self.assertEqual(
            values[self.field_list].option_id, self.field_list.option_ids[0]
        )

    def test_ecuador_tab_layout(self):
        """US-017 (CA-5, CA-6, CA-11): ayudas de una línea, datos adicionales
        en formulario emergente con un único «Valor» visible por tipo y
        encabezados cortos."""
        arch = etree.fromstring(
            self.env["hr.employee"]
            .with_user(self.hr_user)
            .get_views([(False, "form")])["views"]["form"]["arch"]
        )
        page = arch.xpath("//page[@name='erp_ecuador']")[0]
        for paragraph in page.xpath("./p[contains(@class, 'text-muted')]"):
            text = " ".join("".join(paragraph.itertext()).split())
            with self.subTest(help=text):
                self.assertLessEqual(len(text), 130)
                self.assertLessEqual(text.count(". "), 0)
        values = page.xpath("./field[@name='erp_extra_value_ids']")[0]
        row = values.xpath("./list")[0]
        self.assertIsNone(row.get("editable"))
        # Una sola columna «Valor» (texto calculado de solo lectura).
        self.assertEqual(
            [node.get("name") for node in row.xpath("./field")],
            ["field_id", "value_display"],
        )
        form = values.xpath("./form")[0]
        value_fields = {
            "char": "value_char",
            "integer": "value_integer",
            "float": "value_float",
            "date": "value_date",
            "boolean": "value_boolean",
            "selection": "option_id",
        }
        for value_type, name in value_fields.items():
            with self.subTest(value_type=value_type):
                visible = [
                    node.get("name")
                    for node in form.xpath(".//field[@string='Valor']")
                    if not safe_eval(node.get("invisible"), {"value_type": value_type})
                ]
                self.assertEqual(visible, [name])
        option = form.xpath(".//field[@name='option_id']")[0]
        self.assertEqual(option.get("domain"), "[('field_id', '=', field_id)]")
        # Ayuda del dato (M-3): texto atenuado de solo lectura, oculto si el
        # dato no tiene ayuda.
        help_node = form.xpath(".//field[@name='field_help']")[0]
        self.assertIn("text-muted", help_node.get("class"))
        self.assertTrue(safe_eval(help_node.get("readonly")))
        self.assertTrue(safe_eval(help_node.get("invisible"), {"field_help": False}))
        self.assertFalse(
            safe_eval(help_node.get("invisible"), {"field_help": "Según Logística"})
        )
        dependents = page.xpath("./field[@name='erp_dependent_ids']/list")[0]
        self.assertEqual(
            dependents.xpath("./field[@name='birthdate']")[0].get("string"),
            "Nacimiento",
        )
        elections = page.xpath("./field[@name='erp_benefit_election_ids']/list")[0]
        self.assertEqual(
            elections.xpath("./field[@name='date_from']")[0].get("string"), "Desde"
        )

    def test_configuration_forms_have_title(self):
        """US-017 (CA-8): formularios con título (oe_title + h1)."""
        for model in ("erp.hr.extra.field", "erp.establishment"):
            with self.subTest(model=model):
                arch = etree.fromstring(
                    self.env[model]
                    .with_user(self.admin)
                    .get_views([(False, "form")])["views"]["form"]["arch"]
                )
                title = arch.xpath("//div[contains(@class, 'oe_title')]")
                self.assertEqual(len(title), 1)
                self.assertTrue(title[0].xpath("./label[@for='name']"))
                self.assertTrue(title[0].xpath("./h1/field[@name='name']"))
                # Sin repetir el nombre en los grupos (las subvistas, como la
                # lista de opciones, tienen su propio «name»).
                self.assertEqual(
                    len(arch.xpath("//field[@name='name'][not(ancestor::field)]")), 1
                )
        list_arch = etree.fromstring(
            self.env["erp.hr.extra.field"]
            .with_user(self.admin)
            .get_views([(False, "list")])["views"]["list"]["arch"]
        )
        self.assertEqual(
            list_arch.xpath("//field[@name='active']")[0].get("optional"), "hide"
        )

    def test_settings_weekly_hours_unit(self):
        """US-017 (CA-8): unidad «horas» después del número, que se muestra
        con los decimales del modelo (37,5 no se redondea a 38)."""
        arch = etree.fromstring(
            self.env["res.config.settings"]
            .with_user(self.admin)
            .get_views([(False, "form")])["views"]["form"]["arch"]
        )
        setting = arch.xpath("//setting[@id='erp_max_weekly_hours_setting']")[0]
        field = setting.xpath(".//field[@name='erp_max_weekly_hours']")[0]
        self.assertIsNone(field.get("digits"))
        field_def = self.env["res.company"]._fields["erp_max_weekly_hours"]
        self.assertGreaterEqual(field_def.get_digits(self.env)[1], 1)
        self.assertEqual(field.getnext().text.strip(), "horas")
        label = setting.xpath(".//label[@for='erp_max_weekly_hours']")[0]
        self.assertIn("visually-hidden", label.get("class"))

    def test_extra_field_form_as_hr_manager(self):
        form = Form(self.env["erp.hr.extra.field"].with_user(self.hr_manager))
        form.name = "Medio de transporte"
        form.value_type = "selection"
        with form.option_ids.new() as option:
            option.name = "Bus"
        with form.option_ids.new() as option:
            option.name = "Vehículo propio"
        extra_field = form.save()
        self.assertEqual(
            extra_field.option_ids.mapped("name"), ["Bus", "Vehículo propio"]
        )

    def test_establishment_form_readonly_for_hr_user(self):
        """Desde Empleados > Configuración un usuario de RRHH solo consulta."""
        Establishment = self.env["erp.establishment"].with_user(self.hr_user)
        self.assertFalse(Establishment.has_access("create"))
        self.assertTrue(Establishment.has_access("read"))
