"""Modelo, restricciones de BD y permisos de erp.establishment (US-007, CA-1/CA-2).

Las restricciones de BD se prueban con SQL parametrizado para que los tests
sigan siendo válidos cuando la capa de negocio añada normalización y
validaciones previas (que convierten estos casos en ValidationError antes de
llegar a la BD).
"""

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestErpEstablishmentModel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Establishment = cls.env["erp.establishment"]
        cls.pichincha = cls.env.ref("base.state_ec_17")
        cls.est_001 = cls.Establishment.create(
            {
                "code": "001",
                "name": "Matriz Quito – Peñaherrera",
                "street": "Av. Amazonas N00-00 y Calle Ñuñoa",
                "city": "Quito",
                "state_id": cls.pichincha.id,
                "region": "sierra",
            }
        )
        cls.est_002 = cls.Establishment.create(
            {"code": "002", "name": "Agencia Puerto Ayora", "region": "galapagos"}
        )

    def _sql_set_code(self, record, code):
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE erp_establishment SET code = %s WHERE id = %s",
            (code, record.id),
        )

    def test_defaults(self):
        self.assertTrue(self.est_001.active)
        self.assertEqual(self.est_001.company_id, self.env.company)

    def test_decimo_cuarto_regime_from_region(self):
        expected = {
            "costa": "costa_galapagos",
            "galapagos": "costa_galapagos",
            "sierra": "sierra_amazonia",
            "amazonia": "sierra_amazonia",
        }
        for region, regime in expected.items():
            self.est_001.region = region
            self.assertEqual(self.est_001.decimo_cuarto_regime, regime, region)
        # Almacenado: se puede buscar por él.
        self.est_001.region = "amazonia"
        self.assertIn(
            self.est_001,
            self.Establishment.search(
                [("decimo_cuarto_regime", "=", "sierra_amazonia")]
            ),
        )

    def test_unique_code_per_company_db(self):
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._sql_set_code(self.est_002, "001")

    def test_unique_code_includes_archived_db(self):
        self.est_001.active = False
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._sql_set_code(self.est_002, "001")

    def test_same_code_other_company(self):
        other_company = self.env["res.company"].create({"name": "Empresa Ñandú S.A."})
        other = self.Establishment.create(
            {
                "code": "001",
                "name": "Matriz otra",
                "region": "costa",
                "company_id": other_company.id,
            }
        )
        self.assertEqual(other.code, "001")

    def test_code_format_check_db(self):
        for code in ("000", "1234", "A01", "1", "01", " 01"):
            with self.subTest(code=code):
                with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
                    self._sql_set_code(self.est_002, code)

    def test_valid_codes_db(self):
        for code in ("999", "010", "100"):
            self._sql_set_code(self.est_002, code)

    def test_archive_keeps_record(self):
        self.est_002.active = False
        self.assertTrue(
            self.Establishment.with_context(active_test=False).search(
                [("id", "=", self.est_002.id)]
            )
        )

    def test_state_restrict_on_delete(self):
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.pichincha.unlink()
            self.env.flush_all()

    def test_access_internal_user_read_only(self):
        user = new_test_user(
            self.env, login="erp_est_interno", groups="base.group_user"
        )
        Est = self.Establishment.with_user(user)
        self.assertEqual(Est.browse(self.est_001.id).name, self.est_001.name)
        with self.assertRaises(AccessError):
            Est.browse(self.est_001.id).write({"name": "Cambio no permitido"})
        with self.assertRaises(AccessError):
            Est.create({"code": "050", "name": "No permitido", "region": "costa"})
        with self.assertRaises(AccessError):
            Est.browse(self.est_001.id).unlink()

    def test_access_system_user_crud(self):
        user = new_test_user(
            self.env, login="erp_est_admin", groups="base.group_user,base.group_system"
        )
        Est = self.Establishment.with_user(user)
        record = Est.create(
            {"code": "051", "name": "Agencia Cañar", "region": "sierra"}
        )
        record.write({"name": "Agencia Azogues"})
        record.unlink()

    def test_multicompany_rule(self):
        other_company = self.env["res.company"].create({"name": "Otra Empresa S.A."})
        other = self.Establishment.create(
            {
                "code": "001",
                "name": "Otra",
                "region": "costa",
                "company_id": other_company.id,
            }
        )
        user = new_test_user(self.env, login="erp_est_mc", groups="base.group_user")
        self.assertEqual(user.company_ids, self.env.company)
        found = self.Establishment.with_user(user).search([])
        self.assertIn(self.est_001, found)
        self.assertNotIn(other, found)

    def test_import_boolean_values_es(self):
        """Valores Sí/No de la columna Activo de la plantilla (idioma es_EC)."""
        converter = self.env["ir.fields.converter"]
        field = self.Establishment._fields["active"]
        for value, expected in (
            ("Sí", True),
            ("sí", True),
            ("No", False),
            ("1", True),
            ("0", False),
        ):
            with self.subTest(value=value):
                result, warnings = converter._str_to_boolean(
                    self.Establishment, field, value
                )
                self.assertEqual(result, expected)
                self.assertFalse(warnings)
