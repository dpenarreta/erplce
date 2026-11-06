"""18.0.1.2.0 (US-013): pago de décimos acumulados.

En una BD existente la actualización del módulo ya crea, sin script:
- la tabla ``erp_payroll_provision_payment`` (marca de provisión pagada) y
  sus restricciones;
- el índice parcial ``hr_payslip_line_erp_provision_idx`` (``init``);
- los parámetros nuevos de periodo y pago de los décimos y la estructura
  «Pago de décimos acumulados» con sus reglas (datos ``noupdate``: se crean
  los registros que faltan; los existentes no se tocan).

Aquí solo se asignan las cuentas por defecto del plan ``ec`` a las reglas
nuevas (el ``post_init_hook`` no se ejecuta al actualizar). Idempotente: solo
rellena cuentas vacías. Ningún dato existente se modifica: no hay provisiones
pagadas antes de esta versión (todas quedan pendientes).
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    count = env["hr.salary.rule"]._erp_set_default_accounts()
    _logger.info(
        "erp_payroll_ec 18.0.1.2.0: %s cuentas por defecto asignadas a reglas.",
        count,
    )
