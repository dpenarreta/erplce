from odoo import _, fields, models
from odoo.exceptions import UserError

EXTRA_VALUE_TYPE_SELECTION = [
    ("char", "Texto"),
    ("integer", "Entero"),
    ("float", "Decimal"),
    ("date", "Fecha"),
    ("boolean", "Sí/No"),
    ("selection", "Lista de opciones"),
]


class ErpHrExtraField(models.Model):
    _name = "erp.hr.extra.field"
    _description = "Dato adicional de empleado"
    _order = "sequence, name, id"

    name = fields.Char(string="Nombre", required=True)
    sequence = fields.Integer(string="Secuencia", default=10)
    value_type = fields.Selection(
        EXTRA_VALUE_TYPE_SELECTION,
        string="Tipo",
        required=True,
        default="char",
    )
    option_ids = fields.One2many(
        "erp.hr.extra.field.option",
        "field_id",
        string="Opciones",
        help="Valores admitidos cuando el tipo es Lista de opciones.",
    )
    help = fields.Text(
        string="Ayuda", help="Texto de ayuda para quien registra el dato."
    )
    active = fields.Boolean(
        string="Activo",
        default=True,
        help="Archivar un dato lo oculta del formulario del empleado sin borrar "
        "los valores ya registrados.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        index=True,
        ondelete="restrict",
        default=lambda self: self.env.company,
    )

    _sql_constraints = [
        (
            "name_company_uniq",
            "UNIQUE(name, company_id)",
            "Ya existe un dato adicional con ese nombre en la empresa "
            "(incluidos los archivados).",
        ),
    ]

    def write(self, vals):
        if "value_type" in vals:
            self._erp_check_type_change(vals["value_type"])
        return super().write(vals)

    def _erp_check_type_change(self, new_type):
        """Bloquea cambiar el tipo de un dato que ya tiene valores: los
        valores registrados quedarían en una columna que ya no se usa."""
        changed = self.filtered(lambda f: f.value_type != new_type)
        if not changed:
            return
        # sudo: deben contarse los valores de todos los empleados (también los
        # que el usuario no ve); solo se usa el número de empleados.
        groups = (
            self.env["erp.hr.extra.value"]
            .sudo()
            ._read_group(
                [("field_id", "in", changed.ids)],
                groupby=["field_id"],
                aggregates=["__count"],
            )
        )
        if groups:
            field, count = groups[0]
            raise UserError(
                _(
                    "No se puede cambiar el tipo del dato adicional «%(field)s» "
                    "porque ya tiene valores registrados en %(count)s "
                    "empleado(s). Cree un dato nuevo con el tipo deseado y "
                    "archive este.",
                    field=field.with_env(self.env).name,
                    count=count,
                )
            )


class ErpHrExtraFieldOption(models.Model):
    _name = "erp.hr.extra.field.option"
    _description = "Opción de dato adicional"
    _order = "field_id, sequence, id"

    field_id = fields.Many2one(
        "erp.hr.extra.field",
        string="Dato adicional",
        required=True,
        index=True,
        ondelete="cascade",
    )
    name = fields.Char(string="Opción", required=True)
    sequence = fields.Integer(string="Secuencia", default=10)
    active = fields.Boolean(string="Activo", default=True)
    company_id = fields.Many2one(
        related="field_id.company_id",
        store=True,
        precompute=True,
        index=True,
        string="Empresa",
    )

    _sql_constraints = [
        (
            "field_name_uniq",
            "UNIQUE(field_id, name)",
            "La opción ya existe en este dato adicional.",
        ),
    ]
