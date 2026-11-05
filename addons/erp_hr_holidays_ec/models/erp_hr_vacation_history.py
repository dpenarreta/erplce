from collections import Counter

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date

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
        (
            # Una línea por empleado, fecha y año de servicio (vacío = 0):
            # reimportar la plantilla no duplica (QA-FUNC O3). EXCLUDE con
            # COALESCE equivale a un índice único que trata el año vacío como
            # 0. La comprobación previa de create/write da un mensaje con el
            # empleado y la fecha; esta es la garantía (también entre
            # transacciones simultáneas).
            "erp_vacation_history_uniq",
            "EXCLUDE USING btree (employee_id WITH =, date WITH =, "
            "(COALESCE(service_year, 0)) WITH =)",
            "Ya hay una línea de vacaciones gozadas de este empleado en esa "
            "fecha y año de servicio. Si vuelve a importar la plantilla, quite "
            "las filas ya cargadas; para corregir los días, edite la línea "
            "existente.",
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

    # ------------------------------------------------------------------
    # Una línea por empleado, fecha y año de servicio (QA-FUNC O3)
    # ------------------------------------------------------------------
    def _erp_duplicate_error(self, employee_id, date, service_year):
        employee = self.env["hr.employee"].browse(employee_id)
        if service_year:
            return ValidationError(
                _(
                    "Ya hay una línea de vacaciones gozadas de %(employee)s del "
                    "%(date)s para el año de servicio %(year)s. Si vuelve a "
                    "importar la plantilla, quite las filas ya cargadas; para "
                    "corregir los días, edite la línea existente.",
                    employee=employee.name,
                    date=format_date(self.env, date),
                    year=service_year,
                )
            )
        return ValidationError(
            _(
                "Ya hay una línea de vacaciones gozadas de %(employee)s del "
                "%(date)s. Si vuelve a importar la plantilla, quite las filas "
                "ya cargadas; para corregir los días, edite la línea existente.",
                employee=employee.name,
                date=format_date(self.env, date),
            )
        )

    def _erp_check_duplicate_keys(self, keys, exclude_ids=()):
        """Comprueba que las claves ``(empleado, fecha, año de servicio)``
        (año vacío = 0) no se repiten entre sí ni con otras líneas guardadas
        (salvo ``exclude_ids``, las que se están modificando).

        Una sola línea por clave: volver a importar la misma plantilla no
        duplica los días gozados (QA-FUNC O3). Se eligió un error claro y no
        una actualización silenciosa por clave natural: la plantilla no tiene
        un identificador estable, una actualización cambiaría el saldo sin
        que RRHH lo note y el importador de Odoo ya ofrece la vía estándar
        para actualizar (exportar con «ID externo» y reimportar). El botón
        «Probar» del importador muestra el error por fila antes de grabar
        nada. Dos goces del mismo día y año se registran en una sola línea
        con la suma de días.

        La garantía la da la BD (``erp_vacation_history_uniq``, también ante
        importaciones simultáneas); esta comprobación se hace **antes** de
        escribir para que el usuario vea un mensaje que nombra al empleado y
        la fecha en lugar del genérico de la restricción.

        :param keys: lista de ``(employee_id, fecha, año de servicio o 0)``
        :raises ValidationError: clave repetida
        """
        keys = [key for key in keys if key[0] and key[1]]
        if not keys:
            return
        counts = Counter(keys)
        for key, count in counts.items():
            if count > 1:
                raise self._erp_duplicate_error(*key)
        # sudo(): se buscan líneas del mismo empleado en esas fechas (pueden
        # no ser visibles por reglas de registro); no se devuelven.
        stored = self.sudo().search_fetch(
            [
                ("employee_id", "in", list({key[0] for key in keys})),
                ("date", "in", list({key[1] for key in keys})),
                ("id", "not in", list(exclude_ids)),
            ],
            ["employee_id", "date", "service_year"],
        )
        existing = {
            (line.employee_id.id, line.date, line.service_year or 0) for line in stored
        }
        for key in keys:
            if key in existing:
                raise self._erp_duplicate_error(*key)

    @api.constrains("employee_id", "date", "service_year")
    def _check_duplicate_line(self):
        """Red de seguridad en el ORM (la BD ya lo impide con
        ``erp_vacation_history_uniq``): mismo mensaje que la comprobación
        previa de ``create``/``write``."""
        if not self:
            return
        # sudo(): se cuentan las líneas del mismo empleado en esas fechas
        # (pueden no ser visibles por reglas de registro); no se devuelven.
        lines = self.sudo().search_fetch(
            [
                ("employee_id", "in", self.employee_id.ids),
                ("date", "in", list(set(self.mapped("date")))),
            ],
            ["employee_id", "date", "service_year"],
        )
        counts = Counter(
            (line.employee_id.id, line.date, line.service_year or 0) for line in lines
        )
        for line in self:
            key = (line.employee_id.id, line.date, line.service_year or 0)
            if counts[key] > 1:
                raise self._erp_duplicate_error(*key)

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
        # Candado de la generación de vacaciones: el reparto se hace sobre un
        # estado estable de los periodos.
        self.env["hr.employee"]._erp_lock_vacation_generation()
        self._resolve_employees(vals_list)
        today = fields.Date.context_today(self)
        self._erp_check_duplicate_keys(
            [
                (
                    vals.get("employee_id"),
                    fields.Date.to_date(vals.get("date")) or today,
                    vals.get("service_year") or 0,
                )
                for vals in vals_list
            ]
        )
        lines = super().create(vals_list)
        lines.employee_id._erp_apply_vacation_history()
        return lines

    def write(self, vals):
        redistribute = bool(set(HISTORY_DISTRIBUTION_FIELDS) & set(vals))
        if redistribute:
            self.env["hr.employee"]._erp_lock_vacation_generation()
        if {"employee_id", "date", "service_year"} & set(vals):
            self._erp_check_duplicate_keys(
                [
                    (
                        vals.get("employee_id", line.employee_id.id),
                        fields.Date.to_date(vals["date"])
                        if "date" in vals
                        else line.date,
                        (
                            vals["service_year"]
                            if "service_year" in vals
                            else line.service_year
                        )
                        or 0,
                    )
                    for line in self
                ],
                exclude_ids=self.ids,
            )
        old_employees = self.employee_id
        res = super().write(vals)
        if redistribute:
            employees = old_employees | self.employee_id
            employees._erp_apply_vacation_history()
            # Menos días gozados liberan saldo de un periodo: una solicitud
            # que cruzaba su caducidad sin saldo podría pasar a cruzarla con
            # saldo (O-B).
            self.env["hr.leave"]._erp_recheck_expiry_crossings(
                employees,
                _("cambiar las vacaciones gozadas antes del sistema"),
            )
        return res

    def unlink(self):
        employees = self.employee_id
        res = super().unlink()
        employees = employees.exists()
        employees._erp_apply_vacation_history()
        self.env["hr.leave"]._erp_recheck_expiry_crossings(
            employees, _("eliminar las vacaciones gozadas antes del sistema")
        )
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
