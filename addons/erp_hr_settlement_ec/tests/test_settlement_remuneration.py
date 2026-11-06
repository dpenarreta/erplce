"""Base de remuneración de la liquidación (US-013, CA-14) y valor del día de
vacaciones con año móvil (observación O-1 de QA-FUNC).

Valores FICTICIOS de prueba. Escenario «Rosa» (ingreso 15/03/2023, sueldo
1.200, salida 15/04/2026, roles confirmados de marzo de 2025 a abril de
2026):

- Alimentación (fijo, cuenta como remuneración): 100 al mes.
- Comisión (variable, cuenta como remuneración): 300 en abril de 2025.
- Viático (variable, NO cuenta como remuneración): 200 en mayo de 2025 y en
  marzo de 2026.
- Año móvil 16/04/2025 – 15/04/2026: abril de 2025 (1.200 + 100 + 300) ×
  15/30 = 800; mayo de 2025 a marzo de 2026 11 × 1.300 = 14.300 (sin los
  400 de viáticos); abril de 2026 600 + 100 = 700. Total 15.800 / 360 =
  43,8889 el día; 45 días de vacaciones (3 periodos de 15) = 1.975,00.
- Última remuneración: marzo de 2026 = 1.300 (sin el viático de 200).
- Proporcionales desde el 15/03/2026: 1.300 × 16/30 + 700 = 1.393,33 / 24
  = 58,06.

Escenario «Tomás» (mismas fechas, sin conceptos): el día vale la
remuneración del 16/04/2025 al 15/04/2026 / 360 = (600 + 11 × 1.200 + 600)
/ 360 = 40.
"""

from datetime import date
from unittest.mock import patch

from odoo.tests import tagged

from .common import SettlementCase

DEPARTURE = date(2026, 4, 15)
ENTRY = date(2023, 3, 15)


