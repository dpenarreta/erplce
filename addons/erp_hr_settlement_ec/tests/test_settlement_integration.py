"""Integración de la liquidación con el pago de décimos acumulados y con el
reingreso (US-013, observación O-6 de QA-FUNC; CA-3, CA-9, decisión 2).

Valores FICTICIOS de prueba (ver ``common.py``): sueldo 1.000 -> provisión
mensual de décimo tercero 83,33.
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.erp_payroll_ec.models.hr_payslip import (
    PREVENT_COMPUTE_ON_CONFIRM_PARAM,
)

from .common import SettlementCase


@tagged("post_install", "-at_install")
class TestSettlementBenefitPayment(SettlementCase):
    """Pago de décimo tercero y liquidación del mismo empleado sobre las
    mismas provisiones (enero y febrero de 2026): gane quien gane, cada
    provisión se paga una sola vez."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.departure = date(2026, 2, 28)
        cls.employee = cls._employee("Lucía Muñoz Íñiguez")
        cls.contract = cls._contract(
            cls.employee,
            wage=1000.0,
            date_start=date(2026, 1, 1),
            date_end=cls.departure,
        )
        cls.months = cls._confirmed_months(
            cls.contract, date(2026, 1, 1), date(2026, 2, 1)
        )
        cls.provisions = cls.months.line_ids.filtered(
            lambda line: line.code == "D13_PROV"
        )

    def _benefit_payslip(self):
        """Genera el pago de décimo tercero 2026 (queda calculado, sin
        confirmar) y devuelve el rol del empleado."""
        wizard = self.env["erp.payroll.benefit.payment.wizard"].create(
            {"benefit": "thirteenth", "year": 2026}
        )
        wizard.action_generate()
        payslip = wizard.payslip_run_id.slip_ids.filtered(
            lambda slip: slip.employee_id == self.employee
        )
        self.assertEqual(len(payslip), 1)
        return payslip

    @staticmethod
    def _amount(payslip, code="D13_ACC_PAY"):
        return sum(
            payslip.line_ids.filtered(lambda line: line.code == code).mapped("total")
        )

    def _paid_by(self, document_type):
        return self.provisions.erp_provision_payment_ids.filtered(
            lambda payment: payment.document_type == document_type
        )

    def test_benefit_payment_pending_then_settlement_confirmed(self):
        self.assertEqual(len(self.provisions), 2)
        expected = sum(self.provisions.mapped("total"))
        payslip = self._benefit_payslip()
        self.assertNotEqual(payslip.state, "done")
        self.assertAlmostEqual(self._amount(payslip), expected, places=2)
        # La liquidación se calcula y confirma primero: paga las provisiones.
        settlement = self._new_settlement(self.contract, self.departure)
        settlement.action_compute()
        self.assertAlmostEqual(
            self._by_code(settlement)["D13"].amount, expected, places=2
        )
        settlement.action_confirm()
        self.assertEqual(len(self._paid_by("settlement")), 2)
        # Sin recálculo al confirmar (ajuste del motor): pide recalcular.
        Config = self.env["ir.config_parameter"].sudo()
        Config.set_param(PREVENT_COMPUTE_ON_CONFIRM_PARAM, True)
        with self.assertRaisesRegex(UserError, "Recalcule"):
            payslip.action_payslip_done()
        self.assertFalse(self._paid_by("payslip"))
        # Recalculado no paga nada (las provisiones ya están pagadas).
        payslip.compute_sheet()
        self.assertAlmostEqual(self._amount(payslip), 0.0, places=2)
        self.assertAlmostEqual(self._amount(payslip, "NET"), 0.0, places=2)
        # Con el recálculo al confirmar (valor por defecto) se confirma por 0
        # sin marcar ninguna provisión.
        Config.set_param(PREVENT_COMPUTE_ON_CONFIRM_PARAM, False)
        payslip.action_payslip_done()
        self.assertEqual(payslip.state, "done")
        self.assertAlmostEqual(self._amount(payslip), 0.0, places=2)
        self.assertFalse(self._paid_by("payslip"))
        self.assertEqual(
            self._paid_by("settlement"), self.provisions.erp_provision_payment_ids
        )

    def test_settlement_computed_then_benefit_payment_confirmed(self):
        expected = sum(self.provisions.mapped("total"))
        settlement = self._new_settlement(self.contract, self.departure)
        settlement.action_compute()
        self.assertAlmostEqual(
            self._by_code(settlement)["D13"].amount, expected, places=2
        )
        # El pago de décimos se confirma antes: paga las provisiones.
        payslip = self._benefit_payslip()
        payslip.action_payslip_done()
        self.assertEqual(len(self._paid_by("payslip")), 2)
        # La liquidación calculada ya no se confirma: pide recalcular.
        with self.assertRaisesRegex(UserError, "Calcular"):
            settlement.action_confirm()
        self.assertEqual(settlement.state, "computed")
        # Recalculada ya no incluye el décimo tercero y se confirma.
        settlement.action_compute()
        self.assertNotIn("D13", self._by_code(settlement))
        settlement.action_confirm()
        self.assertEqual(settlement.state, "done")
        self.assertFalse(self._paid_by("settlement"))
        self.assertEqual(len(self._paid_by("payslip")), 2)


