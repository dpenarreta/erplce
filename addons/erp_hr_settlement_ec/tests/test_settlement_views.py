"""Vistas, acciones y menús de la liquidación de haberes (US-013, CA-12,
CA-13, DEV-4).

La imagen de Odoo no trae Chrome: no hay tours. Se comprueba que las vistas
cargan (get_views) para el responsable y el usuario de nómina, qué botones ve
cada uno y en qué estados, los permisos de edición que el cliente web deduce
de la ACL y la visibilidad de los menús.
"""

from lxml import etree

from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

MODULE = "erp_hr_settlement_ec"
STATES = ("draft", "computed", "done", "cancel")


def _arch(model, view_type):
    result = model.get_views([(False, view_type)])
    return etree.fromstring(result["views"][view_type]["arch"])


def _denied(arch, operation):
    return arch.get(operation) in ("false", "False", "0")


def _buttons(arch, name):
    return arch.xpath(f"//header/button[@name='{name}']")


def _visible_states(button, record_id=1):
    """Estados en los que se ve el botón de un registro guardado (id) o,
    con ``record_id=False``, de uno nuevo sin guardar."""
    return {
        state
        for state in STATES
        if not safe_eval(
            button.get("invisible") or "False", {"state": state, "id": record_id}
        )
    }


@tagged("post_install", "-at_install")
class TestSettlementViews(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="responsable_nomina_liq_vistas",
            groups="base.group_user,payroll.group_payroll_manager",
        )
        cls.user = new_test_user(
            cls.env,
            login="usuario_nomina_liq_vistas",
            groups="base.group_user,payroll.group_payroll_user",
        )
        cls.internal = new_test_user(
            cls.env, login="interno_sin_nomina_liq_vistas", groups="base.group_user"
        )

    # ------------------------------------------------------------------
    # Carga de vistas y permisos
    # ------------------------------------------------------------------
    def test_views_load_and_access(self):
        for model_name, user_edits in (
            ("erp.hr.settlement", True),
            ("erp.hr.termination.cause", False),
            ("erp.hr.indemnity.bracket", False),
        ):
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
                    for operation in ("edit", "create", "delete"):
                        self.assertFalse(_denied(manager_arch, operation))
                        self.assertEqual(
                            _denied(user_arch, operation), not user_edits, operation
                        )

    def test_actions_have_empty_state_help(self):
        for xmlid in (
            "erp_hr_settlement_action",
            "erp_hr_termination_cause_action",
            "erp_hr_indemnity_bracket_action",
        ):
            with self.subTest(action=xmlid):
                action = self.env.ref(f"{MODULE}.{xmlid}")
                self.assertIn("o_view_nocontent", action.help)
        help_text = self.env.ref(f"{MODULE}.erp_hr_settlement_action").help
        self.assertIn("Calcular", help_text)
        # Mismo término que los mensajes del servidor.
        self.assertIn("responsable de nómina", help_text)
        self.assertNotIn("responsable de rol de pagos", help_text)
        bracket_help = self.env.ref(f"{MODULE}.erp_hr_indemnity_bracket_action").help
        self.assertIn("sin tope", bracket_help)

    # ------------------------------------------------------------------
    # Liquidación
    # ------------------------------------------------------------------
    def test_settlement_form_buttons_by_state_and_group(self):
        Settlement = self.env["erp.hr.settlement"]
        manager_arch = _arch(Settlement.with_user(self.manager), "form")
        user_arch = _arch(Settlement.with_user(self.user), "form")

        # Confirmar: solo el responsable, solo en calculada y con confirmación.
        self.assertFalse(_buttons(user_arch, "action_confirm"))
        confirm = _buttons(manager_arch, "action_confirm")
        self.assertEqual(len(confirm), 1)
        self.assertEqual(_visible_states(confirm[0]), {"computed"})
        self.assertTrue(confirm[0].get("confirm"))
        self.assertIn("btn-primary", confirm[0].get("class"))

        # Calcular (borrador, primario) y Recalcular (calculada): ambos perfiles.
        for arch in (manager_arch, user_arch):
            compute = _buttons(arch, "action_compute")
            self.assertEqual(len(compute), 2)
            self.assertEqual(
                {frozenset(_visible_states(b)) for b in compute},
                {frozenset({"draft"}), frozenset({"computed"})},
            )
            primary = [b for b in compute if "btn-primary" in (b.get("class") or "")]
            self.assertEqual(_visible_states(primary[0]), {"draft"})
            draft = _buttons(arch, "action_draft")
            self.assertEqual(_visible_states(draft[0]), {"computed", "cancel"})

        # Anular: el usuario solo en borrador/calculada; el responsable
        # además en confirmada, con aviso de reversión.
        user_cancel = _buttons(user_arch, "action_cancel")
        self.assertEqual(len(user_cancel), 1)
        self.assertEqual(_visible_states(user_cancel[0]), {"draft", "computed"})
        # Registro nuevo sin guardar: no hay nada que anular.
        self.assertFalse(_visible_states(user_cancel[0], record_id=False))
        manager_cancel = _buttons(manager_arch, "action_cancel")
        self.assertEqual(len(manager_cancel), 2)
        done_cancel = [b for b in manager_cancel if "done" in _visible_states(b)]
        self.assertEqual(len(done_cancel), 1)
        self.assertIn("revertirá", done_cancel[0].get("confirm"))

        # Imprimir: en calculada y confirmada.
        report = self.env.ref(f"{MODULE}.action_report_settlement")
        printing = _buttons(user_arch, str(report.id))
        self.assertEqual(len(printing), 1)
        self.assertEqual(_visible_states(printing[0]), {"computed", "done"})

        # Barra de estado con el flujo y estado no editable a mano.
        statusbar = user_arch.xpath("//header/field[@name='state']")[0]
        self.assertEqual(statusbar.get("widget"), "statusbar")
        self.assertEqual(statusbar.get("statusbar_visible"), "draft,computed,done")
        self.assertNotIn("clickable", statusbar.get("options") or "")

    def test_settlement_form_content(self):
        arch = _arch(self.env["erp.hr.settlement"].with_user(self.user), "form")
        # Aviso de la pestaña Rubros: en el celular «Calcular» está en ⚙.
        notice = arch.xpath("//page[@name='lines']/div[@role='note']")[0]
        self.assertIn("menú ⚙ Acciones", "".join(notice.itertext()))
        # Resumen de vacaciones en lugar de los periodos (hr.leave.allocation).
        self.assertFalse(arch.xpath("//field[@name='settled_allocation_ids']"))
        self.assertTrue(arch.xpath("//field[@name='settled_vacation_summary']"))
        self.assertTrue(arch.xpath("//field[@name='settled_vacation_days']"))
        # Antigüedad: texto del servidor, en lugar de la fila años/meses/días.
        service = arch.xpath("//group[@name='service']/field[@name='service_display']")
        self.assertEqual(len(service), 1)
        self.assertEqual(service[0].get("string"), "Antigüedad")
        for name in ("service_years", "service_months", "service_days"):
            self.assertFalse(arch.xpath(f"//field[@name='{name}']"), name)
        # Solo lectura siempre.
        for name in ("last_wage", "name"):
            field = arch.xpath(f"//sheet//field[@name='{name}']")[0]
            self.assertEqual(field.get("readonly"), "1", name)
        # Datos de la salida: bloqueados en confirmada o anulada.
        for name in ("employee_id", "contract_id", "cause_id", "date_departure"):
            field = arch.xpath(f"//group[@name='departure']/field[@name='{name}']")[0]
            for state, locked in (
                ("draft", False),
                ("computed", False),
                ("done", True),
                ("cancel", True),
            ):
                self.assertEqual(
                    bool(safe_eval(field.get("readonly"), {"state": state})),
                    locked,
                    f"{name} en {state}",
                )
        # Rubros: solo se añaden otros ingresos u otros descuentos manuales.
        lines = arch.xpath("//field[@name='line_ids']")[0]
        creates = lines.xpath("./list/control/create")
        contexts = [safe_eval(create.get("context")) for create in creates]
        self.assertEqual(
            sorted(ctx["default_code"] for ctx in contexts),
            ["OTHER_DEDUCTION", "OTHER_INCOME"],
        )
        self.assertTrue(all(ctx["default_is_manual"] for ctx in contexts))
        self.assertTrue(safe_eval(lines.get("readonly"), {"state": "done"}))
        self.assertFalse(safe_eval(lines.get("readonly"), {"state": "computed"}))
        self.assertTrue(lines.xpath("./list/field[@name='explanation']"))
        # Rubros calculados: solo lectura en el diálogo; manuales editables.
        form = lines.xpath("./form")[0]
        for name in ("name", "amount", "base", "quantity", "explanation"):
            field = form.xpath(f".//field[@name='{name}']")[0]
            self.assertTrue(safe_eval(field.get("readonly"), {"is_manual": False}))
            self.assertFalse(safe_eval(field.get("readonly"), {"is_manual": True}))
        code = form.xpath(".//field[@name='code']")[0]
        self.assertEqual((code.get("readonly"), code.get("force_save")), ("1", "1"))
        account = form.xpath(".//field[@name='account_id']")[0]
        self.assertTrue(safe_eval(account.get("invisible"), {"is_manual": False}))
        # Totales, chatter y diario oculto a quien no es de contabilidad.
        for name in ("total_income", "total_deduction", "net"):
            self.assertTrue(
                arch.xpath(f"//group[@name='totals']/field[@name='{name}']")
            )
        self.assertTrue(arch.xpath("//chatter"))
        self.assertFalse(arch.xpath("//field[@name='journal_id']"))

    def test_settlement_list_and_search(self):
        Settlement = self.env["erp.hr.settlement"].with_user(self.user)
        list_arch = _arch(Settlement, "list")
        state = list_arch.xpath("//field[@name='state']")[0]
        self.assertEqual(state.get("widget"), "badge")
        self.assertTrue(list_arch.xpath("//field[@name='net'][@sum]"))
        departure = list_arch.xpath("//field[@name='date_departure']")[0]
        self.assertEqual(departure.get("string"), "Salida")
        search_arch = _arch(Settlement, "search")
        for name in ("draft", "computed", "done", "cancel", "date_departure"):
            self.assertTrue(search_arch.xpath(f"//filter[@name='{name}']"), name)
        for name in ("group_by_state", "group_by_cause", "group_by_employee"):
            self.assertTrue(search_arch.xpath(f"//filter[@name='{name}']"), name)
        for name in ("employee_id", "cause_id"):
            self.assertTrue(search_arch.xpath(f"/search/field[@name='{name}']"), name)

    # ------------------------------------------------------------------
    # Causas y tramos (CA-12)
    # ------------------------------------------------------------------
    def test_validation_buttons_like_parameters(self):
        for model_name in ("erp.hr.termination.cause", "erp.hr.indemnity.bracket"):
            with self.subTest(model=model_name):
                manager_arch = _arch(
                    self.env[model_name].with_user(self.manager), "form"
                )
                user_arch = _arch(self.env[model_name].with_user(self.user), "form")
                validate = _buttons(manager_arch, "action_validate")
                self.assertEqual(len(validate), 1)
                self.assertTrue(validate[0].get("confirm"))
                self.assertTrue(_buttons(manager_arch, "action_set_to_validate"))
                self.assertFalse(_buttons(user_arch, "action_validate"))
                self.assertFalse(_buttons(user_arch, "action_set_to_validate"))
                state = manager_arch.xpath("//header/field[@name='state']")[0]
                self.assertEqual(state.get("widget"), "statusbar")
                list_state = _arch(
                    self.env[model_name].with_user(self.manager), "list"
                ).xpath("//field[@name='state']")[0]
                self.assertEqual(list_state.get("widget"), "badge")
                search_arch = _arch(
                    self.env[model_name].with_user(self.manager), "search"
                )
                self.assertTrue(search_arch.xpath("//filter[@name='to_validate']"))

    def test_cause_form_shows_items(self):
        arch = _arch(
            self.env["erp.hr.termination.cause"].with_user(self.manager), "form"
        )
        for name in (
            "pays_thirteenth",
            "pays_fourteenth",
            "pays_pending_vacation",
            "pays_proportional_vacation",
            "pays_severance_bonus",
            "pays_unfair_dismissal_indemnity",
        ):
            self.assertTrue(arch.xpath(f"//group[@name='items']/field[@name='{name}']"))
        # Código técnico: siempre en modo desarrollador; fuera de él solo al
        # crear (es obligatorio y el modelo no lo genera).
        codes = arch.xpath("//field[@name='code']")
        self.assertEqual(len(codes), 1)
        self.assertEqual(codes[0].get("invisible"), "id")
        self.assertIn("DESPIDO_INTEMPESTIVO", codes[0].get("placeholder"))
        # base.group_no_one depende del modo desarrollador de la sesión (sin
        # petición HTTP, get_views lo ignora): se comprueba la vista guardada.
        view = self.env.ref(f"{MODULE}.erp_hr_termination_cause_view_form")
        raw = etree.fromstring(view.arch_db)
        dev = raw.xpath("//field[@name='code'][@groups='base.group_no_one']")
        self.assertEqual(len(dev), 1)
        self.assertFalse(dev[0].get("invisible"))
        fallback = raw.xpath("//field[@name='code'][@groups='!base.group_no_one']")
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0].get("invisible"), "id")
        # Las causas cargadas se ven en la acción y empiezan «A validar».
        causes = self.env["erp.hr.termination.cause"].with_user(self.manager).search([])
        self.assertTrue(causes)
        self.assertIn("to_validate", causes.mapped("state"))

    # ------------------------------------------------------------------
    # Ajustes y menús
    # ------------------------------------------------------------------
    def test_settings_accounts(self):
        arch = _arch(self.env["res.config.settings"], "form")
        block = arch.xpath("//block[@id='erp_settlement_accounts']")
        self.assertEqual(len(block), 1)
        for name in (
            "erp_settlement_vacation_account_id",
            "erp_settlement_severance_account_id",
            "erp_settlement_indemnity_account_id",
            "erp_settlement_payable_account_id",
        ):
            field = block[0].xpath(f".//field[@name='{name}']")
            self.assertTrue(field, name)
            # El marcador no debe parecer una cuenta elegida.
            self.assertTrue(
                field[0].get("placeholder", "").startswith("Por defecto:"), name
            )
            # Ancho completo para que el marcador no se corte.
            self.assertTrue(
                {"col-lg-8", "w-100"} & set(field[0].get("class", "").split()), name
            )
        help_text = (
            block[0]
            .xpath(".//setting[@id='erp_settlement_expense_accounts']")[0]
            .get("help")
        )
        for code in ("52020303", "52020304", "52020305"):
            self.assertIn(code, help_text)

    def test_menus_by_group(self):
        Menu = self.env["ir.ui.menu"]
        root = self.env.ref("payroll.payroll_menu_root")
        configuration = self.env.ref("payroll.payroll_menu_configuration")
        settlement = self.env.ref(f"{MODULE}.erp_hr_settlement_menu")
        cause = self.env.ref(f"{MODULE}.erp_hr_termination_cause_menu")
        bracket = self.env.ref(f"{MODULE}.erp_hr_indemnity_bracket_menu")
        self.assertEqual(settlement.parent_id, root)
        self.assertEqual(cause.parent_id, configuration)
        self.assertEqual(bracket.parent_id, configuration)
        self.assertEqual(settlement.name, "Liquidaciones")
        self.assertEqual(cause.name, "Causas de salida")
        self.assertEqual(bracket.name, "Tramos de indemnización")

        visible = Menu.with_user(self.manager)._visible_menu_ids()
        self.assertTrue({settlement.id, cause.id, bracket.id} <= visible)
        visible = Menu.with_user(self.user)._visible_menu_ids()
        self.assertIn(settlement.id, visible)
        self.assertNotIn(cause.id, visible)
        self.assertNotIn(bracket.id, visible)
        visible = Menu.with_user(self.internal)._visible_menu_ids()
        self.assertFalse({settlement.id, cause.id, bracket.id} & visible)

    # ------------------------------------------------------------------
    # Listas de configuración (QA-UX, ronda 1)
    # ------------------------------------------------------------------
    def test_cause_list_short_headers(self):
        arch = _arch(
            self.env["erp.hr.termination.cause"].with_user(self.manager), "list"
        )
        code = arch.xpath("//field[@name='code']")[0]
        self.assertEqual(code.get("optional"), "hide")
        headers = {
            "pays_thirteenth": "13.º",
            "pays_fourteenth": "14.º",
            "pays_pending_vacation": "Vac. pend.",
            "pays_proportional_vacation": "Vac. prop.",
            "pays_severance_bonus": "Desahucio",
            "pays_unfair_dismissal_indemnity": "Indemniz.",
        }
        for name, string in headers.items():
            field = arch.xpath(f"//field[@name='{name}']")[0]
            self.assertEqual(field.get("string"), string, name)

    def test_bracket_list_short_headers_and_no_limit(self):
        Bracket = self.env["erp.hr.indemnity.bracket"].with_user(self.manager)
        arch = _arch(Bracket, "list")
        headers = {
            "date_from": "Vigente desde",
            "years_from": "Más de (años)",
            "years_to": "Hasta (años)",
            "fixed_months": "Meses fijos",
            "months_per_year": "Meses/año",
            "min_months": "Mín. meses",
            "max_months": "Máx. meses",
        }
        for name, string in headers.items():
            field = arch.xpath(f"//field[@name='{name}']")[0]
            self.assertEqual(field.get("string"), string, name)
        # 0 = sin tope: widget propio en lista y formulario.
        form_arch = _arch(Bracket, "form")
        for view_arch in (arch, form_arch):
            for name, widget in (
                ("years_to", "erp_no_limit_integer"),
                ("max_months", "erp_no_limit_float"),
            ):
                field = view_arch.xpath(f"//field[@name='{name}']")[0]
                self.assertEqual(field.get("widget"), widget, name)
        # «Más de (años)» con ancho suficiente para no cortarse.
        self.assertTrue(arch.xpath("//field[@name='years_from']")[0].get("width"))
        # En edición el campo muestra 0: el formulario dice «Sin tope» al lado.
        for name in ("years_to", "max_months"):
            hint = form_arch.xpath(
                f"//field[@name='{name}']/following-sibling::span[@invisible='{name}']"
            )
            self.assertEqual(len(hint), 1, name)
            self.assertEqual(hint[0].text, "Sin tope")

    def test_no_limit_widget_in_backend_assets(self):
        """El widget «Sin tope» está en el bundle del cliente web y se
        transpila como módulo de Odoo con sus dos registros."""
        bundle = self.env["ir.qweb"]._get_asset_bundle(
            "web.assets_backend", js=True, css=False
        )
        own = [
            asset
            for asset in bundle.javascripts
            if asset.url.startswith(f"/{MODULE}/static/src/fields/")
        ]
        self.assertEqual(len(own), 1)
        code = own[0].minify()
        self.assertIn("odoo.define(", code)
        self.assertNotIn("throw new Error", code)
        for text in ("erp_no_limit_integer", "erp_no_limit_float", "Sin tope"):
            self.assertIn(text, code)

    def test_benefit_payment_menu_order(self):
        """Pago de décimos (35) queda entre Liquidaciones (30) y Bonos y
        descuentos asignados (40)."""
        settlement = self.env.ref(f"{MODULE}.erp_hr_settlement_menu")
        benefit = self.env.ref("erp_payroll_ec.erp_payroll_ec_menu_benefit_payment")
        assigned = self.env.ref("erp_payroll_ec.erp_payroll_ec_menu_employee_concept")
        self.assertLess(settlement.sequence, benefit.sequence)
        self.assertLess(benefit.sequence, assigned.sequence)
