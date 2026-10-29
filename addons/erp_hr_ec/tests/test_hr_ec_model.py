"""Modelos, restricciones de BD, datos y permisos de erp_hr_ec (US-007).

Las restricciones únicas se prueban con SQL parametrizado (UPDATE sobre
registros válidos) para que los tests sigan siendo válidos cuando la capa de
negocio añada validaciones previas con ValidationError.
"""

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import SQL, mute_logger


@tagged("post_install", "-at_install")
class TestHrEcModel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Establishment = cls.env["erp.establishment"]
        cls.est_costa = Establishment.create(
            {"code": "101", "name": "Agencia Manta", "region": "costa"}
        )
        cls.est_sierra = Establishment.create(
            {"code": "102", "name": "Agencia Cuenca – Ñamarín", "region": "sierra"}
        )
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "José Peñafiel Íñiguez",
                "erp_establishment_id": cls.est_costa.id,
            }
        )
        cls.employee_2 = cls.env["hr.employee"].create({"name": "María Añazco"})
        cls.field_text = cls.env["erp.hr.extra.field"].create(
            {"name": "Talla de camiseta", "value_type": "char"}
        )
        cls.field_list = cls.env["erp.hr.extra.field"].create(
            {
                "name": "Tipo de sangre",
                "value_type": "selection",
                "option_ids": [
                    (0, 0, {"name": "O+", "sequence": 1}),
                    (0, 0, {"name": "A+", "sequence": 2}),
                ],
            }
        )

    def _sql_update(self, table, column, value, record_id):
        """UPDATE parametrizado de una columna (identificadores escapados)."""
        self.env.flush_all()
        self.env.cr.execute(
            SQL(
                "UPDATE %s SET %s = %s WHERE id = %s",
                SQL.identifier(table),
                SQL.identifier(column),
                value,
                record_id,
            )
        )

    # ------------------------------------------------------------------
    # Empleado: establecimiento y campos heredados
    # ------------------------------------------------------------------
    def test_region_related_from_establishment(self):
        self.assertEqual(self.employee.erp_region, "costa")
        self.assertEqual(self.employee.erp_decimo_cuarto_regime, "costa_galapagos")
        self.employee.erp_establishment_id = self.est_sierra
        self.assertEqual(self.employee.erp_region, "sierra")
        self.assertEqual(self.employee.erp_decimo_cuarto_regime, "sierra_amazonia")
        # Cambiar la región del establecimiento se propaga (related almacenado).
        self.est_sierra.region = "amazonia"
        self.assertEqual(self.employee.erp_region, "amazonia")
        self.assertIn(
            self.employee,
            self.env["hr.employee"].search([("erp_region", "=", "amazonia")]),
        )

    def test_establishment_restrict_on_delete(self):
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.est_costa.unlink()
            self.env.flush_all()

    def test_disability_percentage_check_db(self):
        for value in (-1, 100.5):
            with self.subTest(value=value):
                with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
                    self._sql_update(
                        "hr_employee",
                        "erp_disability_percentage",
                        value,
                        self.employee.id,
                    )
        self._sql_update(
            "hr_employee", "erp_disability_percentage", 100, self.employee.id
        )

    def test_dependents_cascade(self):
        dependent = self.env["erp.hr.dependent"].create(
            {
                "employee_id": self.employee_2.id,
                "name": "Sofía Añazco",
                "relationship": "child",
                "birthdate": "2015-03-01",
            }
        )
        self.assertEqual(dependent.company_id, self.employee_2.company_id)
        self.employee_2.unlink()
        self.assertFalse(dependent.exists())

    def test_public_employee_unaffected(self):
        """Un usuario sin RRHH sigue leyendo el directorio (hr.employee.public)."""
        user = new_test_user(self.env, login="erp_hr_publico", groups="base.group_user")
        public = self.env["hr.employee.public"].with_user(user).browse(self.employee.id)
        self.assertEqual(public.name, self.employee.name)
        self.assertNotIn("erp_establishment_id", public._fields)
        with self.assertRaises(AccessError):
            self.employee.with_user(user).read(["erp_disability"])

    # ------------------------------------------------------------------
    # Elecciones de modalidad de beneficio
    # ------------------------------------------------------------------
    def test_benefit_election_unique_db(self):
        Election = self.env["erp.hr.benefit.election"]
        Election.create(
            {
                "employee_id": self.employee.id,
                "benefit": "reserve_fund",
                "mode": "accumulated",
                "date_from": "2026-01-01",
            }
        )
        second = Election.create(
            {
                "employee_id": self.employee.id,
                "benefit": "reserve_fund",
                "mode": "monthly",
                "date_from": "2026-07-01",
            }
        )
        # Mismo beneficio y fecha en otro empleado: permitido.
        Election.create(
            {
                "employee_id": self.employee_2.id,
                "benefit": "reserve_fund",
                "mode": "monthly",
                "date_from": "2026-01-01",
            }
        )
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._sql_update(
                "erp_hr_benefit_election", "date_from", "2026-01-01", second.id
            )

    def test_benefit_election_order(self):
        Election = self.env["erp.hr.benefit.election"]
        for date_from in ("2026-01-01", "2026-07-01", "2025-01-01"):
            Election.create(
                {
                    "employee_id": self.employee.id,
                    "benefit": "thirteenth",
                    "mode": "monthly",
                    "date_from": date_from,
                }
            )
        dates = [
            str(d) for d in self.employee.erp_benefit_election_ids.mapped("date_from")
        ]
        self.assertEqual(dates, ["2026-07-01", "2026-01-01", "2025-01-01"])

    # ------------------------------------------------------------------
    # Datos adicionales
    # ------------------------------------------------------------------
    def test_extra_value_unique_db(self):
        Value = self.env["erp.hr.extra.value"]
        Value.create(
            {
                "employee_id": self.employee.id,
                "field_id": self.field_text.id,
                "value_char": "M",
            }
        )
        other = Value.create(
            {
                "employee_id": self.employee.id,
                "field_id": self.field_list.id,
                "option_id": self.field_list.option_ids[0].id,
            }
        )
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._sql_update(
                "erp_hr_extra_value", "field_id", self.field_text.id, other.id
            )

    def test_extra_field_name_unique_db(self):
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._sql_update(
                "erp_hr_extra_field", "name", "Tipo de sangre", self.field_text.id
            )

    def test_extra_field_restrict_with_values(self):
        self.env["erp.hr.extra.value"].create(
            {
                "employee_id": self.employee.id,
                "field_id": self.field_text.id,
                "value_char": "L",
            }
        )
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.field_text.unlink()
            self.env.flush_all()

    def test_archived_extra_field_keeps_values(self):
        Value = self.env["erp.hr.extra.value"]
        value_text = Value.create(
            {
                "employee_id": self.employee.id,
                "field_id": self.field_text.id,
                "value_char": "S",
            }
        )
        value_list = Value.create(
            {
                "employee_id": self.employee.id,
                "field_id": self.field_list.id,
                "option_id": self.field_list.option_ids[1].id,
            }
        )
        self.field_text.active = False
        self.assertFalse(value_text.field_active)
        self.employee.invalidate_recordset(["erp_extra_value_ids"])
        self.assertEqual(self.employee.erp_extra_value_ids, value_list)
        # Guardar el One2many (como el formulario) no borra el valor archivado.
        self.employee.write({"erp_extra_value_ids": [(6, 0, value_list.ids)]})
        self.assertTrue(value_text.exists())
        self.field_text.active = True
        self.employee.invalidate_recordset(["erp_extra_value_ids"])
        self.assertEqual(self.employee.erp_extra_value_ids, value_text | value_list)

    def test_option_restrict_with_values(self):
        option = self.field_list.option_ids[0]
        self.env["erp.hr.extra.value"].create(
            {
                "employee_id": self.employee.id,
                "field_id": self.field_list.id,
                "option_id": option.id,
            }
        )
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            option.unlink()
            self.env.flush_all()

    # ------------------------------------------------------------------
    # Tipos de contrato y ajustes de empresa
    # ------------------------------------------------------------------
    def test_contract_types_loaded_noupdate(self):
        expected = {
            "contract_type_ec_indefinido": ("Indefinido", True),
            "contract_type_ec_eventual": ("Eventual", True),
            "contract_type_ec_bajo_factura": ("Bajo factura", False),
            "contract_type_ec_pasantia": ("Pasantía", False),
            "contract_type_ec_tiempo_parcial": ("Tiempo parcial", True),
        }
        ecuador = self.env.ref("base.ec")
        for xmlid, (name, labor) in expected.items():
            with self.subTest(xmlid=xmlid):
                record = self.env.ref(f"erp_hr_ec.{xmlid}")
                self.assertEqual(record.with_context(lang="es_EC").name, name)
                self.assertEqual(record.country_id, ecuador)
                self.assertEqual(record.erp_labor_relationship, labor)
                imd = self.env["ir.model.data"].search(
                    [("module", "=", "erp_hr_ec"), ("name", "=", xmlid)]
                )
                self.assertTrue(imd.noupdate)

    def test_contract_type_default_labor_relationship(self):
        contract_type = self.env["hr.contract.type"].create({"name": "Por obra"})
        self.assertTrue(contract_type.erp_labor_relationship)

    def test_company_defaults(self):
        company = self.env["res.company"].create({"name": "Empresa Nueva Ñ S.A."})
        self.assertEqual(company.erp_default_reserve_fund_mode, "monthly")
        self.assertEqual(company.erp_default_thirteenth_mode, "accumulated")
        self.assertEqual(company.erp_default_fourteenth_mode, "accumulated")
        self.assertEqual(company.erp_max_weekly_hours, 40.0)
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._sql_update("res_company", "erp_max_weekly_hours", 0, company.id)

    def test_config_settings_related(self):
        settings = self.env["res.config.settings"].create(
            {"erp_max_weekly_hours": 44.0, "erp_default_thirteenth_mode": "monthly"}
        )
        settings.execute()
        self.assertEqual(self.company.erp_max_weekly_hours, 44.0)
        self.assertEqual(self.company.erp_default_thirteenth_mode, "monthly")

    # ------------------------------------------------------------------
    # Permisos
    # ------------------------------------------------------------------
    def test_access_hr_user(self):
        user = new_test_user(
            self.env, login="erp_hr_usuario", groups="base.group_user,hr.group_hr_user"
        )
        employee = self.employee.with_user(user)
        employee.write(
            {
                "erp_disability": True,
                "erp_disability_percentage": 40.0,
                "erp_dependent_ids": [
                    (0, 0, {"name": "Lucía Peñafiel", "relationship": "child"})
                ],
                "erp_benefit_election_ids": [
                    (
                        0,
                        0,
                        {
                            "benefit": "fourteenth",
                            "mode": "monthly",
                            "date_from": "2026-01-01",
                        },
                    )
                ],
                "erp_extra_value_ids": [
                    (0, 0, {"field_id": self.field_text.id, "value_char": "XL"})
                ],
            }
        )
        self.assertEqual(len(employee.erp_dependent_ids), 1)
        # Lee el catálogo de datos adicionales pero no lo modifica.
        Field = self.env["erp.hr.extra.field"].with_user(user)
        self.assertTrue(Field.search([("id", "=", self.field_text.id)]))
        with self.assertRaises(AccessError):
            Field.create({"name": "No permitido", "value_type": "char"})
        with self.assertRaises(AccessError):
            Field.browse(self.field_text.id).write({"name": "Cambio"})
        with self.assertRaises(AccessError):
            self.env["erp.hr.extra.field.option"].with_user(user).create(
                {"field_id": self.field_list.id, "name": "B+"}
            )

    def test_access_hr_manager(self):
        user = new_test_user(
            self.env,
            login="erp_hr_responsable",
            groups="base.group_user,hr.group_hr_manager",
        )
        field = (
            self.env["erp.hr.extra.field"]
            .with_user(user)
            .create(
                {
                    "name": "Fecha de examen médico",
                    "value_type": "date",
                }
            )
        )
        field.write({"active": False})

    def test_access_internal_user_without_hr(self):
        user = new_test_user(
            self.env, login="erp_hr_sin_grupo", groups="base.group_user"
        )
        for model in (
            "erp.hr.dependent",
            "erp.hr.benefit.election",
            "erp.hr.extra.value",
            "erp.hr.extra.field",
        ):
            with self.subTest(model=model):
                with self.assertRaises(AccessError):
                    self.env[model].with_user(user).search([])

    def test_multicompany_rule_extra_field(self):
        other_company = self.env["res.company"].create({"name": "Otra RRHH S.A."})
        other_field = self.env["erp.hr.extra.field"].create(
            {"name": "Talla de camiseta", "company_id": other_company.id}
        )
        user = new_test_user(
            self.env, login="erp_hr_mc", groups="base.group_user,hr.group_hr_user"
        )
        found = self.env["erp.hr.extra.field"].with_user(user).search([])
        self.assertIn(self.field_text, found)
        self.assertNotIn(other_field, found)
