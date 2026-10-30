"""Vistas, acción y menú de establecimientos (US-007, DEV-4)."""

from lxml import etree

from odoo.tests import Form, TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestEstablishmentViews(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = new_test_user(
            cls.env,
            login="erp_est_view_admin",
            groups="base.group_user,base.group_system",
        )
        cls.internal = new_test_user(
            cls.env, login="erp_est_view_internal", groups="base.group_user"
        )
        cls.state_ec = cls.env["res.country.state"].search(
            [("country_id.code", "=", "EC")], limit=1
        )

    def _get_views(self, user):
        return (
            self.env["erp.establishment"]
            .with_user(user)
            .get_views([(False, "list"), (False, "form"), (False, "search")])
        )

    def test_views_load_for_admin_and_internal_user(self):
        for user in (self.admin, self.internal):
            with self.subTest(user=user.login):
                views = self._get_views(user)["views"]
                list_arch = etree.fromstring(views["list"]["arch"])
                list_fields = [f.get("name") for f in list_arch.iter("field")]
                for name in (
                    "code",
                    "name",
                    "city",
                    "state_id",
                    "region",
                    "decimo_cuarto_regime",
                    "active",
                ):
                    self.assertIn(name, list_fields)
                self.assertIsNone(list_arch.get("editable"))
                form_arch = etree.fromstring(views["form"]["arch"])
                state = form_arch.xpath("//field[@name='state_id']")[0]
                self.assertIn("'EC'", state.get("domain"))
                regime = form_arch.xpath("//field[@name='decimo_cuarto_regime']")[0]
                self.assertIn(regime.get("readonly"), ("1", "True"))
                self.assertTrue(form_arch.xpath("//widget[@name='web_ribbon']"))
                search_arch = etree.fromstring(views["search"]["arch"])
                filters = {f.get("name") for f in search_arch.iter("filter")}
                self.assertLessEqual(
                    {
                        "region_costa",
                        "region_sierra",
                        "region_amazonia",
                        "region_galapagos",
                        "regime_costa_galapagos",
                        "regime_sierra_amazonia",
                        "inactive",
                        "group_region",
                        "group_state",
                    },
                    filters,
                )

    def test_action_and_menu(self):
        action = self.env.ref("erp_establishment.erp_establishment_action")
        self.assertEqual(action.res_model, "erp.establishment")
        self.assertIn("Importar registros", action.help)
        # US-017 (CA-8): la importación está en el engranaje de la vista,
        # no en un «menú de acciones».
        self.assertIn("engranaje", action.help)
        self.assertNotIn("menú de", action.help)
        menu = self.env.ref("erp_establishment.erp_establishment_menu_settings")
        self.assertEqual(menu.parent_id, self.env.ref("base.menu_users"))
        self.assertEqual(menu.groups_id, self.env.ref("base.group_system"))
        visible = self.env["ir.ui.menu"].with_user(self.internal)._visible_menu_ids()
        self.assertNotIn(menu.id, visible)
        visible = self.env["ir.ui.menu"].with_user(self.admin)._visible_menu_ids()
        self.assertIn(menu.id, visible)

    def test_form_create_establishment(self):
        form = Form(self.env["erp.establishment"].with_user(self.admin))
        form.code = "7"
        form.name = "Agencia Machala"
        form.city = "Machala"
        form.state_id = self.state_ec
        form.region = "costa"
        self.assertEqual(form.decimo_cuarto_regime, "costa_galapagos")
        form.region = "sierra"
        self.assertEqual(form.decimo_cuarto_regime, "sierra_amazonia")
        establishment = form.save()
        self.assertEqual(establishment.code, "007")
        self.assertEqual(establishment.display_name, "007 - Agencia Machala")
        self.assertTrue(establishment.active)
        with self.assertRaises(AssertionError):
            # Campo de solo lectura en el formulario.
            form.decimo_cuarto_regime = "costa_galapagos"

    def test_form_title_and_short_filters(self):
        """US-017 (CA-8): título con el nombre y filtros con etiquetas cortas
        (el desplegable de filtros las trunca)."""
        views = self.env["erp.establishment"].get_views(
            [(False, "form"), (False, "search")]
        )["views"]
        form = etree.fromstring(views["form"]["arch"])
        self.assertTrue(
            form.xpath("//div[contains(@class, 'oe_title')]/h1/field[@name='name']")
        )
        search = etree.fromstring(views["search"]["arch"])
        for node in search.iter("filter"):
            with self.subTest(filter=node.get("name")):
                self.assertLessEqual(len(node.get("string")), 26)
