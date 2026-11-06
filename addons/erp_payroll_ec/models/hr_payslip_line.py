from odoo import api, fields, models
from odoo.tools import SQL

from .const import PROVISION_RULE_CODES
from .hr_payslip import PAYSLIP_SKIP_LINE_COPY_KEY

# Índice parcial para buscar provisiones de décimos pendientes (US-013): por
# empleado, código y mes, solo sobre las líneas de provisión (una pequeña
# parte de hr_payslip_line). Lo usan el pago de décimos acumulados y la
# liquidación (``_erp_get_pending_provision_lines``).
PAYSLIP_LINE_PROVISION_INDEX = "hr_payslip_line_erp_provision_idx"


class HrPayslipLine(models.Model):
    _inherit = "hr.payslip.line"

    # Marca de provisión pagada (US-013, CA-3): como mucho un registro por
    # línea (restricción UNIQUE en erp.payroll.provision.payment).
    erp_provision_payment_ids = fields.One2many(
        "erp.payroll.provision.payment",
        "payslip_line_id",
        string="Pago de la provisión",
        readonly=True,
        groups="payroll.group_payroll_user",
        help="Documento (rol de pago de décimos o liquidación) que pagó esta "
        "provisión. Vacío: pendiente de pago.",
    )

    def init(self):
        """Crea ``PAYSLIP_LINE_PROVISION_INDEX`` (idempotente)."""
        res = super().init()
        self.env.cr.execute(
            SQL(
                "CREATE INDEX IF NOT EXISTS %s ON %s (employee_id, code, date_from) "
                "WHERE code IN %s",
                SQL.identifier(PAYSLIP_LINE_PROVISION_INDEX),
                SQL.identifier(self._table),
                PROVISION_RULE_CODES,
            )
        )
        return res

    # ------------------------------------------------------------------
    # Provisiones de décimos pendientes de pago (US-013, CA-1 a CA-3, CA-6)
    # ------------------------------------------------------------------
    @api.model
    def _erp_pending_provision_domain(
        self, codes, employees=None, date_from=None, date_to=None
    ):
        """Dominio de las líneas de provisión pendientes de pago.

        Pendiente = línea con código de ``codes`` de un rol confirmado
        (``done``), que no es un reembolso ni un rol reembolsado (salvo que su
        reembolso esté anulado) y sin marca de pago
        (``erp.payroll.provision.payment``).

        :param codes: iterable de códigos de ``PROVISION_RULE_CODES``
        :param employees: ``hr.employee`` (``None``: todos)
        :param date_from: primer mes incluido (``date_from`` del rol >= este
            valor); ``None``: sin límite
        :param date_to: último día incluido (``date_from`` del rol <= este
            valor); ``None``: sin límite
        :raises ValueError: código que no es de provisión
        """
        codes = list(codes)
        unknown = set(codes) - set(PROVISION_RULE_CODES)
        if unknown:
            raise ValueError(f"Códigos de provisión desconocidos: {sorted(unknown)}")
        domain = [
            ("code", "in", codes),
            ("slip_id.state", "=", "done"),
            ("slip_id.credit_note", "=", False),
            "|",
            ("slip_id.refunded_id", "=", False),
            ("slip_id.refunded_id.state", "=", "cancel"),
            ("erp_provision_payment_ids", "=", False),
        ]
        if employees is not None:
            domain.append(("employee_id", "in", employees.ids))
        if date_from:
            domain.append(("date_from", ">=", fields.Date.to_date(date_from)))
        if date_to:
            domain.append(("date_from", "<=", fields.Date.to_date(date_to)))
        return domain

    @api.model
    def _erp_get_pending_provision_lines(
        self, codes, employees=None, date_from=None, date_to=None
    ):
        """Líneas de provisión pendientes de pago (una sola búsqueda, en
        lote para varios empleados), ordenadas por empleado y mes.

        Se ejecuta con los permisos del usuario (ACL y reglas multiempresa de
        ``hr.payslip.line``); si la capa de negocio necesita verlas todas,
        debe llamarla con ``sudo()`` y justificarlo.

        :return: ``hr.payslip.line``
        """
        return self.search(
            self._erp_pending_provision_domain(codes, employees, date_from, date_to),
            order="employee_id, date_from, id",
        )

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
