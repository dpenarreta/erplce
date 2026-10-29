from odoo import _, api, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare, formatLang


class HrContract(models.Model):
    _inherit = "hr.contract"

    @api.constrains("state", "kanban_state", "contract_type_id")
    def _check_erp_contract_type_running(self):
        """El tipo de contrato es obligatorio cuando el contrato está en curso
        (``open``) o en borrador marcado como listo (``kanban_state = done``):
        el cron ``update_state`` de Odoo pasa esos borradores a en curso y, si
        faltara el tipo, el contrato se quedaría en borrador en silencio. Un
        borrador que no está listo puede guardarse sin tipo."""
        for contract in self:
            if contract.contract_type_id:
                continue
            if contract.state == "open":
                raise ValidationError(
                    _(
                        "El contrato «%(contract)s» está en curso: indique el "
                        "tipo de contrato (Indefinido, Eventual, etc.).",
                        contract=contract.name,
                    )
                )
            if contract.state == "draft" and contract.kanban_state == "done":
                raise ValidationError(
                    _(
                        "El contrato «%(contract)s» está marcado como listo para "
                        "iniciar: indique el tipo de contrato (Indefinido, "
                        "Eventual, etc.) antes de marcarlo como listo.",
                        contract=contract.name,
                    )
                )

    @api.constrains("resource_calendar_id", "company_id")
    def _check_erp_max_weekly_hours(self):
        self._erp_check_max_weekly_hours()

    def _erp_check_max_weekly_hours(self):
        """Las horas semanales de la jornada del contrato no pueden superar el
        máximo semanal de su empresa (``res.company.erp_max_weekly_hours``).

        Se valida en create/write del contrato cuando cambia la jornada, la
        empresa o el empleado (la jornada y la empresa se recalculan desde el
        empleado), en cualquier estado, y para los contratos en curso cuando
        se modifica su jornada o el máximo de la empresa. Contratos sin
        jornada (totalmente flexibles) no se validan. Las horas de cada
        jornada se calculan una sola vez por lote.
        """
        hours_by_calendar = {}
        for contract in self:
            calendar = contract.resource_calendar_id
            if not calendar:
                continue
            if calendar not in hours_by_calendar:
                hours_by_calendar[calendar] = calendar._erp_get_weekly_hours()
            hours = hours_by_calendar[calendar]
            maximum = contract.company_id.erp_max_weekly_hours
            if float_compare(hours, maximum, precision_digits=2) > 0:
                raise ValidationError(
                    _(
                        "La jornada «%(calendar)s» del contrato «%(contract)s» "
                        "tiene %(hours)s horas semanales y supera el máximo de "
                        "%(maximum)s horas semanales configurado en la empresa "
                        "(Ajustes de Empleados).",
                        calendar=calendar.name,
                        contract=contract.name,
                        hours=formatLang(self.env, hours, digits=2),
                        maximum=formatLang(self.env, maximum, digits=2),
                    )
                )
