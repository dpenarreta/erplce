"""Códigos compartidos del pago de décimos acumulados (US-013).

Solo códigos y correspondencias: ningún valor legal se escribe en código. Los
valores (meses y días de los periodos de cálculo y de pago) viven en
``erp.payroll.parameter`` (``data/erp_payroll_parameter_data.xml``, estado «A
validar»).
"""

# ---------------------------------------------------------------------------
# Provisiones mensuales de décimos (reglas de «Rol mensual Ecuador»)
# ---------------------------------------------------------------------------
PROVISION_D13 = "D13_PROV"
PROVISION_D14_COSTA = "D14_PROV_COSTA"
PROVISION_D14_SIERRA = "D14_PROV_SIERRA"
PROVISION_RULE_CODES = (PROVISION_D13, PROVISION_D14_COSTA, PROVISION_D14_SIERRA)

# ---------------------------------------------------------------------------
# Reglas de la estructura «Pago de décimos acumulados» (EC_BENEFIT_PAY)
# ---------------------------------------------------------------------------
BENEFIT_PAY_STRUCTURE_CODE = "EC_BENEFIT_PAY"
ACCRUED_PAY_D13 = "D13_ACC_PAY"
ACCRUED_PAY_D14_COSTA = "D14_ACC_PAY_COSTA"
ACCRUED_PAY_D14_SIERRA = "D14_ACC_PAY_SIERRA"
# Regla de pago -> (beneficio de erp_hr_ec, régimen o None, provisiones que paga)
ACCRUED_PAY_RULES = {
    ACCRUED_PAY_D13: ("thirteenth", None, (PROVISION_D13,)),
    ACCRUED_PAY_D14_COSTA: ("fourteenth", "costa_galapagos", (PROVISION_D14_COSTA,)),
    ACCRUED_PAY_D14_SIERRA: ("fourteenth", "sierra_amazonia", (PROVISION_D14_SIERRA,)),
}
# Décimo que paga un rol de «Pago de décimos acumulados»
# (hr.payslip.erp_benefit_pay_code): una regla de pago por rol.
ACCRUED_PAY_SELECTION = [
    (ACCRUED_PAY_D13, "Décimo tercer sueldo"),
    (ACCRUED_PAY_D14_COSTA, "Décimo cuarto sueldo (Costa / Galápagos)"),
    (ACCRUED_PAY_D14_SIERRA, "Décimo cuarto sueldo (Sierra / Amazonía)"),
]
# (beneficio, régimen) -> regla de pago.
ACCRUED_PAY_BY_BENEFIT = {
    (benefit, regime): code
    for code, (benefit, regime, _codes) in ACCRUED_PAY_RULES.items()
}

# ---------------------------------------------------------------------------
# Parámetros de periodo y pago de los décimos (erp.payroll.parameter)
# ---------------------------------------------------------------------------
# Prefijo del parámetro por (beneficio, régimen). Cada prefijo tiene cuatro
# códigos: <prefijo>_PERIOD_START_MONTH, <prefijo>_PERIOD_START_DAY,
# <prefijo>_PAYMENT_MONTH y <prefijo>_PAYMENT_DAY. El periodo de cálculo dura
# un año: empieza el día/mes de inicio y termina el día anterior al mismo
# día/mes del año siguiente.
BENEFIT_PERIOD_PARAM_PREFIX = {
    ("thirteenth", None): "THIRTEENTH",
    ("fourteenth", "costa_galapagos"): "FOURTEENTH_COSTA",
    ("fourteenth", "sierra_amazonia"): "FOURTEENTH_SIERRA",
}
PERIOD_START_MONTH = "PERIOD_START_MONTH"
PERIOD_START_DAY = "PERIOD_START_DAY"
PAYMENT_MONTH = "PAYMENT_MONTH"
PAYMENT_DAY = "PAYMENT_DAY"
BENEFIT_PERIOD_SUFFIXES = (
    PERIOD_START_MONTH,
    PERIOD_START_DAY,
    PAYMENT_MONTH,
    PAYMENT_DAY,
)


def benefit_period_param_code(benefit, regime, suffix):
    """Código del parámetro de periodo/pago de un décimo.

    :param benefit: ``"thirteenth"`` o ``"fourteenth"``
    :param regime: ``None`` (décimo tercero) o el régimen de décimo cuarto
        (``"costa_galapagos"`` / ``"sierra_amazonia"``)
    :param suffix: uno de ``BENEFIT_PERIOD_SUFFIXES``
    :raises KeyError: combinación desconocida
    """
    if suffix not in BENEFIT_PERIOD_SUFFIXES:
        raise KeyError(suffix)
    return f"{BENEFIT_PERIOD_PARAM_PREFIX[(benefit, regime)]}_{suffix}"


BENEFIT_PERIOD_PARAMETER_CODES = tuple(
    f"{prefix}_{suffix}"
    for prefix in BENEFIT_PERIOD_PARAM_PREFIX.values()
    for suffix in BENEFIT_PERIOD_SUFFIXES
)
