from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Columna que guarda el valor según el tipo del dato adicional.
VALUE_FIELD_BY_TYPE = {
    "char": "value_char",
    "integer": "value_integer",
    "float": "value_float",
    "date": "value_date",
    "boolean": "value_boolean",
    "selection": "option_id",
}
# Valor vacío de cada columna de valor.
EMPTY_VALUES = {
    "value_char": False,
    "value_integer": 0,
    "value_float": 0.0,
    "value_date": False,
    "value_boolean": False,
    "option_id": False,
}


class ErpHrExtraValue(models.Model):
    """Valor tipado de un dato adicional para un empleado.

    Solo se usa la columna value_* que corresponde al tipo del dato
    (value_type); la coherencia tipo/valor y que la opción pertenezca al dato
    se validan en la capa de negocio.
    """

    _name = "erp.hr.extra.value"
    _description = "Valor de dato adicional"
    _order = "employee_id, field_sequence, field_id"
    _check_company_auto = True

    # Sin index=True propio: el índice de la restricción única
    # (employee_id, field_id) cubre las búsquedas por empleado.
    employee_id = fields.Many2one(
        "hr.employee",
        string="Empleado",
        required=True,
        ondelete="cascade",
        check_company=True,
    )
    field_id = fields.Many2one(
        "erp.hr.extra.field",
        string="Dato adicional",
        required=True,
        index=True,
        ondelete="restrict",
        check_company=True,
    )
    field_sequence = fields.Integer(
        related="field_id.sequence",
        store=True,
        precompute=True,
        string="Secuencia del dato",
    )
    field_active = fields.Boolean(
        related="field_id.active", store=True, precompute=True, string="Dato activo"
    )
    value_type = fields.Selection(related="field_id.value_type", string="Tipo")
    value_char = fields.Char(string="Texto")
    value_integer = fields.Integer(string="Entero")
    value_float = fields.Float(string="Decimal")
    value_date = fields.Date(string="Fecha")
    value_boolean = fields.Boolean(string="Sí/No")
    option_id = fields.Many2one(
        "erp.hr.extra.field.option",
        string="Opción",
        index="btree_not_null",
        ondelete="restrict",
    )
    company_id = fields.Many2one(
        related="employee_id.company_id",
        store=True,
        precompute=True,
        index=True,
        string="Empresa",
    )

    _sql_constraints = [
        (
            "employee_field_uniq",
            "UNIQUE(employee_id, field_id)",
            "El empleado ya tiene un valor para ese dato adicional.",
        ),
    ]

    # ------------------------------------------------------------------
    # Coherencia tipo/valor
    # ------------------------------------------------------------------
    # Regla (predecible): solo se conserva la columna que corresponde al tipo
    # del dato; las demás columnas de valor se guardan vacías. En create y al
    # cambiar de dato (field_id) se vacían todas las demás; en un write que no
    # cambia de dato, los valores enviados a columnas que no corresponden al
    # tipo se ignoran (se guardan vacíos).
    @api.model
    def _erp_clean_value_vals(self, vals, value_type, clear_all):
        kept = VALUE_FIELD_BY_TYPE.get(value_type)
        for column, empty in EMPTY_VALUES.items():
            if column != kept and (clear_all or column in vals):
                vals[column] = empty
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        field_ids = {vals["field_id"] for vals in vals_list if vals.get("field_id")}
        types = {
            field.id: field.value_type
            for field in self.env["erp.hr.extra.field"]
            .with_context(active_test=False)
            .browse(field_ids)
        }
        vals_list = [
            self._erp_clean_value_vals(
                dict(vals), types.get(vals.get("field_id")), clear_all=True
            )
            for vals in vals_list
        ]
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("field_id"):
            value_type = (
                self.env["erp.hr.extra.field"].browse(vals["field_id"]).value_type
            )
            return super().write(
                self._erp_clean_value_vals(dict(vals), value_type, clear_all=True)
            )
        if not set(vals) & set(EMPTY_VALUES):
            return super().write(vals)
        result = True
        for value_type in set(self.mapped("value_type")):
            records = self.filtered(lambda v, t=value_type: v.value_type == t)
            result &= super(ErpHrExtraValue, records).write(
                self._erp_clean_value_vals(dict(vals), value_type, clear_all=False)
            )
        return result

    @api.constrains("field_id", "option_id")
    def _check_option(self):
        for value in self:
            if value.value_type != "selection":
                continue
            if not value.option_id:
                raise ValidationError(
                    _(
                        "Elija una opción para el dato «%(field)s».",
                        field=value.field_id.name,
                    )
                )
            if value.option_id.field_id != value.field_id:
                raise ValidationError(
                    _(
                        "La opción «%(option)s» no pertenece al dato «%(field)s».",
                        option=value.option_id.name,
                        field=value.field_id.name,
                    )
                )
