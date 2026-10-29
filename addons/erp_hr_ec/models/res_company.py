from odoo import api, fields, models

from .const import BENEFIT_MODE_SELECTION

_HELP_TO_VALIDATE = (
    " Valor inicial a validar por la empresa (sin fuente normativa entregada; "
    "ver US-007)."
)


class ResCompany(models.Model):
    _inherit = "res.company"

    erp_default_reserve_fund_mode = fields.Selection(
        BENEFIT_MODE_SELECTION,
        string="Fondos de reserva por defecto",
        required=True,
        default="monthly",
        help="Modalidad de fondos de reserva para los empleados sin elección "
        "propia vigente." + _HELP_TO_VALIDATE,
    )
    erp_default_thirteenth_mode = fields.Selection(
        BENEFIT_MODE_SELECTION,
        string="Décimo tercero por defecto",
        required=True,
        default="accumulated",
        help="Modalidad de décimo tercero sueldo para los empleados sin "
        "elección propia vigente." + _HELP_TO_VALIDATE,
    )
    erp_default_fourteenth_mode = fields.Selection(
        BENEFIT_MODE_SELECTION,
        string="Décimo cuarto por defecto",
        required=True,
        default="accumulated",
        help="Modalidad de décimo cuarto sueldo para los empleados sin "
        "elección propia vigente." + _HELP_TO_VALIDATE,
    )
    erp_max_weekly_hours = fields.Float(
        string="Máximo de horas semanales",
        digits=(5, 2),
        required=True,
        default=40.0,
        help="Horas semanales máximas que admite la jornada de un contrato "
        "(Código del Trabajo: 40 h)." + _HELP_TO_VALIDATE,
    )

    _sql_constraints = [
        (
            "erp_max_weekly_hours_positive",
            "CHECK(erp_max_weekly_hours > 0)",
            "El máximo de horas semanales debe ser mayor que cero.",
        ),
    ]

    @api.constrains("erp_max_weekly_hours")
    def _check_erp_max_weekly_hours_running_contracts(self):
        """Al bajar el máximo semanal, los contratos en curso de la empresa
        deben seguir dentro del nuevo máximo."""
        # sudo: quien cambia el ajuste (Ajustes) puede no tener acceso a
        # contratos; solo se valida.
        contracts = (
            self.env["hr.contract"]
            .sudo()
            .search([("company_id", "in", self.ids), ("state", "=", "open")])
        )
        contracts._erp_check_max_weekly_hours()
