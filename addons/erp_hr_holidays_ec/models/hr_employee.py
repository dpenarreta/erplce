import logging
import zlib
from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import (
    SQL,
    float_compare,
    float_is_zero,
    float_round,
    format_date,
)

from . import const, text

_logger = logging.getLogger(__name__)

# Parámetros que intervienen en los periodos de vacaciones.
ALLOCATION_PARAMETER_CODES = (
    const.VACATION_BASE_DAYS,
    const.VACATION_EXTRA_FROM_YEAR,
    const.VACATION_EXTRA_DAYS_PER_YEAR,
    const.VACATION_EXTRA_MAX_DAYS,
    const.VACATION_VALIDITY_YEARS,
    const.VACATION_GENERATION_START,
)
# Redondeo de los días proporcionales a la jornada: al medio día más cercano
# (2 = medios días; «a validar» por Talento Humano, US-012 CA-3).
VACATION_ROUNDING_FRACTIONS = 2
LEAVE_OFFICER_GROUP = "hr_holidays.group_hr_holidays_user"
# Clave del candado de transacción (pg_advisory_xact_lock) que serializa la
# generación de vacaciones (tarea diaria y botón) y la aplicación de la carga
# histórica: dos ejecuciones simultáneas no calculan sobre el mismo estado.
VACATION_LOCK_KEY = zlib.crc32(b"erp_hr_holidays_ec.vacation_generation")


