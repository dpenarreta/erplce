"""Reglas de negocio de erp.establishment (US-007, CA-1/CA-2)."""

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.erp_establishment.models.erp_establishment import (
    normalize_establishment_code,
)


@tagged("post_install", "-at_install")
class TestErpEstablishmentBusiness(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Establishment = cls.env["erp.establishment"]
        cls.pichincha = cls.env.ref("base.state_ec_17")
        cls.est_001 = cls.Establishment.create(
            {
                "code": "1",
                "name": "Matriz Quito – Peñaherrera",
                "city": "Quito",
                "state_id": cls.pichincha.id,
                "region": "costa",
            }
        )

    # ------------------------------------------------------------------
    # Código
    # ------------------------------------------------------------------
    def test_create_normalizes_code_and_defaults(self):
        """CA-1: código 1 -> 001, régimen calculado, activo y empresa actual."""
        self.assertEqual(self.est_001.code, "001")
        self.assertEqual(self.est_001.decimo_cuarto_regime, "costa_galapagos")
        self.assertTrue(self.est_001.active)
        self.assertEqual(self.est_001.company_id, self.env.company)

    def test_normalize_function(self):
        for raw, expected in (
            ("1", "001"),
            (" 25 ", "025"),
            ("0 1", "001"),
            ("999", "999"),
            ("010", "010"),
            (7, "007"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_establishment_code(self.env, raw), expected)

    def test_invalid_codes_rejected(self):
        for raw in ("", "   ", "A01", "1a", "1234", "000", "0", "-1", "1.0", False):
            with self.subTest(raw=raw):
                with self.assertRaises(ValidationError) as ctx:
                    self.Establishment.create(
                        {"code": raw, "name": "Agencia Ñ", "region": "sierra"}
                    )
                if raw and str(raw).strip():
                    self.assertIn(str(raw), str(ctx.exception))

    def test_create_does_not_mutate_caller_vals(self):
        vals = {"code": "7", "name": "Agencia Ibarra", "region": "sierra"}
        record = self.Establishment.create([vals])
        self.assertEqual(record.code, "007")
        self.assertEqual(vals["code"], "7")

    def test_write_normalizes_code(self):
        est = self.Establishment.create(
            {"code": "50", "name": "Agencia Loja", "region": "sierra"}
        )
        self.assertEqual(est.code, "050")
        est.write({"code": " 51"})
        self.assertEqual(est.code, "051")
        with self.assertRaises(ValidationError):
            est.write({"code": "51A"})

    def test_duplicate_code_rejected_with_message(self):
        for raw in ("001", "1", "01"):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValidationError, "código 001"):
                    self.Establishment.create(
                        {"code": raw, "name": "Repetido", "region": "costa"}
                    )

    def test_duplicate_code_archived_rejected(self):
        self.est_001.active = False
        with self.assertRaisesRegex(ValidationError, "incluidos los archivados"):
            self.Establishment.create(
                {"code": "1", "name": "Repetido", "region": "costa"}
            )

    def test_duplicate_code_in_same_batch(self):
        with self.assertRaisesRegex(ValidationError, "código 007"):
            self.Establishment.create(
                [
                    {"code": "7", "name": "A", "region": "costa"},
                    {"code": "007", "name": "B", "region": "costa"},
                ]
            )

    def test_duplicate_code_on_write(self):
        est = self.Establishment.create(
            {"code": "2", "name": "Agencia Ambato", "region": "sierra"}
        )
        with self.assertRaisesRegex(ValidationError, "código 001"):
            est.write({"code": "1"})
        # Reescribir su propio código no es duplicado.
        est.write({"code": "002", "name": "Agencia Ambato Centro"})

    def test_same_code_other_company_allowed(self):
        other_company = self.env["res.company"].create({"name": "Empresa Ñandú S.A."})
        other = self.Establishment.create(
            {
                "code": "1",
                "name": "Matriz otra",
                "region": "costa",
                "company_id": other_company.id,
            }
        )
        self.assertEqual(other.code, "001")

    # ------------------------------------------------------------------
    # Nombre mostrado y búsqueda
    # ------------------------------------------------------------------
    def test_display_name(self):
        self.assertEqual(self.est_001.display_name, "001 - Matriz Quito – Peñaherrera")

    def test_search_by_code_or_name(self):
        est = self.Establishment.create(
            {"code": "120", "name": "Agencia Cañar", "region": "sierra"}
        )
        by_code = self.Establishment.name_search("120")
        self.assertIn(est.id, [rid for rid, _name in by_code])
        by_name = self.Establishment.name_search("Cañar")
        self.assertIn(est.id, [rid for rid, _name in by_name])
        self.assertIn(
            est, self.Establishment.search([("display_name", "ilike", "120")])
        )

    # ------------------------------------------------------------------
    # Provincia
    # ------------------------------------------------------------------
    def test_state_must_be_ecuador(self):
        bolivar_co = self.env["res.country.state"].search(
            [("country_id.code", "=", "CO"), ("name", "=", "Bolívar")], limit=1
        )
        self.assertTrue(bolivar_co)
        with self.assertRaisesRegex(ValidationError, "Bolívar"):
            self.Establishment.create(
                {
                    "code": "300",
                    "name": "Agencia Guaranda",
                    "region": "sierra",
                    "state_id": bolivar_co.id,
                }
            )
        with self.assertRaisesRegex(ValidationError, "no es de Ecuador"):
            self.est_001.state_id = bolivar_co
        self.est_001.state_id = self.env.ref("base.state_ec_02")  # Bolivar EC

    # ------------------------------------------------------------------
    # Archivado y permisos
    # ------------------------------------------------------------------
    def test_archive_and_restore(self):
        self.est_001.action_archive()
        self.assertFalse(self.est_001.active)
        self.est_001.action_unarchive()
        self.assertTrue(self.est_001.active)

    def test_internal_user_cannot_create(self):
        user = new_test_user(
            self.env, login="erp_est_negocio_interno", groups="base.group_user"
        )
        with self.assertRaises(AccessError):
            self.Establishment.with_user(user).create(
                {"code": "60", "name": "No permitido", "region": "costa"}
            )
        # Puede leer el catálogo con su nombre mostrado.
        self.assertEqual(
            self.Establishment.with_user(user).browse(self.est_001.id).display_name,
            "001 - Matriz Quito – Peñaherrera",
        )

    def test_get_import_templates(self):
        self.assertEqual(
            self.Establishment.get_import_templates(),
            [
                {
                    "label": "Plantilla de establecimientos",
                    "template": "/erp_establishment/static/csv/"
                    "plantilla_establecimientos.csv",
                }
            ],
        )
