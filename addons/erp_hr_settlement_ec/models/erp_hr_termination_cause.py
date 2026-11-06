from odoo import fields, models


class ErpHrTerminationCause(models.Model):
    """Causa de terminación de la relación laboral (US-013, CA-6, CA-12).

    Catálogo común a todas las empresas (las causas son legales, no de la
    empresa). Los indicadores ``pays_*`` dicen qué rubros calcula «Calcular»
    para una liquidación con esta causa; los valores de partida están «A
    validar» por el asesor laboral. Los rubros comunes (décimos y vacaciones)
    vienen activados; RRHH puede desactivarlos si su asesor lo indica.
    """

    _name = "erp.hr.termination.cause"
    _description = "Causa de salida"
    _inherit = ["mail.thread", "erp.hr.settlement.validation.mixin"]
    _order = "sequence, name, id"
    _erp_revalidate_fields = (
        "code",
        "departure_reason_id",
        "legal_basis",
        "pays_thirteenth",
        "pays_fourteenth",
        "pays_pending_vacation",
        "pays_proportional_vacation",
        "pays_severance_bonus",
        "pays_unfair_dismissal_indemnity",
    )

    name = fields.Char(string="Causa", required=True, tracking=True)
    code = fields.Char(
        string="Código",
        required=True,
        tracking=True,
        help="Código técnico único (mayúsculas, dígitos y guion bajo).",
    )
    sequence = fields.Integer(string="Secuencia", default=10)
    active = fields.Boolean(string="Activa", default=True, tracking=True)
    description = fields.Text(
        string="Descripción",
        help="Cuándo se usa esta causa y qué rubros paga.",
    )
    legal_basis = fields.Text(
        string="Norma / fuente",
        help="Artículos del Código del Trabajo u otra norma que respaldan la "
        "causa y sus rubros.",
    )
    departure_reason_id = fields.Many2one(
        "hr.departure.reason",
        string="Motivo de salida en la ficha del empleado",
        ondelete="set null",
        tracking=True,
        help="Motivo de salida que se registra en la ficha del empleado al "
        "confirmar la liquidación (si hay equivalencia).",
    )
    pays_thirteenth = fields.Boolean(
        string="Décimo tercero pendiente",
        default=True,
        tracking=True,
        help="Paga las provisiones de décimo tercero no pagadas.",
    )
    pays_fourteenth = fields.Boolean(
        string="Décimo cuarto pendiente",
        default=True,
        tracking=True,
        help="Paga las provisiones de décimo cuarto no pagadas.",
    )
    pays_pending_vacation = fields.Boolean(
        string="Vacaciones no gozadas",
        default=True,
        tracking=True,
        help="Paga el saldo de los periodos de vacaciones vigentes.",
    )
    pays_proportional_vacation = fields.Boolean(
        string="Vacaciones proporcionales",
        default=True,
        tracking=True,
        help="Paga las vacaciones proporcionales del año de servicio en curso.",
    )
    pays_severance_bonus = fields.Boolean(
        string="Bonificación por desahucio",
        tracking=True,
        help="Paga la bonificación por desahucio (porcentaje de la última "
        "remuneración por año de servicio).",
    )
    pays_unfair_dismissal_indemnity = fields.Boolean(
        string="Indemnización por despido intempestivo",
        tracking=True,
        help="Paga la indemnización por tramos de años de servicio "
        "(Tramos de indemnización).",
    )

    _sql_constraints = [
        (
            "code_uniq",
            "UNIQUE (code)",
            "Ya existe una causa de salida con ese código.",
        ),
        (
            "code_format_check",
            "CHECK (code ~ '^[A-Z][A-Z0-9_]{0,63}$')",
            "El código de la causa de salida debe empezar por una letra "
            "mayúscula y contener solo mayúsculas, dígitos y guion bajo "
            "(máximo 64).",
        ),
    ]