class ErpVacationParameterTable:
    """Valores de los parámetros de vacaciones cargados de una sola vez.

    La generación en lote necesita los parámetros en la fecha de cada
    aniversario (cientos de fechas distintas en el cálculo inicial): en lugar
    de una búsqueda por empleado se leen todos los valores activos de los
    códigos una vez y se resuelven en memoria con la misma regla que
    ``erp.payroll.parameter._get_value`` (valor activo con «Vigente desde» más
    reciente ``<=`` fecha; el de la empresa prevalece sobre el común). Si no
    hay valor se delega en ``_get_value``, que lanza el error en español que
    nombra el parámetro y la fecha.
    """

    def __init__(self, env, codes):
        self.env = env
        # sudo(): lectura de servidor de valores normativos; solo se usan los
        # valores numéricos, nunca se devuelven los registros.
        self.Parameter = env["erp.payroll.parameter"].sudo()
        self.records = defaultdict(list)
        for record in self.Parameter.search_fetch(
            [("code", "in", list(codes))],
            ["code", "date_from", "company_id", "value"],
            order="date_from desc, id desc",
        ):
            self.records[record.code].append(
                (record.date_from, record.company_id.id, record.value)
            )

    def get(self, code, date, company):
        candidates = [
            (company_id, value)
            for date_from, company_id, value in self.records[code]
            if date_from <= date and company_id in (company.id, False)
        ]
        for company_id, value in candidates:
            if company_id:
                return value
        if candidates:
            return candidates[0][1]
        # Sin valor vigente: _get_value lanza el UserError estándar.
        return self.Parameter._get_value(code, date, company)

    def start_date(self, code, company):
        """«Vigente desde» más antiguo del parámetro para la empresa (o común).
        ``None`` si no tiene ningún valor activo."""
        dates = [
            date_from
            for date_from, company_id, _value in self.records[code]
            if company_id in (company.id, False)
        ]
        return min(dates) if dates else None


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    erp_company_entry_date = fields.Date(
        string="Fecha de ingreso a la empresa",
        groups="hr.group_hr_user",
        tracking=True,
        help="Fecha desde la que se cuentan los años de servicio para las "
        "vacaciones. Si está vacía se usa la fecha de inicio del primer "
        "contrato registrado. Regístrela cuando los contratos antiguos no "
        "estén cargados en el sistema.",
    )

    # ------------------------------------------------------------------
    # Aprobador de ausencias = Jefe inmediato (US-012, CA-5) y fecha de
    # ingreso (CA-9)
    # ------------------------------------------------------------------
    def write(self, vals):
        """Mantiene el aprobador de ausencias (``leave_manager_id``) derivado
        del Jefe inmediato (``parent_id``) y protege la fecha de ingreso.

        ``hr_holidays`` ya deriva el aprobador al crear y al cambiar el jefe
        cuando el nuevo jefe tiene usuario, y respeta el aprobador fijado a
        mano por RRHH (solo cambia los empleados cuyo aprobador es el usuario
        del jefe anterior o está vacío). Se completan dos casos que el núcleo
        no cubre:

        - El nuevo jefe no tiene usuario (o se quita el jefe): el aprobador que
          venía del jefe anterior se vacía (aprueba RRHH) en lugar de quedarse
          con el jefe anterior.
        - El jefe cambia de usuario: sus subordinados cuyo aprobador era el
          usuario anterior (o estaba vacío) pasan al usuario nuevo.

        Un aprobador fijado a mano (distinto del usuario del jefe) no se toca.

        Fecha de ingreso: si cambia la fecha efectiva (la propia o, si está
        vacía, la del primer contrato) de un empleado con periodos de
        vacaciones nacidos en la nueva fecha o después (una corrección), se
        exige rechazarlos y eliminarlos antes: se calcularon con la fecha
        anterior. Un reingreso (fecha posterior a todos sus periodos) se
        admite.
        """
        if "erp_company_entry_date" in vals:
            self._erp_check_entry_date_change(vals["erp_company_entry_date"])
        clear_manager = self.browse()
        subordinates_by_user = {}
        if "parent_id" in vals and "leave_manager_id" not in vals:
            new_parent = self.browse(vals["parent_id"] or [])
            if not new_parent.user_id:
                clear_manager = self.filtered(
                    lambda e: e.leave_manager_id
                    and e.leave_manager_id == e.parent_id.user_id
                )
        if "user_id" in vals:
            new_user_id = vals["user_id"] or False
            for employee in self:
                old_user = employee.user_id
                if old_user.id == new_user_id:
                    continue
                subordinates = employee.child_ids.filtered(
                    lambda child, old=old_user: child.leave_manager_id == old
                    or (not child.leave_manager_id and new_user_id)
                )
                if subordinates:
                    subordinates_by_user.setdefault(new_user_id, self.browse())
                    subordinates_by_user[new_user_id] |= subordinates
        res = super().write(vals)
        if clear_manager:
            clear_manager.write({"leave_manager_id": False})
        for user_id, subordinates in subordinates_by_user.items():
            # Los propios registros de esta escritura ya los trató el núcleo.
            (subordinates - self).write({"leave_manager_id": user_id})
        return res

    def _erp_check_entry_date_change(self, new_date):
        new_date = fields.Date.to_date(new_date)
        # sudo(): lectura de la fecha del primer contrato y de los periodos
        # para validar el cambio; no se devuelve ningún dato.
        changed = self.sudo().filtered(
            lambda e: e._erp_get_entry_date()
            != (new_date or e.first_contract_date or False)
        )
        if not changed:
            return
        # Mismo criterio que la generación (_erp_entry_date_conflicts): un
        # reingreso (contrato cerrado que termina antes de la nueva fecha) se
        # admite si los periodos del empleo anterior nacieron antes; volver a
        # la fecha con la que se calcularon los periodos (p. ej. fijar la
        # «Fecha de ingreso a la empresa» tras cambiar el primer contrato) se
        # admite; cualquier otro cambio con periodos activos se bloquea.
        active_periods = changed._erp_active_vacation_periods()
        closed_ends = changed._erp_closed_contract_ends()
        blocked = changed.filtered(
            lambda e: self._erp_entry_date_conflicts(
                new_date or e.first_contract_date or False,
                active_periods.get(e.id, []),
                closed_ends.get(e.id, []),
            )
        )
        if len(blocked) == 1:
            raise UserError(
                _(
                    "No se puede cambiar la fecha de ingreso de %(employee)s: "
                    "ya tiene periodos de vacaciones calculados con la fecha "
                    "anterior. Rechace y elimine esos periodos, cambie la fecha "
                    "y vuelva a calcular las vacaciones.",
                    employee=blocked.name,
                )
            )
        if blocked:
            raise UserError(
                _(
                    "No se puede cambiar la fecha de ingreso de %(employees)s: "
                    "ya tienen periodos de vacaciones calculados con la fecha "
                    "anterior. Rechace y elimine esos periodos, cambie la fecha "
                    "y vuelva a calcular las vacaciones.",
                    employees=self._erp_format_names(blocked),
                )
            )

    @api.model
    def _erp_format_names(self, employees, limit=5):
        """«Ana», «Ana y Luis», «Ana, Luis y Rosa» o, con más de ``limit``,
        «Ana, Luis, …, Rosa y 3 más»."""
        names = employees.mapped("name")
        if len(names) > limit:
            return _(
                "%(names)s y %(count)s más",
                names=", ".join(names[:limit]),
                count=len(names) - limit,
            )
        if len(names) == 1:
            return names[0]
        return _("%(names)s y %(last)s", names=", ".join(names[:-1]), last=names[-1])

    def _erp_closed_contract_ends(self):
        """Fechas de fin de los contratos cerrados de los empleados de
        ``self`` (una sola lectura), para reconocer un reingreso.

        :return: ``{employee_id: [date_end, ...]}``
        """
        # sudo(): lectura de servidor de las fechas de fin de contratos para
        # validar la fecha de ingreso; no se devuelven datos al usuario.
        ends = defaultdict(list)
        for contract in (
            self.env["hr.contract"]
            .sudo()
            .search_fetch(
                [
                    ("employee_id", "in", self.ids),
                    ("state", "=", "close"),
                    ("date_end", "!=", False),
                ],
                ["employee_id", "date_end"],
            )
        ):
            ends[contract.employee_id.id].append(contract.date_end)
        return ends

    def _erp_active_vacation_periods(self):
        """Periodos automáticos no rechazados de los empleados de ``self``,
        agrupados por empleado (una sola lectura).

        :return: ``{employee_id: [hr.leave.allocation, ...]}`` (sudo)
        """
        # sudo(): lectura de servidor de los periodos para validar la fecha
        # de ingreso; no se devuelven datos al usuario.
        periods = defaultdict(list)
        for allocation in (
            self.env["hr.leave.allocation"]
            .sudo()
            .search_fetch(
                [
                    ("employee_id", "in", self.ids),
                    ("erp_auto_generated", "=", True),
                    ("state", "!=", "refuse"),
                ],
                ["employee_id", "erp_entry_date", "date_from"],
            )
        ):
            periods[allocation.employee_id.id].append(allocation)
        return periods

    @api.model
    def _erp_entry_date_conflicts(self, entry, periods, closed_ends=()):
        """Periodos de ``periods`` (automáticos, no rechazados) calculados con
        otra fecha de ingreso que chocan con la fecha efectiva ``entry``: con
        ella se generarían otra vez años de servicio ya cubiertos (saldo
        duplicado; US-012, CA-R3-1).

        - Reingreso (decisión del Tech Lead, O-A): solo si el empleado tiene
          un contrato cerrado que termina antes de ``entry``. Entonces los
          periodos nacidos antes de ``entry`` son del empleo anterior y no
          estorban; los nacidos en ``entry`` o después sí.
        - En cualquier otro caso (p. ej. un adelanto de la fecha con el
          contrato aún abierto), todo periodo con otra fecha de ingreso choca.

        :param entry: fecha de ingreso efectiva (``False``: ninguna; todo
            periodo con fecha de ingreso choca)
        :param closed_ends: fechas de fin de los contratos cerrados del
            empleado (``_erp_closed_contract_ends``)
        :return: lista de periodos en conflicto
        """
        rehire = bool(entry) and any(end < entry for end in closed_ends)
        return [
            period
            for period in periods
            if period.erp_entry_date != entry
            and (not rehire or period.date_from >= entry)
        ]

    def action_time_off_dashboard(self):
        """Calendario de ausencias del empleado (botón de la ficha) con título
        en español: «Ausencias de <empleado>»."""
        action = super().action_time_off_dashboard()
        if len(self) == 1:
            action["name"] = _("Ausencias de %(employee)s", employee=self.name)
        else:
            action["name"] = _("Ausencias")
        return action

    # ------------------------------------------------------------------
    # Vacaciones anuales por antigüedad (US-012, CA-3, CA-9, CA-10, CA-12)
    # ------------------------------------------------------------------
    def _erp_get_entry_date(self):
        """Fecha de ingreso a la empresa para las vacaciones: la registrada
        por RRHH o, si está vacía, la del primer contrato."""
        self.ensure_one()
        return self.erp_company_entry_date or self.first_contract_date or False

    @api.model
    def _erp_vacation_eligible_domain(self):
        """Empleados con derecho a vacaciones: activos, con contrato en curso
        cuyo tipo genera relación laboral (y, por tanto, con fecha del primer
        contrato como fecha de ingreso de respaldo)."""
        return [
            ("active", "=", True),
            ("first_contract_date", "!=", False),
            ("contract_id.state", "=", "open"),
            ("contract_id.contract_type_id.erp_labor_relationship", "=", True),
        ]

    @api.model
    def _erp_lock_vacation_generation(self):
        """Candado de transacción contra la ejecución simultánea de la tarea
        diaria, el botón de cálculo y la carga histórica. Se libera solo al
        terminar la transacción (commit o rollback)."""
        self.env.cr.execute(SQL("SELECT pg_advisory_xact_lock(%s)", VACATION_LOCK_KEY))

    def _erp_get_vacation_type(self, types_by_company):
        """Tipo «Vacaciones anuales» del empleado: el de su empresa o, si no
        hay, el común (sin empresa)."""
        self.ensure_one()
        return types_by_company.get(self.company_id.id) or types_by_company.get(False)

    def _erp_get_vacation_work_rate(self):
        """Tasa de jornada para los días proporcionales (US-007).

        Jornada del contrato en curso (o la del empleado). Una tasa nula (no
        se puede calcular) o mayor que 1 cuenta como tiempo completo: la
        jornada parcial reduce los días, una jornada mayor no los aumenta.
        """
        self.ensure_one()
        calendar = self.contract_id.resource_calendar_id or self.resource_calendar_id
        if not calendar:
            return 1.0
        rate = calendar._erp_get_work_time_rate(self.company_id)
        if float_is_zero(rate, precision_digits=4) or rate > 1.0:
            return 1.0
        return rate

    @api.model
    def _erp_compute_vacation_days(self, params, service_year, anniversary, company):
        """Días de vacaciones del año de servicio ``service_year`` a tiempo
        completo: días base + adicionales.

        Adicionales = (año − año del primer adicional + 1) × días por año, a
        partir del año parametrizado, con tope (Código del Trabajo, art. 69;
        valores en parámetros «a validar»). Parámetros en la fecha del
        aniversario (cuando nace el derecho).

        :return: ``(base, adicionales)``
        """
        base = params.get(const.VACATION_BASE_DAYS, anniversary, company)
        from_year = params.get(const.VACATION_EXTRA_FROM_YEAR, anniversary, company)
        per_year = params.get(const.VACATION_EXTRA_DAYS_PER_YEAR, anniversary, company)
        max_extra = params.get(const.VACATION_EXTRA_MAX_DAYS, anniversary, company)
        extra = 0.0
        if service_year >= from_year:
            extra = min((service_year - from_year + 1) * per_year, max_extra)
        return base, max(extra, 0.0)

    @api.model
    def _erp_vacation_expiry(self, params, anniversary, company):
        """Fecha de caducidad del periodo cuyo derecho nace en
        ``anniversary`` (Código del Trabajo, art. 75; US-012, CA-10).

        Caduca el día anterior a ``anniversary`` + ``VACATION_VALIDITY_YEARS``
        años (valor vigente en el aniversario; admite fracciones de año, que
        se convierten a meses). Con el valor de partida 4: tres años de
        acumulación más el cuarto para gozarlas.
        """
        validity = params.get(const.VACATION_VALIDITY_YEARS, anniversary, company)
        months = int(float_round(validity * 12, precision_digits=0))
        if months <= 0:
            raise UserError(
                _(
                    "El parámetro de nómina %(code)s (años de vigencia de cada "
                    "periodo de vacaciones) debe ser mayor que cero. Corríjalo "
                    "en Parámetros de nómina.",
                    code=const.VACATION_VALIDITY_YEARS,
                )
            )
        return anniversary + relativedelta(months=months, days=-1)

    def _erp_vacation_periods(self, date, params, start_date=None):
        """Periodos de vacaciones que corresponden al empleado a ``date``.

        Un periodo por cada año de servicio cumplido desde la fecha de ingreso
        (``_erp_get_entry_date``), **excepto** los ya caducados a ``date``
        (límite de acumulación) y, si se indica ``start_date`` (corte de la
        tarea automática), los de aniversario anterior al corte. Se recorre
        del más reciente al más antiguo y se para en el primero caducado: los
        anteriores también lo están.

        :return: lista de ``(año de servicio, aniversario, caducidad)`` del
            más antiguo al más nuevo
        """
        self.ensure_one()
        entry = self._erp_get_entry_date()
        if not entry or entry > date:
            return []
        completed = relativedelta(date, entry).years
        periods = []
        for service_year in range(completed, 0, -1):
            anniversary = entry + relativedelta(years=service_year)
            if start_date and anniversary < start_date:
                break
            expiry = self._erp_vacation_expiry(params, anniversary, self.company_id)
            if expiry < date:
                break
            periods.append((service_year, anniversary, expiry))
        return periods[::-1]

    @api.model
    def _erp_format_number(self, value):
        """Número en el formato del idioma, sin decimales si es entero."""
        return text.format_number(self.env, value)

    def _erp_vacation_allocation_vals(self, vacation_type, period, base, extra, rate):
        self.ensure_one()
        service_year, anniversary, expiry = period
        entry = self._erp_get_entry_date()
        full_days = base + extra
        days = (
            float_round(
                full_days * rate * VACATION_ROUNDING_FRACTIONS,
                precision_digits=0,
                rounding_method="HALF-UP",
            )
            / VACATION_ROUNDING_FRACTIONS
        )
        notes = _(
            "Generada automáticamente por antigüedad. Fecha de ingreso: "
            "%(entry)s. Días base: %(base)s; días adicionales: %(extra)s; "
            "jornada: %(rate)s %%; total: %(days)s (redondeado al medio día). "
            "Caduca el %(expiry)s (límite de acumulación, Código del Trabajo, "
            "art. 75).",
            entry=format_date(self.env, entry),
            base=self._erp_format_number(base),
            extra=self._erp_format_number(extra),
            rate=self._erp_format_number(rate * 100),
            days=self._erp_format_number(days),
            expiry=format_date(self.env, expiry),
        )
        return {
            "name": self.env["hr.leave.allocation"]._erp_period_name(
                entry, service_year
            ),
            "employee_id": self.id,
            "holiday_status_id": vacation_type.id,
            "allocation_type": "regular",
            "number_of_days": days,
            "erp_entitled_days": days,
            # Vigencia: desde que nace el derecho hasta su caducidad. El
            # núcleo consume primero la asignación con fecha de fin más
            # próxima (FIFO) y no cuenta las caducadas en el saldo.
            "date_from": anniversary,
            "date_to": expiry,
            "erp_service_year": service_year,
            "erp_entry_date": entry,
            "erp_auto_generated": True,
            "notes": notes,
        }

    def _erp_entry_date_conflict_error(self, entry, conflicts):
        """Error de CA-R3-1: la fecha de ingreso efectiva cambió (p. ej. se
        cargó o corrigió un contrato anterior y la «Fecha de ingreso a la
        empresa» está vacía) y hay periodos calculados con la fecha anterior
        que se duplicarían."""
        self.ensure_one()
        old_dates = sorted({period.erp_entry_date for period in conflicts})
        if self.erp_company_entry_date:
            origin = _("«Fecha de ingreso a la empresa»")
        else:
            origin = _("inicio del primer contrato")
        return UserError(
            _(
                "La fecha de ingreso de %(employee)s cambió del %(old)s al "
                "%(new)s (%(origin)s) y ya tiene periodos de vacaciones "
                "calculados con la fecha anterior. No se generaron periodos "
                "nuevos para no duplicar su saldo. Para continuar: rechace y "
                "elimine los periodos calculados con la fecha anterior y vuelva "
                "a calcular, o registre en la ficha del empleado la «Fecha de "
                "ingreso a la empresa» correcta.",
                employee=self.name,
                old=", ".join(format_date(self.env, day) for day in old_dates),
                new=format_date(self.env, entry),
                origin=origin,
            )
        )

    def _erp_generate_employee_vacations(
        self,
        date,
        vacation_type,
        params,
        existing,
        start_date,
        active_periods=None,
        closed_ends=None,
    ):
        """Crea y valida los periodos pendientes de un empleado (ver
        ``_erp_generate_vacation_allocations``).

        :param active_periods: periodos automáticos no rechazados del
            empleado (``_erp_active_vacation_periods``); ``None``: se leen.
        :param closed_ends: fechas de fin de sus contratos cerrados
            (``_erp_closed_contract_ends``); ``None``: se leen.
        :raises UserError: la fecha de ingreso cambió y hay periodos
            calculados con la anterior que se duplicarían (CA-R3-1).
        :return: asignaciones creadas
        """
        self.ensure_one()
        Allocation = self.env["hr.leave.allocation"].sudo()
        if not vacation_type:
            raise UserError(
                _(
                    "No hay un tipo de ausencia activo marcado como «Vacaciones "
                    "anuales» para la empresa %(company)s. Márquelo en "
                    "Ausencias > Configuración > Tipos de ausencia.",
                    company=self.company_id.name,
                )
            )
        rate = None
        vals_list = []
        entry = self._erp_get_entry_date()
        if active_periods is None:
            active_periods = self._erp_active_vacation_periods().get(self.id, [])
        if closed_ends is None:
            closed_ends = self._erp_closed_contract_ends().get(self.id, [])
        conflicts = self._erp_entry_date_conflicts(entry, active_periods, closed_ends)
        if conflicts:
            raise self._erp_entry_date_conflict_error(entry, conflicts)
        for period in self._erp_vacation_periods(date, params, start_date):
            service_year, anniversary, _expiry = period
            if (self.id, vacation_type.id, entry, service_year) in existing:
                continue
            base, extra = self._erp_compute_vacation_days(
                params, service_year, anniversary, self.company_id
            )
            if rate is None:
                rate = self._erp_get_vacation_work_rate()
            vals = self._erp_vacation_allocation_vals(
                vacation_type, period, base, extra, rate
            )
            if float_compare(vals["number_of_days"], 0.0, precision_digits=2) <= 0:
                # Parámetros en cero: no hay días que asignar.
                continue
            vals_list.append(vals)
        if not vals_list:
            return Allocation
        with Allocation._erp_vacation_generation():
            allocations = Allocation.create(vals_list)
            allocations._erp_validate_generated()
        return allocations

    def _erp_generate_vacation_allocations(
        self, date=None, raise_on_error=True, from_cutoff=False, errors=None
    ):
        """Genera y valida los periodos de vacaciones pendientes de los
        empleados de ``self`` (US-012, CA-3, CA-9, CA-10, CA-12).

        - Solo empleados con derecho (``_erp_vacation_eligible_domain``): sin
          relación laboral o sin contrato en curso no reciben nada.
        - Un periodo por año de servicio cumplido a ``date`` desde la fecha de
          ingreso (``erp_company_entry_date`` o, si está vacía, la del primer
          contrato), con vigencia desde el aniversario hasta su caducidad
          (``VACATION_VALIDITY_YEARS``). Los periodos ya caducados a ``date``
          no se generan.
        - ``from_cutoff=False`` (cálculo inicial, botón de RRHH): todos los
          periodos vigentes desde el ingreso. ``from_cutoff=True`` (tarea
          diaria): solo los de aniversario igual o posterior al corte (el
          «Vigente desde» más antiguo de ``VACATION_GENERATION_START``).
        - Días = (base + adicionales) × tasa de jornada, redondeados al medio
          día, con los parámetros vigentes en cada aniversario. Se validan
          automáticamente (también con doble validación).
        - Idempotente: no se crea si ya existe una asignación automática del
          mismo empleado, tipo, fecha de ingreso y año, en cualquier estado
          (una rechazada a propósito no se regenera sola; para regenerarla,
          eliminarla). La
          restricción ``erp_auto_service_year_uniq`` lo garantiza en la BD.
        - Reingreso: con otra fecha de ingreso (la registrada por RRHH o la del
          primer contrato, que el núcleo reinicia tras un hueco entre
          contratos) los años de servicio vuelven a empezar en 1 y son
          periodos nuevos (la fecha de ingreso es parte de la clave).
        - Cambio de la fecha de ingreso (CA-R3-1): si hay periodos no
          rechazados calculados con otra fecha que nacen en la fecha actual o
          después (p. ej. se cargó un contrato anterior y la «Fecha de ingreso
          a la empresa» está vacía), no se genera nada para ese empleado y se
          lanza (o, en lote, se registra) un error que explica qué hacer.
        - Si el empleado tiene vacaciones gozadas antes del sistema, se
          vuelven a repartir (FIFO) incluyendo los periodos nuevos.
        - Concurrencia: candado de transacción ``pg_advisory_xact_lock``.
        - Aislamiento: cada empleado en su propio *savepoint*; con
          ``raise_on_error=False`` un error se registra en el log (y en
          ``errors``) y se sigue con los demás.

        :param date: fecha de cálculo (por defecto, hoy)
        :param raise_on_error: ``True``: el primer error lanza ``UserError``;
            ``False``: se registra y se sigue.
        :param from_cutoff: aplicar el corte de la generación automática
        :param errors: lista opcional donde se añaden ``(empleado, mensaje)``
        :return: asignaciones creadas (``hr.leave.allocation``, sudo)
        """
        date = fields.Date.to_date(date) or fields.Date.context_today(self)
        Allocation = self.env["hr.leave.allocation"].sudo()
        # sudo(): la generación crea y valida asignaciones de tipos con
        # validación de RRHH; quien la lanza (tarea o encargado de ausencias,
        # ver action_erp_generate_vacation_allocations) ya está autorizado.
        employees = self.sudo().filtered_domain(self._erp_vacation_eligible_domain())
        if not employees:
            return Allocation
        self._erp_lock_vacation_generation()
        types_by_company = {}
        for vacation_type in (
            self.env["hr.leave.type"]
            .sudo()
            .search_fetch([("erp_is_annual_vacation", "=", True)], ["company_id"])
        ):
            types_by_company[vacation_type.company_id.id] = vacation_type
        params = ErpVacationParameterTable(self.env, ALLOCATION_PARAMETER_CODES)
        # Idempotencia: una sola lectura de las asignaciones automáticas (en
        # cualquier estado); las no rechazadas sirven además para detectar un
        # cambio de la fecha de ingreso que duplicaría periodos (CA-R3-1).
        existing = set()
        active_periods = defaultdict(list)
        for allocation in Allocation.search_fetch(
            [
                ("erp_auto_generated", "=", True),
                ("employee_id", "in", employees.ids),
            ],
            [
                "employee_id",
                "holiday_status_id",
                "erp_entry_date",
                "erp_service_year",
                "date_from",
                "state",
            ],
        ):
            existing.add(
                (
                    allocation.employee_id.id,
                    allocation.holiday_status_id.id,
                    allocation.erp_entry_date,
                    allocation.erp_service_year,
                )
            )
            if allocation.state != "refuse":
                active_periods[allocation.employee_id.id].append(allocation)
        closed_ends = employees._erp_closed_contract_ends()
        with_history = set(
            self.env["erp.hr.vacation.history"]
            .sudo()
            .search_fetch([("employee_id", "in", employees.ids)], ["employee_id"])
            .employee_id.ids
        )

        created = Allocation
        for employee in employees:
            try:
                with self.env.cr.savepoint():
                    start_date = None
                    if from_cutoff:
                        start_date = params.start_date(
                            const.VACATION_GENERATION_START, employee.company_id
                        )
                        if not start_date:
                            # Lanza el error estándar que nombra el parámetro.
                            params.get(
                                const.VACATION_GENERATION_START,
                                date,
                                employee.company_id,
                            )
                    allocations = employee._erp_generate_employee_vacations(
                        date,
                        employee._erp_get_vacation_type(types_by_company),
                        params,
                        existing,
                        start_date,
                        active_periods=active_periods.get(employee.id, []),
                        closed_ends=closed_ends.get(employee.id, []),
                    )
                    if allocations and employee.id in with_history:
                        employee._erp_apply_vacation_history()
            except Exception as error:  # noqa: BLE001 - aislamiento por empleado
                self._erp_vacation_generation_error(
                    employee, error, raise_on_error, errors
                )
                continue
            created |= allocations
        return created

    @api.model
    def _erp_vacation_generation_error(self, employee, error, raise_on_error, errors):
        """Error al generar los periodos de un empleado.

        Un error de negocio (``UserError``) se muestra con su mensaje; uno
        técnico se registra con su traza y se informa sin detalles internos.
        Con ``raise_on_error`` (un solo empleado), el error de negocio se
        relanza tal cual (su mensaje ya nombra lo necesario, sin repetir el
        empleado) y el técnico como ``UserError`` con el texto genérico, sin
        traza para el usuario. Se llama desde el bloque ``except``."""
        business = isinstance(error, UserError)
        detail = (
            error.args[0]
            if business
            else _("error técnico; el detalle quedó en el registro del servidor")
        )
        message = _(
            "No se pudieron generar las vacaciones de %(employee)s: %(error)s",
            employee=employee.name,
            error=detail,
        )
        if raise_on_error:
            if business:
                raise error
            _logger.exception("%s", message)
            raise UserError(message) from error
        if business:
            _logger.warning("%s", message)
        else:
            _logger.exception("%s", message)
        if errors is not None:
            errors.append((employee, message))

    def action_erp_generate_vacation_allocations(self):
        """Botón «Calcular vacaciones» (encargado de ausencias): cálculo
        inicial y puesta al día de los periodos de los empleados
        seleccionados a la fecha de hoy, desde su fecha de ingreso y dentro
        del límite de acumulación (sin el corte de la tarea automática). Los
        empleados sin derecho se omiten.

        Con un solo empleado, un error se muestra tal cual; con varios, cada
        empleado se procesa aparte y los errores se listan en la
        notificación.

        :return: notificación con el resultado
        """
        if not self.env.user.has_group(LEAVE_OFFICER_GROUP):
            raise AccessError(
                _(
                    "Solo un encargado de ausencias (Talento Humano) puede "
                    "calcular las vacaciones por antigüedad."
                )
            )
        # Reglas de registro (empresa) sobre los empleados seleccionados.
        self.check_access("read")
        errors = []
        allocations = self._erp_generate_vacation_allocations(
            raise_on_error=len(self) == 1, errors=errors
        )
        eligible = self.sudo().filtered_domain(self._erp_vacation_eligible_domain())
        skipped = len(self) - len(eligible)
        if len(allocations) == 1:
            message = _("Se generó 1 periodo de vacaciones.")
            notification_type = "success"
        elif allocations:
            message = _(
                "Se generaron %(count)s periodos de vacaciones.",
                count=len(allocations),
            )
            notification_type = "success"
        elif not eligible:
            # Ningún seleccionado tiene derecho: decir quién y qué hacer, no
            # que «ya tienen su periodo» (QA-UX).
            not_eligible = self.sudo() - eligible
            if len(not_eligible) == 1:
                message = _(
                    "No se calcularon vacaciones: %(employees)s no tiene un "
                    "contrato en curso con relación laboral. Registre el "
                    "contrato y vuelva a calcular.",
                    employees=not_eligible.name,
                )
            else:
                message = _(
                    "No se calcularon vacaciones: %(employees)s no tienen un "
                    "contrato en curso con relación laboral. Registre los "
                    "contratos y vuelva a calcular.",
                    employees=self._erp_format_names(not_eligible),
                )
            return self._erp_generation_notification(message, "warning", errors)
        else:
            message = _(
                "No hay periodos de vacaciones pendientes de generar: los años "
                "de servicio cumplidos y vigentes ya tienen su periodo."
            )
            notification_type = "info"
        if skipped == 1:
            message += " " + _(
                "1 empleado sin relación laboral o sin contrato en curso no "
                "recibe vacaciones."
            )
        elif skipped:
            message += " " + _(
                "%(count)s empleados sin relación laboral o sin contrato en "
                "curso no reciben vacaciones.",
                count=skipped,
            )
        return self._erp_generation_notification(message, notification_type, errors)

    @api.model
    def _erp_generation_notification(self, message, notification_type, errors):
        """Notificación del botón «Calcular vacaciones»; los errores por
        empleado se añaden al final y la dejan fija (aviso)."""
        if errors:
            message += "\n" + "\n".join(error for _employee, error in errors)
            notification_type = "warning"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Vacaciones por antigüedad"),
                "message": message,
                "type": notification_type,
                "sticky": bool(errors) or notification_type == "warning",
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    # ------------------------------------------------------------------
    # Vacaciones gozadas antes del sistema (US-012, CA-11)
    # ------------------------------------------------------------------
    @api.model
    def _erp_vacation_history_targets(self, allocations, line):
        """Periodos a los que se puede descontar una línea de carga histórica,
        en orden FIFO: el año de servicio indicado o, si no lo hay, los
        periodos vigentes en la fecha de la línea (nacidos y no caducados)."""
        if line.service_year:
            return allocations.filtered(
                lambda a: a.erp_service_year == line.service_year
            )
        return allocations.filtered(
            lambda a: a.date_from <= line.date
            and (not a.date_to or a.date_to >= line.date)
        )

    @api.model
    def _erp_vacation_excess(self, employee, leave_types):
        """Días de ausencias aprobadas que no cubre ningún periodo."""
        excess = employee._get_consumed_leaves(leave_types)[1]
        return sum(
            data["amount"]
            for leave_type in leave_types
            for data in excess[employee][leave_type]["excess_days"].values()
            if not data["is_virtual"]
        )

    def _erp_apply_vacation_history(self):
        """Reparte las vacaciones gozadas antes del sistema
        (``erp.hr.vacation.history``) entre los periodos automáticos validados
        del empleado, del más antiguo al más nuevo (FIFO por fecha de
        caducidad, el mismo orden con el que el núcleo descuenta las
        ausencias nuevas).

        Por cada periodo se guarda lo descontado en ``erp_history_days`` y se
        resta de ``number_of_days`` (el saldo que usa el núcleo): las
        ausencias registradas en el sistema se descuentan después, también en
        FIFO, de lo que queda. Se aplica la diferencia con el reparto
        anterior, de modo que un ajuste manual de los días del periodo se
        conserva. Se recalcula entero en cada cambio de la carga histórica o
        de los periodos.

        :raises UserError: los días gozados superan los de los periodos
            vigentes en su fecha, o un ajuste manual deja el periodo negativo.
        :raises ValidationError: con la carga, ausencias ya aprobadas quedan
            sin saldo.
        """
        if not self:
            return
        self._erp_lock_vacation_generation()
        # sudo(): reparto de servidor sobre asignaciones de vacaciones; quien
        # lo lanza (encargado de ausencias, ACL de erp.hr.vacation.history, o
        # la generación) ya está autorizado. Los campos protegidos se
        # escriben dentro de _erp_vacation_generation().
        employees = self.sudo()
        History = self.env["erp.hr.vacation.history"].sudo()
        Allocation = self.env["hr.leave.allocation"].sudo()
        lines = History.search([("employee_id", "in", employees.ids)], order="date, id")
        allocations = Allocation.search(
            [
                ("employee_id", "in", employees.ids),
                ("erp_auto_generated", "=", True),
                ("holiday_status_id.erp_is_annual_vacation", "=", True),
                ("state", "=", "validate"),
            ],
            order="date_to, date_from, id",
        )
        for employee in employees:
            emp_allocations = allocations.filtered(
                lambda a, e=employee: a.employee_id == e
            )
            leave_types = emp_allocations.holiday_status_id
            excess_before = self._erp_vacation_excess(employee, leave_types)
            free = {
                a.id: a.number_of_days + a.erp_history_days for a in emp_allocations
            }
            new_history = dict.fromkeys(emp_allocations.ids, 0.0)
            for line in lines.filtered(lambda h, e=employee: h.employee_id == e):
                remaining = line.number_of_days
                targets = self._erp_vacation_history_targets(emp_allocations, line)
                for allocation in targets:
                    take = min(remaining, free[allocation.id])
                    if float_compare(take, 0.0, precision_digits=2) <= 0:
                        continue
                    free[allocation.id] -= take
                    new_history[allocation.id] += take
                    remaining -= take
                    if float_is_zero(remaining, precision_digits=2):
                        break
                if float_compare(remaining, 0.0, precision_digits=2) > 0:
                    raise UserError(
                        _(
                            "Los días gozados de %(employee)s del %(date)s "
                            "(%(days)s) superan los días de sus periodos de "
                            "vacaciones vigentes en esa fecha (faltan "
                            "%(missing)s). Calcule primero sus vacaciones "
                            "(botón «Calcular vacaciones») o revise los días, la "
                            "fecha o el año de servicio de la carga.",
                            days=text.format_days(self.env, line.number_of_days),
                            employee=employee.name,
                            date=format_date(self.env, line.date),
                            missing=text.format_days(
                                self.env, float_round(remaining, precision_digits=2)
                            ),
                        )
                    )
            with Allocation._erp_vacation_generation():
                for allocation in emp_allocations:
                    old = allocation.erp_history_days
                    new = float_round(new_history[allocation.id], precision_digits=2)
                    if float_compare(old, new, precision_digits=2) == 0:
                        continue
                    net = float_round(
                        allocation.number_of_days + old - new, precision_digits=2
                    )
                    if float_compare(net, 0.0, precision_digits=2) < 0:
                        raise UserError(
                            _(
                                "El periodo «%(period)s» de %(employee)s quedaría "
                                "con saldo negativo: revise los días del periodo "
                                "o la carga de vacaciones gozadas.",
                                period=allocation.name,
                                employee=employee.name,
                            )
                        )
                    allocation.write({"erp_history_days": new, "number_of_days": net})
            excess_after = self._erp_vacation_excess(employee, leave_types)
            if float_compare(excess_after, excess_before, precision_digits=2) > 0:
                raise ValidationError(
                    _(
                        "Con estas vacaciones gozadas antes del sistema, las "
                        "ausencias ya aprobadas de %(employee)s superan su saldo "
                        "en %(days)s. Revise la carga histórica o las "
                        "ausencias aprobadas.",
                        employee=employee.name,
                        days=text.format_days(
                            self.env, float_round(excess_after - excess_before, 2)
                        ),
                    )
                )
