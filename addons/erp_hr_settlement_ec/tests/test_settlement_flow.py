"""Liquidación de haberes (US-013, CA-5 a CA-10): cálculo según la causa,
rubros manuales, confirmación (último rol, provisiones, vacaciones, asiento,
contrato y empleado), anulación y transiciones protegidas.

Valores FICTICIOS de prueba (no legales). Escenario base:

- Íñigo, ingreso 15/03/2023, sueldo 1.200, contrato hasta el 15/04/2026 (fecha
  de salida), Costa, décimos acumulados.
- Roles mensuales confirmados de mayo de 2025 a abril de 2026 (abril: 15
  días = 600). Remuneración: 11 × 1.200 + 600 = 13.800.
- Provisiones pendientes: décimo tercero 11 × 100 + 50 = 1.150; décimo cuarto
  (SBU 400 / 12) 11 × 33,33 + 16,67 = 383,30.
- Vacaciones: 3 periodos de 15 días (años 1 a 3) − 5 días gozados antes del
  sistema = 40 días. Valor del día (año móvil del 16/04/2025 al 15/04/2026):
  los roles cubren 345 de sus 360 días (falta abril de 2025) -> 13.800 × 360
  / (360 × 345) = 40 -> 1.600,00.
- Año de servicio en curso desde el 15/03/2026: marzo 1.200 × 16/30 = 640 +
  abril 600 = 1.240 / 24 = 51,67.
- Última remuneración: rol de marzo de 2026 = 1.200. Servicio: 3 años y 32
  de 365 días.
- Desahucio: 1.200 × 25 % × 3,0877 = 926,31. Indemnización (fracción = año
  completo, 4 años, tramo «más de 3»: 1 mes por año) = 4.800.
"""

from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.erp_hr_holidays_ec.models import const as holidays_const
from odoo.addons.erp_payroll_ec.tests.common import PayrollEcCase

MODULE = "erp_hr_settlement_ec"
DEPARTURE = date(2026, 4, 15)
# Parámetros ficticios de la liquidación y de vacaciones.
SETTLEMENT_PARAMS = {
    "SEVERANCE_BONUS_RATE": ("percent", 25.0),
    "SEVERANCE_BONUS_PROPORTIONAL_FRACTION": ("number", 1.0),
    "INDEMNITY_YEAR_FRACTION_AS_FULL": ("number", 1.0),
    "VACATION_DAY_BASE_MONTHS": ("number", 12.0),
    "VACATION_DAY_DIVISOR": ("number", 360.0),
    "VACATION_PROPORTIONAL_DIVISOR": ("number", 24.0),
    holidays_const.VACATION_BASE_DAYS: ("number", 15.0),
    holidays_const.VACATION_EXTRA_FROM_YEAR: ("number", 6.0),
    holidays_const.VACATION_EXTRA_DAYS_PER_YEAR: ("number", 1.0),
    holidays_const.VACATION_EXTRA_MAX_DAYS: ("number", 15.0),
    holidays_const.VACATION_VALIDITY_YEARS: ("number", 4.0),
    holidays_const.VACATION_GENERATION_START: ("number", 1.0),
    holidays_const.VACATION_COUNT_CALENDAR_DAYS: ("number", 1.0),
}
EXPECTED = {
    "D13": 1150.0,
    "D14": 383.30,
    "VAC_PENDING": 1600.0,
    "VAC_PROPORTIONAL": 51.67,
    "DESAHUCIO": 926.31,
    "INDEMNITY": 4800.0,
}


def month_range(first, last):
    month = first
    while month <= last:
        yield month, month + relativedelta(day=31)
        month += relativedelta(months=1)


