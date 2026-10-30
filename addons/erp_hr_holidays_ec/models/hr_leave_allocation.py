import logging
from contextlib import contextmanager

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import formatLang

_logger = logging.getLogger(__name__)

# Indicador en ``cr.cache`` (no en el contexto, que controla el cliente RPC):
# la generación de vacaciones por antigüedad (o el reparto de la carga
# histórica) está en curso y puede escribir los campos protegidos. Mismo patrón
# que erp_payroll_ec/models/hr_payslip.py.
VACATION_GENERATION_KEY = "erp_hr_holidays_ec.vacation_generation"
# Campos que solo escriben la generación automática y el reparto de la carga
# histórica (US-012, CA-3, CA-11).
ALLOCATION_PROTECTED_FIELDS = (
    "erp_auto_generated",
    "erp_service_year",
    "erp_entry_date",
    "erp_entitled_days",
    "erp_history_days",
)


class HrLeaveAllocation(models.Model):
    """Asignación de vacaciones por año de servicio = periodo (US-012, CA-3,
    CA-9, CA-10, CA-11).

    La asignación automática (tarea programada o botón del responsable) marca
    ``erp_auto_generated`` y guarda el año de servicio que cubre. La
    restricción ``erp_auto_service_year_uniq`` garantiza en la BD que no haya
    dos asignaciones automáticas no rechazadas por empleado, tipo y año de
    servicio. Las asignaciones manuales no se restringen.

    Vigencia: ``date_from`` = aniversario (nace el derecho), ``date_to`` =
    caducidad (límite de acumulación). Días: ``erp_entitled_days`` = días del
    periodo; ``erp_history_days`` = gozados antes del sistema;
    ``number_of_days`` (el saldo que usa ``hr_holidays``) = días del periodo −
    gozados antes del sistema (más los ajustes manuales de RRHH).
    """

    _inherit = "hr.leave.allocation"

    erp_service_year = fields.Integer(
        string="Año de servicio",
        readonly=True,
        copy=False,
        help="Año de servicio del empleado (1 = primer año desde la fecha de "
        "ingreso) al que corresponde esta asignación de vacaciones. 0: no "
        "aplica (asignación manual).",
    )
    erp_auto_generated = fields.Boolean(
        string="Generada automáticamente",
        readonly=True,
        copy=False,
        help="Asignación creada por la generación anual de vacaciones por "
        "antigüedad.",
    )
    erp_entry_date = fields.Date(
        string="Fecha de ingreso del periodo",
        readonly=True,
        copy=False,
        help="Fecha de ingreso con la que se calculó el año de servicio. "
        "Distingue los periodos de un reingreso (nueva fecha de ingreso, años "
        "de servicio desde 1 otra vez).",
    )
    erp_entitled_days = fields.Float(
        string="Días del periodo",
        readonly=True,
        copy=False,
        digits=(16, 2),
        help="Días de vacaciones que corresponden al periodo según la "
        "antigüedad y la jornada, antes de descontar lo gozado.",
    )
    erp_history_days = fields.Float(
        string="Gozados antes del sistema",
        readonly=True,
        copy=False,
        digits=(16, 2),
        help="Días gozados antes de usar el sistema (carga inicial) que se "
        "descuentan de este periodo, del más antiguo al más nuevo.",
    )
    erp_days_used = fields.Float(
        string="Gozados",
        compute="_compute_erp_period_balance",
        digits=(16, 2),
        help="Gozados antes del sistema + ausencias aprobadas descontadas de "
        "este periodo.",
    )
    erp_days_pending = fields.Float(
        string="Por aprobar",
        compute="_compute_erp_period_balance",
        digits=(16, 2),
        help="Días de solicitudes pendientes de aprobación descontadas de este "
        "periodo.",
    )
    erp_days_available = fields.Float(
        string="Disponibles",
        compute="_compute_erp_period_balance",
        digits=(16, 2),
        help="Días que aún se pueden pedir de este periodo (descontadas las "
        "solicitudes aprobadas y pendientes). Cero si el periodo caducó.",
    )
    erp_days_expired = fields.Float(
        string="Caducados",
        compute="_compute_erp_period_balance",
        digits=(16, 2),
        help="Días no gozados que se perdieron al caducar el periodo.",
    )
    erp_is_expired = fields.Boolean(
        string="Caducado",
        compute="_compute_erp_period_balance",
        help="La fecha de caducidad (fin de vigencia) ya pasó.",
    )

    _sql_constraints = [
        (
            # Redefine la restricción de hr_holidays (mismo nombre): un
            # periodo de vacaciones consumido por completo con días gozados
            # antes del sistema queda con saldo 0 (US-012, CA-11).
            "duration_check",
            "CHECK ((number_of_days > 0 AND allocation_type = 'regular') "
            "OR (allocation_type != 'regular') "
            "OR (erp_history_days > 0 AND number_of_days >= 0))",
            "Los días de la asignación deben ser mayores que cero.",
        ),
        (
            "erp_entitled_days_positive_check",
            "CHECK (erp_entitled_days IS NULL OR erp_entitled_days >= 0)",
            "Los días del periodo no pueden ser negativos.",
        ),
        (
            "erp_history_days_positive_check",
            "CHECK (erp_history_days IS NULL OR erp_history_days >= 0)",
            "Los días gozados antes del sistema no pueden ser negativos.",
        ),
        (
            "erp_service_year_positive_check",
            "CHECK (erp_service_year IS NULL OR erp_service_year >= 0)",
            "El año de servicio no puede ser negativo.",
        ),
        (
            "erp_auto_requires_service_year_check",
            "CHECK (erp_auto_generated IS NOT TRUE OR erp_service_year > 0)",
            "Una asignación automática de vacaciones debe indicar el año de "
            "servicio que cubre.",
        ),
        (
            # Índice único parcial vía EXCLUDE (btree, igualdad): además sirve
            # a la búsqueda de idempotencia (empleado, tipo, fecha de ingreso,
            # año de servicio). La fecha de ingreso forma parte de la clave:
            # tras un reingreso, el año 1 del nuevo ingreso es otro periodo.
            # La BD admite otra asignación del mismo año si la anterior está
            # rechazada, pero la generación no la crea mientras la rechazada
            # exista (idempotencia en cualquier estado, ver
            # hr.employee._erp_generate_vacation_allocations): para
            # regenerarla, RRHH elimina la rechazada.
            "erp_auto_service_year_uniq",
            "EXCLUDE USING btree (employee_id WITH =, holiday_status_id WITH =, "
            "(COALESCE(erp_entry_date, '1900-01-01'::date)) WITH =, "
            "erp_service_year WITH =) "
            "WHERE (erp_auto_generated AND state <> 'refuse')",
            "Ya existe una asignación automática de vacaciones para este "
            "empleado, tipo de ausencia, fecha de ingreso y año de servicio.",
        ),
    ]

    # ------------------------------------------------------------------
    # Protección de los campos de la generación automática (US-012, CA-3,
    # CA-11)
    # ------------------------------------------------------------------
    @contextmanager
    def _erp_vacation_generation(self):
        """Marca en ``cr.cache`` que la generación de vacaciones (o el reparto
        de la carga histórica) está en curso: solo entonces se escriben los
        campos de ``ALLOCATION_PROTECTED_FIELDS``. Se usa ``cr.cache`` y no el
        contexto porque el contexto lo controla el cliente RPC. Alcance por
        cursor; se retira en ``finally`` aunque la generación falle. Admite
        anidamiento."""
        cache = self.env.cr.cache
        cache[VACATION_GENERATION_KEY] = cache.get(VACATION_GENERATION_KEY, 0) + 1
        try:
            yield
        finally:
            cache[VACATION_GENERATION_KEY] -= 1
            if not cache[VACATION_GENERATION_KEY]:
                cache.pop(VACATION_GENERATION_KEY)

    def _erp_can_write_generation_fields(self):
        # env.su: procesos internos, migraciones y la tarea programada.
        return self.env.su or bool(self.env.cr.cache.get(VACATION_GENERATION_KEY))

    def _erp_protected_fields_error(self):
        return UserError(
            _(
                "«Generada automáticamente», «Año de servicio», «Días del "
                "periodo» y «Gozados antes del sistema» los asignan solo el "
                "cálculo de vacaciones por antigüedad y la carga de vacaciones "
                "gozadas. Para dar días adicionales, cree una asignación manual."
            )
        )

    @api.model_create_multi
    def create(self, vals_list):
        if not self._erp_can_write_generation_fields() and any(
            vals.get(name) for vals in vals_list for name in ALLOCATION_PROTECTED_FIELDS
        ):
            raise self._erp_protected_fields_error()
        return super().create(vals_list)

    def write(self, vals):
        if not self._erp_can_write_generation_fields():
            for name in set(ALLOCATION_PROTECTED_FIELDS) & set(vals):
                # Reescribir el mismo valor (p. ej. un formulario que lo
                # reenvía) no es un cambio.
                if any(
                    (allocation[name] or False) != (vals[name] or False)
                    for allocation in self
                ):
                    raise self._erp_protected_fields_error()
        return super().write(vals)

    def _erp_validate_generated(self):
        """Valida las asignaciones recién generadas hasta «Aprobada»
        (``validate``), también si el tipo exige doble validación
        (``allocation_validation_type = 'both'``: la primera aprobación deja
        ``validate1``). Con ``no_validation`` el núcleo ya las valida al
        crear."""
        pending = self.filtered(lambda a: a.state != "validate")
        pending.action_validate()
        pending.filtered(lambda a: a.state == "validate1").action_validate()

    # ------------------------------------------------------------------
    # Presentación (US-012, CA-4, CA-11; QA-UX)
    # ------------------------------------------------------------------
    @api.depends(
        "employee_id",
        "holiday_status_id",
        "type_request_unit",
        "number_of_days",
        "number_of_hours_display",
    )
    def _compute_display_name(self):
        """«Saldo de <tipo>: N días» (u horas); «Nuevo saldo» sin tipo. El
        nativo («Allocation of …») mostraba «False» en un registro nuevo."""
        for allocation in self:
            leave_type = allocation.holiday_status_id
            if not leave_type:
                allocation.display_name = _("Nuevo saldo")
                continue
            hours = allocation.type_request_unit == "hour"
            amount = (
                allocation.number_of_hours_display
                if hours
                else allocation.number_of_days
            )
            digits = 0 if float(amount).is_integer() else 2
            allocation.display_name = _(
                "Saldo de %(type)s: %(amount)s %(unit)s",
                # sudo(): solo el nombre del tipo, como el nativo.
                type=leave_type.sudo().name,
                amount=formatLang(self.env, amount, digits=digits),
                unit=_("horas") if hours else _("días"),
            )

    @api.depends(
        "employee_id",
        "holiday_status_id",
        "number_of_days",
        "erp_history_days",
        "date_to",
        "state",
    )
    def _compute_erp_period_balance(self):
        """Detalle del periodo (CA-11): gozados, por aprobar, disponibles y
        caducados, con el reparto FIFO del núcleo (``_get_consumed_leaves``:
        primero la asignación con fecha de fin más próxima). En la unidad del
        tipo (días para vacaciones)."""
        today = fields.Date.context_today(self)
        consumed = {}
        validated = self.filtered(lambda a: a._origin and a.state == "validate")
        if validated:
            consumed = validated.employee_id._get_consumed_leaves(
                validated.holiday_status_id, today
            )[0]
        for allocation in self:
            origin = allocation._origin
            expired = bool(allocation.date_to and allocation.date_to < today)
            data = {}
            if allocation in validated:
                data = consumed[origin.employee_id][origin.holiday_status_id].get(
                    origin, {}
                )
            taken = data.get("leaves_taken", 0.0)
            virtual_taken = data.get("virtual_leaves_taken", 0.0)
            remaining = max(data.get("virtual_remaining_leaves", 0.0), 0.0)
            allocation.erp_is_expired = expired
            allocation.erp_days_used = allocation.erp_history_days + taken
            allocation.erp_days_pending = max(virtual_taken - taken, 0.0)
            allocation.erp_days_available = 0.0 if expired else remaining
            allocation.erp_days_expired = remaining if expired else 0.0

    # ------------------------------------------------------------------
    # Tarea programada (US-012, CA-3, CA-12)
    # ------------------------------------------------------------------
    @api.model
    def _erp_cron_generate_vacation_allocations(self):
        """Tarea diaria (se instala inactiva): genera los periodos de
        vacaciones de los aniversarios iguales o posteriores al corte
        (``VACATION_GENERATION_START``) de todos los empleados con derecho
        (ver ``hr.employee._erp_generate_vacation_allocations``).

        Cada empleado se procesa en su propio *savepoint*: un error se
        registra en el log y se sigue con los demás.

        :return: asignaciones creadas
        """
        Employee = self.env["hr.employee"]
        # sudo(): tarea de servidor sobre todos los empleados y empresas; no
        # devuelve datos a ningún usuario.
        employees = Employee.sudo().search(Employee._erp_vacation_eligible_domain())
        allocations = employees._erp_generate_vacation_allocations(
            raise_on_error=False, from_cutoff=True
        )
        _logger.info(
            "Vacaciones por antigüedad: %s asignaciones creadas para %s "
            "empleados con derecho.",
            len(allocations),
            len(employees),
        )
        return allocations
