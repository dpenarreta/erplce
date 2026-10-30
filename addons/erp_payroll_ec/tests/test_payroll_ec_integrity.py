"""Integridad del rol mensual Ecuador (US-008, ronda 1 de QA): varios
contratos en un rol, renovación a mitad de mes, guarda de estados y campos
protegidos, anulación con conciliación, consultas por rol, errores de negocio
dentro de las reglas, confirmación en lote y periodo mensual.
Valores ficticios de prueba (ver ``common.py``)."""

import logging
from datetime import date
from unittest.mock import PropertyMock, patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.payroll_account.models.hr_payslip import (
    HrPayslip as PayrollAccountHrPayslip,
)

from ..models.hr_payslip import HrPayslip as ErpHrPayslip
from .common import PayrollEcCase

_logger = logging.getLogger(__name__)

ALLOW_CANCEL = "payroll.allow_cancel_payslips"
PREVENT_COMPUTE = "payroll.prevent_compute_on_confirm"
# Consultas adicionales de compute_sheet por cada rol más en el lote (motor
# OCA: borrar y crear líneas, escribir el rol, secuencia, tracking, lectura
# de las reglas por contrato). Medido en US-008: 37 consultas con 1 rol y 53
# con 5 (4 por rol adicional); el margen absorbe cambios menores del núcleo.
MAX_QUERIES_PER_EXTRA_PAYSLIP = 8


