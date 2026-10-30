import logging

from odoo.tools import SQL

from .models.hr_payslip import PAYSLIP_UNIQUE_PERIOD_INDEX

_logger = logging.getLogger(__name__)

# ACL de OCA que este módulo deja en solo lectura para el usuario de nómina
# (security/erp_payroll_ec_security.xml); al desinstalar vuelven a CRUD.
OCA_PAYSLIP_LINE_ACCESS = "payroll.access_hr_payslip_line"
OCA_READ_ONLY_ACCESSES = (
    OCA_PAYSLIP_LINE_ACCESS,
    "payroll.access_hr_payroll_structure",
    "payroll.access_hr_salary_rule_category",
)


def post_init_hook(env):
    """Asigna las cuentas por defecto del plan ``ec`` a las reglas del rol en
    las empresas que ya tienen el plan cargado.

    En una instalación nueva, ``erp_base`` carga el plan después de los
    ``post_init_hook``; ese caso lo cubre ``account.chart.template._post_load_data``.
    """
    count = env["hr.salary.rule"]._erp_set_default_accounts()
    _logger.info("erp_payroll_ec: %s cuentas por defecto asignadas a reglas.", count)


def uninstall_hook(env):
    """Deshace los cambios hechos fuera de los registros propios del módulo:
    el índice único parcial de ``hr_payslip`` y las ACL de OCA de las líneas
    del rol, las estructuras y las categorías de reglas (vuelven a su valor
    original: CRUD para el usuario de nómina)."""
    env.cr.execute(
        SQL("DROP INDEX IF EXISTS %s", SQL.identifier(PAYSLIP_UNIQUE_PERIOD_INDEX))
    )
    for xmlid in OCA_READ_ONLY_ACCESSES:
        access = env.ref(xmlid, raise_if_not_found=False)
        if access:
            access.write({"perm_write": True, "perm_create": True, "perm_unlink": True})
