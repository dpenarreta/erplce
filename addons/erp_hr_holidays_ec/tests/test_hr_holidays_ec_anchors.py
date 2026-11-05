"""Anclajes de las herencias y textos traducibles (US-012, ronda 3; DEV-4).

- Cada xpath de las plantillas OWL heredadas y de las vistas heredadas del
  módulo encaja con un solo nodo de la plantilla o vista que extiende. Las
  vistas fallarían al instalar si no encajan, pero las plantillas OWL las
  aplica el navegador: un anclaje roto tras actualizar Odoo solo se vería en
  pantalla. Mismo patrón que erp_theme (test_templates_and_patches).
- Los textos de static/src (plantillas y _t()) están en inglés, traducidos en
  i18n/es.po, y ninguno choca con el mismo texto de otro módulo instalado (el
  navegador combina las traducciones de JS de todos los módulos en un único
  diccionario, sin orden fijo).
- Pendientes de QA-UX: sin «asignación» en columnas, filtros y menús de
  saldos; «Año de servicio» vacío o con ayuda; áreas táctiles de 44 px;
  estados vacíos en las acciones propias.
"""

import copy
import re

from lxml import etree

from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import file_open
from odoo.tools.translate import code_translations

MODULE = "erp_hr_holidays_ec"
STATIC = f"{MODULE}/static/src/"
OWN_PREFIX = f"/{STATIC}"
LANG = "es_EC"
OFFICER_GROUP = "hr_holidays.group_hr_holidays_user"
JS_FILES = (
    "dashboard/time_off_dashboard_patch.js",
    "fields/localized_number_field.js",
    "views/calendar_controller_patch.js",
)
XML_FILES = (
    "dashboard/time_off_dashboard_patch.xml",
    "fields/localized_number_field.xml",
    "views/calendar_filter_panel_patch.xml",
)
# Texto de un nodo de plantilla OWL: lo que el compilador pasa a _t().
_T_CALL = re.compile(r"""\b_t\(\s*(["'])((?:(?!\1).)+)\1""")


def _source(name):
    with file_open(STATIC + name) as source:
        return source.read()


def _template_terms(name):
    """Textos traducibles de una plantilla OWL (nodos de texto no vacíos)."""
    root = etree.fromstring(_source(name).encode())
    terms = set()
    for node in root.iter():
        if node is root:
            continue
        texts = [node.tail]
        # Ni el texto de los comentarios ni el valor de <attribute> (es
        # código: «state.allocationRequests»).
        if node.tag is not etree.Comment and node.tag != "attribute":
            texts.append(node.text)
        for text in texts:
            clean = " ".join((text or "").split())
            if clean:
                terms.add(clean)
    return terms


