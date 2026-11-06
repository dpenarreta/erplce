from odoo import _, fields, models


class ErpPayrollProvisionPayment(models.Model):
    """Provisión de décimo pagada en una liquidación (US-013, CA-3, CA-9).

    Añade el tipo de documento «Liquidación» y su referencia sin que
    ``erp_payroll_ec`` dependa de este módulo. La unicidad por línea de
    provisión (``payslip_line_uniq``) es la del modelo base: una provisión
    no puede quedar pagada a la vez por un rol de décimos y una liquidación.
    Al desinstalar este módulo se eliminan las marcas de liquidaciones
    (``ondelete`` del valor de selección) y esas provisiones vuelven a quedar
    pendientes.
    """

    _inherit = "erp.payroll.provision.payment"

    document_type = fields.Selection(
        selection_add=[("settlement", "Liquidación")],
        ondelete={"settlement": "cascade"},
    )
    settlement_id = fields.Many2one(
        "erp.hr.settlement",
        string="Liquidación",
        index="btree_not_null",
        # La liquidación solo se elimina en borrador o anulada, y al anularla
        # la marca ya se eliminó.
        ondelete="cascade",
        check_company=True,
    )

    _sql_constraints = [
        (
            "settlement_document_check",
            "CHECK ((document_type = 'settlement') = (settlement_id IS NOT NULL))",
            "Una provisión pagada en una liquidación debe indicar esa "
            "liquidación (y solo ese tipo de documento la indica).",
        ),
    ]

    def _erp_document_name(self):
        self.ensure_one()
        if self.document_type == "settlement":
            return _(
                "la liquidación %(settlement)s",
                settlement=self.settlement_id.display_name,
            )
        return super()._erp_document_name()
