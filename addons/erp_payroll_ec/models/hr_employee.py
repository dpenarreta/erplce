from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # Conceptos fijos asignados al empleado (US-008, CA-7), para la pestaña de
    # nómina de la ficha. groups="payroll.group_payroll_user": el campo no
    # existe en hr.employee.public y solo lo ve quien tiene acceso a nómina
    # (las asignaciones solo tienen ACL para los grupos de nómina). Al ser un
    # One2many no entra en el prefetch de columnas, así que un usuario sin
    # nómina (RRHH o interno que lee el perfil público) no lo lee nunca.
    erp_payroll_concept_ids = fields.One2many(
        "erp.payroll.employee.concept",
        "employee_id",
        string="Conceptos de nómina",
        groups="payroll.group_payroll_user",
        help="Bonos y descuentos fijos asignados al empleado con importe y "
        "vigencia; entran en cada rol de pagos mientras estén vigentes.",
    )
