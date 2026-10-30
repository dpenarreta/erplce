from odoo import fields, models

from .hr_employee import PARENT_ID_HELP, PARENT_ID_STRING


class ResUsers(models.Model):
    _inherit = "res.users"

    # US-010 (CA-7): en las preferencias del usuario, el jefe inmediato del
    # empleado vinculado (related a hr.employee.parent_id en el núcleo). Solo
    # cambian etiqueta y ayuda; el related, la lectura y la escritura siguen
    # siendo las de hr.
    employee_parent_id = fields.Many2one(
        string=PARENT_ID_STRING,
        help=PARENT_ID_HELP,
    )