@tagged("post_install", "-at_install")
class TestHolidaysEcOwlAnchors(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bundle = cls.env["ir.qweb"]._get_asset_bundle(
            "web.assets_backend", js=True, css=True
        )

    def _templates(self):
        """{nombre: elemento} de las plantillas primarias del bundle y
        [(padre, elemento, url)] de las extensiones de este módulo."""
        primary = {}
        extensions = []
        for block in self.bundle.xml():
            if block["type"] == "templates":
                for element, _url, _inherit in block["templates"]:
                    primary[element.get("t-name")] = element
            else:
                for parent, elements in block["extensions"].items():
                    for element, url in elements:
                        if url.startswith(OWN_PREFIX):
                            extensions.append((parent, element, url))
        return primary, extensions

    def test_owl_template_anchors(self):
        """Cada xpath de las extensiones OWL encaja con un solo nodo de la
        plantilla del núcleo (hr_holidays de Odoo 18)."""
        primary, extensions = self._templates()
        self.assertEqual(
            sorted(parent for parent, _element, _url in extensions),
            [
                "hr_holidays.CalendarFilterPanel",
                "hr_holidays.TimeOffCardPopover",
                "hr_holidays.TimeOffDashboard",
            ],
        )
        checked = 0
        for parent, element, url in extensions:
            self.assertIn(parent, primary, f"{url}: falta la plantilla {parent}")
            core = etree.ElementTree(copy.deepcopy(primary[parent]))
            for xpath in element.iter("xpath"):
                with self.subTest(template=parent, expr=xpath.get("expr")):
                    self.assertEqual(len(core.xpath(xpath.get("expr"))), 1)
                    checked += 1
        self.assertEqual(checked, 5)

    def test_owl_js_patch_targets(self):
        """Los componentes que parchea el JS existen con los nombres y
        métodos que usa el patch (import y displayDialog del calendario)."""
        js_urls = {asset.url for asset in self.bundle.javascripts}
        for name in JS_FILES:
            self.assertIn(OWN_PREFIX + name, js_urls)
        imports = {
            "dashboard/time_off_dashboard_patch.js": (
                "@hr_holidays/dashboard/time_off_dashboard",
                "hr_holidays/static/src/dashboard/time_off_dashboard.js",
                ("export class TimeOffDashboard", "this.actionService"),
            ),
            "views/calendar_controller_patch.js": (
                "@hr_holidays/views/calendar/calendar_controller",
                "hr_holidays/static/src/views/calendar/calendar_controller.js",
                ("export class TimeOffCalendarController",),
            ),
        }
        for name, (module, core_path, needles) in imports.items():
            with self.subTest(patch=name):
                self.assertIn(f'from "{module}"', _source(name))
                with file_open(core_path) as core:
                    core_js = core.read()
                for needle in needles:
                    self.assertIn(needle, core_js)
        # CalendarController crea displayDialog en la instancia (lo envuelve
        # el patch después de super.setup()).
        with file_open("web/static/src/views/calendar/calendar_controller.js") as js:
            self.assertRegex(js.read(), r"this\.displayDialog\s*=")

    def test_owl_texts_translated(self):
        """Todo texto de las plantillas y de _t() tiene traducción es en
        i18n/es.po (código en inglés, pantalla en español)."""
        terms = set()
        for name in XML_FILES:
            terms |= _template_terms(name)
        for name in JS_FILES:
            terms |= {match[1] for match in _T_CALL.findall(_source(name))}
        self.assertEqual(
            terms,
            {
                "Absence request",
                "Approved time off",
                "Balances to approve",
                "Days granted:",
                "Number in local format",
                "Request an absence",
                "This employee has no vacation balance yet. Calculate it with "
                '"Calcular vacaciones" on the employee form.',
                "View employee balances",
                "View my balances",
                "You have no vacation balance yet.",
            },
        )
        messages = {
            message["id"]: message["string"]
            for message in code_translations.get_web_translations(MODULE, LANG)[
                "messages"
            ]
        }
        for term in terms:
            with self.subTest(term=term):
                self.assertTrue(messages.get(term), f"sin traducción: {term}")
                self.assertNotEqual(messages[term], term)
        self.assertEqual(messages["View my balances"], "Ver mis saldos")
        self.assertEqual(messages["Approved time off"], "Aprobado")
        self.assertEqual(messages["Request an absence"], "Solicitar ausencia")
        self.assertEqual(
            messages["You have no vacation balance yet."],
            "Aún no tiene saldo de vacaciones.",
        )

    def test_owl_terms_do_not_collide(self):
        """Ningún otro módulo instalado traduce los mismos textos (la
        traducción del cliente es un único diccionario global)."""
        own = {
            message["id"]
            for message in code_translations.get_web_translations(MODULE, LANG)[
                "messages"
            ]
        }
        self.assertTrue(own)
        modules = self.env["ir.module.module"].search(
            [("state", "=", "installed"), ("name", "!=", MODULE)]
        )
        for module in modules.mapped("name"):
            messages = code_translations.get_web_translations(module, LANG)["messages"]
            clash = own & {message["id"] for message in messages}
            self.assertFalse(clash, f"{module} también traduce {clash}")


@tagged("post_install", "-at_install")
class TestHolidaysEcViewAnchors(TransactionCase):
    def test_view_xpath_anchors(self):
        """Cada xpath de las vistas heredadas del módulo encaja con un solo
        nodo de la vista que extiende (con las demás herencias aplicadas)."""
        View = self.env["ir.ui.view"]
        data = self.env["ir.model.data"].search(
            [("module", "=", MODULE), ("model", "=", "ir.ui.view")]
        )
        views = View.browse(data.mapped("res_id")).filtered("inherit_id")
        self.assertGreaterEqual(len(views), 15)
        checked = 0
        for view in views:
            arch = etree.fromstring(view.arch)
            xpaths = arch.xpath("//xpath")
            self.assertTrue(xpaths, f"{view.xml_id}: herencia sin xpath")
            self.assertFalse(arch.xpath("//xpath[@position='replace']"))
            # Vista padre combinada con las demás herencias, sin esta: se
            # desactiva un momento (el test se deshace al terminar) porque
            # lo que añade la propia herencia también puede encajar con su
            # xpath (p. ej. su <span class="o_stat_text"> propio).
            view.active = False
            try:
                parent = etree.ElementTree(view.inherit_id._get_combined_arch())
            finally:
                view.active = True
            for xpath in xpaths:
                with self.subTest(view=view.xml_id, expr=xpath.get("expr")):
                    self.assertEqual(len(parent.xpath(xpath.get("expr"))), 1)
                    checked += 1
        self.assertGreater(checked, 50)


@tagged("post_install", "-at_install")
class TestHolidaysEcUxRound3(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.officer = new_test_user(
            cls.env,
            login="encargado_ausencias_r3",
            groups=f"base.group_user,{OFFICER_GROUP}",
        )
        cls.holidays_manager = new_test_user(
            cls.env,
            login="admin_ausencias_r3",
            groups="base.group_user,hr_holidays.group_hr_holidays_manager",
        )

    def _arch(self, model, view_type, ref, user=None):
        records = self.env[model].with_user(user or self.officer)
        result = records.get_views([(self.env.ref(ref).id, view_type)])
        return etree.fromstring(result["views"][view_type]["arch"])

    def test_no_allocation_term_in_columns_and_filters(self):
        """Columnas, filtros, menú del kanban y título de actividades de los
        saldos y de los tipos de ausencia sin «asignación»."""
        types = self._arch(
            "hr.leave.type",
            "list",
            "hr_holidays.view_holiday_status_normal_tree",
            self.holidays_manager,
        )
        strings = {
            field.get("name"): field.get("string") for field in types.xpath("//field")
        }
        self.assertEqual(strings["allocation_validation_type"], "Aprobación del saldo")
        self.assertEqual(strings["leave_validation_type"], "Aprobación de la solicitud")
        search = self._arch(
            "hr.leave.allocation",
            "search",
            "hr_holidays.view_hr_leave_allocation_filter",
        )
        self.assertEqual(
            search.xpath("//filter[@name='my_leaves']")[0].get("string"),
            "Mis saldos",
        )
        self.assertEqual(
            search.xpath("//filter[@name='year']")[0].get("help"),
            "Saldos vigentes hoy",
        )
        kanban = self._arch(
            "hr.leave.allocation",
            "kanban",
            "hr_holidays.hr_leave_allocation_view_kanban",
        )
        menu = kanban.xpath("//t[@t-name='menu']/a[@type='open']")
        self.assertEqual([a.get("t-if") for a in menu], ["false", "widget.editable"])
        self.assertEqual(" ".join(menu[1].itertext()).strip(), "Editar saldo")
        activity = self._arch(
            "hr.leave.allocation",
            "activity",
            "hr_holidays.hr_leave_allocation_view_activity",
        )
        self.assertEqual(activity.get("string"), "Saldos de vacaciones")

    def test_own_strings_without_allocation_term(self):
        """Los textos que escribe el módulo en sus vistas (atributos string,
        help, confirm, placeholder y textos) no dicen «asignación»."""
        data = self.env["ir.model.data"].search(
            [("module", "=", MODULE), ("model", "=", "ir.ui.view")]
        )
        for view in self.env["ir.ui.view"].browse(data.mapped("res_id")):
            arch = etree.fromstring(view.arch)
            texts = []
            for node in arch.iter():
                if node.tag is etree.Comment:
                    continue
                texts.append(node.text or "")
                texts.extend(
                    node.get(attr) or ""
                    for attr in ("string", "help", "confirm", "placeholder")
                )
                if node.tag == "attribute" and node.get("name") in (
                    "string",
                    "help",
                ):
                    texts.append(node.text or "")
            with self.subTest(view=view.xml_id):
                self.assertNotIn("asignaci", " ".join(texts).lower())

    def test_service_year_zero(self):
        """«Año de servicio» = 0: vacío en las listas (saldos manuales y
        vacaciones gozadas sin año) y con ayuda en los formularios."""
        allocations = self._arch(
            "hr.leave.allocation", "list", "hr_holidays.hr_leave_allocation_view_tree"
        )
        year = allocations.xpath("//field[@name='erp_service_year']")[0]
        self.assertEqual(year.get("invisible"), "not erp_auto_generated")
        self.assertIn("Vacío en los saldos manuales", year.get("help"))
        form = self._arch(
            "hr.leave.allocation",
            "form",
            "hr_holidays.hr_leave_allocation_view_form_manager",
        )
        for name in ("erp_service_year", "erp_auto_generated"):
            field = form.xpath(f"//field[@name='{name}']")[0]
            self.assertIn("periodo de vacaciones", field.get("help").lower())
        history_list = self._arch(
            "erp.hr.vacation.history",
            "list",
            "erp_hr_holidays_ec.erp_hr_vacation_history_view_list",
        )
        field = history_list.xpath("//field[@name='service_year']")[0]
        self.assertEqual(field.get("invisible"), "not service_year")
        self.assertIn("más antiguo", field.get("help"))
        history_form = self._arch(
            "erp.hr.vacation.history",
            "form",
            "erp_hr_holidays_ec.erp_hr_vacation_history_view_form",
        )
        field = history_form.xpath("//field[@name='service_year']")[0]
        self.assertIn("Vacío o 0", field.get("help"))
        # Una sola explicación (la ayuda del campo), sin nota repetida.
        texts = " ".join(" ".join(history_form.itertext()).split())
        self.assertNotIn("más antiguo", texts)
        self.assertEqual(
            history_form.xpath("//field[@name='identification']")[0].get("placeholder"),
            "Cédula o pasaporte",
        )

    def test_lists_fit_without_fixed_widths(self):
        """Listas de saldos y periodos sin anchos fijos (se desbordaban a
        1536 px); «Antes del sistema» opcional oculta; «Por aprobar» y
        «Caducados» opcionales visibles."""
        refs = (
            "erp_hr_holidays_ec.hr_leave_allocation_view_list_erp_periods",
            "hr_holidays.hr_leave_allocation_view_tree",
            "hr_holidays.hr_leave_allocation_view_tree_my",
        )
        for ref in refs:
            with self.subTest(view=ref):
                tree = self._arch("hr.leave.allocation", "list", ref)
                self.assertFalse(tree.xpath("//field[@width]"))
        periods = self._arch("hr.leave.allocation", "list", refs[0])
        optional = {
            field.get("name"): (field.get("string"), field.get("optional"))
            for field in periods.xpath("/list/field")
        }
        self.assertEqual(optional["erp_history_days"], ("Antes del sistema", "hide"))
        self.assertEqual(optional["erp_days_pending"], ("Por aprobar", "show"))
        self.assertEqual(optional["erp_days_expired"], ("Caducados", "show"))
        self.assertIsNone(optional["employee_id"][1])  # siempre visible
        history = periods.xpath("//field[@name='erp_history_days']")[0]
        self.assertIn("antes de usar el sistema", history.get("help"))
        mine = self._arch("hr.leave.allocation", "list", refs[2])
        year = mine.xpath("//field[@name='erp_service_year']")[0]
        self.assertEqual(year.get("optional"), "show")

    def test_core_help_overrides(self):
        """Ayudas «?» y placeholders del núcleo con «asignación», «tiempo
        personal» o en inglés, sustituidos en el tipo de ausencia y el
        saldo; búsqueda de saldos con «Tipo de ausencia» y «Vigentes»."""
        form = self._arch(
            "hr.leave.type",
            "form",
            "hr_holidays.edit_holiday_status_form",
            self.holidays_manager,
        )
        helps = {
            name: form.xpath(f"//field[@name='{name}']")[0].get("help")
            for name in (
                "requires_allocation",
                "employee_requests",
                "show_on_dashboard",
                "create_calendar_meeting",
            )
        }
        self.assertEqual(
            helps["requires_allocation"],
            "Sí: solo se puede pedir con saldo vigente. No: se puede pedir sin "
            "saldo.",
        )
        for name, text in helps.items():
            with self.subTest(field=name):
                lowered = text.lower()
                for word in ("asignaci", "tiempo personal", "allocation", "leave"):
                    self.assertNotIn(word, lowered)
        for ref in (
            "hr_holidays.hr_leave_allocation_view_form",
            "hr_holidays.hr_leave_allocation_view_form_manager",
        ):
            with self.subTest(view=ref):
                arch = self._arch("hr.leave.allocation", "form", ref)
                names = arch.xpath("//div[hasclass('oe_title')]//field[@name='name']")
                self.assertEqual(
                    names[0].get("placeholder"),
                    "Ej.: Vacaciones anuales (vigencia o sin límite)",
                )
                days = arch.xpath("//field[@name='number_of_days_display']")[0]
                self.assertIn("puede usar de este saldo", days.get("help"))
        search = self._arch(
            "hr.leave.allocation",
            "search",
            "hr_holidays.view_hr_leave_allocation_filter",
        )
        self.assertEqual(
            search.xpath("//filter[@name='group_type']")[0].get("string"),
            "Tipo de ausencia",
        )
        self.assertEqual(
            search.xpath("//filter[@name='year']")[0].get("string"), "Vigentes"
        )

    def test_dashboard_empty_message(self):
        """Tablero sin saldo: mensaje con aire arriba (pt-2) y, para un
        empleado, cómo calcularlo."""
        root = etree.fromstring(
            _source("dashboard/time_off_dashboard_patch.xml").encode()
        )
        message = root.xpath("//p[contains(@class, 'o_erp_no_balance')]")[0]
        self.assertIn("pt-2", message.get("class").split())
        employee = message.xpath("./t[@t-if='props.employeeId']")[0]
        self.assertIn('"Calcular vacaciones"', employee.text)
        messages = {
            item["id"]: item["string"]
            for item in code_translations.get_web_translations(MODULE, LANG)["messages"]
        }
        self.assertEqual(
            messages[" ".join(employee.text.split())],
            "El empleado aún no tiene saldo de vacaciones. Calcúlelo con "
            "«Calcular vacaciones» en su ficha.",
        )

    def test_mobile_touch_targets(self):
        """Botones propios de 44 x 44 px como mínimo en el celular."""
        bundle = self.env["ir.qweb"]._get_asset_bundle(
            "web.assets_backend", js=False, css=True
        )
        css = bundle.preprocess_css()
        self.assertFalse(bundle.css_errors, bundle.css_errors)
        match = re.search(
            r"@media \(max-width: 767\.98px\)\s*\{\s*"
            r"\.o_web_client \.o_erp_generate_vacations,\s*"
            r"\.o_web_client \.o_timeoff_dashboard \.o_erp_open_balances\s*"
            r"\{([^}]*)\}",
            css,
        )
        self.assertTrue(match, "faltan las reglas de 44 px del módulo")
        self.assertIn("min-width: 44px", match[1])
        self.assertIn("min-height: 44px", match[1])

    def test_own_actions_have_empty_state(self):
        """Las acciones de ventana propias del módulo tienen estado vacío
        con mensaje."""
        data = self.env["ir.model.data"].search(
            [("module", "=", MODULE), ("model", "=", "ir.actions.act_window")]
        )
        actions = self.env["ir.actions.act_window"].browse(data.mapped("res_id"))
        self.assertGreaterEqual(len(actions), 2)
        for action in actions:
            with self.subTest(action=action.xml_id):
                self.assertIn("o_view_nocontent_", action.help or "")
        periods = self.env.ref(f"{MODULE}.action_erp_vacation_periods")
        self.assertNotIn("(Acciones)", periods.help)
