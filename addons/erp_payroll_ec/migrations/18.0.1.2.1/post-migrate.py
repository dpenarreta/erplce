"""18.0.1.2.1 (US-013, CA-14): casilla «Cuenta como remuneración»
(``erp.payroll.concept.erp_is_remuneration``, por defecto marcada).

La actualización crea la columna; aquí se deja marcada en todos los conceptos
existentes (los que la columna nueva dejó vacía), para que la liquidación
siga contando como remuneración todo lo que ya contaba. RRHH desmarca
después los viáticos y reembolsos. Idempotente: solo toca valores vacíos.
"""

import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        SQL(
            "UPDATE erp_payroll_concept SET erp_is_remuneration = TRUE "
            "WHERE erp_is_remuneration IS NULL"
        )
    )
    _logger.info(
        "erp_payroll_ec 18.0.1.2.1: %s conceptos marcados como remuneración.",
        cr.rowcount,
    )
