import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

REGION_SELECTION = [
    ("costa", "Costa"),
    ("sierra", "Sierra"),
    ("amazonia", "Amazonía"),
    ("galapagos", "Galápagos"),
]

DECIMO_CUARTO_REGIME_SELECTION = [
    ("costa_galapagos", "Costa / Galápagos"),
    ("sierra_amazonia", "Sierra / Amazonía"),
]

# Código SRI: 1 a 3 dígitos (se rellena con ceros a la izquierda a 3).
_CODE_INPUT_RE = re.compile(r"^[0-9]{1,3}$")

# Mapeo región geográfica -> régimen de décimo cuarto sueldo (US-007, §5).
REGION_TO_DECIMO_CUARTO_REGIME = {
    "costa": "costa_galapagos",
    "galapagos": "costa_galapagos",
    "sierra": "sierra_amazonia",
    "amazonia": "sierra_amazonia",
}


def normalize_establishment_code(env, code):
    """Normaliza un código de establecimiento SRI a 3 dígitos.

    Quita los espacios (también los intermedios, p. ej. ``" 0 1 "``) y rellena
    con ceros a la izquierda: ``1`` -> ``001``, ``25`` -> ``025``.

    :param env: entorno de Odoo (idioma de los mensajes)
    :param code: valor recibido (str, int o vacío)
    :return: código normalizado (str de 3 dígitos, ``001``-``999``)
    :raises ValidationError: código vacío, con caracteres no numéricos, de más
        de 3 dígitos o ``000``; el mensaje indica el valor recibido.
    """
    received = "" if code is None or code is False else str(code)
    compact = re.sub(r"\s+", "", received)
    if not compact:
        raise ValidationError(
            env._("El código de establecimiento es obligatorio (número de 1 a 999).")
        )
    if not _CODE_INPUT_RE.match(compact):
        raise ValidationError(
            env._(
                "El código de establecimiento «%(code)s» no es válido: debe ser "
                "un número de 1 a 3 dígitos (de 1 a 999).",
                code=received,
            )
        )
    normalized = compact.zfill(3)
    if normalized == "000":
        raise ValidationError(
            env._(
                "El código de establecimiento «%(code)s» no es válido: el código "
                "000 no existe en el SRI (use de 001 a 999).",
                code=received,
            )
        )
    return normalized


