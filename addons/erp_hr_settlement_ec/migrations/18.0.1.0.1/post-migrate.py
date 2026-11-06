"""18.0.1.0.1 (US-013): elimina del historial (chatter) los mensajes
automáticos de creación en inglés («Causa de salida created», «Tramo de
indemnización por despido intempestivo created») que dejó la instalación de
los datos de partida. Los datos ya se cargan sin ese mensaje
(``mail_create_nolog`` en los registros XML).

Solo se borran las notas automáticas de creación de esos dos modelos: tipo
``notification``, subtipo «Nota», cuerpo «<descripción del modelo>
created» y sin valores de seguimiento. Los cambios hechos después por los
usuarios (seguimiento de campos, mensajes) se conservan. Idempotente.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

MODELS = ("erp.hr.termination.cause", "erp.hr.indemnity.bracket")
# «%s created» del núcleo, sin traducir o traducido al español.
CREATED_SUFFIXES = ("created", "creado", "creada")


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    note = env.ref("mail.mt_note", raise_if_not_found=False)
    if not note:
        return
    Message = env["mail.message"].with_context(active_test=False)
    total = 0
    for model in MODELS:
        description = env[model]._description
        messages = Message.search(
            [
                ("model", "=", model),
                ("message_type", "=", "notification"),
                ("subtype_id", "=", note.id),
            ]
        ).filtered(
            lambda message, description=description: not message.tracking_value_ids
            and message.body
            and message.body.striptags().strip()
            in {f"{description} {suffix}" for suffix in CREATED_SUFFIXES}
        )
        total += len(messages)
        messages.unlink()
    _logger.info(
        "erp_hr_settlement_ec 18.0.1.0.1: %s mensajes de creación eliminados.", total
    )
