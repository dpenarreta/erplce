from odoo import api, models
from odoo.tools import float_is_zero, float_round

# Jornada por defecto que crea el núcleo (``resource.resource_calendar_std`` y
# ``res.company._init_data_resource_calendar``) y su nombre en español de
# Ecuador. ``resource.calendar.name`` no es traducible: se renombra el registro.
DEFAULT_CALENDAR_ORIGINAL_NAME = "Standard 40 hours/week"
DEFAULT_CALENDAR_ES_NAME = "Estándar 40 horas/semana"


class ResourceCalendar(models.Model):
    _inherit = "resource.calendar"

    @api.model
    def _erp_rename_default_calendars(self):
        """Renombra a «Estándar 40 horas/semana» las jornadas que conservan el
        nombre original del núcleo «Standard 40 hours/week» (de todas las
        empresas, archivadas incluidas). Idempotente: una jornada renombrada
        por el usuario no se toca. Lo llama ``data/resource_calendar_data.xml``
        en cada instalación y actualización del módulo.

        :return: jornadas renombradas
        """
        # sudo(): proceso de instalación de datos; afecta solo al nombre de las
        # jornadas que conservan el nombre por defecto del núcleo.
        calendars = (
            self.sudo()
            .with_context(active_test=False)
            .search([("name", "=", DEFAULT_CALENDAR_ORIGINAL_NAME)])
        )
        if calendars:
            calendars.write({"name": DEFAULT_CALENDAR_ES_NAME})
        return calendars

    def _erp_get_weekly_hours(self):
        """Horas semanales de trabajo de la jornada (promedio semanal).

        - Suma la duración de las asistencias generales de la jornada
          (``_get_global_attendances``: sin descansos ``day_period = lunch``,
          sin líneas de sección ``display_type``, sin asistencias propias de
          un recurso ni periodos con fechas de vigencia).
        - Jornada de dos semanas: promedio semanal (suma / 2).
        - Jornada flexible: ``full_time_required_hours`` (horas semanales que
          Odoo reparte en los días de la semana).

        :return: horas semanales redondeadas a 2 decimales
        """
        self.ensure_one()
        if self.flexible_hours:
            return float_round(self.full_time_required_hours, precision_digits=2)
        hours = sum(
            attendance.hour_to - attendance.hour_from
            for attendance in self._get_global_attendances()
        )
        if self.two_weeks_calendar:
            hours /= 2
        return float_round(hours, precision_digits=2)

    def _erp_get_work_time_rate(self, company=None):
        """Tasa de tiempo de trabajo de la jornada para la nómina (US-008).

        Horas semanales de la jornada / horas de tiempo completo, donde el
        tiempo completo es ``full_time_required_hours`` de la jornada si está
        definido y, si no, el máximo semanal de la empresa
        (``res.company.erp_max_weekly_hours``). Odoo 18 Community no trae el
        campo ``work_time_rate`` (es de nómina Enterprise).

        :param company: empresa cuyo máximo se usa (por defecto la de la
            jornada o la actual)
        :return: tasa entre 0 y 1 (puede superar 1 si la jornada excede el
            tiempo completo), 4 decimales
        """
        self.ensure_one()
        full_time = self.full_time_required_hours
        if float_is_zero(full_time, precision_digits=2):
            company = company or self.company_id or self.env.company
            full_time = company.erp_max_weekly_hours
        if float_is_zero(full_time, precision_digits=2):
            return 0.0
        return float_round(self._erp_get_weekly_hours() / full_time, precision_digits=4)

    @api.constrains(
        "attendance_ids",
        "two_weeks_calendar",
        "flexible_hours",
        "full_time_required_hours",
    )
    def _check_erp_max_weekly_hours_running_contracts(self):
        """Al modificar una jornada, sus contratos en curso deben seguir
        dentro del máximo semanal de su empresa.

        Se dispara al editar la jornada (sus asistencias, el modo de dos
        semanas, el modo flexible o las horas de tiempo completo, que son las
        horas semanales de una jornada flexible) desde el formulario de
        jornadas; editar una asistencia suelta fuera de la jornada no lo
        dispara.
        """
        # sudo: quien edita la jornada puede no tener acceso a contratos; solo
        # se valida, el mensaje indica la jornada y el contrato afectado.
        contracts = (
            self.env["hr.contract"]
            .sudo()
            .search([("resource_calendar_id", "in", self.ids), ("state", "=", "open")])
        )
        contracts._erp_check_max_weekly_hours()
