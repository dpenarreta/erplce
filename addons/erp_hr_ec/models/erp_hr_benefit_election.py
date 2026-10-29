from odoo import fields, models

from .const import BENEFIT_MODE_SELECTION, BENEFIT_SELECTION


class ErpHrBenefitElection(models.Model):
    _name = "erp.hr.benefit.election"
    _description = "Elección de modalidad de beneficio"
    _order = "employee_id, benefit, date_from desc"

    # Sin index=True propio: el índice de la restricción única
    # (employee_id, benefit, date_from) cubre las búsquedas por empleado y la
    # consulta de modalidad vigente (empleado, beneficio, fecha <= X, orden por
    # fecha descendente).
    employee_id = fields.Many2one(
        "hr.employee",
        string="Empleado",
        required=True,
        ondelete="cascade",
    )
    benefit = fields.Selection(BENEFIT_SELECTION, string="Beneficio", required=True)
    mode = fields.Selection(BENEFIT_MODE_SELECTION, string="Modalidad", required=True)
    date_from = fields.Date(
        string="Vigente desde",
        required=True,
        help="Fecha desde la que rige la modalidad elegida, hasta la siguiente "
        "elección del mismo beneficio.",
    )
    note = fields.Text(string="Nota")
    company_id = fields.Many2one(
        related="employee_id.company_id",
        store=True,
        precompute=True,
        index=True,
        string="Empresa",
    )

    _sql_constraints = [
        (
            "employee_benefit_date_uniq",
            "UNIQUE(employee_id, benefit, date_from)",
            "El empleado ya tiene una elección de ese beneficio con la misma "
            "fecha de vigencia.",
        ),
    ]
