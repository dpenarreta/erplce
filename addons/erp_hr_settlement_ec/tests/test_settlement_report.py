"""PDF de la liquidación de haberes (US-013, CA-11, DEV-4).

Se renderiza el informe QWeb en HTML (``_render_qweb_html``: la misma
plantilla que el PDF, sin depender de wkhtmltopdf) para una liquidación de
prueba con un rubro calculado y otro manual, y se comprueban los textos clave:
empresa, trabajador (cédula y cargo), relación laboral, rubros con su
explicación, totales, firmas y la marca «BORRADOR» / «ANULADA».

Valores FICTICIOS de prueba. Los rubros se crean directamente en borrador (el
cálculo lo cubre test_settlement_flow); el estado confirmado o anulado se
fija con sudo (``env.su``), como lo harían las acciones del negocio.
"""

import re
from datetime import date

from odoo.tests import tagged

from odoo.addons.erp_payroll_ec.tests.common import PayrollEcCase

MODULE = "erp_hr_settlement_ec"
REPORT = f"{MODULE}.report_settlement"
# Cédula ecuatoriana válida de prueba (provincia 17, dígito verificador 5).
CEDULA = "1710034065"


@tagged("post_install", "-at_install")
class TestSettlementReport(PayrollEcCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls._employee(
            "Ñusta Cañar Peña",
            identification_id=CEDULA,
            job_title="Mensajera motorizada",
            erp_company_entry_date=date(2023, 3, 15),
        )
        cls.contract = cls._contract(
            cls.employee, wage=1200.0, date_start=date(2023, 3, 15)
        )
        cls.cause = cls.env.ref(f"{MODULE}.cause_unfair_dismissal")
        cls.settlement = cls.env["erp.hr.settlement"].create(
            {
                "employee_id": cls.employee.id,
                "contract_id": cls.contract.id,
                "date_departure": date(2026, 4, 15),
                "cause_id": cls.cause.id,
                "last_wage": 1200.0,
            }
        )
        cls.env["erp.hr.settlement.line"].create(
            [
                {
                    "settlement_id": cls.settlement.id,
                    "code": "D13",
                    "name": "Décimo tercero pendiente",
                    "sequence": 10,
                    "base": 100.0,
                    "quantity": 11.5,
                    "amount": 1150.0,
                    "explanation": "Provisiones no pagadas de mayo de 2025 a "
                    "abril de 2026.\nAbril: 15 días.",
                },
                {
                    "settlement_id": cls.settlement.id,
                    "code": "OTHER_DEDUCTION",
                    "name": "Anticipo de sueldo",
                    "sequence": 90,
                    "amount": 150.0,
                    "is_manual": True,
                    "explanation": "Anticipo entregado el 10/03/2026.",
                },
            ]
        )

    def _html(self, settlement=None, user=None):
        settlement = settlement or self.settlement
        Report = self.env["ir.actions.report"].with_user(user or self.payroll_user)
        html, report_type = Report._render_qweb_html(REPORT, settlement.ids)
        self.assertEqual(report_type, "html")
        return html.decode()

    def assertAmount(self, html, integer, cents="00"):
        """Importe con 2 decimales en el formato del idioma (separador de
        miles y decimal según el idioma del usuario)."""
        thousands, units = divmod(integer, 1000)
        number = rf"{thousands}[.,\s]?{units:03d}" if thousands else str(units)
        self.assertRegex(html, re.compile(rf"(?<![\d.,]){number}[.,]{cents}(?!\d)"))

    def test_report_action(self):
        action = self.env.ref(f"{MODULE}.action_report_settlement")
        self.assertEqual(action.report_type, "qweb-pdf")
        self.assertEqual(action.report_name, REPORT)
        self.assertEqual(action.model, "erp.hr.settlement")
        # Sin entrada en el menú Imprimir / ⚙ (salía también en borrador y en
        # registros nuevos): solo el botón «Imprimir» de la cabecera.
        self.assertFalse(action.binding_model_id)
        self.assertEqual(action.paperformat_id.format, "A4")
        self.assertIn(self.env.ref("payroll.group_payroll_user"), action.groups_id)

    def test_report_draft_content(self):
        self.assertEqual(self.settlement.net, 1000.0)
        html = self._html()
        expected = [
            # Marca y estado.
            "ERP <span>LCE</span>",
            "LIQUIDACIÓN DE HABERES",
            "BORRADOR",
            "Sin número",
            # Empleador.
            "Razón social",
            self.company.name,
            "RUC",
            # Trabajador.
            "Ñusta Cañar Peña",
            CEDULA,
            "Mensajera motorizada",
            # Relación laboral.
            "Fecha de ingreso",
            "Fecha de salida",
            "Antigüedad",
            "Despido intempestivo",
            "Última remuneración",
            # Rubros con su explicación.
            "Décimo tercero pendiente",
            "Provisiones no pagadas de mayo de 2025 a abril de 2026.",
            "Anticipo de sueldo",
            "Anticipo entregado el 10/03/2026.",
            # Totales con su título (contexto si caen al inicio de página).
            "Resumen de la liquidación",
            "Total ingresos",
            "Total descuentos",
            "Neto a recibir",
            # Firmas.
            "Empleador",
            "Trabajador",
            "o_erp_signature_line",
            "Lugar y fecha:",
            # Aviso y estado en el pie de cada página.
            "responsable de nómina la confirme",
            "o_erp_footer_status",
        ]
        for text in expected:
            with self.subTest(text=text):
                self.assertIn(text, html)
        for integer in (1150, 150, 1000, 1200):
            self.assertAmount(html, integer)
        if self.company.vat:
            self.assertIn(self.company.vat, html)
        # Tiempo de servicio: 3 años, 1 mes y 1 día (15/03/2023-15/04/2026).
        self.assertRegex(html, r"3\s+años,\s+1\s+mes\s+y\s+1\s+día")
        self.assertNotIn("ANULADA", html)
        self.assertNotIn("responsable de rol de pagos", html)
        # Marca de agua (primera página) y estado en el encabezado y el pie
        # de cada página.
        self.assertIn("o_erp_watermark", html)
        self.assertIn("o_erp_header_status", html)
        self.assertIn("Sin validez para firma", html)

    def test_report_done_without_draft_mark(self):
        self.settlement.sudo().write({"state": "done", "name": "LIQ/2026/0001"})
        html = self._html()
        self.assertIn("LIQ/2026/0001", html)
        self.assertNotIn("BORRADOR", html)
        self.assertNotIn("ANULADA", html)
        self.assertNotIn("o_erp_watermark", html)
        self.assertNotIn("o_erp_footer_status", html)
        self.assertNotIn("o_erp_header_status", html)
        # El encabezado existe siempre (vacío): Odoo empareja encabezados y
        # documentos por posición al imprimir varias liquidaciones.
        self.assertIn("o_erp_settlement_header", html)

    def test_report_cancelled_mark(self):
        self.settlement.sudo().write({"state": "cancel"})
        html = self._html(user=self.payroll_manager)
        self.assertIn("ANULADA", html)
        self.assertNotIn("BORRADOR", html)

    def test_report_without_lines(self):
        employee = self._employee("Empleado Sin Rubros")
        contract = self._contract(employee, date_start=date(2024, 1, 1))
        settlement = self.env["erp.hr.settlement"].create(
            {
                "employee_id": employee.id,
                "contract_id": contract.id,
                "date_departure": date(2026, 4, 15),
                "cause_id": self.cause.id,
            }
        )
        html = self._html(settlement)
        self.assertIn("Sin rubros: la liquidación aún no se ha calculado.", html)
        self.assertIn("Empleado Sin Rubros", html)


@tagged("post_install", "-at_install")
class TestSettlementReportAssets(PayrollEcCase):
    """Estilos del PDF con los colores de erp_branding (QA-UX, ronda 1)."""

    def test_report_styles_use_brand_colors(self):
        bundle = self.env["ir.qweb"]._get_asset_bundle(
            "web.report_assets_common", js=False, css=True
        )
        css = bundle.preprocess_css().lower()
        self.assertFalse(list(bundle.css_errors), bundle.css_errors)
        self.assertIn(".o_erp_settlement_report", css)
        start = css.index(".o_erp_settlement_report")
        own = css[start:]
        # Gris atenuado de la marca (#5c636a), no el gris propio anterior.
        self.assertIn("#5c636a", own)
        self.assertNotIn("#4d4d4d", own)
        self.assertIn("#fce200", own)
        module = self.env["ir.module.module"].search([("name", "=", MODULE)])
        self.assertIn("erp_branding", module.dependencies_id.mapped("name"))