@tagged("post_install", "-at_install")
class TestSettlementFlow(PayrollEcCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "payroll.allow_cancel_payslips", True
        )
        cls.Parameter.create(
            [
                {
                    "code": code,
                    "name": f"{code} (prueba)",
                    "value_type": value_type,
                    "value": value,
                    # Antes de los valores cargados (archivados por common).
                    "date_from": date(2010, 1, 1),
                    "norm": "Valor ficticio de prueba",
                }
                for code, (value_type, value) in SETTLEMENT_PARAMS.items()
            ]
        )
        Account = cls.env["account.account"]
        cls.expense = {
            key: Account.create(
                {"code": code, "name": f"{key} (prueba)", "account_type": "expense"}
            )
            for key, code in (
                ("vacation", "5999820"),
                ("severance", "5999821"),
                ("indemnity", "5999822"),
            )
        }
        cls.company.write(
            {
                "erp_settlement_vacation_account_id": cls.expense["vacation"].id,
                "erp_settlement_severance_account_id": cls.expense["severance"].id,
                "erp_settlement_indemnity_account_id": cls.expense["indemnity"].id,
            }
        )
        cls.Settlement = cls.env["erp.hr.settlement"]
        cls.Line = cls.env["erp.hr.settlement.line"]
        cls.PayslipLine = cls.env["hr.payslip.line"]
        cls.unfair = cls.env.ref(f"{MODULE}.cause_unfair_dismissal")
        cls.contract_end_cause = cls.env.ref(f"{MODULE}.cause_contract_end")
        cls.employee = cls._employee(
            "Íñigo Muñoz Cañizares", erp_company_entry_date=date(2023, 3, 15)
        )
        cls.contract = cls._contract(
            cls.employee,
            wage=1200.0,
            date_start=date(2023, 3, 15),
            date_end=DEPARTURE,
        )
        cls.payslips = cls.env["hr.payslip"]
        for date_from, date_to in month_range(date(2025, 5, 1), date(2026, 4, 1)):
            slip = cls.env["hr.payslip"].create(
                {
                    "employee_id": cls.employee.id,
                    "contract_id": cls.contract.id,
                    "struct_id": cls.structure.id,
                    "date_from": date_from,
                    "date_to": date_to,
                }
            )
            slip.compute_sheet()
            slip.action_payslip_done()
            cls.payslips |= slip
        cls.april = cls.payslips[-1]
        cls.employee._erp_generate_vacation_allocations(date=DEPARTURE)
        cls.periods = cls.env["hr.leave.allocation"].search(
            [("employee_id", "=", cls.employee.id), ("erp_auto_generated", "=", True)],
            order="erp_service_year",
        )
        cls.env["erp.hr.vacation.history"].create(
            {
                "employee_id": cls.employee.id,
                "date": date(2024, 6, 1),
                "number_of_days": 5,
                "service_year": 1,
            }
        )

    # ------------------------------------------------------------------
    # Ayudas
    # ------------------------------------------------------------------
    def _settlement(self, cause=None, **vals):
        return self.Settlement.create(
            {
                "employee_id": self.employee.id,
                "contract_id": self.contract.id,
                "date_departure": DEPARTURE,
                "cause_id": (cause or self.unfair).id,
                **vals,
            }
        )

    def _computed(self, cause=None, user=None, **vals):
        settlement = self._settlement(cause, **vals)
        (settlement.with_user(user) if user else settlement).action_compute()
        return settlement

    def _amounts(self, settlement):
        return {
            line.code: line.amount for line in settlement.line_ids if not line.is_manual
        }

    def _pending(self):
        return self.PayslipLine._erp_get_pending_provision_lines(
            ("D13_PROV", "D14_PROV_COSTA", "D14_PROV_SIERRA"),
            employees=self.employee,
        )

    # ------------------------------------------------------------------
    # Escenario
    # ------------------------------------------------------------------
    def test_scenario(self):
        self.assertEqual(len(self.periods), 3)
        self.assertEqual(self.periods.mapped("number_of_days"), [10.0, 15.0, 15.0])
        self.assertEqual(len(self._pending()), 24)

    # ------------------------------------------------------------------
    # Calcular (CA-6, CA-7)
    # ------------------------------------------------------------------
    def test_compute_unfair_dismissal(self):
        settlement = self._computed(user=self.payroll_user)
        self.assertEqual(settlement.state, "computed")
        self.assertAlmostEqual(settlement.last_wage, 1200.0)
        amounts = self._amounts(settlement)
        self.assertEqual(set(amounts), set(EXPECTED))
        for code, amount in EXPECTED.items():
            self.assertAlmostEqual(amounts[code], amount, places=2, msg=code)
        lines = {line.code: line for line in settlement.line_ids}
        self.assertEqual(len(lines["D13"].provision_line_ids), 12)
        self.assertEqual(len(lines["D14"].provision_line_ids), 12)
        self.assertEqual(lines["VAC_PENDING"].quantity, 40.0)
        self.assertAlmostEqual(lines["VAC_PENDING"].base, 40.0, places=2)
        self.assertIn("345 de 360 días", lines["VAC_PENDING"].explanation)
        self.assertAlmostEqual(lines["DESAHUCIO"].quantity, 3.0877, places=4)
        self.assertEqual(lines["INDEMNITY"].quantity, 4.0)
        for line in settlement.line_ids:
            self.assertTrue(line.explanation, line.code)
        self.assertIn("Tramo", lines["INDEMNITY"].explanation)
        self.assertIn("marzo", lines["DESAHUCIO"].explanation.lower())
        self.assertIn("año de servicio 2", lines["VAC_PENDING"].explanation)
        self.assertNotIn("No incluye", lines["D13"].explanation)
        self.assertAlmostEqual(settlement.net, sum(EXPECTED.values()), places=2)

    def test_compute_respects_cause_and_keeps_manual_lines(self):
        settlement = self._computed(self.contract_end_cause)
        self.assertEqual(
            set(self._amounts(settlement)),
            {"D13", "D14", "VAC_PENDING", "VAC_PROPORTIONAL"},
        )
        manual = self.Line.create(
            {
                "settlement_id": settlement.id,
                "code": "OTHER_DEDUCTION",
                "name": "Anticipo de sueldo – Ñandú",
                "amount": 100.0,
                "is_manual": True,
            }
        )
        settlement.action_compute()
        self.assertIn(manual, settlement.line_ids)
        self.assertAlmostEqual(
            settlement.net,
            EXPECTED["D13"]
            + EXPECTED["D14"]
            + EXPECTED["VAC_PENDING"]
            + EXPECTED["VAC_PROPORTIONAL"]
            - 100.0,
            places=2,
        )
        # Neto negativo: bloqueado y sin cambios guardados.
        manual.amount = 50000.0
        settlement.action_draft()
        with self.assertRaisesRegex(UserError, "negativo"):
            settlement.action_compute()

    def test_compute_without_last_payslip_and_confirm_blocked(self):
        self.april.with_user(self.payroll_manager).action_payslip_cancel()
        settlement = self._computed(self.contract_end_cause)
        lines = {line.code: line for line in settlement.line_ids}
        self.assertAlmostEqual(lines["D13"].amount, 1100.0, places=2)
        self.assertIn("No incluye el mes de la salida", lines["D13"].explanation)
        with self.assertRaisesRegex(UserError, "Falta el rol mensual"):
            settlement.with_user(self.payroll_manager).action_confirm()

    def test_missing_vacation_periods_block_compute(self):
        employee = self._employee("Ana Peña Ibáñez")
        contract = self._contract(employee, date_start=date(2024, 1, 1))
        settlement = self.Settlement.create(
            {
                "employee_id": employee.id,
                "contract_id": contract.id,
                "date_departure": date(2026, 2, 28),
                "cause_id": self.contract_end_cause.id,
            }
        )
        with self.assertRaisesRegex(UserError, "Faltan los periodos de vacaciones"):
            settlement.action_compute()

    # ------------------------------------------------------------------
    # Confirmar (CA-8, CA-9)
    # ------------------------------------------------------------------
    def test_confirm(self):
        settlement = self._computed()
        with self.assertRaises(AccessError):
            settlement.with_user(self.payroll_user).action_confirm()
        settlement.with_user(self.payroll_manager).action_confirm()
        self.assertEqual(settlement.state, "done")
        self.assertTrue(settlement.name.startswith("LIQ/"))
        self.assertEqual(settlement.display_name, settlement.name)
        # Provisiones pagadas (CA-3, CA-9 d).
        self.assertEqual(len(settlement.provision_payment_ids), 24)
        self.assertEqual(
            set(settlement.provision_payment_ids.mapped("document_type")),
            {"settlement"},
        )
        self.assertFalse(self._pending())
        # Vacaciones liquidadas (CA-9 c): saldo 0 y días guardados.
        self.periods.invalidate_recordset()
        self.assertEqual(self.periods.mapped("number_of_days"), [0.0, 0.0, 0.0])
        self.assertEqual(self.periods.mapped("erp_settled_days"), [10.0, 15.0, 15.0])
        self.assertEqual(settlement.settled_vacation_days, 40.0)
        self.assertIn("año de servicio 3", settlement.settled_vacation_summary)
        # Asiento (CA-9 a).
        move = settlement.move_id
        self.assertEqual(move.state, "posted")
        self.assertEqual(move.date, DEPARTURE)
        by_account = {}
        for line in move.line_ids:
            debit, credit = by_account.get(line.account_id, (0.0, 0.0))
            by_account[line.account_id] = (debit + line.debit, credit + line.credit)
        expected = {
            self.accounts["d13_provision"]: (1150.0, 0.0),
            self.accounts["d14_costa"]: (383.30, 0.0),
            self.expense["vacation"]: (1600.0 + 51.67, 0.0),
            self.expense["severance"]: (926.31, 0.0),
            self.expense["indemnity"]: (4800.0, 0.0),
            self.accounts["net_payable"]: (0.0, sum(EXPECTED.values())),
        }
        self.assertEqual(set(by_account), set(expected))
        for account, (debit, credit) in expected.items():
            self.assertAlmostEqual(by_account[account][0], debit, places=2)
            self.assertAlmostEqual(by_account[account][1], credit, places=2)
        payable = move.line_ids.filtered(
            lambda line: line.account_id == self.accounts["net_payable"]
        )
        self.assertEqual(payable.partner_id, self.employee.work_contact_id)
        # Contrato cerrado y empleado archivado (CA-9 b).
        self.assertEqual(self.contract.state, "close")
        self.assertEqual(self.contract.date_end, DEPARTURE)
        self.assertFalse(self.employee.active)
        self.assertEqual(self.employee.departure_date, DEPARTURE)
        self.assertEqual(
            self.employee.departure_reason_id, self.env.ref("hr.departure_fired")
        )
        # Bloqueos posteriores: rol mensual con provisiones pagadas, edición.
        with self.assertRaisesRegex(UserError, "liquidación"):
            self.april.with_user(self.payroll_manager).action_payslip_cancel()
        manager_settlement = settlement.with_user(self.payroll_manager)
        with self.assertRaises(UserError):
            manager_settlement.write({"date_departure": date(2026, 4, 10)})
        with self.assertRaises(UserError):
            self.Line.with_user(self.payroll_manager).create(
                {
                    "settlement_id": settlement.id,
                    "code": "OTHER_INCOME",
                    "name": "Bono",
                    "amount": 1.0,
                    "is_manual": True,
                }
            )
        with self.assertRaises(UserError):
            manager_settlement.line_ids[:1].unlink()
        manager_settlement.note = "Firmada por el trabajador."

    def test_confirm_detects_changes_since_compute(self):
        settlement = self._computed()
        self.Parameter.create(
            {
                "code": "SEVERANCE_BONUS_RATE",
                "name": "Desahucio (prueba, cambio)",
                "value_type": "percent",
                "value": 30.0,
                "date_from": date(2026, 1, 1),
                "norm": "Valor ficticio de prueba",
            }
        )
        with self.assertRaisesRegex(UserError, "cambiaron"):
            settlement.action_confirm()
        settlement.action_compute()
        self.assertAlmostEqual(
            self._amounts(settlement)["DESAHUCIO"], 1111.57, places=2
        )
        settlement.action_confirm()
        self.assertEqual(settlement.state, "done")

    def test_confirm_blocks_overpaid_last_month(self):
        settlement = self._computed()
        # El contrato se alarga después de calcular abril: el rol de abril
        # pudo pagar días posteriores a la salida.
        self.contract.date_end = date(2026, 4, 30)
        with self.assertRaisesRegex(UserError, "días no trabajados"):
            settlement.action_confirm()

    # ------------------------------------------------------------------
    # Anular y volver a borrador (CA-10)
    # ------------------------------------------------------------------
    def test_cancel_restores_everything(self):
        settlement = self._computed()
        settlement.action_confirm()
        move = settlement.move_id
        with self.assertRaises(AccessError):
            settlement.with_user(self.payroll_user).action_cancel()
        settlement.with_user(self.payroll_manager).action_cancel()
        self.assertEqual(settlement.state, "cancel")
        self.assertTrue(settlement.reversal_move_id)
        self.assertEqual(move.reversal_move_ids, settlement.reversal_move_id)
        self.assertFalse(settlement.provision_payment_ids)
        self.assertEqual(len(self._pending()), 24)
        self.periods.invalidate_recordset()
        self.assertEqual(self.periods.mapped("number_of_days"), [10.0, 15.0, 15.0])
        self.assertFalse(self.periods.erp_settlement_id)
        self.assertEqual(self.periods.mapped("erp_settled_days"), [0.0, 0.0, 0.0])
        self.assertFalse(settlement.settled_vacation_summary)
        # El contrato y el empleado no se reabren solos (se avisa).
        self.assertEqual(self.contract.state, "close")
        self.assertFalse(self.employee.active)
        self.assertIn("no se reabren", settlement.message_ids[:1].body.striptags())
        # Volver a borrador desenlaza los asientos y permite recalcular.
        settlement.action_draft()
        self.assertEqual(settlement.state, "draft")
        self.assertFalse(settlement.move_id or settlement.reversal_move_id)
        settlement.action_cancel()
        with self.assertRaisesRegex(UserError, "ya está anulada"):
            settlement.action_cancel()

    def test_cancel_blocked_when_reconciled(self):
        settlement = self._computed()
        settlement.action_confirm()
        payable = settlement.move_id.line_ids.filtered(
            lambda line: line.account_id == self.accounts["net_payable"]
        )
        bank = self.env["account.account"].create(
            {"code": "1999820", "name": "Banco (prueba)", "account_type": "asset_cash"}
        )
        payment = self.env["account.move"].create(
            {
                "journal_id": self.journal.id,
                "date": DEPARTURE,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "account_id": payable.account_id.id,
                            "partner_id": payable.partner_id.id,
                            "debit": payable.credit,
                        },
                    ),
                    (0, 0, {"account_id": bank.id, "credit": payable.credit}),
                ],
            }
        )
        payment.action_post()
        (
            payable
            | payment.line_ids.filtered(
                lambda line: line.account_id == payable.account_id
            )
        ).reconcile()
        with self.assertRaisesRegex(UserError, "conciliados"):
            settlement.action_cancel()

    # ------------------------------------------------------------------
    # Transiciones e integridad (CA-5)
    # ------------------------------------------------------------------
    def test_state_protection_and_transitions(self):
        settlement = self._settlement()
        self.assertIn("sin número", settlement.display_name)
        with self.assertRaises(UserError):
            settlement.with_user(self.payroll_manager).write({"state": "done"})
        with self.assertRaises(UserError):
            self.Settlement.with_user(self.payroll_manager).create(
                {
                    "employee_id": self.employee.id,
                    "contract_id": self.contract.id,
                    "date_departure": DEPARTURE,
                    "cause_id": self.unfair.id,
                    "state": "computed",
                }
            )
        with self.assertRaisesRegex(UserError, "calculada"):
            settlement.action_confirm()
        with self.assertRaisesRegex(UserError, "borrador"):
            settlement.action_draft()
        settlement.action_compute()
        # Cambiar la causa de una liquidación calculada la devuelve a borrador.
        settlement.with_user(self.payroll_user).cause_id = self.contract_end_cause
        self.assertEqual(settlement.state, "draft")
        # Duplicado por contrato, con mensaje en español.
        with self.assertRaisesRegex(UserError, "Ya existe una liquidación"):
            self._settlement()

    # ------------------------------------------------------------------
    # Configuración «a validar» (CA-12)
    # ------------------------------------------------------------------
    def test_validated_configuration_returns_to_validate(self):
        cause = self.unfair.with_user(self.payroll_manager)
        cause.action_validate()
        self.assertEqual(cause.state, "validated")
        cause.pays_severance_bonus = False
        self.assertEqual(cause.state, "to_validate")
        cause.action_validate()
        cause.description = "Texto de ayuda – sin efecto legal"
        self.assertEqual(cause.state, "validated")
        with self.assertRaises(UserError):
            cause.state = "to_validate"
        Bracket = self.env["erp.hr.indemnity.bracket"]
        Bracket.create(
            {
                "name": "Tramo A (prueba)",
                "date_from": date(2031, 1, 1),
                "years_from": 0,
                "years_to": 5,
                "fixed_months": 3,
                "norm": "Valor ficticio de prueba",
            }
        )
        with self.assertRaises(ValidationError):
            Bracket.create(
                {
                    "name": "Tramo B solapado (prueba)",
                    "date_from": date(2031, 1, 1),
                    "years_from": 4,
                    "years_to": 0,
                    "months_per_year": 1,
                    "norm": "Valor ficticio de prueba",
                }
            )
