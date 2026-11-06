"""Modelo de datos de la liquidación de haberes (US-013): datos cargados
(causas, parámetros, tramos, secuencia), restricciones de BD, unicidad de la
liquidación por contrato y de la provisión pagada, marca de periodos de
vacaciones liquidados, borrado y permisos.

Las restricciones de BD se prueban con SQL parametrizado cuando la capa de
negocio pueda añadir validaciones previas. No se prueban cifras legales como
verdad: de los datos cargados se comprueba su presencia, estado y fuente.
"""

from datetime import date

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import SQL, mute_logger

from odoo.addons.erp_payroll_ec.tests.common import PayrollEcCase

from ..models.const import SETTLEMENT_PARAMETER_CODES

# código de causa -> (bonificación por desahucio, indemnización, motivo de
# salida de Odoo). Valores de partida «a validar».
CAUSES = {
    "RESIGNATION": (True, False, "hr.departure_resigned"),
    "UNFAIR_DISMISSAL": (True, True, "hr.departure_fired"),
    "EMPLOYER_JUST_CAUSE": (False, False, "hr.departure_fired"),
    "EMPLOYEE_JUST_CAUSE": (True, True, "hr.departure_resigned"),
    "CONTRACT_END": (False, False, None),
    "MUTUAL_AGREEMENT": (True, False, None),
    "NOTICE": (True, False, None),
    "DEATH": (False, False, None),
    "RETIREMENT": (False, False, "hr.departure_retired"),
}
MODULE = "erp_hr_settlement_ec"


class SettlementDataCommon:
    @classmethod
    def _setup_settlement_data(cls):
        cls.Settlement = cls.env["erp.hr.settlement"]
        cls.Line = cls.env["erp.hr.settlement.line"]
        cls.Cause = cls.env["erp.hr.termination.cause"]
        cls.cause = cls.env.ref(f"{MODULE}.cause_unfair_dismissal")
        cls.contract_type = cls.env["hr.contract.type"].create(
            {"name": "Indefinido (prueba US-013)", "erp_labor_relationship": True}
        )
        cls.employee_a = cls.env["hr.employee"].create(
            {"name": "Íñigo Muñoz Cañizares", "erp_company_entry_date": "2020-03-15"}
        )
        cls.contract_a = cls.env["hr.contract"].create(
            {
                "name": "Contrato de Íñigo – Logística Ñuñoa",
                "employee_id": cls.employee_a.id,
                "wage": 1234.56,
                "date_start": date(2020, 3, 15),
                "date_end": date(2026, 12, 31),
                "state": "open",
                "contract_type_id": cls.contract_type.id,
            }
        )
        cls.employee_b = cls.env["hr.employee"].create({"name": "Ana Peña Ibáñez"})
        cls.contract_b = cls.env["hr.contract"].create(
            {
                "name": "Contrato de Ana",
                "employee_id": cls.employee_b.id,
                "wage": 600.0,
                "date_start": date(2025, 1, 1),
                "state": "open",
                "contract_type_id": cls.contract_type.id,
            }
        )

    def _settlement(self, employee=None, contract=None, **vals):
        return self.Settlement.create(
            {
                "employee_id": (employee or self.employee_a).id,
                "contract_id": (contract or self.contract_a).id,
                "date_departure": date(2026, 3, 14),
                "cause_id": self.cause.id,
                **vals,
            }
        )

    def _set_state(self, settlement, state):
        # SQL: el estado lo cambian las acciones de negocio (DEV-2); aquí solo
        # se prueba la integridad de la BD.
        self.env.cr.execute(
            SQL(
                "UPDATE erp_hr_settlement SET state = %s WHERE id = %s",
                state,
                settlement.id,
            )
        )
        settlement.invalidate_recordset(["state"])


