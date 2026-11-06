"""Códigos de la liquidación de haberes (US-013).

Solo códigos: los valores legales viven en ``erp.payroll.parameter`` (datos
``data/erp_payroll_parameter_data.xml``, estado «A validar») y en los tramos
de indemnización (``erp.hr.indemnity.bracket``).
"""

# ---------------------------------------------------------------------------
# Parámetros normativos de la liquidación (erp.payroll.parameter)
# ---------------------------------------------------------------------------
# Bonificación por desahucio (Código del Trabajo, art. 185): porcentaje de la
# última remuneración mensual por año de servicio.
SEVERANCE_BONUS_RATE = "SEVERANCE_BONUS_RATE"
# 1 = la fracción de año se paga en proporción; 0 = solo años completos.
SEVERANCE_BONUS_PROPORTIONAL_FRACTION = "SEVERANCE_BONUS_PROPORTIONAL_FRACTION"
# Indemnización por despido intempestivo (art. 188): 1 = la fracción de año
# cuenta como año completo; 0 = solo años completos.
INDEMNITY_YEAR_FRACTION_AS_FULL = "INDEMNITY_YEAR_FRACTION_AS_FULL"
# Valor del día de vacaciones no gozadas: remuneración percibida en los
# VACATION_DAY_BASE_MONTHS meses (año móvil) inmediatamente anteriores a la
# fecha de salida / VACATION_DAY_DIVISOR.
VACATION_DAY_BASE_MONTHS = "VACATION_DAY_BASE_MONTHS"
VACATION_DAY_DIVISOR = "VACATION_DAY_DIVISOR"
# Vacaciones proporcionales (art. 71): remuneraciones del año de servicio en
# curso / VACATION_PROPORTIONAL_DIVISOR.
VACATION_PROPORTIONAL_DIVISOR = "VACATION_PROPORTIONAL_DIVISOR"

SETTLEMENT_PARAMETER_CODES = (
    SEVERANCE_BONUS_RATE,
    SEVERANCE_BONUS_PROPORTIONAL_FRACTION,
    INDEMNITY_YEAR_FRACTION_AS_FULL,
    VACATION_DAY_BASE_MONTHS,
    VACATION_DAY_DIVISOR,
    VACATION_PROPORTIONAL_DIVISOR,
)

# ---------------------------------------------------------------------------
# Liquidación
# ---------------------------------------------------------------------------
SETTLEMENT_STATE_SELECTION = [
    ("draft", "Borrador"),
    ("computed", "Calculada"),
    ("done", "Confirmada"),
    ("cancel", "Anulada"),
]
# Estados en los que una liquidación se puede eliminar.
SETTLEMENT_DELETABLE_STATES = ("draft", "cancel")
SETTLEMENT_SEQUENCE_CODE = "erp.hr.settlement"

# Rubros de la liquidación (código de línea).
LINE_D13 = "D13"
LINE_D14 = "D14"
LINE_VAC_PENDING = "VAC_PENDING"
LINE_VAC_PROPORTIONAL = "VAC_PROPORTIONAL"
LINE_SEVERANCE_BONUS = "DESAHUCIO"
LINE_INDEMNITY = "INDEMNITY"
LINE_OTHER_INCOME = "OTHER_INCOME"
LINE_OTHER_DEDUCTION = "OTHER_DEDUCTION"
SETTLEMENT_LINE_CODE_SELECTION = [
    (LINE_D13, "Décimo tercero pendiente"),
    (LINE_D14, "Décimo cuarto pendiente"),
    (LINE_VAC_PENDING, "Vacaciones no gozadas"),
    (LINE_VAC_PROPORTIONAL, "Vacaciones proporcionales"),
    (LINE_SEVERANCE_BONUS, "Bonificación por desahucio"),
    (LINE_INDEMNITY, "Indemnización por despido intempestivo"),
    (LINE_OTHER_INCOME, "Otro ingreso"),
    (LINE_OTHER_DEDUCTION, "Otro descuento"),
]
# Rubros que RRHH registra a mano (CA-7); el resto los genera «Calcular».
MANUAL_LINE_CODES = (LINE_OTHER_INCOME, LINE_OTHER_DEDUCTION)
DEDUCTION_LINE_CODES = (LINE_OTHER_DEDUCTION,)
LINE_TYPE_SELECTION = [
    ("income", "Ingreso"),
    ("deduction", "Descuento"),
]

# Estado «a validar» de causas y tramos (mismo criterio que los parámetros).
VALIDATION_STATE_SELECTION = [
    ("to_validate", "A validar"),
    ("validated", "Validado"),
]
PAYROLL_MANAGER_GROUP = "payroll.group_payroll_manager"

# ---------------------------------------------------------------------------
# Cálculo de la liquidación (capa de negocio)
# ---------------------------------------------------------------------------
# Líneas del rol mensual confirmado que forman la «remuneración» del mes para
# el valor del día de vacaciones, las vacaciones proporcionales y la última
# remuneración: sueldo del periodo (BASIC) e ingresos propios (INC_OTHER), a
# los que se resta la parte de conceptos con «Cuenta como remuneración»
# desmarcado (viáticos, reembolsos; CA-14,
# hr.payslip._erp_get_non_remuneration_income). Quedan fuera los décimos y los
# fondos de reserva. Interpretación a validar con el asesor laboral.
REMUNERATION_LINE_CODES = ("BASIC", "INC_OTHER")
# Provisiones de décimos que paga cada rubro de la liquidación.
LINE_PROVISION_CODES = {
    LINE_D13: ("D13_PROV",),
    LINE_D14: ("D14_PROV_COSTA", "D14_PROV_SIERRA"),
}
# Orden de los rubros calculados.
LINE_SEQUENCES = {
    LINE_D13: 10,
    LINE_D14: 20,
    LINE_VAC_PENDING: 30,
    LINE_VAC_PROPORTIONAL: 40,
    LINE_SEVERANCE_BONUS: 50,
    LINE_INDEMNITY: 60,
}
# Cuentas de gasto de los rubros: campo de res.company y código por defecto
# del plan l10n_ec (plantilla 'ec') si el campo está vacío. Valores A VALIDAR
# por el contador.
EXPENSE_ACCOUNT_FIELDS = {
    LINE_VAC_PENDING: "erp_settlement_vacation_account_id",
    LINE_VAC_PROPORTIONAL: "erp_settlement_vacation_account_id",
    LINE_SEVERANCE_BONUS: "erp_settlement_severance_account_id",
    LINE_INDEMNITY: "erp_settlement_indemnity_account_id",
}
DEFAULT_ACCOUNT_CODES = {
    "erp_settlement_vacation_account_id": "52020303",
    "erp_settlement_severance_account_id": "52020305",
    "erp_settlement_indemnity_account_id": "52020304",
}
# Indicador en ``cr.cache`` (no en el contexto, que controla el cliente RPC):
# una acción de la liquidación (calcular, confirmar, anular, volver a
# borrador) está en curso; solo entonces se escriben el estado, los asientos
# y los rubros de una liquidación confirmada o anulada.
SETTLEMENT_TRANSITION_KEY = "erp_hr_settlement_ec.settlement_transition"
# Indicador equivalente para el estado «A validar» de causas y tramos.
VALIDATION_TRANSITION_KEY = "erp_hr_settlement_ec.validation_transition"