@tagged("post_install", "-at_install")
class TestSettlementRemuneration(SettlementCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Concept = cls.env["erp.payroll.concept"]
        cls.food = Concept.create(
            {
                "name": "Alimentación (prueba)",
                "code": "ALIMENTACION_T",
                "concept_type": "income",
                "amount_kind": "fixed",
            }
        )
        cls.commission = Concept.create(
            {
                "name": "Comisión de ventas (prueba)",
                "code": "COMISION_T",
                "concept_type": "income",
                "amount_kind": "variable",
            }
        )
        cls.travel = Concept.create(
            {
                "name": "Viático – Cañar (prueba)",
                "code": "VIATICO_T",
                "concept_type": "income",
                "amount_kind": "variable",
                "erp_is_remuneration": False,
            }
        )
        cls.rosa = cls._employee("Rosa Ñúñez Peñaherrera", erp_company_entry_date=ENTRY)
        cls.rosa_contract = cls._contract(
            cls.rosa, wage=1200.0, date_start=ENTRY, date_end=DEPARTURE
        )
        cls.env["erp.payroll.employee.concept"].create(
            {
                "employee_id": cls.rosa.id,
                "concept_id": cls.food.id,
                "amount": 100.0,
                "date_from": date(2025, 1, 1),
            }
        )
        cls.rosa_slips = cls._confirmed_months(
            cls.rosa_contract,
            date(2025, 3, 1),
            date(2026, 4, 1),
            inputs={
                (2025, 4): {"COMISION_T": 300.0},
                (2025, 5): {"VIATICO_T": 200.0},
                (2026, 3): {"VIATICO_T": 200.0},
            },
        )
        cls.rosa._erp_generate_vacation_allocations(date=DEPARTURE)
        cls.tomas = cls._employee("Tomás Ibáñez Ortíz", erp_company_entry_date=ENTRY)
        cls.tomas_contract = cls._contract(
            cls.tomas, wage=1200.0, date_start=ENTRY, date_end=DEPARTURE
        )
        cls._confirmed_months(cls.tomas_contract, date(2025, 3, 1), date(2026, 4, 1))

    def _slip(self, year, month):
        return self.rosa_slips.filtered(
            lambda slip: (slip.date_from.year, slip.date_from.month) == (year, month)
        )

    # ------------------------------------------------------------------
    # Casilla del concepto (CA-14)
    # ------------------------------------------------------------------
    def test_concept_flag_default_and_tracking(self):
        self.assertTrue(self.food.erp_is_remuneration)
        self.assertTrue(self.commission.erp_is_remuneration)
        self.assertFalse(self.travel.erp_is_remuneration)
        field = self.env["erp.payroll.concept"]._fields["erp_is_remuneration"]
        self.assertTrue(field.tracking)
        self.assertEqual(field.string, "Cuenta como remuneración")

    def test_non_remuneration_income_per_payslip(self):
        lines = {line.code: line.total for line in self._slip(2025, 5).line_ids}
        self.assertAlmostEqual(lines["INC_OTHER"], 300.0, places=2)
        self.assertAlmostEqual(
            self._slip(2025, 5)._erp_get_non_remuneration_income(), 200.0, places=2
        )
        self.assertAlmostEqual(
            self._slip(2025, 4)._erp_get_non_remuneration_income(), 0.0, places=2
        )
        self.assertAlmostEqual(
            self._slip(2026, 3)._erp_get_non_remuneration_income(), 200.0, places=2
        )

    # ------------------------------------------------------------------
    # Liquidación (CA-14 y O-1)
    # ------------------------------------------------------------------
    def test_settlement_excludes_non_remuneration_income(self):
        settlement = self._new_settlement(self.rosa_contract, DEPARTURE, self.unfair)
        settlement.action_compute()
        lines = self._by_code(settlement)
        # Última remuneración: marzo de 2026 sin el viático.
        self.assertAlmostEqual(settlement.last_wage, 1300.0, places=2)
        self.assertIn(
            "ingresos que no son remuneración", lines["DESAHUCIO"].explanation
        )
        # Valor del día: año móvil con abril de 2025 en proporción y sin
        # viáticos; la comisión y la alimentación sí cuentan.
        vacation = lines["VAC_PENDING"]
        self.assertEqual(vacation.quantity, 45.0)
        self.assertAlmostEqual(vacation.base, 43.89, places=2)
        self.assertAlmostEqual(vacation.amount, 1975.0, places=2)
        self.assertIn("año anterior a la salida", vacation.explanation)
        self.assertIn("Se excluyeron", vacation.explanation)
        self.assertIn("a validar", vacation.explanation)
        # Proporcionales: marzo de 2026 en proporción, sin su viático.
        proportional = lines["VAC_PROPORTIONAL"]
        self.assertAlmostEqual(proportional.base, 1393.33, places=2)
        self.assertAlmostEqual(proportional.amount, 58.06, places=2)
        self.assertIn("Se excluyeron", proportional.explanation)

    def test_marking_concept_as_remuneration_includes_it(self):
        self.travel.erp_is_remuneration = True
        settlement = self._new_settlement(self.rosa_contract, DEPARTURE, self.unfair)
        settlement.action_compute()
        lines = self._by_code(settlement)
        self.assertAlmostEqual(settlement.last_wage, 1500.0, places=2)
        # (15.800 + 400) / 360 = 45.
        self.assertAlmostEqual(lines["VAC_PENDING"].base, 45.0, places=2)
        self.assertNotIn("Se excluyeron", lines["VAC_PENDING"].explanation)
        self.assertNotIn(
            "ingresos que no son remuneración", lines["DESAHUCIO"].explanation
        )

    def test_vacation_day_value_rolling_year(self):
        """Ingreso 15/03/2023, sueldo 1.200, salida 15/04/2026, roles
        completos: día = remuneración del 16/04/2025 al 15/04/2026 / 360."""
        settlement = self._new_settlement(self.tomas_contract, DEPARTURE)
        history = settlement._erp_get_remuneration_history()
        # Marzo de 2025 queda fuera de la ventana: no cambia el resultado.
        self.assertIn((2025, 3), history)
        day_value, explanation = settlement._erp_vacation_day_value(history)
        self.assertAlmostEqual(day_value, 14400.0 / 360, places=4)
        self.assertIn("año anterior a la salida", explanation)
        self.assertNotIn("Se excluyeron", explanation)

    # ------------------------------------------------------------------
    # Cálculo en lote (QA-TECH P2) y criterio de asignaciones (P3)
    # ------------------------------------------------------------------
    def _count_map_queries(self, slips):
        slips = slips.browse(slips.ids)  # prefetch limitado a ``slips``
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        result = slips._erp_get_non_remuneration_income_map()
        return self.env.cr.sql_log_count - before, result

    def test_non_remuneration_map_queries_do_not_grow_with_payslips(self):
        self.assertEqual(len(self.rosa_slips), 14)
        # Calentamiento: las cachés del registro (reglas de acceso) pueden
        # haberse vaciado en otros tests y no forman parte de la medida.
        self._count_map_queries(self.rosa_slips)
        few, few_result = self._count_map_queries(self.rosa_slips[:3])
        many, many_result = self._count_map_queries(self.rosa_slips)
        self.assertEqual(
            few, many, "El número de consultas no debe crecer con los roles."
        )
        self.assertEqual(set(many_result), set(self.rosa_slips.ids))
        for slip_id, amount in few_result.items():
            self.assertEqual(many_result[slip_id], amount)

    def test_non_remuneration_map_matches_single_payslip(self):
        result = self.rosa_slips._erp_get_non_remuneration_income_map()
        for slip in self.rosa_slips:
            self.assertAlmostEqual(
                result[slip.id], slip._erp_get_non_remuneration_income(), places=2
            )
        self.assertAlmostEqual(result[self._slip(2025, 5).id], 200.0, places=2)
        self.assertAlmostEqual(result[self._slip(2026, 3).id], 200.0, places=2)
        self.assertAlmostEqual(sum(result.values()), 400.0, places=2)

    def test_remuneration_history_uses_batch_map(self):
        settlement = self._new_settlement(self.rosa_contract, DEPARTURE, self.unfair)
        payslip_class = type(self.env["hr.payslip"])
        with patch.object(
            payslip_class,
            "_erp_get_non_remuneration_income",
            side_effect=AssertionError("cálculo por rol (N+1)"),
        ):
            history = settlement._erp_get_remuneration_history()
        self.assertAlmostEqual(history[(2025, 5)]["excluded"], 200.0, places=2)
        self.assertAlmostEqual(history[(2025, 5)]["amount"], 1300.0, places=2)

    def test_archived_fixed_concept_not_excluded(self):
        """Mismo criterio que el cálculo: una asignación de un concepto fijo
        archivado no se pagó, así que no se resta de la remuneración."""
        transport = self.env["erp.payroll.concept"].create(
            {
                "name": "Movilización – Azogues (prueba)",
                "code": "MOVILIZACION_T",
                "concept_type": "income",
                "amount_kind": "fixed",
                "erp_is_remuneration": False,
            }
        )
        self.env["erp.payroll.employee.concept"].create(
            {
                "employee_id": self.rosa.id,
                "concept_id": transport.id,
                "amount": 50.0,
                "date_from": date(2025, 1, 1),
            }
        )
        slip = self._slip(2025, 5)
        # Activo: se resta (200 de viático + 50), sin superar lo pagado (300).
        self.assertAlmostEqual(slip._erp_get_non_remuneration_income(), 250.0, 2)
        transport.active = False
        self.assertAlmostEqual(slip._erp_get_non_remuneration_income(), 200.0, 2)
        self.assertEqual(
            slip._erp_get_assignments().concept_id, self.food, "Mismo criterio."
        )
