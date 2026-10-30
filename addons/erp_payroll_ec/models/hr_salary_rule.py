import logging

from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CHART_TEMPLATE_EC = "ec"

# Cuentas por defecto (plan l10n_ec, plantilla 'ec') de las reglas de la
# estructura «Rol mensual Ecuador». Valores A VALIDAR por el contador: son la
# cuenta equivalente más cercana del plan, no una decisión contable cerrada.
# Las cuentas se crean por empresa al cargar el plan, así que no se pueden
# referenciar por xmlid en los datos: se buscan por código.
#
# Convención de signos del motor OCA (payroll_account): ingresos y aportes en
# positivo, descuentos en negativo. Un importe negativo en la cuenta deudora
# genera un apunte al haber (así se registran los descuentos al pasivo).
#
# xmlid de la regla -> (código cuenta deudora, código cuenta acreedora)
ERP_RULE_DEFAULT_ACCOUNTS = {
    # Gasto: 5202 Gastos administrativos (alternativas: 5201 ventas, 5102 MOD).
    "erp_payroll_ec.rule_ec_basic": ("52020101", None),
    "erp_payroll_ec.rule_ec_inc_other": ("52020408", None),
    "erp_payroll_ec.rule_ec_fr_paid": ("52020202", None),
    "erp_payroll_ec.rule_ec_d13_paid": ("52020301", None),
    "erp_payroll_ec.rule_ec_d14_paid": ("52020302", None),
    # Total informativo: no genera apuntes (evita duplicar los ingresos).
    "erp_payroll_ec.rule_ec_gross": (None, None),
    # Descuento (negativo) en cuenta deudora -> haber del pasivo con el IESS.
    "erp_payroll_ec.rule_ec_iess_personal": ("21070304", None),
    # Descuentos propios (negativo) en cuenta deudora -> haber de 21070402
    # «Otras obligaciones corrientes con empleados» (a validar). Un concepto
    # con «Cuenta acreedora» propia usa la suya.
    "erp_payroll_ec.rule_ec_ded_other": ("21070402", None),
    "erp_payroll_ec.rule_ec_net": (None, "21070401"),
    "erp_payroll_ec.rule_ec_iess_patronal": ("52020201", "21070303"),
    "erp_payroll_ec.rule_ec_fr_accrued": ("52020202", "21070305"),
    "erp_payroll_ec.rule_ec_d13_prov": ("52020301", "2105010102"),
    "erp_payroll_ec.rule_ec_d14_prov_costa": ("52020302", "2105010104"),
    "erp_payroll_ec.rule_ec_d14_prov_sierra": ("52020302", "2105010103"),
}


class HrSalaryRule(models.Model):
    _inherit = "hr.salary.rule"

    def _erp_set_default_accounts(self, companies=None):
        """Asigna las cuentas por defecto del plan ``ec`` a las reglas de la
        estructura «Rol mensual Ecuador» (``ERP_RULE_DEFAULT_ACCOUNTS``).

        Idempotente: solo rellena las cuentas vacías de cada empresa (los
        campos de cuenta son ``company_dependent``), nunca sobrescribe una
        cuenta ya configurada. Las empresas sin el plan ``ec`` y los códigos de
        cuenta que no existan en la empresa se omiten con un aviso en el log.

        Lo llaman ``post_init_hook``, la migración 18.0.1.1.0 y la carga del
        plan ``ec`` (``account.chart.template._post_load_data``).

        :param companies: ``res.company`` a procesar (por defecto, todas).
        :return: número de asignaciones de cuenta realizadas.
        """
        # sudo(): proceso técnico de instalación/carga de plan; las reglas y las
        # cuentas pueden estar fuera de las empresas permitidas del usuario.
        env = self.sudo().env
        if companies is None:
            companies = env["res.company"].search([])
        companies = companies.sudo().filtered(
            lambda c: c.chart_template == CHART_TEMPLATE_EC
        )
        rules = {}
        for xmlid, codes in ERP_RULE_DEFAULT_ACCOUNTS.items():
            rule = env.ref(xmlid, raise_if_not_found=False)
            if rule and any(codes):
                rules[xmlid] = (rule, codes)
        all_codes = {code for _rule, codes in rules.values() for code in codes if code}
        count = 0
        Account = env["account.account"]
        for company in companies:
            company_accounts = Account.with_company(company).search(
                [
                    *Account._check_company_domain(company),
                    ("code", "in", list(all_codes)),
                ]
            )
            by_code = {account.code: account for account in company_accounts}
            missing = sorted(all_codes - set(by_code))
            if missing:
                _logger.warning(
                    "erp_payroll_ec: la empresa %s (id %s) no tiene las cuentas "
                    "%s del plan '%s'; las reglas que las usan quedan sin cuenta "
                    "por defecto.",
                    company.name,
                    company.id,
                    ", ".join(missing),
                    CHART_TEMPLATE_EC,
                )
            for rule, (debit_code, credit_code) in rules.values():
                rule_c = rule.with_company(company)
                vals = {}
                if debit_code and not rule_c.account_debit and debit_code in by_code:
                    vals["account_debit"] = by_code[debit_code].id
                if credit_code and not rule_c.account_credit and credit_code in by_code:
                    vals["account_credit"] = by_code[credit_code].id
                if vals:
                    rule_c.write(vals)
                    count += len(vals)
        return count

    # ------------------------------------------------------------------
    # Errores de negocio dentro de las reglas (US-008)
    # ------------------------------------------------------------------
    # OCA envuelve cualquier excepción del código de la regla (importe,
    # cantidad o condición) en un UserError «Wrong python code defined for
    # salary rule…» con la traza completa. ``safe_eval`` deja pasar sin cambios
    # los ``UserError`` (y sus subclases ``ValidationError``/``AccessError``),
    # así que la causa del error de OCA es el error de negocio original
    # (parámetro sin vigencia, empleado sin establecimiento, neto negativo...):
    # se relanza tal cual, con su mensaje en español. Cualquier otro error (un
    # fallo de programación en la regla) conserva el mensaje de OCA.
    def _erp_call_unwrapping_business_errors(self, method, localdict):
        try:
            return method(localdict)
        except UserError as error:
            cause = error.__cause__
            if isinstance(cause, UserError):
                raise cause from None
            raise

    def _compute_rule_fix(self, localdict):
        return self._erp_call_unwrapping_business_errors(
            super()._compute_rule_fix, localdict
        )

    def _compute_rule_percentage(self, localdict):
        return self._erp_call_unwrapping_business_errors(
            super()._compute_rule_percentage, localdict
        )

    def _compute_rule_code(self, localdict):
        return self._erp_call_unwrapping_business_errors(
            super()._compute_rule_code, localdict
        )

    def _satisfy_condition_range(self, localdict):
        return self._erp_call_unwrapping_business_errors(
            super()._satisfy_condition_range, localdict
        )

    def _satisfy_condition_python(self, localdict):
        return self._erp_call_unwrapping_business_errors(
            super()._satisfy_condition_python, localdict
        )
