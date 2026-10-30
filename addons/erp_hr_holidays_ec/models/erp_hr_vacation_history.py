from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# Campos que cambian el reparto FIFO de la carga histórica.
HISTORY_DISTRIBUTION_FIELDS = ("employee_id", "date", "number_of_days", "service_year")


class ErpHrVacationHistory(models.Model):
    """Vacaciones gozadas antes de usar el sistema (carga inicial, US-012,
    CA-11).

    Talento Humano registra, por empleado, los días de vacaciones que ya gozó
    de sus periodos vigentes: en total a una fecha de corte o por goces con
    fecha, y opcionalmente indicando el año de servicio. Cada cambio vuelve a
    repartir todas las líneas del empleado entre sus periodos (asignaciones
    automáticas validadas), del más antiguo al más nuevo
    (``hr.employee._erp_apply_vacation_history``); las ausencias registradas
    en el sistema se descuentan después de lo que queda.

    Se eligió un modelo propio y no solicitudes de ausencia históricas
    (``hr.leave``): no exige fechas exactas de cada goce (basta el total), no
    choca con el control de solapamiento ni con el calendario laboral, no
    crea ausencias en el calendario ni en la nómina pasada y se importa en
    lote con una plantilla CSV simple.
    """

    _name = "erp.hr.vacation.history"
    _description = "Vacaciones gozadas antes del sistema"
    _inherit = ["mail.thread"]
    _order = "employee_id, date, id"

    employee_id = fields.Many2one(
        "hr.employee",
        string="Empleado",
        required=True,
        index=True,
        ondelete="restrict",
        tracking=True,
    )
    company_id = fields.Many2one(
        related="employee_id.company_id",
        string="Empresa",
        store=True,
        index=True,
    )
    identification = fields.Char(
        string="Identificación",
        compute="_compute_identification",
        store=True,
        readonly=False,
        help="Cédula o pasaporte del empleado. En la importación basta con "
        "esta columna para identificarlo (si se deja vacía la columna "
        "Empleado).",
    )
    date = fields.Date(
        string="Fecha",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        help="Fecha del goce o fecha de corte hasta la que se cuentan los días "
        "gozados. Se descuentan de los periodos vigentes en esa fecha (ya "
        "nacidos y no caducados).",
    )
    number_of_days = fields.Float(
        string="Días gozados",
        required=True,
        digits=(16, 2),
        tracking=True,
    )
    service_year = fields.Integer(
        string="Año de servicio",
        tracking=True,
        help="Opcional: año de servicio (periodo) al que corresponden los "
        "días. Vacío: se descuentan del periodo vigente más antiguo al más "
        "nuevo.",
    )
    note = fields.Char(string="Observación")

    _sql_constraints = [
        (
            "number_of_days_positive_check",
            "CHECK (number_of_days > 0)",
            "Los días gozados deben ser mayores que cero.",
        ),
        (
            "service_year_positive_check",
            "CHECK (service_year IS NULL OR service_year >= 0)",
            "El año de servicio no puede ser negativo.",
        ),
    ]

    @api.depends("employee_id")
    def _compute_identification(self):
        for line in self:
            line.identification = line.employee_id.identification_id or False

    @api.constrains("employee_id", "identification")
    def _check_identification(self):
        for line in self:
            expected = line.employee_id.identification_id
            if line.identification and expected and line.identification != expected:
                raise ValidationError(
                    _(
                        "La identificación %(identification)s no corresponde a "
                        "%(employee)s (su identificación es %(expected)s).",
                        identification=line.identification,
                        employee=line.employee_id.name,
                        expected=expected,
                    )
                )

    @api.model
    def _resolve_employees(self, vals_list):
        """Completa ``employee_id`` a partir de la identificación (importación
        con solo la columna Identificación)."""
        identifications = {
            vals["identification"].strip()
            for vals in vals_list
            if not vals.get("employee_id")
            and (vals.get("identification") or "").strip()
        }
        if not identifications:
            return
        employees = self.env["hr.employee"].search_fetch(
            [("identification_id", "in", list(identifications))],
            ["identification_id"],
        )
        by_identification = {}
        for employee in employees:
            by_identification.setdefault(employee.identification_id, []).append(
                employee
            )
        for vals in vals_list:
            identification = (vals.get("identification") or "").strip()
            if vals.get("employee_id") or not identification:
                continue
            found = by_identification.get(identification, [])
            if len(found) != 1:
                raise UserError(
                    _(
                        "No se encontró un único empleado con la identificación "
                        "%(identification)s. Revise la columna Identificación o "
                        "indique el Empleado.",
                        identification=identification,
                    )
                )
            vals["identification"] = identification
            vals["employee_id"] = found[0].id

    @api.model_create_multi
    def create(self, vals_list):
        self._resolve_employees(vals_list)
        lines = super().create(vals_list)
        lines.employee_id._erp_apply_vacation_history()
        return lines

    def write(self, vals):
        old_employees = self.employee_id
        res = super().write(vals)
        if set(HISTORY_DISTRIBUTION_FIELDS) & set(vals):
            (old_employees | self.employee_id)._erp_apply_vacation_history()
        return res

    def unlink(self):
        employees = self.employee_id
        res = super().unlink()
        employees.exists()._erp_apply_vacation_history()
        return res

    @api.model
    def get_import_templates(self):
        """Plantilla CSV de la carga inicial (Importar > Plantilla)."""
        return [
            {
                "label": _("Plantilla de vacaciones gozadas"),
                "template": "/erp_hr_holidays_ec/static/csv/"
                "plantilla_vacaciones_gozadas.csv",
            }
        ]
