"""Configuración regional de Ecuador al instalar ``erp_base``.

Decisión del Tech Lead (US-001, CA-5/CA-6):

* El ERP es de una sola empresa ecuatoriana. Al instalar ``erp_base`` la
  empresa principal queda con país Ecuador, moneda USD y plan contable ``ec``
  de ``l10n_ec``, salvo que ya tenga apuntes contables: en ese caso no se toca
  ni el país ni el plan (solo se registra un aviso).
* Se activa el idioma ``es_EC`` con sus traducciones y pasa a ser el idioma por
  defecto de los contactos. El administrador recibe idioma ``es_EC`` y zona
  horaria ``America/Guayaquil`` SOLO si conserva los valores de fábrica.
* Todo es idempotente: cada función puede ejecutarse varias veces sin duplicar
  datos ni sobrescribir preferencias cambiadas por el usuario.
"""

import logging

_logger = logging.getLogger(__name__)

LANG_CODE = "es_EC"
TZ = "America/Guayaquil"
CHART_TEMPLATE = "ec"

# Valores con los que Odoo crea al administrador / la empresa. Cualquier otro
# valor se considera una preferencia elegida por el usuario y se respeta.
FACTORY_LANGS = (False, "", "en_US")
# "Europe/Brussels" es la zona que asignan los datos de Odoo (demo) al
# administrador; se mantiene como "de fábrica" a propósito: en un ERP de una
# empresa ecuatoriana nadie la elige deliberadamente y así también quedan bien
# configuradas las BD instaladas con demo (pruebas, formación).
FACTORY_TZS = (False, "", "UTC", "Etc/UTC", "Europe/Brussels")


def post_init_hook(env):
    """Punto de entrada declarado en ``__manifest__.py`` (solo en instalación)."""
    _setup_ecuador(env)


def _setup_ecuador(env):
    """Aplica toda la configuración de Ecuador. Seguro de ejecutar varias veces."""
    _setup_language(env)
    company = env.ref("base.main_company", raise_if_not_found=False)
    if company:
        _setup_company(company)
        _setup_partner_preferences(company.partner_id)
    admin = env.ref("base.user_admin", raise_if_not_found=False)
    if admin:
        _setup_partner_preferences(admin.partner_id)


def _setup_language(env):
    """Activa ``es_EC`` (cargando traducciones) y lo fija como idioma por
    defecto de los contactos si el valor por defecto sigue siendo el de fábrica.

    :return: registro ``res.lang`` de ``es_EC`` (vacío si no existe).
    """
    lang = env["res.lang"]._activate_and_install_lang(LANG_CODE)
    if not lang:
        _logger.warning("erp_base: el idioma %s no existe; no se activa.", LANG_CODE)
        return lang
    IrDefault = env["ir.default"]
    if IrDefault._get("res.partner", "lang") in (None,) + FACTORY_LANGS:
        IrDefault.set("res.partner", "lang", LANG_CODE)
    return lang


def _setup_partner_preferences(partner):
    """Pone idioma ``es_EC`` y zona ``America/Guayaquil`` en el contacto (y por
    tanto en su usuario, que los hereda) solo si conserva valores de fábrica."""
    vals = {}
    installed = dict(partner.env["res.lang"].get_installed())
    if partner.lang in FACTORY_LANGS and LANG_CODE in installed:
        vals["lang"] = LANG_CODE
    if partner.tz in FACTORY_TZS:
        vals["tz"] = TZ
    if vals:
        partner.write(vals)
    return vals


def _setup_company(company):
    """País Ecuador, moneda USD y plan contable ``ec`` en ``company``.

    No hace nada (salvo registrar un aviso) si la empresa ya tiene apuntes
    contables: cambiar país, moneda o plan con contabilidad existente
    corrompería los datos.

    :return: ``"skipped"`` (contabilidad existente), ``"deferred"`` (plan
        programado para el final de la carga del registro), ``"loaded"`` (plan
        cargado ahora) o ``"unchanged"`` (ya tenía el plan ``ec``).
    """
    env = company.env
    if company._existing_accounting():
        _logger.warning(
            "erp_base: la empresa %s (id %s) ya tiene apuntes contables; no se "
            "modifican su país, moneda ni plan contable.",
            company.name,
            company.id,
        )
        return "skipped"

    ecuador = env.ref("base.ec")
    usd = env.ref("base.USD")
    vals = {}
    if company.country_id != ecuador:
        vals["country_id"] = ecuador.id
    if company.currency_id != usd:
        if not usd.active:
            usd.active = True
        vals["currency_id"] = usd.id
    if vals:
        company.write(vals)

    # Al instalar ``account`` / ``l10n_*``, ``ir.module.module.write`` deja en
    # ``registry._auto_install_template`` una carga de plan pendiente (la del
    # país de la empresa o ``generic_coa``) que ``_register_hook`` ejecuta
    # DESPUÉS de los post_init_hook: si aquí cargáramos 'ec' directamente,
    # luego esa carga lo pisaría. Por eso, si existe, se sustituye por la de
    # 'ec'. Es un atributo privado del núcleo (Odoo 18): se accede de forma
    # defensiva con getattr y, si no existe, se carga el plan en el momento.
    # El test test_core_pending_template_api vigila que el núcleo lo mantenga.
    pending = getattr(env.registry, "_auto_install_template", None)
    if pending is None:
        return _load_chart(company)

    company_id = company.id
    # La carga pendiente del núcleo actúa sobre ``env.company`` (la empresa del
    # usuario que instala). Solo se descarta si es la misma empresa: si no, se
    # encadena (primero la original, luego 'ec' en ``company``) para no dejar a
    # la otra empresa sin plan; cada carga afecta a una empresa distinta, así
    # que no se pisan.
    same_company = env.company.id == company_id
    if not same_company:
        _logger.warning(
            "erp_base: la carga de plan pendiente del núcleo es para la empresa "
            "%s (id %s), no para %s (id %s); se ejecuta y después se carga el "
            "plan '%s' en esta última.",
            env.company.name,
            env.company.id,
            company.name,
            company_id,
            CHART_TEMPLATE,
        )

    def _load_ec_chart(env):
        if not same_company:
            pending(env)
        target = env["res.company"].browse(company_id)
        if target.exists():
            _load_chart(target)

    env.registry._auto_install_template = _load_ec_chart
    return "deferred"


def _load_chart(company):
    """Carga el plan ``ec`` si la empresa no lo tiene y no tiene apuntes."""
    if company.chart_template == CHART_TEMPLATE:
        return "unchanged"
    if company._existing_accounting():
        _logger.warning(
            "erp_base: la empresa %s (id %s) tiene apuntes contables; no se "
            "carga el plan '%s'.",
            company.name,
            company.id,
            CHART_TEMPLATE,
        )
        return "skipped"
    _logger.info(
        "erp_base: cargando el plan contable '%s' en la empresa %s (id %s).",
        CHART_TEMPLATE,
        company.name,
        company.id,
    )
    company.env["account.chart.template"].try_loading(CHART_TEMPLATE, company)
    return "loaded"
