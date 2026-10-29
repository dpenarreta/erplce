"""Importación de establecimientos con el importador nativo (US-007, CA-3).

Se usa ``base_import.import`` como la interfaz: ``parse_preview`` propone el
mapeo de columnas a partir de la cabecera y ``execute_import`` importa, en el
idioma es_EC.
"""

from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools.misc import file_open

TEMPLATE_PATH = "erp_establishment/static/csv/plantilla_establecimientos.csv"
TEMPLATE_URL = "/erp_establishment/static/csv/plantilla_establecimientos.csv"
HEADER = "Código,Nombre,Dirección,Ciudad,Provincia,Región,Activo\n"

IMPORT_OPTIONS = {
    "import_skip_records": [],
    "import_set_empty_fields": [],
    "fallback_values": {},
    "name_create_enabled_fields": {},
    "encoding": "utf-8",
    "separator": ",",
    "quoting": '"',
    "date_format": "",
    "datetime_format": "",
    "float_thousand_separator": ",",
    "float_decimal_separator": ".",
    "advanced": False,
    "has_headers": True,
    "keep_matches": False,
    "limit": 2000,
    "skip": 0,
    "tracking_disable": True,
}

EXPECTED_MATCHES = [
    "code",
    "name",
    "street",
    "city",
    "state_id",
    "region",
    "active",
]


