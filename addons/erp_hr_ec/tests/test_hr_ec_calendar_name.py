"""Nombre en español de la jornada por defecto (US-017, QA-UX)."""

from odoo.tests import TransactionCase, tagged

from ..models.resource_calendar import (
    DEFAULT_CALENDAR_ES_NAME,
    DEFAULT_CALENDAR_ORIGINAL_NAME,
)


@tagged("post_install", "-at_install")
class TestHrEcCalendarName(TransactionCase):
    def test_default_calendar_renamed_on_install(self):
        calendar = self.env.ref("resource.resource_calendar_std")
        self.assertEqual(calendar.name, "Estándar 40 horas/semana")
        self.assertFalse(
            self.env["resource.calendar"]
            .with_context(active_test=False)
            .search_count([("name", "=", DEFAULT_CALENDAR_ORIGINAL_NAME)])
        )

    def test_rename_only_original_name_and_idempotent(self):
        Calendar = self.env["resource.calendar"]
        original = Calendar.create({"name": DEFAULT_CALENDAR_ORIGINAL_NAME})
        archived = Calendar.create(
            {"name": DEFAULT_CALENDAR_ORIGINAL_NAME, "active": False}
        )
        custom = Calendar.create({"name": "Jornada bodega – Ñ 40 h"})
        renamed = Calendar._erp_rename_default_calendars()
        self.assertEqual(renamed, original | archived)
        self.assertEqual(original.name, DEFAULT_CALENDAR_ES_NAME)
        self.assertEqual(archived.name, DEFAULT_CALENDAR_ES_NAME)
        self.assertEqual(custom.name, "Jornada bodega – Ñ 40 h")
        # Segunda ejecución (actualización del módulo): no cambia nada.
        self.assertFalse(Calendar._erp_rename_default_calendars())
        # Un nombre puesto por el usuario se respeta en actualizaciones.
        original.name = "Turno administrativo"
        self.assertFalse(Calendar._erp_rename_default_calendars())
        self.assertEqual(original.name, "Turno administrativo")
