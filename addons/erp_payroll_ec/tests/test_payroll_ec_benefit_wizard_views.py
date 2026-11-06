"""Vistas y menú del asistente «Pago de décimos», campo «Décimo que paga» del
rol de pagos y casilla «Cuenta como remuneración» de los conceptos (US-013,
CA-13, CA-14, DEV-4).

La imagen de Odoo no trae Chrome: no hay tours. Se comprueba la carga de la
vista (get_views), la visibilidad por grupo del menú y de la acción, y el
comportamiento del formulario con odoo.tests.Form como en el cliente web.
"""

from lxml import etree

from odoo.tests import Form, TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

WIZARD = "erp.payroll.benefit.payment.wizard"


@tagged("post_install", "-at_install")
class TestPayrollEcBenefitWizardViews(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="responsable_nomina_decimos_vistas",
            groups="base.group_user,payroll.group_payroll_manager",
        )
        cls.user = new_test_user(
            cls.env,
            login="usuario_nomina_decimos_vistas",
            groups="base.group_user,payroll.group_payroll_user",
        )
        cls.menu = cls.env.ref("erp_payroll_ec.erp_payroll_ec_menu_benefit_payment")
        cls.action = cls.env.ref(
            "erp_payroll_ec.erp_payroll_benefit_payment_wizard_action"
        )

    def _arch(self, user, model=WIZARD, view_type="form"):
        result = self.env[model].with_user(user).get_views([(False, view_type)])
        return etree.fromstring(result["views"][view_type]["arch"])

    def test_menu_and_action(self):
        self.assertEqual(self.menu.parent_id, self.env.ref("payroll.payroll_menu_root"))
        self.assertEqual(self.menu.action, self.action)
        self.assertEqual(self.action.target, "new")
        self.assertEqual(self.action.name, "Pago de décimos")
        Menu = self.env["ir.ui.menu"]
        self.assertIn(self.menu.id, Menu.with_user(self.manager)._visible_menu_ids())
        self.assertNotIn(self.menu.id, Menu.with_user(self.user)._visible_menu_ids())

    def test_wizard_form_content(self):
        arch = self._arch(self.manager)
        regime = arch.xpath("//field[@name='regime']")[0]
        self.assertEqual(regime.get("widget"), "radio")
        # Régimen solo para el décimo cuarto, y obligatorio en ese caso.
        self.assertTrue(safe_eval(regime.get("invisible"), {"benefit": "thirteenth"}))
        self.assertFalse(safe_eval(regime.get("invisible"), {"benefit": "fourteenth"}))
        self.assertTrue(safe_eval(regime.get("required"), {"benefit": "fourteenth"}))
        # Año sin separador de miles («2026», no «2.026»): opción del
        # IntegerField de Odoo 18 (enable_formatting; «format» no existe).
        year = arch.xpath("//field[@name='year']")[0]
        self.assertEqual(safe_eval(year.get("options")), {"enable_formatting": False})
        # Radios: sin etiqueta automática (su «for» no apuntaría a ninguna
        # entrada del widget); texto de etiqueta visible y nombre accesible
        # del grupo con el atributo string (aria-label del radiogroup).
        for name, label in (("benefit", "Décimo"), ("regime", "Régimen")):
            field = arch.xpath(f"//field[@name='{name}']")[0]
            self.assertEqual(field.get("nolabel"), "1", name)
            self.assertEqual(field.get("string"), label, name)
            self.assertFalse(arch.xpath(f"//label[@for='{name}']"), name)
            self.assertTrue(
                arch.xpath(
                    f"//span[contains(@class, 'o_td_label')]"
                    f"/span[contains(@class, 'o_form_label')][text()='{label}']"
                ),
                name,
            )
        regime_label = arch.xpath(
            "//span[contains(@class, 'o_td_label')][span[text()='Régimen']]"
        )[0]
        self.assertEqual(regime_label.get("invisible"), regime.get("invisible"))
        # Botón primario oculto mientras haya un aviso de periodo.
        button = arch.xpath("//footer/button[@name='action_generate']")[0]
        self.assertIn("btn-primary", button.get("class"))
        self.assertTrue(safe_eval(button.get("invisible"), {"period_message": "x"}))
        self.assertFalse(safe_eval(button.get("invisible"), {"period_message": False}))
        self.assertTrue(arch.xpath("//footer/button[@special='cancel']"))
        # Campos de resultado: no se muestran (la acción cierra el asistente).
        for name in ("created_count", "skipped_count", "summary", "payslip_run_id"):
            self.assertFalse(arch.xpath(f"//field[@name='{name}']"), name)
        # El diario solo para usuarios de contabilidad.
        self.assertFalse(arch.xpath("//field[@name='journal_id']"))

    def test_wizard_form_regime_message(self):
        """Décimo cuarto sin régimen: el formulario muestra el aviso en
        español en lugar del periodo."""
        # Sin guardar: el asistente solo se usa con su botón.
        wizard = Form(self.env[WIZARD].with_user(self.manager))
        wizard.benefit = "fourteenth"
        self.assertIn("régimen", wizard.period_message)
        self.assertFalse(wizard.date_start)
        wizard.regime = "sierra_amazonia"
        self.assertEqual(wizard.pay_code, "D14_ACC_PAY_SIERRA")

    def test_payslip_form_benefit_pay_code(self):
        arch = self._arch(self.user, model="hr.payslip")
        field = arch.xpath("//field[@name='erp_benefit_pay_code']")
        self.assertEqual(len(field), 1)
        self.assertEqual(field[0].get("readonly"), "1")
        self.assertTrue(
            safe_eval(field[0].get("invisible"), {"erp_benefit_pay_code": False})
        )


@tagged("post_install", "-at_install")
class TestPayrollEcConceptRemunerationView(TransactionCase):
    """Casilla «Cuenta como remuneración» de los conceptos (US-013, CA-14):
    solo en los conceptos de ingreso, en el formulario y como columna
    opcional (oculta por defecto) en la lista."""

    def _arch(self, view_type):
        result = self.env["erp.payroll.concept"].get_views([(False, view_type)])
        return etree.fromstring(result["views"][view_type]["arch"])

    def test_concept_form_remuneration(self):
        arch = self._arch("form")
        field = arch.xpath("//group[@name='bases']/field[@name='erp_is_remuneration']")
        self.assertEqual(len(field), 1)
        invisible = field[0].get("invisible")
        self.assertTrue(safe_eval(invisible, {"concept_type": "deduction"}))
        self.assertFalse(safe_eval(invisible, {"concept_type": "income"}))

    def test_concept_list_remuneration(self):
        arch = self._arch("list")
        field = arch.xpath("//field[@name='erp_is_remuneration']")
        self.assertEqual(len(field), 1)
        self.assertEqual(field[0].get("optional"), "hide")
        invisible = field[0].get("invisible")
        self.assertTrue(safe_eval(invisible, {"concept_type": "deduction"}))
        self.assertFalse(safe_eval(invisible, {"concept_type": "income"}))
