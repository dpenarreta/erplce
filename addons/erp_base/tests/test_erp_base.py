import inspect
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.erp_base import hooks


@tagged("post_install", "-at_install")
class TestErpBaseInstalled(TransactionCase):
    """Estado de la base tras instalar erp_base (CA-5)."""

    def test_language_es_ec_active_and_default(self):
        lang = (
            self.env["res.lang"]
            .with_context(active_test=False)
            .search([("code", "=", "es_EC")])
        )
        self.assertTrue(lang.active)
        self.assertEqual(self.env["ir.default"]._get("res.partner", "lang"), "es_EC")

    def test_admin_preferences(self):
        admin = self.env.ref("base.user_admin")
        self.assertEqual(admin.lang, "es_EC")
        self.assertEqual(admin.tz, "America/Guayaquil")

    def test_localization_installed(self):
        modules = self.env["ir.module.module"].search(
            [("name", "in", ("account", "l10n_ec"))]
        )
        self.assertEqual(len(modules), 2)
        self.assertEqual(set(modules.mapped("state")), {"installed"})

    def test_main_company(self):
        if self.env.ref("base.module_base").demo:
            self.skipTest(
                "BD con datos de demostración: la empresa principal llega con "
                "apuntes del plan genérico antes de instalar erp_base y, por "
                "diseño, no se modifica (ver test_company_with_accounting_untouched)."
            )
        company = self.env.ref("base.main_company")
        self.assertEqual(company.country_id, self.env.ref("base.ec"))
        self.assertEqual(company.currency_id, self.env.ref("base.USD"))
        self.assertEqual(company.chart_template, "ec")
        self.assertGreater(
            self.env["account.account"].search_count(
                [("company_ids", "in", company.id)]
            ),
            100,
        )


