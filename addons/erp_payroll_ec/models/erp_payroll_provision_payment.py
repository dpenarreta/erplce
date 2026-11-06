from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.base.models.ir_model import MODULE_UNINSTALL_FLAG

from .const import PROVISION_RULE_CODES

DOCUMENT_TYPE_SELECTION = [
    ("payslip", "Rol de pago de décimos"),
]


class ErpPayrollProvisionPayment(models.Model):
    """Provisión de décimo pagada (US-013, CA-3).

    Un registro = una línea de provisión (``D13_PROV``, ``D14_PROV_COSTA``,
    ``D14_PROV_SIERRA``) de un rol mensual confirmado que ya se pagó, y el
    documento que la pagó. Es la marca persistente de «pagada» (no se
    recalcula): lo pendiente de un empleado son sus líneas de provisión de
    roles confirmados **sin** registro aquí
    (``hr.payslip.line._erp_get_pending_provision_lines``).

    Ciclo de vida (lo implementa la capa de negocio):

    - se crea al **confirmar** el documento que paga (rol de pago de décimos
      o liquidación);
    - se **elimina** al anular ese documento: la provisión vuelve a quedar
      pendiente. La traza de la anulación queda en el documento (chatter y
      asiento de reversión).

    Escritura solo desde el servidor: ni el usuario ni el responsable de
    nómina tienen permiso de escritura (ACL de solo lectura) y, además,
    ``create``/``write``/``unlink`` exigen ``env.su`` (los flujos de
    confirmación y anulación ya trabajan con ``sudo()``): una marca editada a
    mano rompería la garantía de no pagar dos veces (CA-3).

    Integridad en la BD:

    - ``payslip_line_uniq``: una línea de provisión solo puede estar pagada
      por un documento (``UNIQUE``). Como la anulación elimina el registro,
      no hace falta un índice parcial por estado.
    - ``payslip_line_id`` con ``ondelete='restrict'``: una provisión pagada no
      puede desaparecer (p. ej. al recalcular un rol que se anuló después).
    - Documento que paga: ``document_type`` dice qué columna lo referencia;
      ``payslip_document_check`` exige que ``payslip_id`` esté informado si y
      solo si el tipo es ``payslip``. ``erp_hr_settlement_ec`` añade el tipo
      ``settlement`` con su columna ``settlement_id`` y su propia
      restricción, sin que este módulo dependa de él.
    """

    _name = "erp.payroll.provision.payment"
    _description = "Provisión de décimo pagada"
    _order = "employee_id, provision_date, id"
    _rec_name = "payslip_line_id"
    _check_company_auto = True

    payslip_line_id = fields.Many2one(
        "hr.payslip.line",
        string="Línea de provisión",
        required=True,
        # Sin index=True: lo cubre el índice de la restricción UNIQUE.
        ondelete="restrict",
        help="Línea de provisión de décimo de un rol mensual confirmado.",
    )
    provision_payslip_id = fields.Many2one(
        "hr.payslip",
        string="Rol de la provisión",
        related="payslip_line_id.slip_id",
        store=True,
        index=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Empleado",
        related="payslip_line_id.employee_id",
        store=True,
        index=True,
    )
    provision_code = fields.Char(
        string="Código de provisión",
        related="payslip_line_id.code",
        store=True,
    )
    provision_date = fields.Date(
        string="Mes de la provisión",
        related="payslip_line_id.date_from",
        store=True,
        help="Inicio del periodo del rol mensual que generó la provisión.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        related="payslip_line_id.slip_id.company_id",
        store=True,
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        related="company_id.currency_id",
    )
    amount = fields.Monetary(
        string="Importe pagado",
        required=True,
        currency_field="currency_id",
        help="Importe de la provisión pagado (copia del total de la línea al "
        "pagarla).",
    )
    document_type = fields.Selection(
        DOCUMENT_TYPE_SELECTION,
        string="Pagada en",
        required=True,
        help="Tipo de documento que pagó la provisión.",
    )
    payslip_id = fields.Many2one(
        "hr.payslip",
        string="Rol de pago de décimos",
        index="btree_not_null",
        # El rol que paga solo se puede borrar en borrador o anulado, y al
        # anularlo la marca ya se eliminó.
        ondelete="cascade",
        check_company=True,
    )

    _sql_constraints = [
        (
            "payslip_line_uniq",
            "UNIQUE (payslip_line_id)",
            "Esta provisión de décimo ya está pagada en otro documento (rol de "
            "pago de décimos o liquidación). Anule ese documento antes de "
            "volver a pagarla.",
        ),
        (
            "payslip_document_check",
            "CHECK ((document_type = 'payslip') = (payslip_id IS NOT NULL))",
            "Una provisión pagada en un rol de pago de décimos debe indicar ese "
            "rol (y solo ese tipo de documento lo indica).",
        ),
        (
            "amount_positive_check",
            "CHECK (amount >= 0)",
            "El importe pagado de una provisión no puede ser negativo.",
        ),
    ]

    # ------------------------------------------------------------------
    # Escritura reservada al servidor (US-013, CA-3)
    # ------------------------------------------------------------------
    def _erp_check_server_write(self):
        """Las marcas solo las crean y eliminan la confirmación y la anulación
        del documento que paga (con ``sudo()``). Cualquier otra escritura,
        aunque venga del responsable de nómina: ``UserError``. Se admite la
        desinstalación de módulos (``MODULE_UNINSTALL_FLAG``)."""
        if self.env.su or self.env.context.get(MODULE_UNINSTALL_FLAG):
            return
        raise UserError(
            _(
                "Las provisiones de décimos pagadas no se registran, modifican "
                "ni eliminan a mano: las marca la confirmación del rol de pago "
                "de décimos o de la liquidación y las libera su anulación. "
                "Anule el documento que pagó la provisión si necesita "
                "corregirla."
            )
        )

    @api.model_create_multi
    def create(self, vals_list):
        self._erp_check_server_write()
        return super().create(vals_list)

    def write(self, vals):
        self._erp_check_server_write()
        return super().write(vals)

    def unlink(self):
        self._erp_check_server_write()
        return super().unlink()

    def _erp_document_name(self):
        """Nombre legible del documento que pagó la provisión (mensajes de
        bloqueo, US-013 CA-3). ``erp_hr_settlement_ec`` añade la
        liquidación."""
        self.ensure_one()
        if self.document_type == "payslip":
            return _(
                "el rol de pago de décimos %(payslip)s",
                payslip=self.payslip_id.number or self.payslip_id.name or "",
            )
        return dict(self._fields["document_type"]._description_selection(self.env))[
            self.document_type
        ]

    @api.constrains("payslip_line_id")
    def _check_provision_line(self):
        """Solo se marcan como pagadas líneas de provisión de décimos de roles
        confirmados que no son reembolsos."""
        for payment in self:
            line = payment.payslip_line_id
            if line.code not in PROVISION_RULE_CODES:
                raise ValidationError(
                    _(
                        "Solo se pueden marcar como pagadas las provisiones de "
                        "décimos (%(codes)s); la línea «%(line)s» tiene el código "
                        "%(code)s.",
                        codes=", ".join(PROVISION_RULE_CODES),
                        line=line.name,
                        code=line.code,
                    )
                )
            if line.slip_id.state != "done" or line.slip_id.credit_note:
                raise ValidationError(
                    _(
                        "La provisión «%(line)s» de %(employee)s no es de un rol "
                        "de pagos confirmado: solo se pagan provisiones de roles "
                        "mensuales confirmados.",
                        line=line.name,
                        employee=line.employee_id.name,
                    )
                )
