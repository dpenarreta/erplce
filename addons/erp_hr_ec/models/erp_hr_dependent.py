from odoo import fields, models


class ErpHrDependent(models.Model):
    _name = "erp.hr.dependent"
    _description = "Carga familiar"
    _order = "employee_id, birthdate, id"

    employee_id = fields.Many2one(
        "hr.employee",
        string="Empleado",
        required=True,
        index=True,
        ondelete="cascade",
    )
    name = fields.Char(string="Nombre", required=True)
    identification = fields.Char(
        string="Identificación", help="Cédula o pasaporte de la carga familiar."
    )
    relationship = fields.Selection(
        [
            ("spouse", "Cónyuge"),
            ("partner", "Conviviente"),
            ("child", "Hijo/a"),
            ("parent", "Padre/Madre"),
            ("other", "Otro"),
        ],
        string="Parentesco",
        required=True,
    )
    birthdate = fields.Date(string="Fecha de nacimiento")
    disability = fields.Boolean(string="Discapacidad")
    company_id = fields.Many2one(
        related="employee_id.company_id",
        store=True,
        precompute=True,
        index=True,
        string="Empresa",
    )
