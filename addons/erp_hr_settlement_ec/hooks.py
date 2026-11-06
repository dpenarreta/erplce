import logging

from odoo.exceptions import UserError
from odoo.tools import SQL

from odoo.addons.erp_hr_holidays_ec.models.const import ALLOCATION_DURATION_CHECK

_logger = logging.getLogger(__name__)

ALLOCATION_DURATION_CONSTRAINT = "hr_leave_allocation_duration_check"


def uninstall_hook(env):
    """Prepara la desinstalación de la liquidación de haberes (US-013).

    1. Bloqueo: si hay liquidaciones confirmadas, ``UserError`` (se revierte
       toda la desinstalación). Al desinstalar, Odoo eliminaría en cascada
       sus marcas de provisión pagada (valor ``settlement`` de
       ``erp.payroll.provision.payment.document_type``) y las columnas de
       periodos de vacaciones liquidados: esas provisiones y esos días
       volverían a quedar pendientes y se pagarían dos veces. Primero hay
       que anular las liquidaciones confirmadas (lo que revierte su asiento
       y restituye provisiones y saldos).
    2. Restricción ``hr_leave_allocation_duration_check``: este módulo la
       redefine con ``erp_settlement_id``; al eliminar esa columna
       PostgreSQL elimina también la restricción, y Odoo no la vuelve a
       crear porque la siguen declarando hr_holidays y erp_hr_holidays_ec.
       Se restituye aquí, antes de eliminar la columna, con la definición
       de erp_hr_holidays_ec (que no usa esa columna). Sin liquidaciones
       confirmadas ningún periodo está liquidado, así que los datos la
       cumplen.
    """
    done = env["erp.hr.settlement"].sudo().search_count([("state", "=", "done")])
    if done:
        raise UserError(
            env._(
                "No se puede desinstalar la liquidación de haberes: hay %(count)s "
                "liquidaciones confirmadas. Anúlelas antes (se revierten sus "
                "asientos y vuelven a quedar pendientes sus provisiones de "
                "décimos y sus días de vacaciones); de lo contrario esos "
                "valores se pagarían dos veces.",
                count=done,
            )
        )
    env.cr.execute(
        SQL(
            "ALTER TABLE hr_leave_allocation DROP CONSTRAINT IF EXISTS %s",
            SQL.identifier(ALLOCATION_DURATION_CONSTRAINT),
        )
    )
    env.cr.execute(
        SQL(
            "ALTER TABLE hr_leave_allocation ADD CONSTRAINT %s %s",
            SQL.identifier(ALLOCATION_DURATION_CONSTRAINT),
            SQL(ALLOCATION_DURATION_CHECK),
        )
    )
    _logger.info(
        "erp_hr_settlement_ec: restricción %s restituida con la definición de "
        "erp_hr_holidays_ec.",
        ALLOCATION_DURATION_CONSTRAINT,
    )
