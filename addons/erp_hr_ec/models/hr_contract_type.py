from odoo import fields, models


class HrContractType(models.Model):
    _inherit = "hr.contract.type"

    erp_labor_relationship = fields.Boolean(
        string="Relación laboral (IESS y beneficios de ley)",
        default=True,
        help="Indica si el tipo de contrato genera relación de dependencia "
        "(afiliación al IESS y beneficios de ley). La nómina lo usará para "
        "excluir del rol o de aportes. Valores iniciales a validar por la "
        "empresa (US-007).",
    )
