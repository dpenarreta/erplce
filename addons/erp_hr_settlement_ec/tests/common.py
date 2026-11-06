"""Base de los tests de liquidación de la ronda de correcciones de US-013
(remuneración, valor del día de vacaciones, integración con el pago de
décimos y reingreso).

Valores FICTICIOS de prueba (no legales): los de ``erp_payroll_ec`` (ver su
``tests/common.py``: SBU 400, divisor del décimo tercero 12, mes de 30 días)
más los parámetros de liquidación y vacaciones de ``SETTLEMENT_PARAMS`` y los
periodos de décimos de ``BENEFIT_PERIODS``.
"""

from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.addons.erp_hr_holidays_ec.models import const as holidays_const
from odoo.addons.erp_payroll_ec.tests.common import PayrollEcCase

MODULE = "erp_hr_settlement_ec"
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
# Prefijo -> (mes y día de inicio del periodo, mes y día de pago).
BENEFIT_PERIODS = {
    "THIRTEENTH": (12, 1, 12, 24),
    "FOURTEENTH_COSTA": (3, 1, 3, 15),
    "FOURTEENTH_SIERRA": (8, 1, 8, 15),
}
BENEFIT_PERIOD_SUFFIXES = (
    "PERIOD_START_MONTH",
    "PERIOD_START_DAY",
    "PAYMENT_MONTH",
    "PAYMENT_DAY",
)


def month_range(first, last):
    """``(primer día, último día)`` de cada mes de ``first`` a ``last``."""
    month = first
    while month <= last:
        yield month, month + relativedelta(day=31)
        month += relativedelta(months=1)


class SettlementCase(PayrollEcCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "payroll.allow_cancel_payslips", True
        )
        values = [
            (code, value_type, value)
            for code, (value_type, value) in SETTLEMENT_PARAMS.items()
        ] + [
            (f"{prefix}_{suffix}", "number", value)
            for prefix, period in BENEFIT_PERIODS.items()
            for suffix, value in zip(BENEFIT_PERIOD_SUFFIXES, period, strict=True)
        ]
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
                for code, value_type, value in values
            ]
        )
        Account = cls.env["account.account"]
        cls.expense = {
            key: Account.create(
                {"code": code, "name": f"{key} (prueba)", "account_type": "expense"}
            )
            for key, code in (
                ("vacation", "5999830"),
                ("severance", "5999831"),
                ("indemnity", "5999832"),
            )
        }
        cls.company.write(
            {
                "erp_settlement_vacation_account_id": cls.expense["vacation"].id,
                "erp_settlement_severance_account_id": cls.expense["severance"].id,
                "erp_settlement_indemnity_account_id": cls.expense["indemnity"].id,
            }
        )
        cls.benefit_structure = cls.env.ref("erp_payroll_ec.structure_ec_benefit_pay")
        benefit_rules = {rule.code: rule for rule in cls.benefit_structure.rule_ids}
        for code, account in (
            ("D13_ACC_PAY", "d13_provision"),
            ("D14_ACC_PAY_COSTA", "d14_costa"),
            ("D14_ACC_PAY_SIERRA", "d14_sierra"),
        ):
            benefit_rules[code].with_company(cls.company).write(
                {"account_debit": cls.accounts[account].id, "account_credit": False}
            )
        cls.Settlement = cls.env["erp.hr.settlement"]
        cls.Line = cls.env["erp.hr.settlement.line"]
        cls.PayslipLine = cls.env["hr.payslip.line"]
        cls.unfair = cls.env.ref(f"{MODULE}.cause_unfair_dismissal")
        cls.contract_end_cause = cls.env.ref(f"{MODULE}.cause_contract_end")

    @classmethod
    def _confirmed_months(cls, contract, first, last, inputs=None):
        """Roles mensuales confirmados de ``contract`` de ``first`` a ``last``
        (cada uno cortado al fin del contrato). ``inputs``: ``{(año, mes):
        {código: importe}}`` de entradas variables."""
        payslips = cls.env["hr.payslip"]
        for date_from, date_to in month_range(first, last):
            if contract.date_end:
                date_to = min(date_to, contract.date_end)
            month_inputs = (inputs or {}).get((date_from.year, date_from.month), {})
            slip = cls.env["hr.payslip"].create(
                {
                    "employee_id": contract.employee_id.id,
                    "contract_id": contract.id,
                    "struct_id": cls.structure.id,
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
                        for code, amount in month_inputs.items()
                    ],
                }
            )
            slip.compute_sheet()
            slip.action_payslip_done()
            payslips |= slip
        return payslips

    def _new_settlement(self, contract, departure, cause=None):
        return self.Settlement.create(
            {
                "employee_id": contract.employee_id.id,
                "contract_id": contract.id,
                "date_departure": departure,
                "cause_id": (cause or self.contract_end_cause).id,
            }
        )

    @staticmethod
    def _by_code(settlement):
        return {line.code: line for line in settlement.line_ids if not line.is_manual}
