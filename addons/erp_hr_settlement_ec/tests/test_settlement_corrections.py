"""Correcciones de la ronda 1 de US-013 (QA-TECH, QA-FUNC, QA-UX): nombres y
textos de servidor, campos protegidos, dominio de cuentas de los rubros y
desinstalación del módulo.

Valores FICTICIOS de prueba.
"""

from datetime import date
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests import new_test_user, tagged
from odoo.tools import SQL

from odoo.addons.erp_hr_holidays_ec.models.const import ALLOCATION_DURATION_CHECK

from ..hooks import ALLOCATION_DURATION_CONSTRAINT, uninstall_hook
from ..models.const import DEFAULT_ACCOUNT_CODES
from .common import SettlementCase


@tagged("post_install", "-at_install")
class TestSettlementCorrections(SettlementCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls._employee(
            "Íñigo Cañizares Peña", erp_company_entry_date=date(2023, 3, 15)
        )
        cls.contract = cls._contract(
            cls.employee, wage=1200.0, date_start=date(2023, 3, 15)
        )
        cls.settlement = cls._new_settlement_cls(cls.contract, date(2026, 4, 15))

    @classmethod
    def _new_settlement_cls(cls, contract, departure):
        return cls.env["erp.hr.settlement"].create(
            {
                "employee_id": contract.employee_id.id,
                "contract_id": contract.id,
                "date_departure": departure,
                "cause_id": cls.contract_end_cause.id,
            }
        )

    def _constraint_definition(self):
        self.env.cr.execute(
            SQL(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = %s",
                ALLOCATION_DURATION_CONSTRAINT,
            )
        )
        row = self.env.cr.fetchone()
        return row and row[0]

    # ------------------------------------------------------------------
    # Nombres y textos (QA-UX)
    # ------------------------------------------------------------------
    def test_display_name_without_number(self):
        self.assertEqual(
            self.settlement.display_name,
            "Liquidación de Íñigo Cañizares Peña (sin número)",
        )
        self.assertEqual(self.Settlement.new({}).display_name, "Nueva liquidación")

    def test_service_display(self):
        self.assertEqual(self.settlement.service_display, "3 años, 1 mes y 1 día")
        cases = {
            (date(2024, 1, 1), date(2024, 12, 31)): "1 año, 0 meses y 0 días",
            (date(2023, 1, 10), date(2025, 3, 11)): "2 años, 2 meses y 2 días",
            (date(2026, 1, 1), date(2026, 1, 1)): "0 años, 0 meses y 1 día",
        }
        for (entry, departure), expected in cases.items():
            with self.subTest(entry=entry, departure=departure):
                record = self.Settlement.new(
                    {"date_entry": entry, "date_departure": departure}
                )
                self.assertEqual(record.service_display, expected)
                self.assertNotIn("  ", record.service_display)

    def test_field_labels_and_tracking(self):
        fields_ = self.Settlement._fields
        self.assertTrue(fields_["date_entry"].tracking)
        self.assertNotEqual(
            fields_["settled_allocation_ids"].string,
            fields_["settled_vacation_summary"].string,
        )
        self.assertEqual(
            self.env["erp.hr.termination.cause"]._fields["departure_reason_id"].string,
            "Motivo de salida en la ficha del empleado",
        )
        self.assertEqual(
            self.env["hr.leave.allocation"]._fields["erp_settled_days"].groups,
            "payroll.group_payroll_user",
        )

    def test_missing_account_message_path(self):
        self.company.erp_settlement_vacation_account_id = False
        field = "erp_settlement_vacation_account_id"
        # Código por defecto inexistente: ni ajuste ni cuenta del plan.
        with patch.dict(DEFAULT_ACCOUNT_CODES, {field: "ZZ999999"}):
            with self.assertRaisesRegex(
                UserError, "Ajustes › Nómina › Liquidación de haberes"
            ):
                self.settlement._erp_get_account(field)

    def test_no_creation_message_on_loaded_data(self):
        causes = self.env["erp.hr.termination.cause"].search([])
        brackets = self.env["erp.hr.indemnity.bracket"].search([])
        messages = self.env["mail.message"].search(
            [
                (
                    "model",
                    "in",
                    ("erp.hr.termination.cause", "erp.hr.indemnity.bracket"),
                ),
                ("res_id", "in", causes.ids + brackets.ids),
                ("body", "ilike", "created"),
            ]
        )
        self.assertFalse(messages)

    # ------------------------------------------------------------------
    # Marca de periodo liquidado protegida (QA-TECH)
    # ------------------------------------------------------------------
    def test_settled_mark_only_from_settlement_actions(self):
        holidays_manager = new_test_user(
            self.env,
            login="responsable_ausencias_us013",
            groups="base.group_user,hr_holidays.group_hr_holidays_manager,"
            "payroll.group_payroll_manager",
        )
        allocation = self.env["hr.leave.allocation"].create(
            {
                "name": "Vacaciones – periodo de prueba",
                "employee_id": self.employee.id,
                "holiday_status_id": self.env.ref(
                    "erp_hr_holidays_ec.leave_type_annual_vacation"
                ).id,
                "number_of_days": 5,
                "allocation_type": "regular",
                "date_from": date(2025, 3, 15),
            }
        )
        as_manager = allocation.with_user(holidays_manager)
        for vals in (
            {"erp_settled_days": 5.0},
            {"erp_settlement_id": self.settlement.id},
        ):
            with (
                self.subTest(vals=vals),
                self.assertRaisesRegex(UserError, "no se modifica a mano"),
            ):
                as_manager.write(vals)
        # Dentro de una acción de la liquidación sí se escribe.
        with self.settlement._erp_transition():
            as_manager.write(
                {"erp_settled_days": 5.0, "erp_settlement_id": self.settlement.id}
            )
        self.assertEqual(allocation.erp_settled_days, 5.0)

    # ------------------------------------------------------------------
    # Cuenta de los rubros manuales (QA-TECH)
    # ------------------------------------------------------------------
    def test_manual_line_account_domain(self):
        Account = self.env["account.account"]
        bank = Account.create(
            {"code": "1999830", "name": "Banco (prueba)", "account_type": "asset_cash"}
        )
        old = Account.create(
            {
                "code": "5999839",
                "name": "Gasto obsoleto (prueba)",
                "account_type": "expense",
                "deprecated": True,
            }
        )
        domain = self.Line._fields["account_id"].domain
        self.assertNotIn(bank, Account.search(domain))
        self.assertNotIn(old, Account.search(domain))
        for account in (bank, old):
            with self.subTest(account=account.name), self.assertRaises(ValidationError):
                self.Line.create(
                    {
                        "settlement_id": self.settlement.id,
                        "code": "OTHER_INCOME",
                        "name": "Bono acordado – Ñandú",
                        "amount": 10.0,
                        "is_manual": True,
                        "account_id": account.id,
                    }
                )
        line = self.Line.create(
            {
                "settlement_id": self.settlement.id,
                "code": "OTHER_INCOME",
                "name": "Bono acordado",
                "amount": 10.0,
                "is_manual": True,
                "account_id": self.accounts["expense_bonus"].id,
            }
        )
        self.assertEqual(line.account_id, self.accounts["expense_bonus"])

    # ------------------------------------------------------------------
    # Desinstalación (QA-TECH)
    # ------------------------------------------------------------------
    def test_uninstall_hook(self):
        self.assertIn("erp_settlement_id", self._constraint_definition())
        # Con una liquidación confirmada se bloquea.
        self.env.cr.execute(
            SQL(
                "UPDATE erp_hr_settlement SET state = 'done' WHERE id = %s",
                self.settlement.id,
            )
        )
        self.settlement.invalidate_recordset()
        with self.assertRaisesRegex(UserError, "liquidaciones confirmadas"):
            uninstall_hook(self.env)
        self.assertIn("erp_settlement_id", self._constraint_definition())
        # Sin liquidaciones confirmadas restituye la restricción de
        # erp_hr_holidays_ec (sin la columna que se eliminará).
        self.env.cr.execute(
            SQL(
                "UPDATE erp_hr_settlement SET state = 'draft' WHERE id = %s",
                self.settlement.id,
            )
        )
        self.settlement.invalidate_recordset()
        uninstall_hook(self.env)
        definition = self._constraint_definition()
        self.assertNotIn("erp_settlement_id", definition)
        self.assertIn("erp_history_days", definition)
        self.assertTrue(ALLOCATION_DURATION_CHECK.startswith("CHECK"))
