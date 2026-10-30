from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, format_date, formatLang

from . import const

LEAVE_OFFICER_GROUP = "hr_holidays.group_hr_holidays_user"


class HrLeave(models.Model):
    """Solicitudes de ausencia con las reglas de Ecuador (US-012, CA-6)."""

    _inherit = "hr.leave"

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _erp_company(self):
        self.ensure_one()
        return self.employee_company_id or self.company_id or self.env.company

    def _erp_request_date(self):
        self.ensure_one()
        return self.request_date_from or (self.date_from and self.date_from.date())

    @api.model
    def _erp_format_number(self, value):
        digits = 0 if float(value).is_integer() else 2
        return formatLang(self.env, value, digits=digits)

    @api.model
    def _erp_unit_label(self, request_unit):
        return _("horas") if request_unit == "hour" else _("días")

    # ------------------------------------------------------------------
    # Conteo de días calendario (US-012, CA-6)
    # ------------------------------------------------------------------
    def _erp_calendar_count_code(self):
        """Código del parámetro que decide si la solicitud se cuenta en días
        calendario, o ``False`` si sigue el conteo nativo (días laborables).

        - Vacaciones anuales: ``VACATION_COUNT_CALENDAR_DAYS``.
        - Licencias por días con duración máxima legal (maternidad,
          paternidad, calamidad doméstica): ``LEAVE_COUNT_CALENDAR_DAYS``.
        - Resto (enfermedad, tipos por horas, permisos por horas y solicitudes
          con horas personalizadas): conteo nativo.
        """
        self.ensure_one()
        leave_type = self.holiday_status_id
        if (
            not leave_type
            or leave_type.request_unit not in ("day", "half_day")
            or self.request_unit_hours
        ):
            return False
        if leave_type.erp_is_annual_vacation:
            return const.VACATION_COUNT_CALENDAR_DAYS
        if leave_type.erp_max_duration_param_code:
            return const.LEAVE_COUNT_CALENDAR_DAYS
        return False

    def _get_durations(self, check_leave_type=True, resource_calendar=None):
        """Si el parámetro de conteo vale 1, la duración en días de la
        solicitud son los días naturales entre la fecha de inicio y la de fin
        (ambas incluidas, con fines de semana y feriados); media jornada = 0,5.
        Las horas siguen siendo las laborables (las que deja de trabajar). El
        saldo de vacaciones se descuenta con esta duración en días.

        Se aplica también con ``check_leave_type=False`` para que el aviso
        nativo «solo días completos» no salte por los días no laborables.
        """
        result = super()._get_durations(
            check_leave_type=check_leave_type, resource_calendar=resource_calendar
        )
        Parameter = self.env["erp.payroll.parameter"]
        values = {}
        for leave in self:
            code = leave._erp_calendar_count_code()
            if not code or leave.id not in result:
                continue
            if not leave.request_date_from or not leave.request_date_to:
                continue
            key = (code, leave.request_date_from, leave._erp_company().id)
            if key not in values:
                values[key] = Parameter._get_value(
                    code, leave.request_date_from, leave._erp_company()
                )
            if float_compare(values[key], 1.0, precision_digits=2) != 0:
                continue
            if leave.request_unit_half:
                days = 0.5
            else:
                days = (leave.request_date_to - leave.request_date_from).days + 1
            result[leave.id] = (days, result[leave.id][1])
        return result

    # ------------------------------------------------------------------
    # Saldo insuficiente (US-012, CA-6)
    # ------------------------------------------------------------------
    def _check_validity(self):
        """Saldo: el control es el nativo; si falla, se sustituye su mensaje
        (sin traducir y sin cifras) por uno en español con el saldo
        disponible. Después, duración máxima por solicitud."""
        try:
            res = super()._check_validity()
        except ValidationError as error:
            message = self._erp_balance_error_message()
            if not message:
                raise
            raise ValidationError(message) from error
        # El núcleo llama a _check_validity después de recalcular la duración
        # al crear (en la restricción, durante el INSERT, la duración puede
        # estar aún sin calcular) y al cambiar fechas, tipo o estado.
        self._check_erp_max_duration()
        return res

    def _erp_balance_error_message(self):
        """Mensaje en español del control nativo de saldo, solo para los
        empleados cuyas solicitudes realmente fallan (mismo criterio que
        ``hr.leave._check_validity``: sin asignación vigente, o las
        solicitudes generan un exceso que sin ellas no había).

        :return: texto, o ``False`` si no se identifica la causa (se deja el
            error nativo)
        """
        groups = defaultdict(lambda: self.env["hr.leave"])
        for leave in self:
            leave_type = leave.holiday_status_id
            if (
                leave_type.requires_allocation == "yes"
                and not leave_type.allows_negative
                and leave.date_from
            ):
                groups[(leave_type, leave.date_from.date())] |= leave
        messages = []
        for (leave_type, date_from), leaves in groups.items():
            employees = leaves.employee_id
            data = leave_type.get_allocation_data(employees, date_from)
            previous = leave_type.with_context(
                ignored_leave_ids=leaves.ids
            ).get_allocation_data(employees, date_from)
            unit = leave_type.request_unit
            field = "number_of_hours" if unit == "hour" else "number_of_days"
            for employee in employees:
                info = data[employee][0][1] if data.get(employee) else {}
                before = previous[employee][0][1] if previous.get(employee) else {}
                if not info.get("max_leaves"):
                    messages.append(
                        _(
                            "%(employee)s no tiene saldo de «%(type)s» vigente al "
                            "%(date)s. Pida a Talento Humano la asignación antes de "
                            "solicitar la ausencia.",
                            employee=employee.name,
                            type=leave_type.name,
                            date=format_date(self.env, date_from),
                        )
                    )
                    continue
                excess = info.get("virtual_excess_data") or {}
                excess_before = before.get("virtual_excess_data") or {}
                if not excess or (
                    excess == excess_before or len(excess) < len(excess_before)
                ):
                    # Este empleado no es el que hace fallar el control.
                    continue
                requested = sum(
                    leaves.filtered(lambda lv, e=employee: lv.employee_id == e).mapped(
                        field
                    )
                )
                available = max(before.get("virtual_remaining_leaves", 0.0), 0.0)
                if float_compare(requested, available, precision_digits=2) <= 0:
                    # Hay saldo en total, pero no en las fechas pedidas: parte
                    # de la solicitud cae fuera de la vigencia de los periodos.
                    messages.append(
                        _(
                            "Saldo insuficiente de «%(type)s» para %(employee)s en "
                            "las fechas solicitadas: parte de los días cae después "
                            "de la caducidad de un periodo o antes de que nazca el "
                            "siguiente. Divida la solicitud o ajuste las fechas.",
                            type=leave_type.name,
                            employee=employee.name,
                        )
                    )
                    continue
                messages.append(
                    _(
                        "Saldo insuficiente de «%(type)s» para %(employee)s: "
                        "disponible %(available)s %(unit)s, solicitado "
                        "%(requested)s %(unit)s. Reduzca las fechas de la "
                        "solicitud o pida a Talento Humano una asignación "
                        "adicional.",
                        type=leave_type.name,
                        employee=employee.name,
                        available=self._erp_format_number(available),
                        requested=self._erp_format_number(requested),
                        unit=self._erp_unit_label(unit),
                    )
                )
        return "\n".join(messages) or False

    # ------------------------------------------------------------------
    # Duración máxima por solicitud (US-012, CA-6)
    # ------------------------------------------------------------------
    @api.constrains(
        "holiday_status_id",
        "employee_id",
        "request_date_from",
        "request_date_to",
        "request_unit_half",
        "request_unit_hours",
        "request_hour_from",
        "request_hour_to",
        "date_from",
        "date_to",
    )
    def _check_erp_max_duration(self):
        """La solicitud no supera la duración máxima legal de su tipo
        (``erp_max_duration_param_code``, parámetro con vigencia en la fecha
        de inicio):

        - Tipos por días: días de la solicitud (con la convención de conteo
          parametrizada, ver ``_get_durations``).
        - Tipos por horas (lactancia): horas por día = horas de la solicitud /
          días (mínimo 1); una solicitud de horas en un solo día compara sus
          horas.
        """
        Parameter = self.env["erp.payroll.parameter"]
        for leave in self:
            code = leave.holiday_status_id.erp_max_duration_param_code
            when = leave._erp_request_date()
            if not code or not when or leave.state in ("refuse", "cancel"):
                continue
            maximum = Parameter._get_value(code, when, leave._erp_company())
            if leave.leave_type_request_unit == "hour":
                value = leave.number_of_hours / max(leave.number_of_days, 1.0)
                if float_compare(value, maximum, precision_digits=2) > 0:
                    raise ValidationError(
                        _(
                            "La solicitud de «%(type)s» equivale a %(value)s horas "
                            "por día y supera el máximo de %(maximum)s horas por "
                            "día. Reduzca las horas de la solicitud.",
                            type=leave.holiday_status_id.name,
                            value=self._erp_format_number(round(value, 2)),
                            maximum=self._erp_format_number(maximum),
                        )
                    )
                continue
            if float_compare(leave.number_of_days, maximum, precision_digits=2) > 0:
                raise ValidationError(
                    _(
                        "La solicitud de «%(type)s» dura %(value)s días y supera "
                        "la duración máxima de %(maximum)s días por solicitud. "
                        "Ajuste las fechas.",
                        type=leave.holiday_status_id.name,
                        value=self._erp_format_number(leave.number_of_days),
                        maximum=self._erp_format_number(maximum),
                    )
                )

    # ------------------------------------------------------------------
    # Adjunto obligatorio (US-012, CA-2 / CA-6)
    # ------------------------------------------------------------------
    def _erp_check_required_attachments(self):
        """Los tipos con «Adjunto obligatorio» no se aprueban sin documento
        de respaldo. La solicitud sí se puede registrar sin él (p. ej. el
        certificado médico llega al volver al trabajo); queda «Por aprobar»
        hasta que se adjunte. Los tipos sin aprobación (``no_validation``)
        no pueden exigir adjunto (restricción del tipo) y se omiten."""
        leaves = self.filtered(
            lambda leave: leave.holiday_status_id.erp_attachment_required
            and leave.validation_type != "no_validation"
        )
        if not leaves:
            return
        # sudo(): solo se cuentan los adjuntos de solicitudes que el usuario
        # está aprobando (el acceso lo comprueba el flujo nativo); no se
        # devuelve ningún dato de los adjuntos.
        with_documents = set(
            self.env["ir.attachment"]
            .sudo()
            .search_fetch(
                [("res_model", "=", self._name), ("res_id", "in", leaves.ids)],
                ["res_id"],
            )
            .mapped("res_id")
        )
        missing = leaves.filtered(lambda leave: leave.id not in with_documents)
        if missing:
            raise UserError(
                _(
                    "No se puede aprobar sin el documento de respaldo (p. ej. "
                    "certificado médico). Adjúntelo en la solicitud y vuelva a "
                    "aprobar: %(leaves)s",
                    leaves=", ".join(
                        f"{leave.employee_id.name} – {leave.holiday_status_id.name}"
                        for leave in missing
                    ),
                )
            )

    def action_approve(self, check_state=True):
        # Las de validación simple las comprueba action_validate, al que llama
        # el núcleo: aquí solo la primera aprobación de las de doble
        # validación, para no buscar los adjuntos dos veces.
        self.filtered(
            lambda leave: leave.validation_type == "both"
        )._erp_check_required_attachments()
        return super().action_approve(check_state=check_state)

    def action_validate(self, check_state=True):
        self._erp_check_required_attachments()
        return super().action_validate(check_state=check_state)

    # ------------------------------------------------------------------
    # Anulación de solicitudes aprobadas (US-012, CA-6)
    # ------------------------------------------------------------------
    @api.ondelete(at_uninstall=False)
    def _unlink_except_erp_first_approval(self):
        """El núcleo deja eliminar al empleado (o al jefe sin grupo de
        ausencias) una solicitud con la primera aprobación (``validate1``,
        doble validación). Aquí no: ya la aprobó el jefe; la anulan el jefe o
        RRHH con el asistente «Anular» (queda el motivo en el historial)."""
        if self.env.su or self.env.user.has_group(LEAVE_OFFICER_GROUP):
            return
        approved = self.filtered(lambda leave: leave.state == "validate1")
        if approved:
            raise UserError(
                _(
                    "La solicitud de %(employee)s ya tiene la aprobación del jefe "
                    "y no se puede eliminar. Pida a su jefe inmediato o a Talento "
                    "Humano que la anule.",
                    employee=", ".join(approved.employee_id.mapped("name")),
                )
            )

    @api.depends_context("uid")
    @api.depends("state", "employee_id")
    def _compute_can_cancel(self):
        """Una solicitud aprobada (o con la primera aprobación) que aún no
        empieza solo la anula el aprobador del empleado (Jefe inmediato) o un
        encargado de ausencias (RRHH), con motivo (asistente nativo, queda en
        el historial). En Odoo la anulaba el propio empleado; aquí el empleado
        debe pedírsela a su jefe. Las solicitudes ya iniciadas se rechazan con
        «Rechazar» (jefe/RRHH)."""
        today = fields.Date.context_today(self)
        is_officer = self.env.user.has_group(LEAVE_OFFICER_GROUP)
        for leave in self:
            leave.can_cancel = bool(
                leave.id
                and leave.state in ("validate", "validate1")
                and leave.date_from
                and leave.date_from.date() >= today
                and (
                    is_officer
                    # sudo(): solo se compara el aprobador del empleado con el
                    # usuario actual (lo mismo que hace el flujo nativo).
                    or leave.employee_id.sudo().leave_manager_id == self.env.user
                )
            )
