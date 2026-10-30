"""Vistas, menús y terminología de Ausencias Ecuador (US-012, CA-4, CA-7; DEV-4).

La imagen de Odoo no trae Chrome: no hay tours. Se comprueba que las vistas
heredadas cargan (get_views) para un empleado sin RRHH, un jefe inmediato
(usuario con subordinados, que hr_holidays hace «responsable de ausencias»),
un usuario de RRHH sin ausencias, el encargado de ausencias y el
administrador de ausencias; qué botones y menús ve cada uno, y que la
terminología de Ecuador sobrevive a recargar las traducciones sobrescribiendo.
"""

from lxml import etree

from odoo.exceptions import RedirectWarning
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import file_open

LANG = "es_EC"
OFFICER_GROUP = "hr_holidays.group_hr_holidays_user"


def _arch(model, view_type, view_ref=None):
    view_id = model.env.ref(view_ref).id if view_ref else False
    result = model.get_views([(view_id, view_type)])
    return etree.fromstring(result["views"][view_type]["arch"])


def _text(node):
    return " ".join("".join(node.itertext()).split())


@tagged("post_install", "-at_install")
class TestHolidaysEcViews(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee_user = new_test_user(
            cls.env, login="empleado_ausencias_vistas", groups="base.group_user"
        )
        cls.boss_user = new_test_user(
            cls.env, login="jefe_ausencias_vistas", groups="base.group_user"
        )
        cls.hr_user = new_test_user(
            cls.env,
            login="rrhh_sin_ausencias_vistas",
            groups="base.group_user,hr.group_hr_user",
        )
        cls.officer = new_test_user(
            cls.env,
            login="encargado_ausencias_vistas",
            groups=f"base.group_user,{OFFICER_GROUP}",
        )
        cls.holidays_manager = new_test_user(
            cls.env,
            login="admin_ausencias_vistas",
            groups="base.group_user,hr_holidays.group_hr_holidays_manager",
        )
        Employee = cls.env["hr.employee"]
        cls.boss = Employee.create(
            {"name": "Jefa Vistas Ausencias", "user_id": cls.boss_user.id}
        )
        # Subordinado: hr_holidays deriva el aprobador (Jefe inmediato) y da
        # al jefe el grupo «responsable de ausencias».
        cls.employee = Employee.create(
            {
                "name": "Empleado Vistas Ausencias",
                "user_id": cls.employee_user.id,
                "parent_id": cls.boss.id,
            }
        )

    # ------------------------------------------------------------------
    # Perfiles
    # ------------------------------------------------------------------
    def test_boss_is_leave_responsible(self):
        self.assertEqual(self.employee.leave_manager_id, self.boss_user)
        self.assertTrue(
            self.boss_user.has_group("hr_holidays.group_hr_holidays_responsible")
        )
        self.assertFalse(self.boss_user.has_group(OFFICER_GROUP))

    def test_leave_and_allocation_views_load_by_profile(self):
        """CA-4/CA-7: solicitud, saldos y búsqueda cargan para cada perfil."""
        views = (
            ("hr.leave", "form", "hr_holidays.hr_leave_view_form"),
            ("hr.leave", "form", "hr_holidays.hr_leave_view_form_manager"),
            ("hr.leave", "list", "hr_holidays.hr_leave_view_tree_my"),
            ("hr.leave", "calendar", "hr_holidays.hr_leave_view_dashboard"),
            ("hr.leave", "search", "hr_holidays.hr_leave_view_search_my"),
            ("hr.leave", "search", "hr_holidays.hr_leave_view_search_manager"),
            (
                "hr.leave.allocation",
                "form",
                "hr_holidays.hr_leave_allocation_view_form",
            ),
            (
                "hr.leave.allocation",
                "form",
                "hr_holidays.hr_leave_allocation_view_form_manager",
            ),
            (
                "hr.leave.allocation",
                "list",
                "hr_holidays.hr_leave_allocation_view_tree_my",
            ),
            (
                "hr.leave.allocation",
                "list",
                "hr_holidays.hr_leave_allocation_view_tree",
            ),
            (
                "hr.leave.allocation",
                "search",
                "hr_holidays.hr_leave_allocation_view_search_manager",
            ),
        )
        for user in (self.employee_user, self.boss_user, self.officer):
            for model, view_type, ref in views:
                with self.subTest(user=user.login, view=ref):
                    _arch(self.env[model].with_user(user), view_type, ref)

    def test_employee_without_hr_uses_public_profile(self):
        """El empleado sin RRHH (y el jefe sin RRHH) no abre la ficha privada:
        Odoo lo redirige al perfil público, que sigue cargando."""
        for user in (self.employee_user, self.boss_user):
            with self.subTest(user=user.login):
                with self.assertRaises(RedirectWarning):
                    self.env["hr.employee"].with_user(user).get_views([(False, "form")])
                arch = _arch(self.env["hr.employee.public"].with_user(user), "form")
                self.assertFalse(
                    arch.xpath(
                        "//button[@name='action_erp_generate_vacation_allocations']"
                    )
                )

    # ------------------------------------------------------------------
    # Ficha del empleado: botón «Calcular vacaciones», fecha de ingreso y saldo
    # ------------------------------------------------------------------
    def test_employee_form_generate_button_by_group(self):
        xpath = "//header/button[@name='action_erp_generate_vacation_allocations']"
        officer_arch = _arch(self.env["hr.employee"].with_user(self.officer), "form")
        buttons = officer_arch.xpath(xpath)
        self.assertEqual(len(buttons), 1)
        button = buttons[0]
        self.assertEqual(button.get("string"), "Calcular vacaciones")
        self.assertEqual(button.get("type"), "object")
        self.assertTrue(button.get("confirm"))
        # Secundario: la ficha no gana un segundo botón primario.
        self.assertNotIn("oe_highlight", button.get("class", ""))
        self.assertNotIn("btn-primary", button.get("class", ""))
        self.assertFalse(
            officer_arch.xpath(
                "//header/button[contains(@class, 'oe_highlight') "
                "or contains(@class, 'btn-primary')]"
            )
        )
        # RRHH sin el grupo de ausencias: sin botón.
        hr_arch = _arch(self.env["hr.employee"].with_user(self.hr_user), "form")
        self.assertFalse(hr_arch.xpath(xpath))

    def test_employee_form_balance_stat_button(self):
        """CA-4: el saldo de la ficha dice qué es («Saldo disponible», «X de
        Y días») en lugar de «X/Y Días · Vacaciones»."""
        arch = _arch(self.env["hr.employee"].with_user(self.officer), "form")
        stat = arch.xpath(
            "//div[@name='button_box']/button[@name='action_time_off_dashboard']"
            "[.//field[@name='allocation_remaining_display']]"
        )
        self.assertEqual(len(stat), 1)
        # Los textos nativos quedan ocultos; se muestran los propios.
        for native in stat[0].xpath("./div[not(@name)]"):
            self.assertEqual(native.get("invisible"), "1")
        self._assert_balance_stat(stat[0])

    def _assert_balance_stat(self, stat):
        """Saldo «X de Y días» con formato decimal del idioma (widget
        erp_localized_number: 7,5 y no 7.5), «día» en singular y «Ausencias»
        sin saldo (no «0 de 0 días»)."""
        balance = stat.xpath("./div[@name='erp_balance']")[0]
        self.assertEqual(balance.get("invisible"), "allocation_display == '0'")
        text = _text(balance)
        self.assertIn("Saldo disponible", text)
        self.assertIn("de", text.split())
        for name in ("allocation_remaining_display", "allocation_display"):
            field = balance.xpath(f".//field[@name='{name}']")
            self.assertEqual(len(field), 1, name)
            self.assertEqual(field[0].get("widget"), "erp_localized_number")
        units = {
            _text(span): span.get("invisible")
            for span in balance.xpath(".//span[not(@class)]")
        }
        self.assertEqual(
            units,
            {"día": "allocation_display != '1'", "días": "allocation_display == '1'"},
        )
        empty = stat.xpath("./div[@name='erp_no_balance']")[0]
        self.assertEqual(empty.get("invisible"), "allocation_display != '0'")
        self.assertEqual(_text(empty), "Ausencias")
        self.assertIn("pendiente de aprobar", stat.get("help", ""))

    def test_employee_form_entry_date(self):
        """CA-9: «Fecha de ingreso a la empresa» en la pestaña Ecuador, solo
        RRHH (el empleado sin RRHH usa el perfil público, sin el campo)."""
        for user in (self.hr_user, self.officer):
            with self.subTest(user=user.login):
                arch = _arch(self.env["hr.employee"].with_user(user), "form")
                fields = arch.xpath(
                    "//page[@name='erp_ecuador']//group[@name='erp_vacation']"
                    "/field[@name='erp_company_entry_date']"
                )
                self.assertEqual(len(fields), 1)
        label = self.env["hr.employee"].fields_get(
            ["erp_company_entry_date"], ["string"]
        )["erp_company_entry_date"]["string"]
        self.assertEqual(label, "Fecha de ingreso a la empresa")
        public = _arch(
            self.env["hr.employee.public"].with_user(self.employee_user), "form"
        )
        self.assertFalse(public.xpath("//field[@name='erp_company_entry_date']"))

    def test_generate_list_action_by_group(self):
        """Acciones > Calcular vacaciones en la lista de empleados, solo para
        el encargado de ausencias."""
        action = self.env.ref(
            "erp_hr_holidays_ec.action_server_erp_generate_vacation_allocations"
        )
        self.assertEqual(action.name, "Calcular vacaciones")
        self.assertEqual(action.binding_model_id.model, "hr.employee")
        self.assertEqual(action.binding_view_types, "list")
        self.assertIn(self.env.ref(OFFICER_GROUP), action.groups_id)

        def bound(user):
            bindings = (
                self.env["ir.actions.actions"]
                .with_user(user)
                .get_bindings("hr.employee")
            )
            return {item["id"] for item in bindings.get("action", [])}

        self.assertIn(action.id, bound(self.officer))
        self.assertNotIn(action.id, bound(self.hr_user))

    def test_user_profile_single_primary_and_balance(self):
        """Mi perfil: un solo botón primario y el saldo con el mismo texto que
        la ficha del empleado."""
        arch = _arch(
            self.env["res.users"].with_user(self.employee_user),
            "form",
            "hr.res_users_view_form_profile",
        )
        primary = arch.xpath(
            "//header/button[contains(@class, 'btn-primary') "
            "or contains(@class, 'oe_highlight')]"
        )
        self.assertEqual([b.get("string") for b in primary], ["Solicitar ausencia"])
        balances = arch.xpath(
            "//div[@name='button_box']/button"
            "[.//field[@name='allocation_remaining_display']]"
        )
        self.assertEqual(len(balances), 1)
        for native in balances[0].xpath("./div[not(@name)]"):
            self.assertEqual(native.get("invisible"), "1")
        self._assert_balance_stat(balances[0])

    # ------------------------------------------------------------------
    # Tipos de ausencia, asignaciones y solicitud
    # ------------------------------------------------------------------
    def test_leave_type_form_ecuador_fields(self):
        arch = _arch(self.env["hr.leave.type"].with_user(self.holidays_manager), "form")
        rules = arch.xpath("//group[@name='erp_ecuador_rules']")
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].get("string"), "Reglas de Ecuador")
        names = [field.get("name") for field in rules[0].xpath(".//field")]
        self.assertEqual(
            names,
            [
                "erp_is_annual_vacation",
                "unpaid",
                "erp_max_duration_display",
                "erp_max_duration_param_code",
            ],
        )
        display = rules[0].xpath(".//field[@name='erp_max_duration_display']")[0]
        self.assertEqual(display.get("readonly"), "1")
        self.assertEqual(display.get("string"), "Duración máxima")
        self.assertIn(
            "Código del parámetro (Nómina › Configuración › Parámetros normativos)",
            _text(rules[0]),
        )
        # Ayuda de una línea.
        for hint in rules[0].xpath(".//div[contains(@class, 'text-muted')]"):
            self.assertLessEqual(len(_text(hint)), 90)
        unpaid = rules[0].xpath(".//field[@name='unpaid']")[0]
        self.assertEqual(unpaid.get("string"), "Sin sueldo")
        attachment = arch.xpath("//field[@name='erp_attachment_required']")
        self.assertEqual(len(attachment), 1)
        self.assertEqual(attachment[0].get("invisible"), "not support_document")
        support = arch.xpath("//field[@name='support_document']")[0]
        self.assertEqual(support.get("string"), "Documento de respaldo")

        # Botones inteligentes con la terminología de la aplicación.
        stats = {}
        for button in arch.xpath("//div[@name='button_box']/button"):
            texts = button.xpath(".//span[@class='o_stat_text']")
            if not texts:
                continue
            for native in texts:
                if native.get("name") != "erp_stat_text":
                    self.assertEqual(native.get("invisible"), "1")
            own = button.xpath(".//span[@name='erp_stat_text']")
            stats[button.get("name")] = _text(own[0])
        self.assertEqual(stats["action_see_days_allocated"], "Saldos")
        self.assertEqual(stats["action_see_group_leaves"], "Ausencias")
        self.assertEqual(stats["action_see_accrual_plans"], "Acumulación")

        list_arch = _arch(
            self.env["hr.leave.type"].with_user(self.holidays_manager), "list"
        )
        self.assertTrue(
            list_arch.xpath("//field[@name='unpaid'][@string='Sin sueldo']")
        )
        self.assertTrue(
            list_arch.xpath(
                "//field[@name='erp_max_duration_display'][@string='Duración máxima']"
            )
        )

    def test_leave_type_form_code_only_for_manager(self):
        """El código del parámetro solo lo ve el administrador de ausencias;
        los demás ven la duración legible."""
        arch = _arch(self.env["hr.leave.type"].with_user(self.officer), "form")
        self.assertTrue(arch.xpath("//field[@name='erp_max_duration_display']"))
        self.assertFalse(arch.xpath("//field[@name='erp_max_duration_param_code']"))
        self.assertNotIn("Parámetros normativos", _text(arch))

    def test_allocation_views_service_year(self):
        form = _arch(
            self.env["hr.leave.allocation"].with_user(self.officer),
            "form",
            "hr_holidays.hr_leave_allocation_view_form_manager",
        )
        for name in ("erp_auto_generated", "erp_service_year", "erp_entry_date"):
            fields = form.xpath(
                f"//group[@name='alloc_right_col']/field[@name='{name}']"
            )
            self.assertEqual(len(fields), 1, name)
            self.assertEqual(fields[0].get("invisible"), "not erp_auto_generated")
        label = form.xpath("//label[@for='notes']")
        self.assertEqual(label[0].get("string"), "Detalle del cálculo")
        self.assertEqual(form.get("string"), "Saldo de vacaciones")
        days = form.xpath("//label[@for='number_of_days_display']")
        self.assertEqual(days[0].get("string"), "Días")
        # CA-11: detalle del periodo con los días del periodo (no
        # number_of_days, que ya descuenta lo gozado antes del sistema).
        detail = form.xpath("//group[@name='erp_period_detail']")
        self.assertEqual(len(detail), 1)
        self.assertEqual(detail[0].get("string"), "Detalle del periodo")
        self.assertEqual(detail[0].get("invisible"), "not erp_auto_generated")
        detail_fields = [field.get("name") for field in detail[0].xpath(".//field")]
        self.assertEqual(
            detail_fields,
            [
                "date_from",
                "date_to",
                "erp_entitled_days",
                "erp_history_days",
                "erp_days_used",
                "erp_days_pending",
                "erp_days_available",
                "erp_days_expired",
                "erp_is_expired",
            ],
        )
        self.assertNotIn("number_of_days", detail_fields)
        strings = {
            field.get("name"): field.get("string")
            for field in detail[0].xpath(".//field[@string]")
        }
        self.assertEqual(strings, {"date_from": "Nace el", "date_to": "Caduca el"})

        tree = _arch(
            self.env["hr.leave.allocation"].with_user(self.officer),
            "list",
            "hr_holidays.hr_leave_allocation_view_tree",
        )
        year = tree.xpath("//field[@name='erp_service_year']")[0]
        self.assertEqual(year.get("string"), "Año de servicio")
        self.assertEqual(year.get("optional"), "show")
        # Ancho suficiente: el encabezado no se trunca (columna entera, 71 px).
        self.assertEqual(year.get("width"), "120px")
        columns = {
            field.get("name"): (field.get("string"), field.get("optional"))
            for field in tree.xpath("/list/field")
        }
        self.assertEqual(columns["duration_display"][0], "Días")
        self.assertEqual(columns["date_to"], ("Caduca el", "show"))
        self.assertEqual(columns["allocation_type"], ("Origen", "hide"))
        self.assertEqual(columns["accrual_plan_id"], ("Regla de acumulación", "hide"))
        self.assertEqual(columns["erp_days_available"][0], "Disponibles")
        self.assertEqual(columns["erp_days_pending"][0], "Por aprobar")

        search = _arch(
            self.env["hr.leave.allocation"].with_user(self.officer),
            "search",
            "hr_holidays.hr_leave_allocation_view_search_manager",
        )
        self.assertTrue(search.xpath("//filter[@name='erp_auto_generated']"))
        self.assertTrue(search.xpath("//filter[@name='erp_manual']"))
        group = search.xpath("//filter[@name='group_allocation_type']")[0]
        self.assertEqual(group.get("string"), "Origen")

    def test_my_balances_list(self):
        """«Mis saldos»: detalle por periodo, sin términos «Asignación» /
        «Plan de acumulación» visibles y sin «Nuevo» (salvo Talento
        Humano)."""
        Allocation = self.env["hr.leave.allocation"]
        tree = _arch(
            Allocation.with_user(self.employee_user),
            "list",
            "hr_holidays.hr_leave_allocation_view_tree_my",
        )
        columns = [
            (field.get("name"), field.get("string"), field.get("optional"))
            for field in tree.xpath("/list/field")
            if field.get("column_invisible") not in ("1", "True")
        ]
        names = [name for name, _string, _optional in columns]
        for name in (
            "date_from",
            "date_to",
            "erp_entitled_days",
            "erp_days_used",
            "erp_days_pending",
            "erp_days_available",
            "erp_days_expired",
        ):
            self.assertIn(name, names)
        visible = {string for _name, string, optional in columns if optional != "hide"}
        self.assertTrue(
            {"Nace el", "Caduca el", "Días del periodo", "Gozados", "Disponibles"}
            <= visible
        )
        for string in visible:
            self.assertNotIn("asignación", (string or "").lower())
            self.assertNotIn("plan de acumulación", (string or "").lower())
        self.assertIn(tree.get("create"), ("0", "false", "False"))

        # Lista, formulario y kanban de la acción «Mis saldos»: sin «Nuevo».
        action = self.env.ref("hr_holidays.hr_leave_allocation_action_my")
        my_views = {view.view_mode: view.view_id for view in action.view_ids}
        self.assertEqual(
            my_views["form"],
            self.env.ref("erp_hr_holidays_ec.hr_leave_allocation_view_form_erp_my"),
        )
        self.assertEqual(
            my_views["kanban"],
            self.env.ref("erp_hr_holidays_ec.hr_leave_allocation_view_kanban_erp_my"),
        )
        for user in (self.employee_user, self.boss_user, self.officer):
            for view_type, view in my_views.items():
                with self.subTest(user=user.login, view=view_type):
                    arch = _arch(
                        Allocation.with_user(user),
                        view_type,
                        view.get_external_id()[view.id],
                    )
                    self.assertIn(arch.get("create"), ("0", "false", "False"))
        # Talento Humano crea saldos manuales desde «Saldos de vacaciones».
        for view_type, ref in (
            ("list", "hr_holidays.hr_leave_allocation_view_tree"),
            ("form", "hr_holidays.hr_leave_allocation_view_form_manager"),
        ):
            with self.subTest(officer_view=ref):
                arch = _arch(Allocation.with_user(self.officer), view_type, ref)
                self.assertNotIn(arch.get("create"), ("0", "false", "False"))

    def test_vacation_periods_list(self):
        """CA-10/CA-11: «Periodos de vacaciones» con el detalle por periodo,
        filtros vigentes/caducados y agrupación por empleado."""
        action = self.env.ref("erp_hr_holidays_ec.action_erp_vacation_periods")
        self.assertEqual(action.res_model, "hr.leave.allocation")
        self.assertIn("erp_auto_generated", action.domain)
        self.assertIn("search_default_erp_current", action.context)
        self.assertIn("search_default_erp_group_employee", action.context)
        self.assertIn("o_view_nocontent_empty_folder", action.help)
        self.assertIn("Calcular vacaciones", action.help)
        Allocation = self.env["hr.leave.allocation"]
        for user in (self.employee_user, self.boss_user, self.officer):
            with self.subTest(user=user.login):
                tree = _arch(
                    Allocation.with_user(user),
                    "list",
                    "erp_hr_holidays_ec.hr_leave_allocation_view_list_erp_periods",
                )
                self.assertIn(tree.get("create"), ("0", "false", "False"))
                columns = [
                    (field.get("name"), field.get("string"))
                    for field in tree.xpath("/list/field")
                    if field.get("column_invisible") not in ("1", "True")
                    and field.get("optional") != "hide"
                ]
                self.assertEqual(
                    columns,
                    [
                        ("employee_id", None),
                        ("erp_service_year", "Año de servicio"),
                        ("date_from", "Nace el"),
                        ("date_to", "Caduca el"),
                        ("erp_entitled_days", "Días del periodo"),
                        ("erp_history_days", "Gozados antes del sistema"),
                        ("erp_days_used", "Gozados"),
                        ("erp_days_pending", "Por aprobar"),
                        ("erp_days_available", "Disponibles"),
                        ("erp_days_expired", "Caducados"),
                    ],
                )
                search = _arch(
                    Allocation.with_user(user),
                    "search",
                    "erp_hr_holidays_ec.hr_leave_allocation_view_search_erp_periods",
                )
                for name in ("erp_current", "erp_expired", "erp_group_employee"):
                    self.assertTrue(search.xpath(f"//filter[@name='{name}']"), name)
        # Los cálculos del periodo no dependen del número de días neto.
        fields = Allocation.fields_get(
            ["erp_entitled_days", "erp_days_available"], ["string"]
        )
        self.assertEqual(fields["erp_entitled_days"]["string"], "Días del periodo")
        self.assertEqual(fields["erp_days_available"]["string"], "Disponibles")

    def test_vacation_history_views(self):
        """CA-11: «Vacaciones gozadas antes del sistema» para el encargado de
        ausencias, con estado vacío que explica la plantilla y la
        importación."""
        History = self.env["erp.hr.vacation.history"]
        for view_type in ("list", "form", "search"):
            with self.subTest(view=view_type):
                _arch(History.with_user(self.officer), view_type)
        form = _arch(History.with_user(self.officer), "form")
        self.assertTrue(
            form.xpath("//div[@class='oe_title']//field[@name='employee_id']")
        )
        action = self.env.ref("erp_hr_holidays_ec.action_erp_hr_vacation_history")
        self.assertEqual(action.res_model, "erp.hr.vacation.history")
        self.assertIn("o_view_nocontent_empty_folder", action.help)
        self.assertIn("Importar registros", action.help)
        template = History.get_import_templates()[0]["label"]
        self.assertIn(template, action.help)
        menu = self.env.ref("erp_hr_holidays_ec.menu_erp_hr_vacation_history")
        self.assertEqual(menu.action, action)

    def test_leave_form_and_search_labels(self):
        form = _arch(
            self.env["hr.leave"].with_user(self.employee_user),
            "form",
            "hr_holidays.hr_leave_view_form",
        )
        label = form.xpath("//label[@for='supported_attachment_ids']")[0]
        self.assertEqual(label.get("string"), "Documento de respaldo")
        # Aviso atenuado al crear: por qué puede faltar «Vacaciones anuales».
        hint = form.xpath(
            "//field[@name='holiday_status_id']"
            "/following-sibling::div[@name='erp_no_vacation_hint']"
        )
        self.assertEqual(len(hint), 1)
        self.assertEqual(hint[0].get("invisible"), "id")
        self.assertEqual(hint[0].get("role"), "note")
        self.assertIn("text-muted", hint[0].get("class"))
        self.assertEqual(
            _text(hint[0]),
            "¿No ve Vacaciones anuales? Aún no tiene saldo; consulte a Talento "
            "Humano.",
        )
        # El botón nativo «Cancelar» sigue dependiendo de can_cancel (DEV-2).
        cancel = form.xpath("//header/button[@name='action_cancel']")[0]
        self.assertIn("can_cancel", cancel.get("invisible"))

        for user, name in (
            (self.boss_user, "waiting_for_me"),
            (self.officer, "waiting_for_me_manager"),
        ):
            with self.subTest(user=user.login):
                search = _arch(
                    self.env["hr.leave"].with_user(user),
                    "search",
                    "hr_holidays.hr_leave_view_search_manager",
                )
                filters = search.xpath(f"//filter[@name='{name}']")
                self.assertEqual(len(filters), 1)
                self.assertEqual(filters[0].get("string"), "Esperando mi aprobación")

    def test_report_lists_short_day_header(self):
        """Reportes: encabezado «Días» (no «Número de días», truncado)."""
        for model, ref in (
            ("hr.leave", "hr_holidays.view_holiday_list"),
            ("hr.leave.report", "hr_holidays.hr_leave_report_tree"),
        ):
            with self.subTest(view=ref):
                arch = _arch(self.env[model].with_user(self.officer), "list", ref)
                field = arch.xpath("//field[@name='number_of_days']")[0]
                self.assertEqual(field.get("string"), "Días")

    # ------------------------------------------------------------------
    # Menús por grupo
    # ------------------------------------------------------------------
    def _visible(self, user):
        menu_ids = self.env["ir.ui.menu"].with_user(user)._visible_menu_ids(debug=False)
        result = set()
        for xmlid in (
            "hr_holidays.menu_hr_holidays_root",
            "hr_holidays.menu_hr_holidays_my_leaves",
            "hr_holidays.hr_leave_menu_new_request",
            "hr_holidays.hr_leave_menu_my",
            "hr_holidays.menu_open_allocation",
            "hr_holidays.menu_hr_holidays_dashboard",
            "hr_holidays.menu_hr_holidays_management",
            "hr_holidays.menu_open_department_leave_approve",
            "hr_holidays.hr_holidays_menu_manager_approve_allocations",
            "erp_hr_holidays_ec.menu_erp_vacation_periods",
            "erp_hr_holidays_ec.menu_erp_hr_vacation_history",
            "hr_holidays.menu_hr_holidays_report",
            "hr_holidays.menu_hr_holidays_configuration",
            "hr_holidays.hr_holidays_status_menu_configuration",
        ):
            menu = self.env.ref(xmlid)
            # Visible si el menú y todos sus ancestros lo son (el cliente no
            # muestra hijos de un menú oculto).
            ancestors = [int(i) for i in menu.parent_path.strip("/").split("/")]
            if all(menu_id in menu_ids for menu_id in ancestors):
                result.add(xmlid.split(".")[1])
        return result

    def test_menus_visible_by_group(self):
        own = {
            "menu_hr_holidays_root",
            "menu_hr_holidays_my_leaves",
            "hr_leave_menu_new_request",
            "hr_leave_menu_my",
            "menu_open_allocation",
            "menu_hr_holidays_dashboard",
        }
        approvals = {
            "menu_hr_holidays_management",
            "menu_open_department_leave_approve",
            "hr_holidays_menu_manager_approve_allocations",
            "menu_erp_vacation_periods",
        }
        # Carga inicial de vacaciones gozadas: solo encargados de ausencias.
        history = {"menu_erp_hr_vacation_history"}
        configuration = {
            "menu_hr_holidays_configuration",
            "hr_holidays_status_menu_configuration",
        }
        self.assertEqual(self._visible(self.employee_user), own)
        self.assertEqual(self._visible(self.boss_user), own | approvals)
        self.assertEqual(
            self._visible(self.officer),
            own | approvals | history | {"menu_hr_holidays_report"},
        )
        self.assertEqual(
            self._visible(self.holidays_manager),
            own | approvals | history | {"menu_hr_holidays_report"} | configuration,
        )

    # ------------------------------------------------------------------
    # Terminología (es_EC) y estados vacíos
    # ------------------------------------------------------------------
    EXPECTED_NAMES = {
        "hr_holidays.menu_hr_holidays_root": "Ausencias",
        "hr_holidays.menu_hr_holidays_my_leaves": "Mis ausencias",
        "hr_holidays.hr_leave_menu_new_request": "Solicitar ausencia",
        "hr_holidays.hr_leave_menu_my": "Mis solicitudes",
        "hr_holidays.menu_open_allocation": "Mis saldos",
        "hr_holidays.menu_hr_holidays_dashboard": "Calendario del equipo",
        "hr_holidays.menu_hr_holidays_management": "Aprobaciones",
        "hr_holidays.menu_open_department_leave_approve": "Ausencias por aprobar",
        "hr_holidays.hr_holidays_menu_manager_approve_allocations": (
            "Saldos de vacaciones"
        ),
        "hr_holidays.menu_hr_holidays_balance": "Saldos por empleado",
        "hr_holidays.hr_holidays_status_menu_configuration": "Tipos de ausencia",
        "hr_holidays.hr_holidays_public_time_off_menu_configuration": "Feriados",
        "hr_holidays.hr_holidays_mandatory_day_menu_configuration": (
            "Días sin ausencias"
        ),
        "hr_holidays.hr_holidays_accrual_menu_configuration": "Reglas de acumulación",
        "hr_holidays.menu_hr_available_holidays_report_tree": "Ausencias por empleado",
        "hr_holidays.menu_hr_holidays_summary_all": "Ausencias por tipo",
        "hr_holidays.hr_leave_action_new_request": "Solicitar ausencia",
        "hr_holidays.hr_leave_action_my": "Mis solicitudes",
        "hr_holidays.hr_leave_action_my_request": "Solicitud de ausencia",
        "hr_holidays.hr_leave_action_action_approve_department": (
            "Ausencias por aprobar"
        ),
        "hr_holidays.hr_leave_action_holiday_allocation_id": "Ausencias",
        "hr_holidays.action_hr_holidays_dashboard": "Calendario del equipo",
        "hr_holidays.hr_leave_allocation_action_my": "Mis saldos",
        "hr_holidays.hr_leave_allocation_action_approve_department": (
            "Saldos de vacaciones"
        ),
        "hr_holidays.hr_leave_allocation_action_all": "Todos los saldos",
        "hr_holidays.open_view_holiday_status": "Tipos de ausencia",
        "hr_holidays.open_view_public_holiday": "Feriados",
        "hr_holidays.hr_leave_mandatory_day_action": "Días sin ausencias",
        "hr_holidays.action_hr_available_holidays_report": "Ausencias por empleado",
        "hr_holidays.action_hr_leave_report": "Ausencias por tipo",
        "hr_holidays.open_view_accrual_plans": "Reglas de acumulación",
        "hr_holidays.action_hr_holidays_by_employee_and_type_report": (
            "Saldos por empleado"
        ),
        "hr_holidays.action_manager_approval": "Aprobar (jefe inmediato)",
        "hr_holidays.action_hr_approval": "Aprobar (Talento Humano)",
        "hr_holidays.ir_actions_server_approve_allocations": "Aprobar saldos",
    }
    SMILING = "o_view_nocontent_smiling_face"
    NEUTRAL = "o_view_nocontent_empty_folder"
    EXPECTED_HELP = {
        "hr_holidays.hr_leave_action_new_request": (
            SMILING,
            "Aún no tiene ausencias registradas",
        ),
        "hr_holidays.hr_leave_action_my": (SMILING, "Aún no ha solicitado ausencias"),
        "hr_holidays.hr_leave_action_action_approve_department": (
            SMILING,
            "No hay ausencias por aprobar",
        ),
        "hr_holidays.hr_leave_allocation_action_my": (
            SMILING,
            "Aún no tiene saldo de vacaciones",
        ),
        # Estado vacío neutro: no hay nada que celebrar si faltan saldos.
        "hr_holidays.hr_leave_allocation_action_approve_department": (
            NEUTRAL,
            "Aún no hay saldos de vacaciones",
        ),
        "hr_holidays.hr_leave_allocation_action_all": (
            NEUTRAL,
            "Aún no hay saldos de vacaciones",
        ),
    }
    EXPECTED_LABELS = (
        ("hr.leave.type", "unpaid", "Sin sueldo"),
        ("hr.leave.type", "support_document", "Documento de respaldo"),
        ("hr.leave", "leave_type_support_document", "Documento de respaldo"),
        ("hr.leave.type", "name", "Tipo de ausencia"),
        ("hr.leave", "holiday_status_id", "Tipo de ausencia"),
        ("hr.leave.allocation", "holiday_status_id", "Tipo de ausencia"),
        ("hr.leave.type", "leave_validation_type", "Aprobación de la solicitud"),
        ("hr.leave.type", "request_unit", "Se solicita por"),
        ("hr.leave.type", "requires_allocation", "Requiere saldo"),
        ("hr.leave.type", "time_type", "Se registra como"),
        ("hr.leave.type", "create_calendar_meeting", "Mostrar en el calendario"),
        ("hr.leave.type", "include_public_holidays_in_duration", "Incluir feriados"),
        ("hr.leave.type", "responsible_ids", "Talento Humano a notificar"),
        ("hr.leave.allocation", "allocation_type", "Origen"),
        ("hr.leave.allocation", "accrual_plan_id", "Regla de acumulación"),
    )
    EXPECTED_VALIDATION = {
        "no_validation": "Sin aprobación",
        "hr": "Talento Humano",
        "manager": "Jefe inmediato",
        "both": "Jefe inmediato y Talento Humano",
    }

    def _assert_terminology(self):
        es = self.env(context={"lang": LANG})
        names = {xmlid: es.ref(xmlid).name for xmlid in self.EXPECTED_NAMES}
        self.assertEqual(names, self.EXPECTED_NAMES)
        for xmlid, (css_class, text) in self.EXPECTED_HELP.items():
            with self.subTest(help=xmlid):
                help_html = es.ref(xmlid).help
                self.assertIn(css_class, help_html)
                self.assertIn(text, help_html)
                self.assertNotIn("tiempo personal", help_html.lower())
                self.assertNotIn("Generar vacaciones", help_html)
        for model, field, label in self.EXPECTED_LABELS:
            with self.subTest(model=model, field=field):
                string = es[model].fields_get([field], ["string"])[field]["string"]
                self.assertEqual(string, label)
        selections = es["hr.leave.type"].fields_get(
            [
                "leave_validation_type",
                "allocation_validation_type",
                "requires_allocation",
            ],
            ["selection"],
        )
        for field in ("leave_validation_type", "allocation_validation_type"):
            with self.subTest(selection=field):
                self.assertEqual(
                    dict(selections[field]["selection"]), self.EXPECTED_VALIDATION
                )
        self.assertEqual(
            dict(selections["requires_allocation"]["selection"])["no"], "No"
        )
        origin = es["hr.leave.allocation"].fields_get(
            ["allocation_type"], ["selection"]
        )["allocation_type"]["selection"]
        self.assertEqual(
            dict(origin),
            {"regular": "Talento Humano", "accrual": "Acumulación automática"},
        )

    def test_terminology_survives_translation_reload(self):
        """CA-7: términos de Ecuador en es_EC, también tras recargar las
        traducciones de hr_holidays con «Sobrescribir términos existentes»."""
        self.assertTrue(self.env["res.lang"]._lang_get(LANG).active)
        self._assert_terminology()
        self.env["ir.module.module"]._load_module_terms(
            ["hr_holidays", "erp_hr_holidays_ec"], [LANG], overwrite=True
        )
        self.env.invalidate_all()
        self.env.registry.clear_cache()
        self._assert_terminology()

    def test_main_menus_have_no_confusing_terms(self):
        """Ningún menú de Ausencias visible para el empleado usa «tiempo
        personal» ni «asignaciones»."""
        es = self.env(context={"lang": LANG})
        root = es.ref("hr_holidays.menu_hr_holidays_root")
        menus = es["ir.ui.menu"].search([("id", "child_of", root.id)])
        for menu in menus:
            with self.subTest(menu=menu.name):
                lowered = menu.name.lower()
                self.assertNotIn("tiempo personal", lowered)
                self.assertNotIn("asignaciones", lowered)

    def test_report_names_are_distinct(self):
        """Los dos reportes de ausencias no comparten nombre."""
        es = self.env(context={"lang": LANG})
        names = [
            es.ref("hr_holidays.action_hr_available_holidays_report").name,
            es.ref("hr_holidays.action_hr_leave_report").name,
        ]
        self.assertEqual(len(set(names)), 2)

    # ------------------------------------------------------------------
    # Textos de JS/OWL de hr_holidays (herencia de plantillas y patch)
    # ------------------------------------------------------------------
    STATIC = "erp_hr_holidays_ec/static/src/"
    OWL_FILES = (
        "dashboard/time_off_dashboard_patch.js",
        "dashboard/time_off_dashboard_patch.xml",
        "views/calendar_controller_patch.js",
        "views/calendar_filter_panel_patch.xml",
        "fields/localized_number_field.js",
        "fields/localized_number_field.xml",
    )

    def _source(self, name):
        with file_open(self.STATIC + name) as source:
            return source.read()

    def test_owl_patches_in_backend_bundle(self):
        """Las herencias OWL y los patch están en web.assets_backend."""
        files = [
            path
            for path, *_rest in self.env["ir.asset"]._get_asset_paths(
                "web.assets_backend", {}
            )
        ]
        for name in self.OWL_FILES:
            with self.subTest(file=name):
                self.assertTrue(
                    any(path.endswith(self.STATIC + name) for path in files)
                )

    def _templates(self, name):
        root = etree.fromstring(self._source(name).encode())
        return {node.get("t-inherit"): node for node in root.xpath("/templates/t")}

    def test_owl_template_extensions(self):
        """Tablero, ventana de saldo y leyenda del calendario: extensiones (no
        copias) de las plantillas de hr_holidays con los textos de Ecuador."""
        dashboard = self._templates("dashboard/time_off_dashboard_patch.xml")
        legend = self._templates("views/calendar_filter_panel_patch.xml")
        expected = {
            "hr_holidays.TimeOffDashboard": (
                dashboard,
                ("Saldos por aprobar", "Ver mis saldos", "Ver saldos del empleado"),
            ),
            "hr_holidays.TimeOffCardPopover": (dashboard, ("Días otorgados:",)),
            "hr_holidays.CalendarFilterPanel": (legend, ("Aprobado",)),
        }
        for template, (templates, texts) in expected.items():
            with self.subTest(template=template):
                node = templates[template]
                self.assertEqual(node.get("t-inherit-mode"), "extension")
                content = _text(node)
                for text in texts:
                    self.assertIn(text, content)
        # Sin enlace para pedir saldo: el botón abre los saldos.
        board = dashboard["hr_holidays.TimeOffDashboard"]
        replaced = board.xpath(
            ".//xpath[@expr=\"//a[@t-on-click='newAllocationRequest']\"]"
        )
        self.assertEqual(replaced[0].get("position"), "replace")
        button = replaced[0].xpath(".//button")[0]
        self.assertEqual(button.get("type"), "button")
        self.assertEqual(button.get("t-on-click"), "erpOpenBalances")
        self.assertNotIn("newAllocationRequest", etree.tostring(button).decode())

    def test_owl_js_patches(self):
        """Título de la ventana de solicitud («Solicitar ausencia» /
        «Solicitud de ausencia») y apertura de saldos por patch()."""
        controller = self._source("views/calendar_controller_patch.js")
        self.assertIn("patch(TimeOffCalendarController.prototype", controller)
        self.assertIn('_t("Solicitar ausencia")', controller)
        self.assertIn('_t("Solicitud de ausencia")', controller)
        dashboard = self._source("dashboard/time_off_dashboard_patch.js")
        self.assertIn("patch(TimeOffDashboard.prototype", dashboard)
        self.assertIn("hr_holidays.hr_leave_allocation_action_my", dashboard)
        self.assertIn("erp_hr_holidays_ec.action_erp_vacation_periods", dashboard)
        # Las acciones que abre el tablero existen.
        self.env.ref("hr_holidays.hr_leave_allocation_action_my")
        self.env.ref("erp_hr_holidays_ec.action_erp_vacation_periods")
        number = self._source("fields/localized_number_field.js")
        self.assertIn('add("erp_localized_number"', number)
        self.assertIn("formatFloat", number)
