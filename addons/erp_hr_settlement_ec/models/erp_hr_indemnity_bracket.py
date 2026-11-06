from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import format_date, formatLang


class ErpHrIndemnityBracket(models.Model):
    """Tramo de la indemnización por despido intempestivo (US-013, CA-6).

    Meses de remuneración según los años de servicio, con vigencia por fecha:

        meses = meses fijos + meses por año × años de servicio,
        acotado a [mínimo, máximo] (máximo 0 = sin tope).

    Un tramo cubre los años ``years_from < años <= years_to`` (``years_to`` =
    0: sin límite superior). Rige la versión (``date_from``) más reciente que
    sea ``<=`` a la fecha de salida; una versión de la empresa prevalece sobre
    la común (sin empresa), como en ``erp.payroll.parameter``. Cómo se
    redondea la fracción de año lo dice el parámetro
    ``INDEMNITY_YEAR_FRACTION_AS_FULL``.
    """

    _name = "erp.hr.indemnity.bracket"
    _description = "Tramo de indemnización por despido intempestivo"
    _inherit = ["mail.thread", "erp.hr.settlement.validation.mixin"]
    _order = "date_from desc, years_from, id"
    _erp_revalidate_fields = (
        "date_from",
        "years_from",
        "years_to",
        "fixed_months",
        "months_per_year",
        "min_months",
        "max_months",
        "norm",
        "company_id",
    )

    name = fields.Char(string="Tramo", required=True, tracking=True)
    date_from = fields.Date(
        string="Vigente desde",
        required=True,
        tracking=True,
        help="Fecha desde la que rige esta versión de los tramos, hasta la "
        "siguiente versión.",
    )
    years_from = fields.Integer(
        string="Más de (años)",
        required=True,
        default=0,
        tracking=True,
        help="El tramo aplica a quien tiene MÁS de estos años de servicio.",
    )
    years_to = fields.Integer(
        string="Hasta (años)",
        tracking=True,
        help="El tramo aplica hasta estos años de servicio (incluidos). 0: sin "
        "límite superior.",
    )
    fixed_months = fields.Float(
        string="Meses fijos",
        digits=(16, 4),
        tracking=True,
        help="Meses de remuneración que se pagan en el tramo, sin importar los "
        "años de servicio.",
    )
    months_per_year = fields.Float(
        string="Meses por año de servicio",
        digits=(16, 4),
        tracking=True,
        help="Meses de remuneración que se suman por cada año de servicio.",
    )
    min_months = fields.Float(
        string="Mínimo (meses)",
        digits=(16, 4),
        tracking=True,
        help="Mínimo de meses de remuneración del tramo.",
    )
    max_months = fields.Float(
        string="Máximo (meses)",
        digits=(16, 4),
        tracking=True,
        help="Tope de meses de remuneración del tramo. 0: sin tope.",
    )
    norm = fields.Text(
        string="Norma / fuente",
        required=True,
        tracking=True,
        help="Norma y artículo que respaldan el tramo.",
    )
    note = fields.Text(string="Notas")
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        index="btree_not_null",
        ondelete="cascade",
        tracking=True,
        help="Vacío: el tramo es común a todas las empresas.",
    )
    active = fields.Boolean(string="Activo", default=True, tracking=True)

    _sql_constraints = [
        (
            # También sirve a la búsqueda del tramo vigente.
            "date_years_company_uniq",
            "UNIQUE NULLS NOT DISTINCT (date_from, years_from, company_id)",
            "Ya existe un tramo de indemnización con la misma vigencia, los "
            "mismos años de inicio y la misma empresa.",
        ),
        (
            "years_check",
            "CHECK (years_from >= 0 AND (years_to = 0 OR years_to > years_from))",
            "Los años del tramo no son válidos: «Más de» no puede ser negativo "
            "y «Hasta» debe ser mayor que «Más de» (o 0 si no tiene límite).",
        ),
        (
            "months_positive_check",
            "CHECK (fixed_months >= 0 AND months_per_year >= 0 "
            "AND min_months >= 0 AND max_months >= 0)",
            "Los meses del tramo no pueden ser negativos.",
        ),
        (
            "max_months_check",
            "CHECK (max_months = 0 OR max_months >= min_months)",
            "El máximo de meses del tramo no puede ser menor que el mínimo.",
        ),
    ]

    @api.constrains("date_from", "company_id", "years_from", "years_to", "active")
    def _check_no_overlap(self):
        """Los tramos activos de una misma versión (vigencia y empresa) no se
        solapan: cada número de años de servicio cae en un solo tramo."""
        for bracket in self.filtered("active"):
            siblings = self.search(
                [
                    ("id", "!=", bracket.id),
                    ("date_from", "=", bracket.date_from),
                    ("company_id", "=", bracket.company_id.id),
                ]
            )
            upper = bracket.years_to or float("inf")
            for other in siblings:
                other_upper = other.years_to or float("inf")
                if bracket.years_from < other_upper and other.years_from < upper:
                    raise ValidationError(
                        _(
                            "Los tramos «%(bracket)s» y «%(other)s» de "
                            "indemnización vigentes desde el %(date)s se "
                            "solapan: cada número de años de servicio debe "
                            "caer en un solo tramo.",
                            bracket=bracket.name,
                            other=other.name,
                            date=format_date(self.env, bracket.date_from),
                        )
                    )

    @api.model
    def _get_bracket(self, years, date, company=None):
        """Tramo vigente en ``date`` que cubre ``years`` años de servicio.

        :param years: años de servicio ya redondeados según
            ``INDEMNITY_YEAR_FRACTION_AS_FULL`` (``int`` o ``float``)
        :param date: fecha de salida (``date`` o cadena ISO)
        :param company: ``res.company`` (por defecto, la empresa actual)
        :return: ``erp.hr.indemnity.bracket`` (un registro)
        :raises UserError: no hay versión vigente o ningún tramo la cubre
        """
        date = fields.Date.to_date(date)
        company = company or self.env.company
        # sudo(): consulta de servidor de valores normativos para el cálculo;
        # el filtro de empresa se aplica de forma explícita.
        brackets = self.sudo().search(
            [
                ("date_from", "<=", date),
                ("company_id", "in", [company.id, False]),
            ],
            order="date_from desc, years_from, id",
        )
        own = brackets.filtered("company_id")
        version = own or brackets
        if version:
            version_date = version[0].date_from
            version = version.filtered(lambda b: b.date_from == version_date)
        bracket = version.filtered(
            lambda b: b.years_from < years and (not b.years_to or years <= b.years_to)
        )[:1]
        if not bracket:
            raise UserError(
                _(
                    "No hay un tramo de indemnización por despido intempestivo "
                    "vigente al %(date)s para %(years)s años de servicio. "
                    "Registre los tramos en Nómina › Configuración › Tramos de "
                    "indemnización.",
                    date=format_date(self.env, date),
                    # Formato local: entero si los años no tienen fracción
                    # (p. ej. «5»), con dos decimales si la tienen («4,50»).
                    years=formatLang(
                        self.env,
                        years,
                        digits=0 if float(years).is_integer() else 2,
                    ),
                )
            )
        return bracket.with_env(self.env)