@tagged("post_install", "-at_install")
class TestErpBaseSetup(TransactionCase):
    """Reglas de las funciones del hook: no destructivas e idempotentes (CA-6)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ecuador = cls.env.ref("base.ec")
        cls.usd = cls.env.ref("base.USD")
        cls.eur = cls.env.ref("base.EUR")
        cls.eur.active = True
        # Idioma alternativo elegido por un usuario (sin cargar traducciones).
        cls.env["res.lang"]._activate_lang("es_419")

    def _new_company(self, name):
        return self.env["res.company"].create(
            {
                "name": name,
                "country_id": self.env.ref("base.us").id,
                "currency_id": self.eur.id,
            }
        )

    def _patch_try_loading(self):
        return patch.object(
            self.registry["account.chart.template"], "try_loading", autospec=True
        )

    def test_factory_preferences_are_updated_once(self):
        partner = self.env["res.partner"].create(
            {"name": "Año Nuevo Peñaherrera", "lang": "en_US", "tz": "Europe/Brussels"}
        )
        vals = hooks._setup_partner_preferences(partner)
        self.assertEqual(vals, {"lang": "es_EC", "tz": "America/Guayaquil"})
        self.assertEqual(partner.lang, "es_EC")
        self.assertEqual(partner.tz, "America/Guayaquil")
        # Segunda ejecución: nada que cambiar.
        self.assertEqual(hooks._setup_partner_preferences(partner), {})

    def test_empty_tz_is_factory_value(self):
        partner = self.env["res.partner"].create(
            {"name": "José Ñúñez", "lang": "en_US", "tz": False}
        )
        hooks._setup_partner_preferences(partner)
        self.assertEqual(partner.tz, "America/Guayaquil")

    def test_changed_user_preferences_not_overwritten(self):
        admin = self.env.ref("base.user_admin")
        admin.write({"lang": "es_419", "tz": "America/Bogota"})
        with self._patch_try_loading():
            hooks._setup_ecuador(self.env)
            hooks._setup_ecuador(self.env)
        self.assertEqual(admin.lang, "es_419")
        self.assertEqual(admin.tz, "America/Bogota")

    def test_changed_partner_default_lang_not_overwritten(self):
        IrDefault = self.env["ir.default"]
        IrDefault.set("res.partner", "lang", "es_419")
        hooks._setup_language(self.env)
        self.assertEqual(IrDefault._get("res.partner", "lang"), "es_419")

    def test_language_setup_idempotent(self):
        lang = hooks._setup_language(self.env)
        self.assertEqual(hooks._setup_language(self.env), lang)
        self.assertTrue(lang.active)
        self.assertEqual(
            self.env["res.lang"]
            .with_context(active_test=False)
            .search_count([("code", "=", "es_EC")]),
            1,
        )
        self.assertEqual(self.env["ir.default"]._get("res.partner", "lang"), "es_EC")

    def test_company_with_accounting_untouched(self):
        company = self._new_company("Empresa con Contabilidad Cía. Ltda.")
        with (
            patch.object(
                self.registry["res.company"], "_existing_accounting", return_value=True
            ),
            self._patch_try_loading() as try_loading,
            self.assertLogs("odoo.addons.erp_base.hooks", level="WARNING"),
        ):
            result = hooks._setup_company(company)
        self.assertEqual(result, "skipped")
        try_loading.assert_not_called()
        self.assertEqual(company.country_id, self.env.ref("base.us"))
        self.assertEqual(company.currency_id, self.eur)
        self.assertFalse(company.chart_template)

    def _set_pending(self, func):
        """Simula la carga de plan pendiente que deja IrModule.write."""
        registry = self.env.registry
        self.assertFalse(hasattr(registry, "_auto_install_template"))

        def _cleanup():
            if hasattr(registry, "_auto_install_template"):
                del registry._auto_install_template

        registry._auto_install_template = func
        self.addCleanup(_cleanup)
        return registry

    def test_pending_template_same_company_is_replaced(self):
        company = self._new_company("Empresa Diferida S.A.")
        # La carga pendiente del núcleo actúa sobre env.company: aquí coincide.
        company = company.with_context(allowed_company_ids=[company.id])
        self.assertEqual(company.env.company, company)
        original = MagicMock()
        registry = self._set_pending(original)
        with self._patch_try_loading() as try_loading:
            self.assertEqual(hooks._setup_company(company), "deferred")
            try_loading.assert_not_called()
            self.assertEqual(company.country_id, self.ecuador)
            self.assertEqual(company.currency_id, self.usd)
            # Lo que hace IrModule._register_hook al terminar la carga.
            registry._auto_install_template(self.env)
            original.assert_not_called()
            try_loading.assert_called_once()
            self.assertEqual(try_loading.call_args.args[1:], ("ec", company))

    def test_pending_template_other_company_is_chained(self):
        company = self._new_company("Empresa Encadenada S.A.")
        self.assertNotEqual(self.env.company, company)
        calls = []
        registry = self._set_pending(lambda env: calls.append("original"))
        with (
            self._patch_try_loading() as try_loading,
            self.assertLogs("odoo.addons.erp_base.hooks", level="WARNING"),
        ):
            try_loading.side_effect = lambda *args, **kw: calls.append("ec")
            self.assertEqual(hooks._setup_company(company), "deferred")
            registry._auto_install_template(self.env)
        # Primero la carga original (otra empresa) y después la de 'ec'.
        self.assertEqual(calls, ["original", "ec"])
        self.assertEqual(try_loading.call_args.args[1:], ("ec", company))

    def test_core_pending_template_api(self):
        """Vigila la API privada del núcleo de la que depende el hook.

        Si una actualización de la imagen de Odoo la cambia, este test falla y
        hay que revisar ``hooks._setup_company`` (si no, el plan genérico
        podría pisar el de Ecuador en instalaciones nuevas).
        """
        from odoo.addons.account.models.ir_module import IrModule

        # Productor: IrModule.write deja la carga pendiente en el registro.
        self.assertIn(
            "registry._auto_install_template", inspect.getsource(IrModule.write)
        )
        # Consumidor (comprobado por comportamiento): el _register_hook de
        # account la ejecuta con un env y la elimina del registro. Se llama solo
        # a la implementación de account (no a toda la cadena de herencia) y
        # con el super() neutralizado, para que efectos de otros módulos en su
        # _register_hook no influyan en este test.
        records = self.env["ir.module.module"]
        mro = type(records).__mro__
        self.assertIn(IrModule, mro)
        next_class = mro[mro.index(IrModule) + 1]
        self.assertFalse(hasattr(self.env.registry, "_delayed_account_translator"))
        pending = MagicMock()
        registry = self._set_pending(pending)
        with patch.object(next_class, "_register_hook") as super_hook:
            IrModule._register_hook(records)
        super_hook.assert_called_once()
        pending.assert_called_once()
        self.assertEqual(pending.call_args.args[0], records.env)
        self.assertFalse(hasattr(registry, "_auto_install_template"))

    def test_new_company_loads_ec_chart_idempotent(self):
        company = self._new_company("Compañía Ecuatoriana de Pruebas S.A.")
        self.assertFalse(hasattr(self.env.registry, "_auto_install_template"))
        self.assertEqual(hooks._setup_company(company), "loaded")
        self.assertEqual(company.chart_template, "ec")
        self.assertEqual(company.country_id, self.ecuador)
        self.assertEqual(company.currency_id, self.usd)
        account_domain = [("company_ids", "in", company.id)]
        journal_domain = [("company_id", "=", company.id)]
        Account = self.env["account.account"].with_company(company)
        Journal = self.env["account.journal"]
        accounts = Account.search_count(account_domain)
        journals = Journal.search_count(journal_domain)
        self.assertGreater(accounts, 100)
        # Segunda ejecución: no recarga ni duplica.
        with self._patch_try_loading() as try_loading:
            self.assertEqual(hooks._setup_company(company), "unchanged")
            try_loading.assert_not_called()
        self.assertEqual(Account.search_count(account_domain), accounts)
        self.assertEqual(Journal.search_count(journal_domain), journals)
