"""Reglas de negocio de empleados, modalidades y datos adicionales (US-007,
CA-4 a CA-7)."""

from contextlib import contextmanager
from datetime import date

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import SQL, index_exists, mute_logger

from odoo.addons.erp_hr_ec.models.hr_employee import IDENTIFICATION_UNIQUE_INDEX

CEDULA_1 = "1710034065"
CEDULA_2 = "0923456784"
CEDULA_3 = "1304567892"


@tagged("post_install", "-at_install")
class TestHrEcBusiness(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.ecuador = cls.env.ref("base.ec")
        cls.colombia = cls.env.ref("base.co")
        Establishment = cls.env["erp.establishment"]
        cls.est_costa = Establishment.create(
            {"code": "201", "name": "Agencia Manta", "region": "costa"}
        )
        cls.est_sierra = Establishment.create(
            {"code": "202", "name": "Agencia Cuenca – Ñamarín", "region": "sierra"}
        )
        cls.Employee = cls.env["hr.employee"]
        cls.employee = cls.Employee.create(
            {
                "name": "José Peñafiel Íñiguez",
                "country_id": cls.ecuador.id,
                "identification_id": CEDULA_1,
                "erp_establishment_id": cls.est_costa.id,
            }
        )
        cls.field_text = cls.env["erp.hr.extra.field"].create(
            {"name": "Talla de camiseta", "value_type": "char"}
        )
        cls.field_int = cls.env["erp.hr.extra.field"].create(
            {"name": "Años en el sector", "value_type": "integer"}
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
        cls.field_list_2 = cls.env["erp.hr.extra.field"].create(
            {
                "name": "Turno preferido",
                "value_type": "selection",
                "option_ids": [(0, 0, {"name": "Mañana"})],
            }
        )

    @contextmanager
    def _raises(self, exception, text):
        """``assertRaises`` de Odoo (deshace en un savepoint lo escrito por la
        operación que falla, a diferencia de ``assertRaisesRegex``) y comprueba
        que el mensaje contiene ``text``."""
        with self.assertRaises(exception) as ctx:
            yield ctx
        self.assertIn(text, str(ctx.exception))

    # ------------------------------------------------------------------
    # Cédula
    # ------------------------------------------------------------------
    def test_valid_cedula_saved(self):
        employee = self.Employee.create(
            {
                "name": "María Añazco",
                "country_id": self.ecuador.id,
                "identification_id": CEDULA_2,
            }
        )
        self.assertEqual(employee.identification_id, CEDULA_2)

    def test_cedula_with_separators_normalized(self):
        employee = self.Employee.create(
            {
                "name": "Íñigo Muñoz",
                "country_id": self.ecuador.id,
                "identification_id": " 130456789-2 ",
            }
        )
        self.assertEqual(employee.identification_id, CEDULA_3)

    def test_invalid_cedula_rejected(self):
        for cedula in ("1710034066", "12345", "9910034065", "ABCDEFGHIJ"):
            with self.subTest(cedula=cedula):
                with self._raises(ValidationError, cedula):
                    self.Employee.create(
                        {
                            "name": "Ñusta Quispe",
                            "country_id": self.ecuador.id,
                            "identification_id": cedula,
                        }
                    )
        with self._raises(ValidationError, "no es válida"):
            self.employee.identification_id = "1710034066"

    def test_changing_nationality_to_ecuador_validates(self):
        employee = self.Employee.create(
            {
                "name": "Andrés Gómez",
                "country_id": self.colombia.id,
                "identification_id": "AB123456",
            }
        )
        with self.assertRaises(ValidationError):
            employee.country_id = self.ecuador

    def test_foreign_employee_with_passport(self):
        employee = self.Employee.create(
            {
                "name": "Andrés Gómez",
                "country_id": self.colombia.id,
                "identification_id": "AB123456",
                "passport_id": "AB123456",
            }
        )
        self.assertEqual(employee.identification_id, "AB123456")
        # Sin nacionalidad tampoco se valida el formato de cédula.
        self.Employee.create({"name": "Sin nacionalidad", "identification_id": "X-1"})

    def test_duplicate_cedula_same_company(self):
        with self.assertRaises(ValidationError) as ctx:
            self.Employee.create(
                {
                    "name": "Duplicado",
                    "country_id": self.ecuador.id,
                    "identification_id": "171003406-5",
                }
            )
        message = str(ctx.exception)
        self.assertIn("ya está registrada en otro empleado", message)
        # No revela quién es el otro empleado.
        self.assertNotIn(self.employee.name, message)

    def test_duplicate_cedula_in_batch(self):
        with self._raises(ValidationError, CEDULA_2):
            self.Employee.create(
                [
                    {"name": "A", "identification_id": CEDULA_2},
                    {"name": "B", "identification_id": CEDULA_2},
                ]
            )

    def test_duplicate_cedula_archived_or_other_company(self):
        self.employee.action_archive()
        other = self.Employee.create(
            {
                "name": "Reingreso",
                "country_id": self.ecuador.id,
                "identification_id": CEDULA_1,
            }
        )
        # Reactivar el archivado con la misma cédula: rechazado.
        with self._raises(ValidationError, "ya está registrada"):
            self.employee.action_unarchive()
        other.action_archive()
        other_company = self.env["res.company"].create({"name": "Otra Ñ S.A."})
        self.Employee.create(
            {
                "name": "Otra empresa",
                "identification_id": CEDULA_1,
                "company_id": other_company.id,
            }
        )
        self.employee.action_unarchive()
        self.assertTrue(self.employee.active)

    # ------------------------------------------------------------------
    # Discapacidad
    # ------------------------------------------------------------------
    def test_disability_valid(self):
        self.employee.write(
            {
                "erp_disability": True,
                "erp_disability_percentage": 45.5,
                "erp_disability_card": "MSP-0001",
            }
        )
        self.assertEqual(self.employee.erp_disability_percentage, 45.5)
        self.employee.erp_disability_percentage = 100
        self.assertEqual(self.employee.erp_disability_percentage, 100)

    def test_disability_without_percentage_rejected(self):
        with self._raises(ValidationError, "indique el porcentaje"):
            self.employee.write({"erp_disability": True})
        with self._raises(ValidationError, "indique el porcentaje"):
            self.Employee.create(
                {
                    "name": "Sin porcentaje",
                    "erp_disability": True,
                    "erp_disability_percentage": 0,
                }
            )

    def test_disability_out_of_range_rejected(self):
        for value in (-1, 100.5, 150):
            with self.subTest(value=value):
                with self._raises(ValidationError, "entre 0 y 100"):
                    self.Employee.create(
                        {
                            "name": "Fuera de rango",
                            "erp_disability": True,
                            "erp_disability_percentage": value,
                        }
                    )
                with self._raises(ValidationError, "entre 0 y 100"):
                    self.employee.write(
                        {"erp_disability": True, "erp_disability_percentage": value}
                    )

    def test_disability_unchecked_clears_percentage(self):
        self.employee.write({"erp_disability": True, "erp_disability_percentage": 40})
        self.employee.write({"erp_disability": False})
        self.assertEqual(self.employee.erp_disability_percentage, 0)
        employee = self.Employee.create(
            {
                "name": "Limpio",
                "erp_disability": False,
                "erp_disability_percentage": 30,
            }
        )
        self.assertEqual(employee.erp_disability_percentage, 0)

    def test_percentage_without_disability_rejected(self):
        with self._raises(ValidationError, "no tiene marcada"):
            self.employee.write({"erp_disability_percentage": 30})

    # ------------------------------------------------------------------
    # Establecimiento archivado
    # ------------------------------------------------------------------
    def test_archived_establishment_not_assignable(self):
        self.est_sierra.action_archive()
        with self._raises(ValidationError, "202 - Agencia Cuenca"):
            self.employee.erp_establishment_id = self.est_sierra
        with self._raises(ValidationError, "archivado"):
            self.Employee.create(
                {"name": "Nuevo", "erp_establishment_id": self.est_sierra.id}
            )

    def test_establishment_archived_later_does_not_block(self):
        self.est_costa.action_archive()
        self.employee.write(
            {"job_title": "Mensajero motorizado", "erp_disability": False}
        )
        self.assertEqual(self.employee.erp_establishment_id, self.est_costa)
        self.assertEqual(self.employee.erp_region, "costa")
        self.employee.erp_establishment_id = self.est_sierra
        self.assertEqual(self.employee.erp_decimo_cuarto_regime, "sierra_amazonia")

    # ------------------------------------------------------------------
    # Modalidad de beneficios (CA-6)
    # ------------------------------------------------------------------
    def _elect(self, benefit, mode, date_from, employee=None):
        return self.env["erp.hr.benefit.election"].create(
            {
                "employee_id": (employee or self.employee).id,
                "benefit": benefit,
                "mode": mode,
                "date_from": date_from,
            }
        )

    def test_benefit_mode_ca6(self):
        self.company.erp_default_reserve_fund_mode = "monthly"
        self._elect("reserve_fund", "accumulated", "2026-01-01")
        self._elect("reserve_fund", "monthly", "2026-07-01")
        mode = self.employee._get_benefit_mode
        self.assertEqual(mode("reserve_fund", date(2026, 3, 15)), "accumulated")
        self.assertEqual(mode("reserve_fund", "2026-08-01"), "monthly")
        self.assertEqual(mode("reserve_fund", "2026-07-01"), "monthly")
        self.assertEqual(mode("reserve_fund", "2026-06-30"), "accumulated")
        self.assertEqual(mode("reserve_fund", "2026-01-01"), "accumulated")
        # Antes de la primera elección: valor por defecto de la empresa.
        self.assertEqual(mode("reserve_fund", "2025-12-31"), "monthly")
        self.company.erp_default_reserve_fund_mode = "accumulated"
        self.assertEqual(mode("reserve_fund", "2025-12-31"), "accumulated")

    def test_benefit_mode_defaults_per_benefit(self):
        self.company.write(
            {
                "erp_default_thirteenth_mode": "accumulated",
                "erp_default_fourteenth_mode": "monthly",
            }
        )
        self._elect("thirteenth", "monthly", "2026-01-01")
        mode = self.employee._get_benefit_mode
        self.assertEqual(mode("thirteenth", "2026-02-01"), "monthly")
        # Una elección de otro beneficio no afecta.
        self.assertEqual(mode("fourteenth", "2026-02-01"), "monthly")
        self.assertEqual(mode("thirteenth", "2025-02-01"), "accumulated")

    def test_benefit_mode_other_employee_isolated(self):
        other = self.Employee.create({"name": "Otra Persona Ñ"})
        self._elect("fourteenth", "monthly", "2026-01-01", employee=other)
        self.company.erp_default_fourteenth_mode = "accumulated"
        self.assertEqual(
            self.employee._get_benefit_mode("fourteenth", "2026-05-01"), "accumulated"
        )
        self.assertEqual(other._get_benefit_mode("fourteenth", "2026-05-01"), "monthly")

    def test_benefit_mode_errors(self):
        with self.assertRaises(ValueError):
            self.employee._get_benefit_mode("utilidades", "2026-01-01")
        with self.assertRaises(ValueError):
            self.employee._get_benefit_mode("thirteenth", False)
        with self.assertRaises(ValueError):
            (self.employee | self.Employee.create({"name": "X"}))._get_benefit_mode(
                "thirteenth", "2026-01-01"
            )

    def test_benefit_same_date_rejected(self):
        self._elect("reserve_fund", "accumulated", "2026-01-01")
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._elect("reserve_fund", "monthly", "2026-01-01")

    def test_benefit_mode_without_hr_rights(self):
        """La consulta de nómina no depende del grupo de RRHH del usuario."""
        self._elect("reserve_fund", "accumulated", "2026-01-01")
        user = new_test_user(
            self.env, login="erp_nomina_sin_rrhh", groups="base.group_user"
        )
        self.assertEqual(
            self.employee.with_user(user)._get_benefit_mode(
                "reserve_fund", "2026-02-01"
            ),
            "accumulated",
        )

    # ------------------------------------------------------------------
    # Datos adicionales (CA-7)
    # ------------------------------------------------------------------
    def _value(self, field, **vals):
        return self.env["erp.hr.extra.value"].create(
            dict(vals, employee_id=self.employee.id, field_id=field.id)
        )

    def test_selection_value_requires_own_option(self):
        value = self._value(self.field_list, option_id=self.field_list.option_ids[0].id)
        self.assertEqual(value.option_id.name, "O+")
        with self._raises(ValidationError, "no pertenece al dato"):
            value.option_id = self.field_list_2.option_ids[0]
        with self._raises(ValidationError, "Elija una opción"):
            value.option_id = False
        with self._raises(ValidationError, "Elija una opción"):
            self._value(self.field_list_2)

    def test_unused_value_columns_cleared_on_create(self):
        value = self._value(
            self.field_int,
            value_integer=12,
            value_char="doce",
            value_float=1.5,
            value_boolean=True,
            value_date="2026-01-01",
            option_id=self.field_list.option_ids[0].id,
        )
        self.assertEqual(value.value_integer, 12)
        self.assertFalse(value.value_char)
        self.assertEqual(value.value_float, 0.0)
        self.assertFalse(value.value_boolean)
        self.assertFalse(value.value_date)
        self.assertFalse(value.option_id)

    def test_unused_value_columns_ignored_on_write(self):
        value = self._value(self.field_text, value_char="M")
        value.write({"value_char": "XL", "value_integer": 3})
        self.assertEqual(value.value_char, "XL")
        self.assertEqual(value.value_integer, 0)
        # Cambiar de dato vacía las columnas que ya no corresponden.
        value.write({"field_id": self.field_int.id, "value_integer": 7})
        self.assertFalse(value.value_char)
        self.assertEqual(value.value_integer, 7)

    def test_write_on_mixed_types(self):
        text = self._value(self.field_text, value_char="S")
        integer = self._value(self.field_int, value_integer=2)
        (text | integer).write({"value_char": "L", "value_integer": 9})
        self.assertEqual((text.value_char, text.value_integer), ("L", 0))
        self.assertEqual((integer.value_char, integer.value_integer), (False, 9))

    def test_type_change_blocked_with_values(self):
        self._value(self.field_text, value_char="M")
        with self._raises(UserError, "Talla de camiseta"):
            self.field_text.value_type = "integer"
        # Mismo tipo u otros cambios: permitido.
        self.field_text.write({"value_type": "char", "name": "Talla de polo"})
        # Sin valores, el tipo puede cambiar.
        field = self.env["erp.hr.extra.field"].create(
            {"name": "Número de calzado", "value_type": "char"}
        )
        field.value_type = "integer"
        self.assertEqual(field.value_type, "integer")

    # ------------------------------------------------------------------
    # Permisos
    # ------------------------------------------------------------------
    def test_hr_user_creates_full_employee(self):
        user = new_test_user(
            self.env,
            login="erp_hr_negocio",
            groups="base.group_user,hr.group_hr_user",
        )
        employee = self.Employee.with_user(user).create(
            {
                "name": "Lucía Ñaupari",
                "country_id": self.ecuador.id,
                "identification_id": CEDULA_2,
                "erp_establishment_id": self.est_sierra.id,
                "erp_disability": True,
                "erp_disability_percentage": 35,
                "erp_disability_card": "MSP-0002",
                "erp_dependent_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Mateo Ñaupari",
                            "identification": CEDULA_3,
                            "relationship": "child",
                            "birthdate": "2018-05-20",
                            "disability": True,
                        },
                    )
                ],
                "erp_benefit_election_ids": [
                    (
                        0,
                        0,
                        {
                            "benefit": "reserve_fund",
                            "mode": "accumulated",
                            "date_from": "2026-01-01",
                        },
                    )
                ],
                "erp_extra_value_ids": [
                    (0, 0, {"field_id": self.field_text.id, "value_char": "S"}),
                    (
                        0,
                        0,
                        {
                            "field_id": self.field_list.id,
                            "option_id": self.field_list.option_ids[1].id,
                        },
                    ),
                ],
            }
        )
        self.assertEqual(employee.erp_region, "sierra")
        self.assertEqual(len(employee.erp_dependent_ids), 1)
        self.assertEqual(len(employee.erp_extra_value_ids), 2)
        self.assertEqual(
            employee._get_benefit_mode("reserve_fund", "2026-03-01"), "accumulated"
        )

    def test_internal_user_without_hr_cannot_touch_sensitive_fields(self):
        user = new_test_user(
            self.env, login="erp_interno_sin_rrhh", groups="base.group_user"
        )
        employee = self.employee.with_user(user)
        with self.assertRaises(AccessError):
            employee.read(["erp_disability_percentage"])
        with self.assertRaises(AccessError):
            employee.write({"erp_disability": True, "erp_disability_percentage": 10})
        with self.assertRaises(AccessError):
            employee.write({"erp_establishment_id": self.est_sierra.id})
        with self.assertRaises(AccessError):
            self.env["erp.hr.dependent"].with_user(user).create(
                {
                    "employee_id": self.employee.id,
                    "name": "No permitido",
                    "relationship": "child",
                }
            )

    # ------------------------------------------------------------------
    # Ronda QA 1: cédula sin nacionalidad, índice único, multiempresa
    # ------------------------------------------------------------------
    def test_cedula_without_nationality(self):
        """Sin nacionalidad, 10 dígitos se validan como cédula; con otra
        nacionalidad, cualquier documento de 10 dígitos es válido."""
        with self._raises(ValidationError, "indique su nacionalidad"):
            self.Employee.create(
                {"name": "Sin país", "identification_id": "1234567890"}
            )
        with self._raises(ValidationError, "1234567890"):
            self.Employee.create(
                {"name": "Sin país", "identification_id": "123456789-0"}
            )
        employee = self.Employee.create(
            {"name": "Ecuatoriano sin país", "identification_id": CEDULA_2}
        )
        self.assertEqual(employee.identification_id, CEDULA_2)
        peruvian = self.Employee.create(
            {
                "name": "Rosa Quispe Ñahui",
                "country_id": self.env.ref("base.pe").id,
                "identification_id": "1234567890",
            }
        )
        self.assertEqual(peruvian.identification_id, "1234567890")
        # Quitar la nacionalidad obliga a que sea una cédula válida.
        with self._raises(ValidationError, "no es válida"):
            peruvian.country_id = False
        # Otros formatos sin nacionalidad no se validan como cédula.
        self.Employee.create({"name": "Pasaporte", "identification_id": "AB1234567"})
        self.Employee.create(
            {"name": "Nueve dígitos", "identification_id": "123456789"}
        )

    def test_identification_unique_index_exists(self):
        self.env.cr.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'hr_employee' "
            "AND indexname = %s",
            [IDENTIFICATION_UNIQUE_INDEX],
        )
        row = self.env.cr.fetchone()
        self.assertTrue(row, "Falta el índice único de identificación")
        indexdef = row[0]
        self.assertIn("UNIQUE", indexdef)
        self.assertIn("identification_id, company_id", indexdef)
        self.assertIn("WHERE (active AND (identification_id IS NOT NULL))", indexdef)

    def test_identification_index_enforced_in_db(self):
        other = self.Employee.create({"name": "Otro", "identification_id": CEDULA_2})
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    "UPDATE hr_employee SET identification_id = %s WHERE id = %s",
                    [CEDULA_1, other.id],
                )

    def test_identification_index_skipped_with_duplicates(self):
        """Con duplicados previos init() no rompe: avisa y omite el índice."""
        cr = self.env.cr
        cr.execute(SQL("DROP INDEX %s", SQL.identifier(IDENTIFICATION_UNIQUE_INDEX)))
        other = self.Employee.create({"name": "Otro", "identification_id": CEDULA_2})
        cr.execute(
            "UPDATE hr_employee SET identification_id = %s WHERE id = %s",
            [CEDULA_1, other.id],
        )
        with self.assertLogs(
            "odoo.addons.erp_hr_ec.models.hr_employee", level="WARNING"
        ) as logs:
            self.Employee.init()
        self.assertIn(IDENTIFICATION_UNIQUE_INDEX, logs.output[0])
        self.assertFalse(index_exists(cr, IDENTIFICATION_UNIQUE_INDEX))
        # Depurado el duplicado, init() lo crea.
        cr.execute(
            "UPDATE hr_employee SET identification_id = NULL WHERE id = %s",
            [other.id],
        )
        self.Employee.init()
        self.assertTrue(index_exists(cr, IDENTIFICATION_UNIQUE_INDEX))

    def test_duplicate_cedula_on_write_is_validation_error(self):
        """Escribir una cédula repetida da el mensaje en español, no el error
        técnico del índice único."""
        other = self.Employee.create({"name": "Otro", "identification_id": CEDULA_2})
        with self._raises(ValidationError, "ya está registrada"):
            other.identification_id = "171003406-5"
        # Crear archivado con la misma cédula se permite; reactivarlo, no.
        archived = self.Employee.create(
            {
                "name": "Archivado al crear",
                "identification_id": CEDULA_1,
                "active": False,
            }
        )
        self.assertFalse(archived.active)
        with self._raises(ValidationError, "ya está registrada"):
            archived.write({"active": True})

    def test_establishment_company_checked(self):
        other_company = self.env["res.company"].create({"name": "Courier Ñandú S.A."})
        other_establishment = self.env["erp.establishment"].create(
            {
                "code": "301",
                "name": "Agencia Loja",
                "region": "sierra",
                "company_id": other_company.id,
            }
        )
        with self.assertRaises(UserError):
            self.Employee.create(
                {"name": "Mezcla", "erp_establishment_id": other_establishment.id}
            )
        with self.assertRaises(UserError):
            self.employee.erp_establishment_id = other_establishment
        # Cambiar la empresa del empleado dejando el establecimiento de la
        # anterior también se rechaza.
        with self.assertRaises(UserError):
            self.employee.company_id = other_company
        # Empresa y establecimiento coherentes: aceptado.
        self.employee.write(
            {
                "company_id": other_company.id,
                "erp_establishment_id": other_establishment.id,
            }
        )
        self.assertEqual(self.employee.erp_region, "sierra")