@tagged("post_install", "-at_install")
class TestSettlementData(SettlementDataCommon, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_settlement_data()

    # ------------------------------------------------------------------
    # Datos cargados
    # ------------------------------------------------------------------
    def test_causes_loaded_to_validate(self):
        causes = self.Cause.search([])
        self.assertEqual(set(causes.mapped("code")), set(CAUSES))
        for cause in causes:
            severance, indemnity, reason = CAUSES[cause.code]
            self.assertEqual(cause.state, "to_validate", cause.code)
            self.assertEqual(cause.pays_severance_bonus, severance, cause.code)
            self.assertEqual(
                cause.pays_unfair_dismissal_indemnity, indemnity, cause.code
            )
            self.assertTrue(cause.pays_thirteenth and cause.pays_fourteenth)
            self.assertTrue(
                cause.pays_pending_vacation and cause.pays_proportional_vacation
            )
            self.assertEqual(
                cause.departure_reason_id,
                self.env.ref(reason) if reason else self.env["hr.departure.reason"],
                cause.code,
            )
            self.assertIn("a validar", cause.description, cause.code)
            self.assertTrue(cause.legal_basis, cause.code)
        data = self.env["ir.model.data"].search(
            [("module", "=", MODULE), ("model", "=", "erp.hr.termination.cause")]
        )
        self.assertEqual(len(data), len(CAUSES))
        self.assertTrue(all(data.mapped("noupdate")))

    def test_cause_code_unique_and_format(self):
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.Cause.create({"name": "Duplicada", "code": "RESIGNATION"})
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.Cause.create({"name": "Código inválido", "code": "renuncia ñ"})

    def test_parameters_loaded_to_validate(self):
        params = (
            self.env["erp.payroll.parameter"]
            .with_context(active_test=False)
            .search([("code", "in", SETTLEMENT_PARAMETER_CODES)])
        )
        self.assertEqual(set(params.mapped("code")), set(SETTLEMENT_PARAMETER_CODES))
        for param in params:
            self.assertEqual(param.state, "to_validate", param.code)
            self.assertTrue(param.norm.strip(), param.code)
            self.assertFalse(param.company_id, param.code)
        self.assertEqual(
            params.filtered(lambda p: p.code == "SEVERANCE_BONUS_RATE").value_type,
            "percent",
        )
        data = self.env["ir.model.data"].search(
            [("module", "=", MODULE), ("model", "=", "erp.payroll.parameter")]
        )
        self.assertEqual(len(data), len(SETTLEMENT_PARAMETER_CODES))
        self.assertTrue(all(data.mapped("noupdate")))

    def test_sequence_loaded(self):
        sequence = self.env.ref(f"{MODULE}.seq_erp_hr_settlement")
        self.assertEqual(sequence.code, "erp.hr.settlement")
        self.assertTrue(sequence.use_date_range)
        self.assertTrue(sequence.prefix.startswith("LIQ/"))

    # ------------------------------------------------------------------
    # Tramos de indemnización
    # ------------------------------------------------------------------
    def test_indemnity_brackets_loaded_and_lookup(self):
        Bracket = self.env["erp.hr.indemnity.bracket"]
        short = self.env.ref(f"{MODULE}.indemnity_bracket_up_to_3_2020")
        long_ = self.env.ref(f"{MODULE}.indemnity_bracket_over_3_2020")
        self.assertEqual((short | long_).mapped("state"), ["to_validate"] * 2)
        departure = date(2026, 3, 14)
        self.assertEqual(Bracket._get_bracket(1, departure), short)
        self.assertEqual(Bracket._get_bracket(3, departure), short)
        self.assertEqual(Bracket._get_bracket(4, departure), long_)
        self.assertEqual(Bracket._get_bracket(40, departure), long_)
        with self.assertRaises(UserError):
            Bracket._get_bracket(2, date(2019, 12, 31))
        # Una versión propia de la empresa prevalece sobre la común.
        own = Bracket.create(
            {
                "name": "Tramo único de la empresa (prueba)",
                "date_from": date(2025, 1, 1),
                "years_from": 0,
                "fixed_months": 4,
                "norm": "Valor ficticio de prueba",
                "company_id": self.env.company.id,
            }
        )
        self.assertEqual(Bracket._get_bracket(10, departure), own)
        self.assertEqual(Bracket._get_bracket(10, date(2024, 12, 31)), long_)

    def test_indemnity_bracket_checks(self):
        Bracket = self.env["erp.hr.indemnity.bracket"]
        base = {
            "name": "Tramo de prueba",
            "date_from": date(2030, 1, 1),
            "norm": "Valor ficticio de prueba",
        }
        invalid = [
            {"years_from": 5, "years_to": 3},
            {"years_from": -1},
            {"fixed_months": -1},
            {"min_months": 5, "max_months": 3},
        ]
        for vals in invalid:
            with self.subTest(vals=vals), mute_logger("odoo.sql_db"):
                with self.assertRaises(IntegrityError), self.env.cr.savepoint():
                    Bracket.create({**base, **vals})
        Bracket.create(base)
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                Bracket.create(base)

    # ------------------------------------------------------------------
    # Liquidación: unicidad por contrato, fechas, borrado
    # ------------------------------------------------------------------
    def test_one_active_settlement_per_contract(self):
        first = self._settlement()
        self.assertEqual(first.state, "draft")
        self.assertEqual(first.name, "/")
        self.assertEqual(first.currency_id, self.env.company.currency_id)
        # La capa de negocio avisa en español antes que la BD (DEV-2); la
        # restricción de la BD se prueba con SQL.
        with self.assertRaisesRegex(UserError, "Ya existe una liquidación"):
            self._settlement()
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    SQL(
                        "INSERT INTO erp_hr_settlement (name, company_id, "
                        "employee_id, contract_id, date_departure, cause_id, "
                        "state) VALUES ('/', %s, %s, %s, %s, %s, 'draft')",
                        first.company_id.id,
                        first.employee_id.id,
                        first.contract_id.id,
                        first.date_departure,
                        first.cause_id.id,
                    )
                )
        # Otra liquidación del mismo contrato solo si la anterior está anulada.
        self._set_state(first, "cancel")
        second = self._settlement()
        self.assertTrue(second)
        # Contratos distintos no chocan.
        self.assertTrue(
            self._settlement(
                self.employee_b, self.contract_b, date_departure=date(2026, 3, 1)
            )
        )

    def test_settlement_number_unique_per_company(self):
        first = self._settlement(name="LIQ/2026/0001")
        self._set_state(first, "cancel")
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._settlement(name="LIQ/2026/0001")

    def test_departure_date_within_contract(self):
        invalid = [
            {"date_departure": date(2020, 3, 14)},
            {"date_departure": date(2027, 1, 1)},
            {"employee": self.employee_b},
        ]
        for vals in invalid:
            with self.subTest(vals=vals), self.assertRaises(ValidationError):
                with self.env.cr.savepoint():
                    self._settlement(**vals)
        settlement = self._settlement(date_departure=date(2026, 12, 31))
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            settlement.date_departure = date(2027, 1, 1)
            settlement.flush_recordset()
        # Contrato sin fin: cualquier fecha posterior al inicio.
        self.assertTrue(
            self._settlement(
                self.employee_b, self.contract_b, date_departure=date(2030, 1, 1)
            )
        )

    def test_service_time_snapshot(self):
        settlement = self._settlement()
        self.assertEqual(settlement.date_entry, date(2020, 3, 15))
        self.assertEqual(
            (
                settlement.service_years,
                settlement.service_months,
                settlement.service_days,
            ),
            (6, 0, 0),
        )
        self.assertEqual(
            settlement.service_total_days,
            (date(2026, 3, 14) - date(2020, 3, 15)).days + 1,
        )
        settlement.date_departure = date(2026, 5, 20)
        self.assertEqual(
            (
                settlement.service_years,
                settlement.service_months,
                settlement.service_days,
            ),
            (6, 2, 6),
        )
        # Un cambio posterior de la ficha (reingreso) no altera la liquidación.
        self.employee_a.erp_company_entry_date = date(2026, 6, 1)
        self.assertEqual(settlement.date_entry, date(2020, 3, 15))
        # Sin fecha de ingreso en la ficha: la del primer contrato.
        other = self._settlement(
            self.employee_b, self.contract_b, date_departure=date(2026, 1, 31)
        )
        self.assertEqual(other.date_entry, date(2025, 1, 1))
        self.assertEqual((other.service_years, other.service_months), (1, 1))

    def test_unlink_only_draft_or_cancelled(self):
        computed = self._settlement()
        self._set_state(computed, "computed")
        with self.assertRaises(UserError):
            computed.unlink()
        self._set_state(computed, "done")
        with self.assertRaises(UserError):
            computed.unlink()
        self._set_state(computed, "cancel")
        computed.unlink()
        self.assertFalse(computed.exists())
        draft = self._settlement(self.employee_b, self.contract_b)
        draft.unlink()
        self.assertFalse(draft.exists())

    # ------------------------------------------------------------------
    # Rubros y totales
    # ------------------------------------------------------------------
    def _line(self, settlement, code, amount, **vals):
        return self.Line.create(
            {
                "settlement_id": settlement.id,
                "code": code,
                "name": f"Rubro {code} – año 2026",
                "amount": amount,
                **vals,
            }
        )

    def test_lines_and_totals(self):
        settlement = self._settlement()
        self._line(settlement, "D13", 100.555)
        self._line(settlement, "VAC_PENDING", 250.0, base=10.0, quantity=25.0)
        deduction = self._line(settlement, "OTHER_DEDUCTION", 50.0, is_manual=True)
        self.assertEqual(deduction.line_type, "deduction")
        self.assertEqual(deduction.company_id, settlement.company_id)
        self.assertAlmostEqual(settlement.total_income, 350.56, places=2)
        self.assertAlmostEqual(settlement.total_deduction, 50.0, places=2)
        self.assertAlmostEqual(settlement.net, 300.56, places=2)
        # Neto negativo: admitido en borrador, nunca confirmado (BD).
        self._line(settlement, "OTHER_DEDUCTION", 1000.0, is_manual=True)
        self.assertLess(settlement.net, 0)
        self.env.flush_all()
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._set_state(settlement, "done")
        # Borrar la liquidación (borrador) borra sus rubros.
        lines = settlement.line_ids
        settlement.unlink()
        self.assertFalse(lines.exists())

    def test_line_checks(self):
        settlement = self._settlement()
        invalid = [
            {"code": "D13", "amount": -1.0},
            {"code": "D13", "amount": 1.0, "quantity": -1.0},
            {"code": "INDEMNITY", "amount": 1.0, "is_manual": True},
        ]
        for vals in invalid:
            with self.subTest(vals=vals), mute_logger("odoo.sql_db"):
                with self.assertRaises(IntegrityError), self.env.cr.savepoint():
                    self.Line.create(
                        {"settlement_id": settlement.id, "name": "Prueba", **vals}
                    )
        account = self.env["account.account"].create(
            {
                "code": "2999901",
                "name": "Anticipos (prueba)",
                "account_type": "asset_current",
            }
        )
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._line(settlement, "D14", 1.0, account_id=account.id)
        manual = self._line(
            settlement, "OTHER_INCOME", 1.0, is_manual=True, account_id=account.id
        )
        self.assertEqual(manual.line_type, "income")

    # ------------------------------------------------------------------
    # Periodos de vacaciones liquidados
    # ------------------------------------------------------------------
    def test_settled_vacation_period_mark(self):
        settlement = self._settlement()
        allocation = self.env["hr.leave.allocation"].create(
            {
                "name": "Vacaciones – saldo de prueba",
                "employee_id": self.employee_a.id,
                "holiday_status_id": self.env.ref(
                    "erp_hr_holidays_ec.leave_type_annual_vacation"
                ).id,
                "number_of_days": 5,
                "allocation_type": "regular",
                "date_from": date(2025, 3, 15),
            }
        )

        def update(settlement_id, days, number_of_days):
            self.env.cr.execute(
                SQL(
                    "UPDATE hr_leave_allocation SET erp_settlement_id = %s, "
                    "erp_settled_days = %s, number_of_days = %s WHERE id = %s",
                    settlement_id,
                    days,
                    number_of_days,
                    allocation.id,
                )
            )

        # Días liquidados sin liquidación, días negativos y saldo 0 sin
        # liquidación: rechazados por la BD.
        for args in ((None, 5.0, 5.0), (settlement.id, -1.0, 5.0), (None, 0, 0)):
            with self.subTest(args=args), mute_logger("odoo.sql_db"):
                with self.assertRaises(IntegrityError), self.env.cr.savepoint():
                    update(*args)
        # Periodo liquidado: saldo 0 admitido.
        update(settlement.id, 5.0, 0)
        allocation.invalidate_recordset()
        self.assertEqual(allocation.erp_settlement_id, settlement)
        self.assertEqual(settlement.settled_allocation_ids, allocation)
        # Una liquidación con periodos marcados no se puede borrar (BD).
        self._set_state(settlement, "cancel")
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                settlement.unlink()

    # ------------------------------------------------------------------
    # Permisos y multiempresa
    # ------------------------------------------------------------------
    def test_access_and_multicompany(self):
        user = new_test_user(
            self.env,
            login="usuario_nomina_us013",
            groups="base.group_user,payroll.group_payroll_user",
        )
        manager = new_test_user(
            self.env,
            login="responsable_nomina_us013",
            groups="base.group_user,payroll.group_payroll_manager",
        )
        nobody = new_test_user(
            self.env, login="interno_us013", groups="base.group_user"
        )
        Access = self.env["ir.model.access"]
        for model in ("erp.hr.settlement", "erp.hr.settlement.line"):
            for operation in ("read", "write", "create", "unlink"):
                self.assertTrue(Access.with_user(user).check(model, operation, False))
                self.assertFalse(
                    Access.with_user(nobody).check(model, operation, False)
                )
        for model in ("erp.hr.termination.cause", "erp.hr.indemnity.bracket"):
            self.assertTrue(Access.with_user(user).check(model, "read", False))
            for operation in ("write", "create", "unlink"):
                self.assertFalse(Access.with_user(user).check(model, operation, False))
                self.assertTrue(
                    Access.with_user(manager).check(model, operation, False)
                )
        # Validar causas y tramos: solo el responsable de nómina.
        with self.assertRaises(AccessError):
            self.cause.with_user(user).action_validate()
        self.cause.with_user(manager).action_validate()
        self.assertEqual(self.cause.state, "validated")
        self.cause.with_user(manager).action_set_to_validate()
        self.assertEqual(self.cause.state, "to_validate")
        # Multiempresa: la liquidación de otra empresa no es visible.
        other_company = self.env["res.company"].create({"name": "Otra empresa US-013"})
        other_employee = self.env["hr.employee"].create(
            {"name": "Empleado de otra empresa", "company_id": other_company.id}
        )
        other_contract = self.env["hr.contract"].create(
            {
                "name": "Contrato otra empresa",
                "employee_id": other_employee.id,
                "company_id": other_company.id,
                "wage": 500.0,
                "date_start": date(2025, 1, 1),
            }
        )
        foreign = self.Settlement.create(
            {
                "company_id": other_company.id,
                "employee_id": other_employee.id,
                "contract_id": other_contract.id,
                "date_departure": date(2026, 1, 31),
                "cause_id": self.cause.id,
            }
        )
        own = self._settlement()
        visible = self.Settlement.with_user(user).search([])
        self.assertIn(own, visible)
        self.assertNotIn(foreign, visible)


