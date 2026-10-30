from odoo import models

from .hr_salary_rule import CHART_TEMPLATE_EC


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _post_load_data(self, template_code, company, template_data):
        """Tras cargar el plan ``ec`` en una empresa, asigna las cuentas por
        defecto a las reglas del rol de Ecuador (solo las vacías).

        Necesario porque, en una instalación nueva, ``erp_base`` difiere la
        carga del plan hasta después de los ``post_init_hook`` (ver
        ``erp_base/hooks.py``), y porque una empresa puede cargar el plan
        después de instalar este módulo.
        """
        res = super()._post_load_data(template_code, company, template_data)
        if template_code == CHART_TEMPLATE_EC:
            self.env["hr.salary.rule"]._erp_set_default_accounts(
                company or self.env.company
            )
        return res