@tagged("post_install", "-at_install")
class TestSettlementRehire(SettlementCase):
    """Reingreso tras una liquidación confirmada (decisión 2 del usuario):
    las vacaciones liquidadas no vuelven a aparecer y una segunda
    liquidación solo incluye lo nuevo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.entry = date(2023, 3, 15)
        cls.departure = date(2026, 4, 15)
        cls.employee = cls._employee(
            "Andrés Peña Ñauta", erp_company_entry_date=cls.entry
        )
        cls.contract = cls._contract(
            cls.employee,
            wage=1200.0,
            date_start=cls.entry,
            date_end=cls.departure,
        )
        cls.first_slips = cls._confirmed_months(
            cls.contract, date(2026, 4, 1), date(2026, 4, 1)
        )
        cls.employee._erp_generate_vacation_allocations(date=cls.departure)
        cls.periods = cls.env["hr.leave.allocation"].search(
            [("employee_id", "=", cls.employee.id), ("erp_auto_generated", "=", True)]
        )

    def test_rehire_starts_from_zero(self):
        self.assertEqual(len(self.periods), 3)
        first = self._new_settlement(self.contract, self.departure)
        first.action_compute()
        self.assertEqual(self._by_code(first)["VAC_PENDING"].quantity, 45.0)
        first.action_confirm()
        self.assertEqual(first.settled_allocation_ids, self.periods)
        self.assertFalse(self.employee.active)

        # Reingreso: ficha reactivada, nueva fecha de ingreso y contrato.
        new_entry = date(2026, 6, 1)
        new_departure = date(2026, 8, 15)
        self.employee.action_unarchive()
        self.employee.erp_company_entry_date = new_entry
        contract = self._contract(
            self.employee,
            wage=1500.0,
            date_start=new_entry,
            date_end=new_departure,
        )
        slips = self._confirmed_months(contract, date(2026, 6, 1), date(2026, 8, 1))
        # «Calcular vacaciones» con la nueva fecha: sin saldo previo.
        self.employee._erp_generate_vacation_allocations(date=new_departure)
        self.assertFalse(
            self.employee._erp_get_settlement_vacation_balance(new_departure)
        )
        self.periods.invalidate_recordset()
        self.assertEqual(self.periods.mapped("number_of_days"), [0.0, 0.0, 0.0])

        # Segunda liquidación: solo el periodo y las provisiones nuevas.
        second = self._new_settlement(contract, new_departure)
        self.assertEqual(second.date_entry, new_entry)
        second.action_compute()
        lines = self._by_code(second)
        self.assertNotIn("VAC_PENDING", lines)
        self.assertEqual(lines["D13"].provision_line_ids.slip_id, slips)
        self.assertIn("VAC_PROPORTIONAL", lines)
        # (1.500 × 2 + 750) / 24 = 156,25: solo la remuneración nueva.
        self.assertAlmostEqual(lines["VAC_PROPORTIONAL"].amount, 156.25, places=2)
        second.action_confirm()
        self.assertEqual(second.state, "done")
        self.assertFalse(second.settled_allocation_ids)
