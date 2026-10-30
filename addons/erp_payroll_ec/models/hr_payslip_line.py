from odoo import api, models

from .hr_payslip import PAYSLIP_SKIP_LINE_COPY_KEY


class HrPayslipLine(models.Model):
    _inherit = "hr.payslip.line"

    # ------------------------------------------------------------------
    # Integridad (US-008, CA-8)
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        slip_ids = {vals["slip_id"] for vals in vals_list if vals.get("slip_id")}
        self.env["hr.payslip"].browse(slip_ids)._erp_check_lines_editable()
        return super().create(vals_list)

    def write(self, vals):
        self.slip_id._erp_check_lines_editable()
        if vals.get("slip_id"):
            self.env["hr.payslip"].browse(vals["slip_id"])._erp_check_lines_editable()
        return super().write(vals)

    def unlink(self):
        self.slip_id._erp_check_lines_editable()
        return super().unlink()

    def copy(self, default=None):
        """Al duplicar un rol (``hr.payslip.copy`` fuera de un reembolso) las
        líneas calculadas no se copian: OCA copia cada línea después de crear
        el rol nuevo y aquí se omite mientras esté activo
        ``PAYSLIP_SKIP_LINE_COPY_KEY`` (indicador en ``cr.cache``)."""
        if self.env.cr.cache.get(PAYSLIP_SKIP_LINE_COPY_KEY):
            return self.browse()
        return super().copy(default)

    # ------------------------------------------------------------------
    # Contabilización (US-008, CA-10)
    # ------------------------------------------------------------------
    def _get_partner_id(self, credit_account):
        """Tercero del apunte de la línea.

        ``payroll_account`` pone al empleado en cuentas por cobrar y pasivos
        corrientes, y en cuentas por pagar (``liability_payable``) solo el
        tercero del registro de contribución de la regla. En el plan
        ``l10n_ec`` «Sueldos por pagar» (21070401) es una cuenta por pagar:
        sin registro de contribución, el tercero es el empleado (el neto se le
        debe a él).
        """
        partner_id = super()._get_partner_id(credit_account)
        if partner_id:
            return partner_id
        rule = self.salary_rule_id
        account = rule.account_credit if credit_account else rule.account_debit
        if account.account_type == "liability_payable" and not rule.register_id:
            return self.slip_id._erp_get_employee_partner().id
        return partner_id
