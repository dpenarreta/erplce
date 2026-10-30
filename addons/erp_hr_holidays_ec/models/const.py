"""Códigos de los parámetros normativos de ausencias (US-012, CA-1).

Los valores viven en ``erp.payroll.parameter`` (datos de
``data/erp_payroll_parameter_data.xml``, estado «A validar»); aquí solo están
los códigos, para no repetir literales en la lógica ni en los tests. Ningún
número legal se escribe en código.
"""

# Vacaciones anuales (Código del Trabajo, art. 69)
VACATION_BASE_DAYS = "VACATION_BASE_DAYS"
VACATION_EXTRA_FROM_YEAR = "VACATION_EXTRA_FROM_YEAR"
VACATION_EXTRA_DAYS_PER_YEAR = "VACATION_EXTRA_DAYS_PER_YEAR"
VACATION_EXTRA_MAX_DAYS = "VACATION_EXTRA_MAX_DAYS"
# Acumulación (Código del Trabajo, art. 75): años de vigencia de cada periodo
# de vacaciones desde que nace el derecho (aniversario). El periodo caduca el
# día anterior al aniversario + este número de años (US-012, CA-10).
VACATION_VALIDITY_YEARS = "VACATION_VALIDITY_YEARS"
# Corte de la generación automática (US-012, CA-12): el valor no se usa; rige
# su «Vigente desde» más antiguo. La tarea diaria solo genera aniversarios
# iguales o posteriores a esa fecha.
VACATION_GENERATION_START = "VACATION_GENERATION_START"
# 1 = días calendario (incluye no laborables); 0 = días laborables.
VACATION_COUNT_CALENDAR_DAYS = "VACATION_COUNT_CALENDAR_DAYS"
# Igual convención para las licencias por días con duración máxima legal.
LEAVE_COUNT_CALENDAR_DAYS = "LEAVE_COUNT_CALENDAR_DAYS"

# Duraciones máximas por solicitud (las referencia hr.leave.type
# mediante erp_max_duration_param_code).
LEAVE_MATERNITY_MAX_DAYS = "LEAVE_MATERNITY_MAX_DAYS"
LEAVE_PATERNITY_MAX_DAYS = "LEAVE_PATERNITY_MAX_DAYS"
LEAVE_CALAMITY_MAX_DAYS = "LEAVE_CALAMITY_MAX_DAYS"
LEAVE_NURSING_HOURS_PER_DAY = "LEAVE_NURSING_HOURS_PER_DAY"
# Periodo (meses posteriores al parto) en que rige la jornada de lactancia.
# Pendiente (US-012 §5): aún no lo usa ninguna validación; se registra para
# la historia que controle la fecha de parto.
LEAVE_NURSING_MONTHS = "LEAVE_NURSING_MONTHS"

VACATION_PARAMETER_CODES = (
    VACATION_BASE_DAYS,
    VACATION_EXTRA_FROM_YEAR,
    VACATION_EXTRA_DAYS_PER_YEAR,
    VACATION_EXTRA_MAX_DAYS,
    VACATION_VALIDITY_YEARS,
    VACATION_GENERATION_START,
    VACATION_COUNT_CALENDAR_DAYS,
)
LEAVE_PARAMETER_CODES = (
    LEAVE_COUNT_CALENDAR_DAYS,
    LEAVE_MATERNITY_MAX_DAYS,
    LEAVE_PATERNITY_MAX_DAYS,
    LEAVE_CALAMITY_MAX_DAYS,
    LEAVE_NURSING_HOURS_PER_DAY,
    LEAVE_NURSING_MONTHS,
)
ALL_PARAMETER_CODES = VACATION_PARAMETER_CODES + LEAVE_PARAMETER_CODES
