"""Base de los tests de cálculo y flujo del rol mensual Ecuador (US-008).

Todos los valores son FICTICIOS de prueba (CA-11): los parámetros cargados
por el módulo se archivan y se crean otros con cifras redondas que no son las
legales (SBU 400, aporte personal 10 %, patronal 12 %, fondos de reserva 8 %,
divisor 12, 12 meses de décimo cuarto, mes de 30 días, 12 meses de servicio
para fondos de reserva). Las cuentas contables y el diario también son de
prueba y se asignan a las reglas de la estructura «Rol mensual Ecuador».
"""

from datetime import date

from odoo.tests import TransactionCase, new_test_user

LC = "liability_current"
LP = "liability_payable"

TEST_PARAMETERS = {
    "SBU": ("amount", 400.0),
    "IESS_PERSONAL": ("percent", 10.0),
    "IESS_PATRONAL": ("percent", 12.0),
    "RESERVE_FUND_RATE": ("percent", 8.0),
    "THIRTEENTH_DIVISOR": ("number", 12.0),
    "FOURTEENTH_MONTHS": ("number", 12.0),
    "MONTH_DAYS": ("number", 30.0),
    "RESERVE_FUND_MIN_MONTHS": ("number", 12.0),
}

# código de regla -> (cuenta deudora, cuenta acreedora) por clave de cls.accounts
TEST_RULE_ACCOUNTS = {
    "BASIC": ("expense_wage", None),
    "INC_OTHER": ("expense_other", None),
    "FR_PAID": ("expense_fr", None),
    "D13_PAID": ("expense_d13", None),
    "D14_PAID": ("expense_d14", None),
    "GROSS": (None, None),
    "IESS_PERSONAL": ("iess_personal", None),
    "DED_OTHER": ("employee_payable", None),
    "NET": (None, "net_payable"),
    "IESS_PATRONAL": ("expense_patronal", "iess_patronal"),
    "FR_ACCRUED": ("expense_fr", "fr_payable"),
    "D13_PROV": ("expense_d13", "d13_provision"),
    "D14_PROV_COSTA": ("expense_d14", "d14_costa"),
    "D14_PROV_SIERRA": ("expense_d14", "d14_sierra"),
}


def day_lines(days, hour_from, hour_to):
    """Asistencias de lunes (0) a ``days - 1`` de ``hour_from`` a ``hour_to``."""
    return [
        {
            "name": f"Día {day}",
            "dayofweek": str(day),
            "hour_from": hour_from,
            "hour_to": hour_to,
            "day_period": "morning",
        }
        for day in range(days)
    ]


class PayrollEcCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.company.write(
            {
                "erp_max_weekly_hours": 40.0,
                "erp_default_reserve_fund_mode": "accumulated",
                "erp_default_thirteenth_mode": "accumulated",
                "erp_default_fourteenth_mode": "accumulated",
            }
        )
        cls.structure = cls.env.ref("erp_payroll_ec.structure_ec_monthly")
        cls.rules = {rule.code: rule for rule in cls.structure.rule_ids}

        # Parámetros ficticios (los cargados por el módulo se archivan).
        cls.Parameter = cls.env["erp.payroll.parameter"]
        cls.Parameter.search([]).write({"active": False})
        cls.parameters = cls.Parameter.create(
            [
                {
                    "code": code,
                    "name": f"{code} (prueba)",
                    "value_type": value_type,
                    "value": value,
                    "date_from": date(2020, 1, 1),
                    "norm": "Valor ficticio de prueba",
                }
                for code, (value_type, value) in TEST_PARAMETERS.items()
            ]
        )

        # Contabilidad de prueba.
        Account = cls.env["account.account"]
        specs = {
            "expense_wage": ("5999801", "Sueldos (prueba)", "expense"),
            "expense_other": ("5999802", "Otros ingresos (prueba)", "expense"),
            "expense_fr": ("5999803", "Fondos de reserva (prueba)", "expense"),
            "expense_d13": ("5999804", "Décimo tercero (prueba)", "expense"),
            "expense_d14": ("5999805", "Décimo cuarto (prueba)", "expense"),
            "expense_patronal": ("5999806", "Aporte patronal (prueba)", "expense"),
            "expense_bonus": ("5999807", "Bono propio (prueba)", "expense"),
            "iess_personal": (
                "2999801",
                "IESS personal por pagar (prueba)",
                "liability_current",
            ),
            "iess_patronal": (
                "2999802",
                "IESS patronal por pagar (prueba)",
                "liability_current",
            ),
            "fr_payable": (
                "2999803",
                "Fondos de reserva IESS (prueba)",
                "liability_current",
            ),
            "d13_provision": ("2999804", "Provisión D13 (prueba)", LC),
            "d14_costa": (
                "2999805",
                "Provisión D14 Costa (prueba)",
                "liability_current",
            ),
            "d14_sierra": (
                "2999806",
                "Provisión D14 Sierra (prueba)",
                "liability_current",
            ),
            "net_payable": (
                "2999807",
                "Sueldos por pagar (prueba)",
                "liability_payable",
            ),
            "employee_payable": (
                "2999808",
                "Otras cuentas por pagar empleados (prueba)",
                "liability_payable",
            ),
            "deduction_payable": (
                "2999809",
                "Comisariato por pagar (prueba)",
                "liability_current",
            ),
        }
        cls.accounts = {
            key: Account.create(
                {"code": code, "name": name, "account_type": account_type}
            )
            for key, (code, name, account_type) in specs.items()
        }
        for code, (debit, credit) in TEST_RULE_ACCOUNTS.items():
            cls.rules[code].with_company(cls.company).write(
                {
                    "account_debit": cls.accounts[debit].id if debit else False,
                    "account_credit": cls.accounts[credit].id if credit else False,
                }
            )
        cls.journal = cls.env["account.journal"].create(
            {
                "name": "Nómina Ecuador (prueba)",
                "code": "NOMEC",
                "type": "general",
                "default_account_id": cls.accounts["expense_wage"].id,
            }
        )

        # Jornadas, tipos de contrato y establecimientos.
        Calendar = cls.env["resource.calendar"]
        cls.cal_40 = Calendar.create(
            {
                "name": "Jornada 40 h (prueba)",
                "full_time_required_hours": 40.0,
                "attendance_ids": [(0, 0, vals) for vals in day_lines(5, 8, 16)],
            }
        )
        cls.cal_20 = Calendar.create(
            {
                "name": "Medio tiempo 20 h (prueba)",
                "full_time_required_hours": 40.0,
                "attendance_ids": [(0, 0, vals) for vals in day_lines(5, 8, 12)],
            }
        )
        cls.type_labor = cls.env["hr.contract.type"].create(
            {"name": "Indefinido (prueba US-008)", "erp_labor_relationship": True}
        )
        cls.type_no_labor = cls.env["hr.contract.type"].create(
            {"name": "Bajo factura (prueba US-008)", "erp_labor_relationship": False}
        )
        Establishment = cls.env["erp.establishment"]
        cls.est_costa = Establishment.create(
            {"code": "801", "name": "Agencia Manta (prueba)", "region": "costa"}
        )
        cls.est_sierra = Establishment.create(
            {"code": "802", "name": "Agencia Cuenca – Ñamarín", "region": "sierra"}
        )

        # Usuarios.
        cls.payroll_user = new_test_user(
            cls.env,
            login="usuario_nomina_us008",
            groups="base.group_user,payroll.group_payroll_user",
        )
        cls.payroll_manager = new_test_user(
            cls.env,
            login="responsable_nomina_us008",
            groups="base.group_user,payroll.group_payroll_manager",
        )

        cls.Concept = cls.env["erp.payroll.concept"]
        cls.EmployeeConcept = cls.env["erp.payroll.employee.concept"]

    # ------------------------------------------------------------------
    # Ayudas
    # ------------------------------------------------------------------
    @classmethod
    def _employee(cls, name, establishment=None, **vals):
        if establishment is None:
            establishment = cls.est_costa
        return cls.env["hr.employee"].create(
            {
                "name": name,
                "erp_establishment_id": establishment.id if establishment else False,
                **vals,
            }
        )

    @classmethod
    def _contract(
        cls,
        employee,
        wage=1000.0,
        date_start=date(2024, 1, 1),
        date_end=False,
        state="open",
        contract_type=None,
        calendar=None,
    ):
        return cls.env["hr.contract"].create(
            {
                "name": f"Contrato de {employee.name}",
                "employee_id": employee.id,
                "wage": wage,
                "date_start": date_start,
                "date_end": date_end,
                "state": state,
                "contract_type_id": (contract_type or cls.type_labor).id,
                "resource_calendar_id": (calendar or cls.cal_40).id,
                "struct_id": cls.structure.id,
                "journal_id": cls.journal.id,
            }
        )

    @classmethod
    def _election(cls, employee, benefit, mode, date_from=date(2020, 1, 1)):
        return cls.env["erp.hr.benefit.election"].create(
            {
                "employee_id": employee.id,
                "benefit": benefit,
                "mode": mode,
                "date_from": date_from,
            }
        )

    @classmethod
    def _all_monthly(cls, employee):
        for benefit in ("reserve_fund", "thirteenth", "fourteenth"):
            cls._election(employee, benefit, "monthly")

    def _payslip(
        self,
        employee,
        contract=None,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
        inputs=None,
    ):
        contract = contract or employee.contract_ids[:1]
        return self.env["hr.payslip"].create(
            {
                "employee_id": employee.id,
                "contract_id": contract.id,
                "struct_id": self.structure.id,
                "date_from": date_from,
                "date_to": date_to,
                "input_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": f"Entrada {code}",
                            "code": code,
                            "amount": amount,
                            "contract_id": contract.id,
                        },
                    )
                    for code, amount in (inputs or {}).items()
                ],
            }
        )

    def _computed(self, employee, **kwargs):
        payslip = self._payslip(employee, **kwargs)
        payslip.compute_sheet()
        return payslip

    def _lines(self, payslip):
        """``{código: total}`` de las líneas del rol."""
        return {line.code: line.total for line in payslip.line_ids}

    def _assert_lines(self, payslip, expected):
        """Las líneas del rol son exactamente ``expected`` (código: total),
        cada importe redondeado a centavos."""
        lines = self._lines(payslip)
        self.assertEqual(set(lines), set(expected), lines)
        for code, amount in expected.items():
            self.assertEqual(lines[code], self.currency.round(lines[code]), code)
            self.assertAlmostEqual(lines[code], amount, places=2, msg=code)

    def _concept(self, code, concept_type="income", amount_kind="fixed", **vals):
        return self.Concept.create(
            {
                "name": f"Concepto {code} (prueba)",
                "code": code,
                "concept_type": concept_type,
                "amount_kind": amount_kind,
                **vals,
            }
        )

    def _assign(self, employee, concept, amount, date_from=date(2026, 1, 1), **vals):
        return self.EmployeeConcept.create(
            {
                "employee_id": employee.id,
                "concept_id": concept.id,
                "amount": amount,
                "date_from": date_from,
                **vals,
            }
        )