@tagged("post_install", "-at_install")
class TestPayrollEcIntegrity(PayrollEcCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls._employee("Begoña Ñáñez")
        cls.contract = cls._contract(cls.employee)

    # ------------------------------------------------------------------
    # Ayudas
    # ------------------------------------------------------------------
    def _slip_without_contract(self, employee, date_from=None, date_to=None):
        return self.env["hr.payslip"].create(
            {
                "employee_id": employee.id,
                "struct_id": self.structure.id,
                "date_from": date_from or date(2026, 1, 1),
                "date_to": date_to or date(2026, 1, 31),
            }
        )

    def _codes_by_contract(self, payslip):
        result = {}
        for line in payslip.line_ids:
            result.setdefault(line.contract_id, {})[line.code] = line.total
        return result

    def _move_balance(self, move, account):
        return sum(
            move.line_ids.filtered(lambda ml: ml.account_id == account).mapped(
                "balance"
            )
        )

    def _run_wizard(self, employees, date_from=None, date_to=None):
        run = self.env["hr.payslip.run"].create(
            {
                "name": "Lote de prueba – renovación",
                "date_start": date_from or date(2026, 1, 1),
                "date_end": date_to or date(2026, 1, 31),
                "struct_id": self.structure.id,
                "journal_id": self.journal.id,
            }
        )
        wizard = (
            self.env["hr.payslip.employees"]
            .with_context(active_id=run.id)
            .create({"employee_ids": [(6, 0, employees.ids)]})
        )
        return run, wizard

    # ------------------------------------------------------------------
    # P1-a: una pasada del motor por contrato
    # ------------------------------------------------------------------
    def test_contracts_evaluated_separately(self):
        """A sin relación laboral (1–15/01) y B con relación laboral (desde
        16/01) con un concepto fijo: B tiene sus reglas de ley y el concepto;
        A solo sueldo, total y neto."""
        employee = self._employee("Ismael Ordóñez")
        contract_a = self._contract(
            employee,
            wage=600.0,
            date_start=date(2026, 1, 1),
            date_end=date(2026, 1, 15),
            contract_type=self.type_no_labor,
        )
        contract_b = self._contract(employee, wage=1000.0, date_start=date(2026, 1, 16))
        bonus = self._concept("BONO_RENOV")
        self._assign(employee, bonus, 100.0)
        payslip = self._slip_without_contract(employee)
        payslip.compute_sheet()
        lines = self._codes_by_contract(payslip)
        self.assertEqual(set(lines[contract_a]), {"BASIC", "GROSS", "NET"})
        self.assertTrue(
            {"IESS_PERSONAL", "IESS_PATRONAL", "D13_PROV", "INC_OTHER"}
            <= set(lines[contract_b]),
            lines[contract_b],
        )
        self.assertAlmostEqual(lines[contract_a]["BASIC"], 300.00)
        self.assertAlmostEqual(lines[contract_a]["NET"], 300.00)
        # B: 500 de sueldo (15 días) + 100 de bono; IESS 10 % de 500.
        self.assertAlmostEqual(lines[contract_b]["BASIC"], 500.00)
        self.assertAlmostEqual(lines[contract_b]["INC_OTHER"], 100.00)
        self.assertAlmostEqual(lines[contract_b]["GROSS"], 600.00)
        self.assertAlmostEqual(lines[contract_b]["IESS_PERSONAL"], -50.00)
        self.assertAlmostEqual(lines[contract_b]["NET"], 550.00)
        # Asiento: un único asiento cuadrado; sueldos por pagar = suma de netos.
        payslip.action_payslip_done()
        move = payslip.move_id
        self.assertEqual(move.state, "posted")
        self.assertEqual(move.journal_id, self.journal)
        self.assertAlmostEqual(sum(move.line_ids.mapped("balance")), 0.0)
        self.assertAlmostEqual(
            self._move_balance(move, self.accounts["net_payable"]), -850.00
        )
        self.assertAlmostEqual(
            self._move_balance(move, self.accounts["expense_wage"]), 800.00
        )

    # ------------------------------------------------------------------
    # B3: renovación a mitad de mes
    # ------------------------------------------------------------------
    def _renewal_employee(self, name):
        employee = self._employee(name)
        old = self._contract(
            employee,
            date_start=date(2025, 1, 1),
            date_end=date(2026, 1, 15),
            state="close",
        )
        new = self._contract(employee, date_start=date(2026, 1, 16))
        return employee, old, new

    def _assert_full_renewal_month(self, payslip, old, new):
        lines = self._codes_by_contract(payslip)
        self.assertEqual(set(lines), {old, new})
        basic = sum(
            payslip.line_ids.filtered(lambda line: line.code == "BASIC").mapped("total")
        )
        self.assertAlmostEqual(basic, 1000.00)
        inc_other = payslip.line_ids.filtered(lambda line: line.code == "INC_OTHER")
        self.assertEqual(len(inc_other), 1)
        self.assertEqual(inc_other.contract_id, new)
        self.assertAlmostEqual(inc_other.total, 80.00)

    def test_mid_month_renewal_manual_payslip(self):
        employee, old, new = self._renewal_employee("Nuria Peñafiel")
        self._assign(employee, self._concept("MOVIL"), 80.0)
        payslip = self._slip_without_contract(employee)
        payslip.compute_sheet()
        self._assert_full_renewal_month(payslip, old, new)
        # Con el contrato nuevo asignado explícitamente, igual.
        payslip.action_payslip_cancel()
        explicit = self._payslip(employee, contract=new)
        explicit.compute_sheet()
        self._assert_full_renewal_month(explicit, old, new)

    def test_mid_month_renewal_batch(self):
        employee, old, new = self._renewal_employee("Íker Muñoz")
        self._assign(employee, self._concept("MOVIL"), 80.0)
        run, wizard = self._run_wizard(employee)
        wizard.compute_sheet()
        payslip = run.slip_ids
        self.assertEqual(payslip.contract_id, new)
        self._assert_full_renewal_month(payslip, old, new)

    # ------------------------------------------------------------------
    # P1-b: guarda de estados y campos protegidos
    # ------------------------------------------------------------------
    def test_payroll_user_cannot_write_protected_fields(self):
        payslip = self._payslip(self.employee)
        as_user = payslip.with_user(self.payroll_user)
        for vals in ({"state": "done"}, {"state": "verify"}, {"credit_note": True}):
            with self.assertRaises(UserError) as error:
                as_user.write(vals)
            self.assertIn("no se modifican directamente", str(error.exception))
        self.assertEqual(payslip.state, "draft")
        as_user.compute_sheet()
        payslip.action_payslip_done()
        other_move = payslip.move_id.copy()
        with self.assertRaises(UserError):
            as_user.write({"move_id": other_move.id})
        with self.assertRaises(UserError):
            as_user.write(
                {
                    "refunded_id": self._payslip(
                        self.employee,
                        date_from=date(2026, 2, 1),
                        date_to=date(2026, 2, 28),
                    ).id
                }
            )
        with self.assertRaises(UserError) as error:
            as_user.write({"date_to": date(2026, 1, 30)})
        self.assertIn("confirmado", str(error.exception))
        self.assertEqual(payslip.date_to, date(2026, 1, 31))
        # Nota interna y pagado sí se editan en un rol confirmado.
        as_user.write({"note": "Pagado por transferencia – ñandú"})
        payslip.with_user(self.payroll_manager).write({"paid": True})
        self.assertTrue(payslip.paid)

    def test_manager_cannot_write_move_nor_create_done(self):
        payslip = self._computed(self.employee)
        payslip.action_payslip_done()
        move = payslip.move_id
        as_manager = payslip.with_user(self.payroll_manager)
        with self.assertRaises(UserError):
            as_manager.write({"move_id": False})
        with self.assertRaises(UserError):
            as_manager.write({"state": "cancel"})
        self.assertEqual(payslip.move_id, move)
        with self.assertRaises(UserError):
            self.env["hr.payslip"].with_user(self.payroll_manager).create(
                {
                    "employee_id": self.employee.id,
                    "struct_id": self.structure.id,
                    "date_from": date(2026, 2, 1),
                    "date_to": date(2026, 2, 28),
                    "state": "done",
                }
            )

    def test_normal_flow_with_guard(self):
        """Calcular (usuario), confirmar, reembolsar, anular y volver a
        borrador (responsable) siguen funcionando con la guarda activa."""
        self.env["ir.config_parameter"].sudo().set_param(ALLOW_CANCEL, "True")
        payslip = self._payslip(self.employee)
        payslip.with_user(self.payroll_user).compute_sheet()
        as_manager = payslip.with_user(self.payroll_manager)
        as_manager.action_payslip_done()
        self.assertEqual(payslip.state, "done")
        with self.assertRaises(AccessError):
            payslip.with_user(self.payroll_user).refund_sheet()
        as_manager.refund_sheet()
        refund = payslip.refunded_id
        self.assertEqual(refund.state, "done")
        self.assertTrue(refund.credit_note)
        self.assertTrue(refund.line_ids)
        refund.with_user(self.payroll_manager).action_payslip_cancel()
        as_manager.action_payslip_cancel()
        self.assertEqual(payslip.state, "cancel")
        as_manager.action_payslip_draft()
        self.assertEqual(payslip.state, "draft")

    def test_superuser_bypasses_guard(self):
        """``env.su`` (procesos internos) no se restringe."""
        payslip = self._computed(self.employee)
        payslip.write({"state": "draft"})
        self.assertEqual(payslip.state, "draft")

    # ------------------------------------------------------------------
    # P2-a: anular con apuntes conciliados
    # ------------------------------------------------------------------
    def test_cancel_with_reconciled_payment_blocked(self):
        self.env["ir.config_parameter"].sudo().set_param(ALLOW_CANCEL, "True")
        payslip = self._computed(self.employee)
        payslip.action_payslip_done()
        net_account = self.accounts["net_payable"]
        net_account.reconcile = True
        bank = self.env["account.account"].create(
            {"code": "1999801", "name": "Banco (prueba)", "account_type": "asset_cash"}
        )
        partner = self.employee.work_contact_id
        payment = self.env["account.move"].create(
            {
                "journal_id": self.journal.id,
                "date": date(2026, 2, 5),
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Pago de sueldo",
                            "account_id": net_account.id,
                            "partner_id": partner.id,
                            "debit": 900.0,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Pago de sueldo",
                            "account_id": bank.id,
                            "credit": 900.0,
                        },
                    ),
                ],
            }
        )
        payment.action_post()
        to_reconcile = (payment.line_ids | payslip.move_id.line_ids).filtered(
            lambda ml: ml.account_id == net_account
        )
        to_reconcile.reconcile()
        self.assertTrue(all(ml.reconciled for ml in to_reconcile))
        with self.assertRaises(UserError) as error:
            payslip.with_user(self.payroll_manager).action_payslip_cancel()
        self.assertIn("rompa la conciliación", str(error.exception))
        self.assertEqual(payslip.state, "done")
        self.assertFalse(payslip.move_id.reversal_move_ids)
        # Rota la conciliación, se anula y se revierte.
        to_reconcile.remove_move_reconcile()
        payslip.with_user(self.payroll_manager).action_payslip_cancel()
        self.assertEqual(payslip.state, "cancel")
        self.assertTrue(payslip.move_id.reversal_move_ids)

    # ------------------------------------------------------------------
    # P2-b: sin búsqueda de duplicados por rol al calcular
    # ------------------------------------------------------------------
    def _employees_with_contracts(self, count, prefix):
        employees = self.env["hr.employee"]
        for index in range(count):
            employee = self._employee(f"{prefix} Peña {index}")
            self._contract(employee)
            employees |= employee
        return employees

    def _count_compute_queries(self, payslips):
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.cr.sql_log_count
        payslips.compute_sheet()
        self.env.flush_all()
        return self.cr.sql_log_count - before

    def test_compute_queries_per_payslip(self):
        one = self._slip_without_contract(self._employees_with_contracts(1, "Uno"))
        five = self.env["hr.payslip"]
        for employee in self._employees_with_contracts(5, "Cinco"):
            five |= self._payslip(employee)
        # Calentamiento (cachés de registros técnicos: secuencia, reglas...).
        self._computed(self._employees_with_contracts(1, "Previo"))
        original = ErpHrPayslip._erp_check_duplicate_period
        calls = []

        def counting(slips, items):
            calls.append(len(items))
            return original(slips, items)

        with patch.object(ErpHrPayslip, "_erp_check_duplicate_period", counting):
            queries_one = self._count_compute_queries(one)
            queries_five = self._count_compute_queries(five)
        per_extra = (queries_five - queries_one) / 4
        _logger.info(
            "compute_sheet: %s consultas con 1 rol, %s con 5 (%.1f por rol "
            "adicional).",
            queries_one,
            queries_five,
            per_extra,
        )
        # Ninguna comprobación de duplicados al calcular (solo cambia el
        # estado a «Calculado»).
        self.assertEqual(calls, [])
        self.assertLessEqual(per_extra, MAX_QUERIES_PER_EXTRA_PAYSLIP)

    def test_duplicate_check_still_runs_when_leaving_cancel(self):
        first = self._payslip(self.employee)
        first.action_payslip_cancel()
        self._payslip(self.employee)
        with self.assertRaises(UserError):
            first.action_payslip_draft()

    # ------------------------------------------------------------------
    # P3
    # ------------------------------------------------------------------
    def test_mro_no_override_skipped(self):
        """``action_payslip_done``/``action_payslip_cancel`` llaman a
        ``super(PayrollAccountHrPayslip, self)``: ninguna clase entre la de
        este módulo y la de ``payroll_account`` puede redefinirlos (su código
        no se ejecutaría)."""
        mro = type(self.env["hr.payslip"]).__mro__
        start = mro.index(ErpHrPayslip)
        end = mro.index(PayrollAccountHrPayslip)
        self.assertLess(start, end)
        skipped = [
            cls
            for cls in mro[start + 1 : end]
            if {"action_payslip_done", "action_payslip_cancel"} & set(vars(cls))
        ]
        self.assertEqual(skipped, [])

    def test_assignments_cache_by_period(self):
        """Dos roles del mismo empleado (enero y febrero) calculados juntos:
        la asignación vigente solo en febrero no entra en enero."""
        concept = self._concept("BONO_FEB")
        self._assign(
            self.employee, concept, 50.0, date_from=date(2026, 2, 1)
        ).date_to = date(2026, 2, 28)
        january = self._payslip(self.employee)
        february = self._payslip(
            self.employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28)
        )
        (january | february).compute_sheet()
        self.assertNotIn("INC_OTHER", self._lines(january))
        self.assertAlmostEqual(self._lines(february)["INC_OTHER"], 50.0)

    def test_benefit_modes_prefetched_as_employee_method(self):
        """La precarga en lote de modalidades coincide con
        ``hr.employee._get_benefit_mode`` (cambio de modalidad a mitad de año
        y valor por defecto de la empresa)."""
        self._election(self.employee, "thirteenth", "monthly", date(2026, 6, 1))
        january = self._payslip(self.employee)
        july = self._payslip(
            self.employee, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31)
        )
        (january | july).compute_sheet()
        self.assertIn("D13_PROV", self._lines(january))
        self.assertIn("D13_PAID", self._lines(july))
        for slip in january | july:
            for benefit in ("reserve_fund", "thirteenth", "fourteenth"):
                with slip._erp_compute_scope():
                    slip._erp_prefetch_benefit_modes()
                    self.assertEqual(
                        slip._erp_get_benefit_mode(benefit),
                        self.employee._get_benefit_mode(benefit, slip.date_to),
                    )

    def test_batch_reuses_period_contracts(self):
        employees = self._employees_with_contracts(3, "Lote")
        run, wizard = self._run_wizard(employees, date(2026, 3, 1), date(2026, 3, 31))
        original = ErpHrPayslip._erp_get_period_contracts
        calls = []

        def counting(slips, *args, **kwargs):
            calls.append(args)
            return original(slips, *args, **kwargs)

        with patch.object(ErpHrPayslip, "_erp_get_period_contracts", counting):
            wizard.compute_sheet()
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(run.slip_ids), 3)
        for slip in run.slip_ids:
            self.assertEqual(slip.contract_id.employee_id, slip.employee_id)

    def test_payslip_vals_ignore_foreign_contract_in_map(self):
        other = self._employee("Otro Núñez")
        other_contract = self._contract(other)
        vals = (
            self.env["hr.payslip"]
            .with_context(erp_period_contract_ids={self.employee.id: other_contract.id})
            .get_payslip_vals(date(2026, 1, 1), date(2026, 1, 31), self.employee.id)
        )
        self.assertEqual(vals["value"]["contract_id"], self.contract.id)

    def test_contract_without_calendar(self):
        """La jornada del contrato es obligatoria en la BD; la comprobación es
        defensiva (contrato en memoria o dato inconsistente)."""
        payslip = self._payslip(self.employee)
        contract = self.env["hr.contract"].new(
            {
                "name": "Contrato sin jornada",
                "employee_id": self.employee.id,
                "wage": 1000.0,
                "resource_calendar_id": False,
            }
        )
        contract.resource_calendar_id = False
        with self.assertRaises(UserError) as error:
            payslip._erp_get_work_time_rate(contract)
        self.assertIn("no tiene jornada de trabajo", str(error.exception))

    def test_company_without_max_weekly_hours(self):
        calendar = self.env["resource.calendar"].create(
            {
                "name": "Jornada sin tiempo completo (prueba)",
                "full_time_required_hours": 0.0,
                "attendance_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Lunes",
                            "dayofweek": "0",
                            "hour_from": 8,
                            "hour_to": 12,
                            "day_period": "morning",
                        },
                    )
                ],
            }
        )
        employee = self._employee("Jornada Cero")
        contract = self._contract(employee, calendar=calendar)
        # erp_hr_ec impide un máximo de 0 (CHECK > 0 en la BD y validación con
        # contratos en curso): la comprobación es defensiva y se simula el
        # valor 0 sustituyendo el campo durante el cálculo.
        payslip = self._payslip(employee, contract=contract)
        with (
            patch.object(
                type(self.company),
                "erp_max_weekly_hours",
                new_callable=PropertyMock,
                return_value=0.0,
            ),
            self.assertRaises(UserError) as error,
        ):
            payslip.compute_sheet()
        self.assertIn("máximo de horas semanales", str(error.exception))

    def test_inputs_of_done_payslip_locked(self):
        concept = self._concept("COMISION", amount_kind="variable")
        payslip = self._computed(self.employee, inputs={"COMISION": 25.0})
        payslip.action_payslip_done()
        line = payslip.input_line_ids
        Input = self.env["hr.payslip.input"].with_user(self.payroll_manager)
        with self.assertRaises(UserError):
            line.with_user(self.payroll_manager).write({"amount": 30.0})
        with self.assertRaises(UserError):
            line.with_user(self.payroll_manager).unlink()
        with self.assertRaises(UserError):
            Input.create(
                {
                    "name": "Comisión extra",
                    "payslip_id": payslip.id,
                    "erp_concept_id": concept.id,
                    "amount": 5.0,
                    "contract_id": self.contract.id,
                }
            )
        self.assertAlmostEqual(line.amount, 25.0)

    def test_payroll_user_duplicates_payslip(self):
        """Duplicar como usuario de nómina: sin error de permisos; el rol
        nuevo nace en borrador, sin líneas calculadas y con las entradas."""
        self._concept("HORAS", amount_kind="variable")
        payslip = self._computed(self.employee, inputs={"HORAS": 40.0})
        payslip.action_payslip_cancel()
        duplicate = payslip.with_user(self.payroll_user).copy()
        self.assertEqual(duplicate.state, "draft")
        self.assertFalse(duplicate.line_ids)
        self.assertEqual(duplicate.input_line_ids.mapped("amount"), [40.0])
        duplicate.with_user(self.payroll_user).compute_sheet()
        self.assertAlmostEqual(self._lines(duplicate)["BASIC"], 1000.0)
        # Duplicar un rol vigente choca con el duplicado del periodo: mensaje
        # de negocio, no de permisos.
        with self.assertRaises(UserError) as error:
            duplicate.with_user(self.payroll_user).copy()
        self.assertIn("Ya existe un rol de pagos no anulado", str(error.exception))

    # ------------------------------------------------------------------
    # B1: errores de negocio dentro de las reglas, sin traza de OCA
    # ------------------------------------------------------------------
    def _assert_clean_error(self, error):
        message = str(error.exception)
        self.assertNotIn("Wrong python", message)
        self.assertNotIn("Traceback", message)
        return message

    def test_missing_parameter_message_unwrapped(self):
        self.parameters.filtered(lambda p: p.code == "IESS_PERSONAL").active = False
        with self.assertRaises(UserError) as expected:
            self.Parameter._get_value("IESS_PERSONAL", date(2026, 1, 31), self.company)
        payslip = self._payslip(self.employee)
        with self.assertRaises(UserError) as error:
            payslip.compute_sheet()
        self.assertEqual(
            self._assert_clean_error(error), str(expected.exception), error.exception
        )

    def test_no_establishment_message_unwrapped(self):
        employee = self._employee("Sin Agencia Ñ", establishment=False)
        self._contract(employee)
        with self.assertRaises(UserError) as error:
            self._computed(employee)
        message = self._assert_clean_error(error)
        self.assertTrue(message.startswith("No se puede calcular el rol de"), message)
        self.assertIn("establecimiento", message)

    def test_negative_net_message_unwrapped(self):
        self._assign(
            self.employee, self._concept("DESC_GRANDE", concept_type="deduction"), 5000
        )
        with self.assertRaises(UserError) as error:
            self._computed(self.employee)
        message = self._assert_clean_error(error)
        self.assertTrue(message.startswith("El neto a recibir de"), message)

    # ------------------------------------------------------------------
    # B4: confirmar varios roles a la vez
    # ------------------------------------------------------------------
    def test_confirm_several_payslips_at_once(self):
        employee_2 = self._employee("Lucía Ibáñez")
        self._contract(employee_2, wage=800.0)
        payslips = self._payslip(self.employee) | self._payslip(employee_2)
        payslips.with_user(self.payroll_manager).action_payslip_done()
        self.assertEqual(set(payslips.mapped("state")), {"done"})
        self.assertEqual(len(payslips.move_id), 2)
        for slip in payslips:
            self.assertEqual(slip.move_id.ref, slip.number)
            self.assertAlmostEqual(sum(slip.move_id.line_ids.mapped("balance")), 0.0)

    def test_confirm_several_payslips_without_recompute(self):
        self.env["ir.config_parameter"].sudo().set_param(PREVENT_COMPUTE, "True")
        employee_2 = self._employee("Tomás Cañizares")
        self._contract(employee_2, wage=800.0)
        payslips = self._payslip(self.employee) | self._payslip(employee_2)
        payslips.compute_sheet()
        payslips.with_user(self.payroll_manager).action_payslip_done()
        self.assertEqual(set(payslips.mapped("state")), {"done"})
        self.assertEqual(len(payslips.move_id), 2)

    # ------------------------------------------------------------------
    # B5: periodo dentro de un mes natural
    # ------------------------------------------------------------------
    def test_period_spanning_two_months_rejected(self):
        payslip = self._payslip(
            self.employee, date_from=date(2026, 1, 15), date_to=date(2026, 2, 14)
        )
        with self.assertRaises(UserError) as error:
            payslip.compute_sheet()
        self.assertIn("mes natural", str(error.exception))
        self.assertFalse(payslip.line_ids)
        with self.assertRaises(UserError):
            payslip.with_context(without_compute_sheet=True).action_payslip_done()
        # Un periodo parcial dentro del mes sí se calcula.
        partial = self._payslip(
            self.employee, date_from=date(2026, 3, 1), date_to=date(2026, 3, 15)
        )
        partial.compute_sheet()
        self.assertAlmostEqual(self._lines(partial)["BASIC"], 500.0)

    # ------------------------------------------------------------------
    # Parámetros: sin total en la lista agrupada
    # ------------------------------------------------------------------
    def test_parameter_value_not_aggregated(self):
        description = self.Parameter.fields_get(["value"])["value"]
        self.assertFalse(description.get("aggregator"), description)

    # ------------------------------------------------------------------
    # Ronda 2 de QA: neto del rol completo
    # ------------------------------------------------------------------
    def _renewal_on_30th(self, name):
        """A 01–29/01 (1.000, cerrado) + B desde 30/01: B cubre 1 día."""
        employee = self._employee(name)
        contract_a = self._contract(
            employee,
            date_start=date(2025, 1, 1),
            date_end=date(2026, 1, 29),
            state="close",
        )
        contract_b = self._contract(employee, date_start=date(2026, 1, 30))
        return employee, contract_a, contract_b

    def test_net_checked_on_whole_payslip(self):
        """B (1 día) con un descuento fijo de 100 tiene NET negativo, pero el
        neto del rol (suma de las líneas NET) es positivo: se calcula."""
        employee, contract_a, contract_b = self._renewal_on_30th("Ñusta Cañar")
        self._assign(
            employee, self._concept("DESC_FIJO", concept_type="deduction"), 100.0
        )
        payslip = self._slip_without_contract(employee)
        payslip.compute_sheet()
        self.assertEqual(payslip.state, "verify")
        lines = self._codes_by_contract(payslip)
        # A: 1.000 × 29 / 30 = 966,67; IESS 96,67; neto 870,00.
        self.assertAlmostEqual(lines[contract_a]["BASIC"], 966.67)
        self.assertAlmostEqual(lines[contract_a]["NET"], 870.00)
        # B: 1.000 × 1 / 30 = 33,33; IESS 3,33; descuento 100 → neto −70,00.
        self.assertAlmostEqual(lines[contract_b]["BASIC"], 33.33)
        self.assertAlmostEqual(lines[contract_b]["DED_OTHER"], -100.00)
        self.assertAlmostEqual(lines[contract_b]["NET"], -70.00)
        net = sum(
            payslip.line_ids.filtered(lambda line: line.code == "NET").mapped("total")
        )
        self.assertAlmostEqual(net, 800.00)
        # El asiento cuadra y sueldos por pagar recoge el neto total.
        payslip.action_payslip_done()
        self.assertAlmostEqual(sum(payslip.move_id.line_ids.mapped("balance")), 0.0)
        self.assertAlmostEqual(
            self._move_balance(payslip.move_id, self.accounts["net_payable"]), -800.00
        )

    def test_negative_whole_payslip_net_still_raises(self):
        employee, _contract_a, _contract_b = self._renewal_on_30th("Íñigo Quishpe")
        self._assign(
            employee, self._concept("DESC_TOTAL", concept_type="deduction"), 1000.0
        )
        payslip = self._slip_without_contract(employee)
        with self.assertRaises(UserError) as error:
            payslip.compute_sheet()
        message = self._assert_clean_error(error)
        self.assertTrue(message.startswith("El neto a recibir de"), message)
        # −100,00 = 870,00 (A) + (33,33 − 3,33 − 1.000) (B).
        self.assertTrue("100.00" in message or "100,00" in message, message)
        self.assertFalse(payslip.line_ids)
        self.assertEqual(payslip.state, "draft")

    # ------------------------------------------------------------------
    # Ronda 2 de QA: analítica por contrato
    # ------------------------------------------------------------------
    def test_analytic_account_per_line_contract(self):
        plan = self.env["account.analytic.plan"].create({"name": "Centros (prueba)"})
        Analytic = self.env["account.analytic.account"]
        analytic_a = Analytic.create({"name": "Agencia Manta – ñ", "plan_id": plan.id})
        analytic_b = Analytic.create({"name": "Agencia Cuenca", "plan_id": plan.id})
        employee, old, new = self._renewal_employee("Maite Yánez")
        old.analytic_account_id = analytic_a
        new.analytic_account_id = analytic_b
        # El rol tiene asignado el contrato nuevo: aun así, las líneas del
        # contrato anterior van a su propia analítica.
        payslip = self._payslip(employee, contract=new)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        wage_lines = payslip.move_id.line_ids.filtered(
            lambda ml: ml.account_id == self.accounts["expense_wage"]
        )
        by_analytic = {}
        for move_line in wage_lines:
            self.assertEqual(len(move_line.analytic_distribution), 1)
            key = next(iter(move_line.analytic_distribution))
            by_analytic[key] = by_analytic.get(key, 0.0) + move_line.balance
        self.assertEqual(set(by_analytic), {str(analytic_a.id), str(analytic_b.id)})
        self.assertAlmostEqual(by_analytic[str(analytic_a.id)], 500.00)
        self.assertAlmostEqual(by_analytic[str(analytic_b.id)], 500.00)

    # ------------------------------------------------------------------
    # Ronda 2 de QA: el marcador de transición no sobrevive a un fallo
    # ------------------------------------------------------------------
    def test_guard_active_after_failed_compute(self):
        self._assign(
            self.employee, self._concept("DESC_FALLO", concept_type="deduction"), 5000
        )
        payslip = self._payslip(self.employee)
        as_user = payslip.with_user(self.payroll_user)
        with self.assertRaises(UserError):
            as_user.compute_sheet()
        self.assertFalse(payslip._erp_in_transition())
        with self.assertRaises(UserError) as error:
            as_user.write({"state": "verify"})
        self.assertIn("no se modifican directamente", str(error.exception))
        self.assertEqual(payslip.state, "draft")
