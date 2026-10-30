"""Valor legible de los datos adicionales (US-017, CA-6)."""

from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestHrEcExtraValueDisplay(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("es_EC")
        cls.env = cls.env(context=dict(cls.env.context, lang="es_EC"))
        Field = cls.env["erp.hr.extra.field"]
        cls.fields_by_type = {
            value_type: Field.create(
                {"name": f"Dato {value_type} – Ñandú", "value_type": value_type}
            )
            for value_type in ("char", "integer", "float", "date", "boolean")
        }
        cls.field_list = Field.create(
            {
                "name": "Turno preferido",
                "value_type": "selection",
                "option_ids": [(0, 0, {"name": "Mañana – ñ"})],
            }
        )
        cls.employee = cls.env["hr.employee"].create({"name": "Íñigo Peña Ñúñez"})
        cls.Value = cls.env["erp.hr.extra.value"]

    def _value(self, value_type, **vals):
        field = self.fields_by_type.get(value_type, self.field_list)
        record = self.Value.search(
            [("employee_id", "=", self.employee.id), ("field_id", "=", field.id)]
        )
        if record:
            record.write(vals)
            return record
        return self.Value.create(
            {"employee_id": self.employee.id, "field_id": field.id, **vals}
        )

    def test_char(self):
        record = self._value("char", value_char="Talla M – cañón")
        self.assertEqual(record.value_display, "Talla M – cañón")
        record.value_char = False
        self.assertEqual(record.value_display, "")

    def test_integer_es_ec(self):
        record = self._value("integer", value_integer=1234567)
        self.assertEqual(record.value_display, "1.234.567")
        record.value_integer = 0
        self.assertEqual(record.value_display, "0")

    def test_float_es_ec(self):
        record = self._value("float", value_float=1234.5)
        self.assertEqual(record.value_display, "1.234,50")
        # No se redondea a 2 decimales si el valor tiene más.
        record.value_float = 1.375
        self.assertEqual(record.value_display, "1,375")
        record.value_float = -0.000001
        self.assertEqual(record.value_display, "-0,000001")

    def test_date_es_ec(self):
        record = self._value("date", value_date=date(2026, 12, 31))
        self.assertEqual(record.value_display, "31/12/2026")
        record.value_date = False
        self.assertEqual(record.value_display, "")

    def test_boolean(self):
        record = self._value("boolean", value_boolean=True)
        self.assertEqual(record.value_display, "Sí")
        record.value_boolean = False
        self.assertEqual(record.value_display, "No")

    def test_selection_follows_option_name(self):
        option = self.field_list.option_ids
        record = self._value("selection", option_id=option.id)
        self.assertEqual(record.value_display, "Mañana – ñ")
        option.name = "Tarde"
        self.assertEqual(record.value_display, "Tarde")

    def test_other_language_format(self):
        self.env["res.lang"]._activate_lang("en_US")
        record = self._value("float", value_float=1234.5)
        self.assertEqual(record.with_context(lang="en_US").value_display, "1,234.50")
        self.assertEqual(record.with_context(lang="es_EC").value_display, "1.234,50")

    def test_field_help_follows_field(self):
        """La ayuda del dato se ve en el valor, sigue a la del dato y no se
        almacena ni se edita desde el valor (US-017, CA-6)."""
        field = self.fields_by_type["char"]
        field.help = "Talla del uniforme según la tabla de Logística – ñ."
        record = self._value("char", value_char="M")
        self.assertEqual(
            record.field_help, "Talla del uniforme según la tabla de Logística – ñ."
        )
        field.help = False
        self.assertFalse(record.field_help)
        definition = self.Value._fields["field_help"]
        self.assertFalse(definition.store)
        self.assertTrue(definition.readonly)
        self.assertEqual(definition.related, "field_id.help")
