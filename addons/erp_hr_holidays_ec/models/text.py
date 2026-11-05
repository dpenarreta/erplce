"""Cifras en los textos al usuario (US-012, QA-UX): número en el formato del
idioma (sin decimales si es entero) y unidad en singular o plural: «1 día»,
«2 días», «0,5 días», «1 hora», «2 horas».

Funciones sobre ``env`` (``env._`` traduce con el idioma del entorno) para
no repetir la misma lógica en empleados, solicitudes, saldos y tipos.
"""

from odoo.tools import float_compare, formatLang


def format_number(env, value):
    """Número en el formato del idioma, sin decimales si es entero."""
    digits = 0 if float(value).is_integer() else 2
    return formatLang(env, value, digits=digits)


def _is_one(value):
    return float_compare(abs(value), 1.0, precision_digits=2) == 0


def format_days(env, value):
    """«1 día», «2 días», «0,5 días»."""
    number = format_number(env, value)
    if _is_one(value):
        return env._("%(number)s día", number=number)
    return env._("%(number)s días", number=number)


def format_hours(env, value):
    """«1 hora», «2 horas», «1,5 horas»."""
    number = format_number(env, value)
    if _is_one(value):
        return env._("%(number)s hora", number=number)
    return env._("%(number)s horas", number=number)


def format_quantity(env, value, request_unit):
    """Días u horas según la unidad del tipo de ausencia."""
    if request_unit == "hour":
        return format_hours(env, value)
    return format_days(env, value)