class ErpEstablishment(models.Model):
    _name = "erp.establishment"
    _description = "Establecimiento SRI"
    _order = "company_id, code"
    _check_company_auto = True
    _rec_names_search = ["code", "name"]

    # Las etiquetas (string) de los campos importables coinciden con la
    # cabecera de static/csv/plantilla_establecimientos.csv para que el
    # importador nativo mapee las columnas solo.
    code = fields.Char(
        string="Código",
        required=True,
        index=True,
        help="Código de establecimiento SRI de 3 dígitos (001-999). Se guarda "
        "con ceros a la izquierda; es único por empresa, incluidos los "
        "establecimientos archivados.",
    )
    name = fields.Char(string="Nombre", required=True)
    street = fields.Char(string="Dirección")
    city = fields.Char(string="Ciudad")
    state_id = fields.Many2one(
        "res.country.state",
        string="Provincia",
        ondelete="restrict",
        help="Provincia de Ecuador donde se ubica el establecimiento.",
    )
    region = fields.Selection(
        REGION_SELECTION,
        string="Región",
        required=True,
        help="Región geográfica del establecimiento. Determina el régimen de "
        "décimo cuarto sueldo de los empleados asignados.",
    )
    decimo_cuarto_regime = fields.Selection(
        DECIMO_CUARTO_REGIME_SELECTION,
        string="Régimen de décimo cuarto",
        compute="_compute_decimo_cuarto_regime",
        store=True,
        help="Calculado de la región: Costa y Galápagos -> Costa / Galápagos; "
        "Sierra y Amazonía -> Sierra / Amazonía.",
    )
    active = fields.Boolean(string="Activo", default=True)
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
            "code_company_uniq",
            "UNIQUE(code, company_id)",
            "Ya existe un establecimiento con ese código en la empresa "
            "(incluidos los archivados).",
        ),
        (
            "code_format_check",
            "CHECK(code ~ '^[0-9]{3}$' AND code <> '000')",
            "El código de establecimiento debe tener 3 dígitos entre 001 y 999.",
        ),
    ]

    @api.depends("region")
    def _compute_decimo_cuarto_regime(self):
        for establishment in self:
            establishment.decimo_cuarto_regime = REGION_TO_DECIMO_CUARTO_REGIME.get(
                establishment.region
            )

    @api.depends("code", "name")
    def _compute_display_name(self):
        for establishment in self:
            if establishment.code and establishment.name:
                establishment.display_name = (
                    f"{establishment.code} - {establishment.name}"
                )
            else:
                establishment.display_name = establishment.name or establishment.code

    # ------------------------------------------------------------------
    # Código: normalización y unicidad
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        # Copias: no se modifican los diccionarios del llamador.
        vals_list = [dict(vals) for vals in vals_list]
        default_company_id = self.env.company.id
        pairs = []
        for vals in vals_list:
            if "code" in vals:
                vals["code"] = normalize_establishment_code(self.env, vals["code"])
                company_id = vals.get("company_id") or self.env.context.get(
                    "default_company_id", default_company_id
                )
                pairs.append((vals["code"], company_id))
        self._erp_check_code_unique(pairs)
        return super().create(vals_list)

    def write(self, vals):
        if "code" in vals:
            vals = dict(vals, code=normalize_establishment_code(self.env, vals["code"]))
        if "code" in vals or "company_id" in vals:
            pairs = [
                (
                    vals.get("code", establishment.code),
                    vals.get("company_id", establishment.company_id.id),
                )
                for establishment in self
            ]
            self._erp_check_code_unique(pairs, exclude_ids=self.ids)
        return super().write(vals)

    @api.model
    def _erp_check_code_unique(self, pairs, exclude_ids=()):
        """Comprueba que los pares (código, empresa) no estén repetidos.

        Detecta repeticiones dentro del propio lote (p. ej. dos filas de un
        archivo de importación) y frente a los establecimientos existentes,
        incluidos los archivados, antes de llegar a la restricción SQL
        ``code_company_uniq`` (que daría un error técnico). Una sola búsqueda
        por lote.

        :param pairs: lista de tuplas ``(code, company_id)`` ya normalizadas
        :param exclude_ids: ids que se están modificando (no cuentan como
            existentes)
        :raises ValidationError: código repetido
        """
        pairs = [(code, company_id) for code, company_id in pairs if code]
        if not pairs:
            return
        seen = set()
        for pair in pairs:
            if pair in seen:
                raise ValidationError(self._erp_duplicate_code_message(pair[0]))
            seen.add(pair)
        # sudo: la unicidad es por empresa e incluye archivados y registros
        # que el usuario podría no ver; solo se devuelve si existe el código,
        # sin datos del otro registro.
        existing = (
            self.sudo()
            .with_context(active_test=False)
            .search_fetch(
                [
                    ("code", "in", list({code for code, _company in pairs})),
                    ("company_id", "in", list({company for _code, company in pairs})),
                    ("id", "not in", list(exclude_ids)),
                ],
                ["code", "company_id"],
            )
        )
        existing_pairs = {(rec.code, rec.company_id.id) for rec in existing}
        for pair in pairs:
            if pair in existing_pairs:
                raise ValidationError(self._erp_duplicate_code_message(pair[0]))

    @api.model
    def _erp_duplicate_code_message(self, code):
        return _(
            "Ya existe un establecimiento con el código %(code)s en la empresa "
            "(incluidos los archivados). Use otro código o modifique el "
            "establecimiento existente.",
            code=code,
        )

    # ------------------------------------------------------------------
    # Provincia
    # ------------------------------------------------------------------
    @api.constrains("state_id")
    def _check_state_ecuador(self):
        for establishment in self:
            state = establishment.state_id
            if state and state.country_id.code != "EC":
                raise ValidationError(
                    _(
                        "La provincia «%(state)s» (%(country)s) no es de Ecuador. "
                        "El establecimiento %(code)s debe estar en una provincia "
                        "de Ecuador.",
                        state=state.name,
                        country=state.country_id.name,
                        code=establishment.code,
                    )
                )

    # ------------------------------------------------------------------
    # Importación
    # ------------------------------------------------------------------
    @api.model
    def get_import_templates(self):
        return [
            {
                "label": _("Plantilla de establecimientos"),
                "template": "/erp_establishment/static/csv/"
                "plantilla_establecimientos.csv",
            }
        ]
