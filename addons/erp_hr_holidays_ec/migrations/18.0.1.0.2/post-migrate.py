"""18.0.1.0.2 (US-013, corrección autorizada por el Tech Lead):

La restricción ``duration_check`` de ``hr.leave.allocation`` pasa a usar
``COALESCE(erp_history_days, 0)``: antes, con ``erp_history_days`` NULL la
condición daba NULL y PostgreSQL aceptaba un saldo regular de 0 o negativo.

El ORM vuelve a crear la restricción al actualizar el módulo (detecta que la
definición cambió). Si alguna fila la incumpliera, PostgreSQL no podría
crearla y Odoo solo lo registraría en el log; aquí se cuenta y se avisa, sin
modificar datos (en erp_dev se comprobó que ninguna fila la incumple).
"""

import logging

from odoo.tools import SQL
from odoo.tools.sql import column_exists

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    # erp_hr_settlement_ec admite además saldo 0 en periodos liquidados.
    settled = (
        SQL("AND erp_settlement_id IS NULL")
        if column_exists(cr, "hr_leave_allocation", "erp_settlement_id")
        else SQL("")
    )
    cr.execute(
        SQL(
            "SELECT count(*) FROM hr_leave_allocation "
            "WHERE allocation_type = 'regular' AND number_of_days <= 0 "
            "AND COALESCE(erp_history_days, 0) <= 0 %s",
            settled,
        )
    )
    invalid = cr.fetchone()[0]
    if invalid:
        _logger.warning(
            "erp_hr_holidays_ec 18.0.1.0.2: %s saldos regulares con 0 días o "
            "menos y sin días gozados antes del sistema incumplen "
            "duration_check; corríjalos y vuelva a actualizar el módulo.",
            invalid,
        )
