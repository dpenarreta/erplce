"""18.0.1.1.0 (US-008): en BD existentes el ``post_init_hook`` no se ejecuta;
se asignan aquí las cuentas por defecto del plan ``ec`` a las reglas nuevas del
rol (solo las vacías, idempotente)."""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    count = env["hr.salary.rule"]._erp_set_default_accounts()
    _logger.info(
        "erp_payroll_ec 18.0.1.1.0: %s cuentas por defecto asignadas a reglas.",
        count,
    )
