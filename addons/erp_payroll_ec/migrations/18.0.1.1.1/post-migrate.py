"""18.0.1.1.1 (US-008): la nota del parámetro de meses de servicio para fondos
de reserva (dato ``noupdate``) describía «a partir del mes siguiente»; el
cálculo los genera desde el día en que se cumple el periodo, proporcionales a
los días con derecho. Se actualiza la nota solo si conserva el texto original
(si el usuario la editó, se respeta)."""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

XMLID = "erp_payroll_ec.param_reserve_fund_min_months_2026"
OLD_NOTE = (
    "Valor de partida a validar. El fondo de reserva se genera a partir del mes "
    "siguiente al cumplimiento de este periodo (a confirmar)."
)
NEW_NOTE = (
    "Valor de partida a validar. El fondo de reserva se genera desde el día en "
    "que se cumple este periodo de servicio (contado desde la fecha del primer "
    "contrato); en ese mes se paga o provisiona en proporción a los días con "
    "derecho (a confirmar)."
)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    parameter = env.ref(XMLID, raise_if_not_found=False)
    if parameter and (parameter.note or "").strip() == OLD_NOTE:
        parameter.note = NEW_NOTE
        _logger.info("erp_payroll_ec 18.0.1.1.1: nota de %s actualizada.", XMLID)
