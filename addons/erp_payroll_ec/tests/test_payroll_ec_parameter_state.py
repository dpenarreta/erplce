"""Validación deliberada de parámetros de nómina (US-017, CA-10)."""

from datetime import date

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestPayrollParameterState(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Parameter = cls.env["erp.payroll.parameter"]
        cls.params = cls.Parameter.create(
            [
                {
                    "code": f"TEST_ESTADO_{index}",
                    "name": f"Parámetro de prueba {index} – Ñandú",
                    "value_type": "amount",
                    "value": 100.0 + index,
                    "date_from": date(2026, 1, 1),
                    "norm": "Norma de prueba, art. 1",
                }
                for index in range(2)
            ]
        )
        cls.payroll_user = new_test_user(
            cls.env,
            login="usuario_param_ec",
            groups="base.group_user,payroll.group_payroll_user",
        )
        cls.payroll_manager = new_test_user(
            cls.env,
            login="responsable_param_ec",
            groups="base.group_user,payroll.group_payroll_manager",
        )
        cls.plain_user = new_test_user(
            cls.env, login="sin_nomina_param_ec", groups="base.group_user"
        )

    def _tracked_states(self, param):
        self.env.flush_all()
        self.env.cr.precommit.run()
        values = param.message_ids.tracking_value_ids.filtered(
            lambda v: v.field_id.name == "state"
        )
        return values

    def test_manager_validates_batch_with_trace(self):
        self.assertEqual(set(self.params.mapped("state")), {"to_validate"})
        result = self.params.with_user(self.payroll_manager).action_validate()
        self.assertTrue(result)
        self.assertEqual(set(self.params.mapped("state")), {"validated"})
        for param in self.params:
            tracking = self._tracked_states(param)
            self.assertEqual(len(tracking), 1)
            self.assertEqual(tracking.old_value_char, "A validar")
            self.assertEqual(tracking.new_value_char, "Validado")
            self.assertEqual(
                tracking.mail_message_id.author_id,
                self.payroll_manager.partner_id,
            )

    def test_validate_is_idempotent(self):
        manager_params = self.params.with_user(self.payroll_manager)
        manager_params[0].action_validate()
        manager_params.action_validate()
        manager_params.action_validate()
        self.assertEqual(set(self.params.mapped("state")), {"validated"})
        self.assertEqual(len(self._tracked_states(self.params[0])), 1)

    def test_manager_sets_back_to_validate(self):
        manager_params = self.params.with_user(self.payroll_manager)
        manager_params.action_validate()
        # El seguimiento compara el valor inicial y el final de la transacción:
        # se cierra la primera acción antes de la segunda.
        self.assertEqual(len(self._tracked_states(self.params[0])), 1)
        manager_params.action_set_to_validate()
        self.assertEqual(set(self.params.mapped("state")), {"to_validate"})
        self.assertEqual(len(self._tracked_states(self.params[0])), 2)

    def test_payroll_user_cannot_validate(self):
        for user in (self.payroll_user, self.plain_user):
            with self.assertRaisesRegex(AccessError, "Solo el responsable de nómina"):
                self.params.with_user(user).action_validate()
        self.params.action_validate()
        with self.assertRaisesRegex(AccessError, "Solo el responsable de nómina"):
            self.params.with_user(self.payroll_user).action_set_to_validate()
        self.assertEqual(set(self.params.mapped("state")), {"validated"})

    def test_state_not_writable_directly(self):
        manager_params = self.params.with_user(self.payroll_manager)
        with self.assertRaisesRegex(UserError, "Marcar como validado"):
            manager_params.write({"state": "validated"})
        self.assertEqual(set(self.params.mapped("state")), {"to_validate"})
        manager_params.action_validate()
        with self.assertRaisesRegex(UserError, "Marcar como validado"):
            manager_params[0].state = "to_validate"
        # Reescribir el mismo estado (p. ej. importación) no es un cambio.
        manager_params.write({"state": "validated", "note": "Revisado – ñ"})
        self.assertEqual(set(self.params.mapped("state")), {"validated"})

    def test_copy_starts_to_validate(self):
        self.params[0].action_validate()
        duplicate = self.params[0].copy({"date_from": date(2026, 6, 1)})
        self.assertEqual(duplicate.state, "to_validate")

    def test_other_company_parameter_not_validated(self):
        other_company = self.env["res.company"].create({"name": "Empresa Ñ (prueba)"})
        other = self.Parameter.create(
            {
                "code": "TEST_ESTADO_OTRA",
                "name": "Parámetro de otra empresa",
                "value_type": "number",
                "value": 30,
                "date_from": date(2026, 1, 1),
                "norm": "Norma de prueba",
                "company_id": other_company.id,
            }
        )
        self.payroll_manager.write(
            {
                "company_ids": [(6, 0, self.env.company.ids)],
                "company_id": self.env.company.id,
            }
        )
        with self.assertRaises(AccessError):
            other.with_user(self.payroll_manager).action_validate()
        self.assertEqual(other.state, "to_validate")

    # ------------------------------------------------------------------
    # Revalidación al cambiar el valor normativo (ronda 2 de QA)
    # ------------------------------------------------------------------
    def _validated(self, param):
        param = param.with_env(self.env)
        param.with_user(self.payroll_manager).action_validate()
        self.assertEqual(param.state, "validated")
        # Cierra el seguimiento de la validación antes del cambio.
        self._tracked_states(param)
        return param.with_user(self.payroll_manager)

    def test_normative_change_sets_back_to_validate(self):
        other_company = self.env["res.company"].create({"name": "Empresa Ñ (reval.)"})
        self.payroll_manager.write({"company_ids": [(4, other_company.id)]})
        changes = (
            {"value": 460.5},
            {"value_type": "number"},
            {"date_from": date(2026, 2, 1)},
            {"norm": "Acuerdo ministerial de prueba – art. 2"},
            {"company_id": other_company.id},
        )
        for vals in changes:
            with self.subTest(vals=vals):
                # Lectura del chatter con el usuario del test (el seguimiento
                # solo lo leen los administradores).
                record = self.params[0]
                param = self._validated(record).with_context(
                    allowed_company_ids=(self.env.company | other_company).ids
                )
                messages_before = len(record.message_ids)
                param.write(vals)
                self.assertEqual(record.state, "to_validate")
                tracking = self._tracked_states(record)
                self.assertEqual(tracking[:1].new_value_char, "A validar")
                notes = record.message_ids[: len(record.message_ids) - messages_before]
                self.assertTrue(
                    any("vuelve a «A validar»" in (m.body or "") for m in notes),
                    notes.mapped("body"),
                )
                if "company_id" in vals:
                    param.write({"company_id": False})

    def test_non_normative_or_same_value_keeps_validated(self):
        param = self._validated(self.params[0])
        param.write(
            {"name": "Nombre corregido – ñ", "note": "Revisado", "active": True}
        )
        param.write({"value": param.value, "norm": param.norm})
        self.assertEqual(param.state, "validated")

    def test_revalidation_only_validated_records_in_batch(self):
        self._validated(self.params[0])
        self.assertEqual(self.params[1].state, "to_validate")
        self.params.with_user(self.payroll_manager).write({"value": 77.0})
        self.assertEqual(set(self.params.mapped("state")), {"to_validate"})

    def test_payroll_user_cannot_change_value(self):
        self._validated(self.params[0])
        with self.assertRaises(AccessError):
            self.params[0].with_user(self.payroll_user).write({"value": 1.0})
        self.assertEqual(self.params[0].state, "validated")

    def test_superuser_exempt_from_state_guard(self):
        """``env.su`` (procesos internos) escribe el estado directamente y,
        si lo fija en la misma escritura que el valor, se respeta."""
        param = self.params[0].sudo()
        param.write({"state": "validated"})
        self.assertEqual(param.state, "validated")
        param.write({"value": 999.0, "state": "validated"})
        self.assertEqual(param.state, "validated")
        # Sin estado explícito, también se revalida con su.
        param.write({"value": 998.0})
        self.assertEqual(param.state, "to_validate")