@tagged("post_install", "-at_install")
class TestErpEstablishmentImport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("es_EC")
        cls.env = cls.env(context=dict(cls.env.context, lang="es_EC"))
        cls.Establishment = cls.env["erp.establishment"].with_context(active_test=False)

    def _import(self, content, dryrun=False):
        """Importa ``content`` (bytes CSV) como la interfaz.

        :return: (resultado de execute_import, matches de parse_preview)
        """
        wizard = self.env["base_import.import"].create(
            {
                "res_model": "erp.establishment",
                "file": content,
                "file_name": "plantilla_establecimientos.csv",
                "file_type": "text/csv",
            }
        )
        preview = wizard.parse_preview(dict(IMPORT_OPTIONS))
        self.assertFalse(preview.get("error"), preview.get("error"))
        matches = preview["matches"]
        fields = [
            "/".join(matches.get(index) or []) or False
            for index in range(len(preview["headers"]))
        ]
        result = wizard.execute_import(
            fields, preview["headers"], dict(IMPORT_OPTIONS), dryrun=dryrun
        )
        return result, fields

    def _errors(self, result):
        return [m for m in result["messages"] if m["type"] == "error"]

    def _by_code(self, codes):
        return self.Establishment.search([("code", "in", codes)])

    def test_import_module_template(self):
        with file_open(TEMPLATE_PATH, "rb") as template:
            content = template.read()
        result, fields = self._import(content)
        # Las columnas en español se mapean solas.
        self.assertEqual(fields, EXPECTED_MATCHES)
        self.assertFalse(self._errors(result), result["messages"])
        self.assertEqual(len(result["ids"]), 3)

        records = self.Establishment.browse(result["ids"])
        by_code = {rec.code: rec for rec in records}
        self.assertEqual(set(by_code), {"001", "002", "003"})
        self.assertEqual(by_code["001"].region, "sierra")
        self.assertEqual(by_code["001"].state_id, self.env.ref("base.state_ec_17"))
        self.assertEqual(by_code["002"].region, "costa")
        self.assertEqual(by_code["002"].decimo_cuarto_regime, "costa_galapagos")
        self.assertEqual(by_code["002"].state_id, self.env.ref("base.state_ec_09"))
        # "Bolívar" (con tilde, existe también en Colombia) -> Bolivar de Ecuador.
        self.assertEqual(by_code["003"].state_id, self.env.ref("base.state_ec_02"))
        self.assertTrue(by_code["001"].active)
        self.assertTrue(by_code["002"].active)
        # Activo = No -> archivado.
        self.assertFalse(by_code["003"].active)

    def test_import_ecuador_states_with_accents(self):
        """Nombres oficiales con tildes, ñ y mayúsculas se resuelven a Ecuador."""
        rows = [
            ("Bolívar", "base.state_ec_02"),
            ("Cañar", "base.state_ec_03"),
            ("Los Ríos", "base.state_ec_12"),
            ("Manabí", "base.state_ec_13"),
            ("Galápagos", "base.state_ec_20"),
            ("Sucumbíos", "base.state_ec_21"),
            ("Santo Domingo de los Tsáchilas", "base.state_ec_23"),
            ("zamora chinchipe", "base.state_ec_19"),
            ("MORONA SANTIAGO", "base.state_ec_14"),
            ("  Santa   Elena ", "base.state_ec_24"),
            ("El Oro", "base.state_ec_07"),
            ("17", "base.state_ec_17"),
        ]
        lines = [
            f'{index + 10},Agencia {index},,,"{state}",Costa,Sí'
            for index, (state, _xmlid) in enumerate(rows)
        ]
        content = (HEADER + "\n".join(lines) + "\n").encode("utf-8")
        result, _fields = self._import(content)
        self.assertFalse(self._errors(result), result["messages"])
        for index, (state, xmlid) in enumerate(rows):
            with self.subTest(state=state):
                record = self._by_code([f"{index + 10:03d}"])
                self.assertEqual(record.state_id, self.env.ref(xmlid))

    def test_import_unknown_state_fails_row(self):
        content = (
            HEADER
            + "10,Agencia A,,,Pichincha,Sierra,Sí\n"
            + "11,Agencia B,,,Provincia Inventada,Sierra,Sí\n"
        ).encode("utf-8")
        result, _fields = self._import(content)
        errors = self._errors(result)
        self.assertTrue(errors)
        self.assertIn("Provincia Inventada", str(errors))
        self.assertEqual(errors[0]["rows"], {"from": 1, "to": 1})
        self.assertFalse(self._by_code(["010", "011"]))

    def test_import_foreign_state_fails_row(self):
        """Una provincia que solo existe en otro país se rechaza en su fila."""
        content = (HEADER + "10,Agencia A,,,Antioquia,Sierra,Sí\n").encode("utf-8")
        result, _fields = self._import(content)
        errors = self._errors(result)
        self.assertTrue(errors)
        self.assertIn("no es de Ecuador", str(errors))
        self.assertFalse(self._by_code(["010"]))

    def test_import_code_normalized(self):
        content = (HEADER + "1,Matriz,,,Pichincha,Sierra,Sí\n").encode("utf-8")
        result, _fields = self._import(content)
        self.assertFalse(self._errors(result), result["messages"])
        self.assertEqual(self.Establishment.browse(result["ids"]).code, "001")

    def test_import_duplicate_in_file_fails(self):
        content = (
            HEADER
            + "5,Agencia A,,,Pichincha,Sierra,Sí\n"
            + "005,Agencia B,,,Guayas,Costa,Sí\n"
        ).encode("utf-8")
        result, _fields = self._import(content)
        errors = self._errors(result)
        self.assertTrue(errors)
        self.assertIn("código 005", str(errors))
        self.assertIn({"from": 1, "to": 1}, [e.get("rows") for e in errors])
        self.assertFalse(self._by_code(["005"]))

    def test_import_existing_code_fails(self):
        self.Establishment.create(
            {"code": "20", "name": "Ya existente", "region": "costa", "active": False}
        )
        content = (HEADER + "020,Agencia Nueva,,,Guayas,Costa,Sí\n").encode("utf-8")
        result, _fields = self._import(content)
        errors = self._errors(result)
        self.assertTrue(errors)
        self.assertIn("código 020", str(errors))
        self.assertEqual(len(self._by_code(["020"])), 1)

    def test_import_invalid_code_fails(self):
        content = (HEADER + "A1,Agencia,,,Guayas,Costa,Sí\n").encode("utf-8")
        result, _fields = self._import(content)
        errors = self._errors(result)
        self.assertTrue(errors)
        self.assertIn("A1", str(errors))

    def test_import_active_values(self):
        """Activo: Sí/Si/si/SI/1 -> activo; No/0 -> archivado; vacío ->
        activo (ajuste propio de la importación de establecimientos,
        documentado en la guía)."""
        content = (
            HEADER
            + "31,Agencia 31,,,Guayas,Costa,Sí\n"
            + "32,Agencia 32,,,Guayas,Costa,1\n"
            + "33,Agencia 33,,,Guayas,Costa,No\n"
            + "34,Agencia 34,,,Guayas,Costa,0\n"
            + "35,Agencia 35,,,Guayas,Costa,\n"
            + "36,Agencia 36,,,Guayas,Costa,Si\n"
            + "37,Agencia 37,,,Guayas,Costa,si\n"
            + "38,Agencia 38,,,Guayas,Costa,SI\n"
            + "39,Agencia 39,,,Guayas,Costa,no\n"
        ).encode("utf-8")
        result, _fields = self._import(content)
        self.assertFalse(self._errors(result), result["messages"])
        self.assertFalse(result["messages"], result["messages"])
        records = self._by_code([f"{code:03d}" for code in range(31, 40)])
        active = {rec.code: rec.active for rec in records}
        self.assertEqual(
            active,
            {
                "031": True,
                "032": True,
                "033": False,
                "034": False,
                "035": True,
                "036": True,
                "037": True,
                "038": True,
                "039": False,
            },
        )

    def test_import_unknown_active_value_fails(self):
        content = (HEADER + "40,Agencia 40,,,Guayas,Costa,Quizás\n").encode("utf-8")
        result, _fields = self._import(content)
        self.assertTrue(result["messages"])
        self.assertIn("Quizás", str(result["messages"]))
        self.assertFalse(result["ids"])

    def test_import_region_values(self):
        """La región se compara sin mayúsculas y acepta el valor técnico sin
        tilde (``Amazonia``, ``Galapagos``) o la etiqueta con tilde."""
        rows = [
            ("COSTA", "costa"),
            ("sierra", "sierra"),
            ("Amazonia", "amazonia"),
            ("AMAZONÍA", "amazonia"),
            ("galápagos", "galapagos"),
            ("Galapagos", "galapagos"),
        ]
        lines = [
            f"{index + 50},Agencia {index},,,,{region},Sí"
            for index, (region, _value) in enumerate(rows)
        ]
        content = (HEADER + "\n".join(lines) + "\n").encode("utf-8")
        result, _fields = self._import(content)
        self.assertFalse(self._errors(result), result["messages"])
        for index, (region, value) in enumerate(rows):
            with self.subTest(region=region):
                self.assertEqual(self._by_code([f"{index + 50:03d}"]).region, value)

    def test_active_conversion_scoped_to_establishment(self):
        """Fuera de los establecimientos los booleanos importados siguen el
        estándar: vacío -> False y ``Si`` sin tilde es un valor desconocido."""
        converter = self.env["ir.fields.converter"]
        warnings = []

        def log(field, warning):
            warnings.append((field, warning))

        partner_convert = converter.for_model(self.env["res.partner"])
        self.assertIs(partner_convert({"active": ""}, log)["active"], False)
        self.assertFalse(warnings)
        partner_convert({"active": "Si"}, log)
        self.assertTrue(warnings)
        self.assertEqual(warnings[0][0], "active")
        establishment_convert = converter.for_model(self.env["erp.establishment"])
        self.assertIs(establishment_convert({"active": ""}, log)["active"], True)
        self.assertIs(establishment_convert({"active": "SI"}, log)["active"], True)
        self.assertIs(establishment_convert({"active": "No"}, log)["active"], False)
        self.assertEqual(len(warnings), 1)

    def test_dryrun_creates_nothing(self):
        with file_open(TEMPLATE_PATH, "rb") as template:
            content = template.read()
        result, _fields = self._import(content, dryrun=True)
        self.assertFalse(self._errors(result), result["messages"])
        self.assertFalse(self._by_code(["001", "002", "003"]))

    def test_state_resolution_scoped_to_establishment(self):
        """Fuera de la importación de establecimientos, la búsqueda por nombre
        de provincias no cambia (la tilde sigue encontrando la de Colombia)."""
        found = self.env["res.country.state"].name_search("Bolívar", operator="=")
        countries = (
            self.env["res.country.state"]
            .browse([rid for rid, _name in found])
            .mapped("country_id.code")
        )
        self.assertNotIn("EC", countries)


@tagged("post_install", "-at_install")
class TestErpEstablishmentTemplateHttp(HttpCase):
    def test_template_download(self):
        response = self.url_open(TEMPLATE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.content.decode("utf-8").startswith(HEADER.strip()),
            response.content[:100],
        )
