"""18.0.1.0.1 (US-012, ronda de pulido):

- La tarea programada (dato ``noupdate``) se llamaba «… generar asignaciones
  anuales de vacaciones»; pasa a «… generar periodos anuales de vacaciones»
  (sin «asignación», QA-UX O-C). Solo se cambia si conserva el nombre
  original, en cada idioma instalado; no se toca su estado (sigue inactiva
  salvo que el administrador la haya activado) ni su horario.
- La restricción ``erp_vacation_history_uniq`` (una línea de vacaciones
  gozadas por empleado, fecha y año de servicio) la crea el ORM al actualizar.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

XMLID = "erp_hr_holidays_ec.ir_cron_generate_vacation_allocations"
OLD_NAME = "Ausencias Ecuador: generar asignaciones anuales de vacaciones"
NEW_NAME = "Ausencias Ecuador: generar periodos anuales de vacaciones"


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref(XMLID, raise_if_not_found=False)
    if not cron:
        return
    langs = ["en_US"] + [
        code for code, _name in env["res.lang"].get_installed() if code != "en_US"
    ]
    for lang in langs:
        localized = cron.with_context(lang=lang)
        if localized.name == OLD_NAME:
            localized.name = NEW_NAME
            _logger.info(
                "erp_hr_holidays_ec 18.0.1.0.1: nombre de la tarea %s "
                "actualizado (%s).",
                XMLID,
                lang,
            )