@tagged("post_install", "-at_install")
class TestSettlementProvisionPayment(SettlementDataCommon, PayrollEcCase):
    """Marca de provisión pagada en una liquidación (US-013, CA-3, CA-9)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_settlement_data()
        cls.Payment = cls.env["erp.payroll.provision.payment"]
        cls.worker = cls._employee("Begoña Ñáñez Ortíz")
        cls.worker_contract = cls._contract(cls.worker)

    def _provision_line(self):
        payslip = self._payslip(self.worker)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        return payslip.line_ids.filtered(lambda line: line.code == "D13_PROV")

    def test_provision_paid_by_settlement_once(self):
        line = self._provision_line()
        settlement = self._settlement(
            self.worker, self.worker_contract, date_departure=date(2026, 2, 28)
        )
        payment = self.Payment.create(
            {
                "payslip_line_id": line.id,
                "amount": line.total,
                "document_type": "settlement",
                "settlement_id": settlement.id,
            }
        )
        self.assertEqual(settlement.provision_payment_ids, payment)
        self.assertFalse(
            self.env["hr.payslip.line"]._erp_get_pending_provision_lines(
                ["D13_PROV"], employees=self.worker
            )
        )
        benefit_slip = self.env["hr.payslip"].create(
            {
                "employee_id": self.worker.id,
                "contract_id": self.worker_contract.id,
                "struct_id": self.env.ref("erp_payroll_ec.structure_ec_benefit_pay").id,
                "date_from": date(2025, 12, 1),
                "date_to": date(2026, 11, 30),
            }
        )
        # Ya pagada por la liquidación: ni otro rol ni otra liquidación.
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.Payment.create(
                    {
                        "payslip_line_id": line.id,
                        "amount": line.total,
                        "document_type": "payslip",
                        "payslip_id": benefit_slip.id,
                    }
                )
        # Anular la liquidación elimina la marca: vuelve a estar pendiente.
        payment.unlink()
        self.assertEqual(
            self.env["hr.payslip.line"]._erp_get_pending_provision_lines(
                ["D13_PROV"], employees=self.worker
            ),
            line,
        )

    def test_settlement_document_reference_checks(self):
        line = self._provision_line()
        settlement = self._settlement(
            self.worker, self.worker_contract, date_departure=date(2026, 2, 28)
        )
        benefit_slip = self.env["hr.payslip"].create(
            {
                "employee_id": self.worker.id,
                "contract_id": self.worker_contract.id,
                "struct_id": self.env.ref("erp_payroll_ec.structure_ec_benefit_pay").id,
                "date_from": date(2025, 12, 1),
                "date_to": date(2026, 11, 30),
            }
        )
        invalid = [
            {"document_type": "settlement"},
            {
                "document_type": "settlement",
                "settlement_id": settlement.id,
                "payslip_id": benefit_slip.id,
            },
            {"document_type": "payslip", "settlement_id": settlement.id},
        ]
        for vals in invalid:
            with self.subTest(vals=vals), mute_logger("odoo.sql_db"):
                with self.assertRaises(IntegrityError), self.env.cr.savepoint():
                    self.Payment.create(
                        {"payslip_line_id": line.id, "amount": line.total, **vals}
                    )
