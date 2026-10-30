from contextlib import contextmanager

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import format_date

# Caché acotada a un cálculo de roles (``hr.payslip.compute_sheet``): vive en
# ``cr.cache`` solo mientras dura el cálculo (ver ``hr.payslip._erp_compute_scope``)
# y evita repetir las mismas consultas de parámetros y conceptos por regla y por
# rol. Fuera de un cálculo no hay caché (cada consulta va a la BD).
PAYROLL_COMPUTE_CACHE_KEY = "erp_payroll_ec.compute_cache"

PARAMETER_VALUE_TYPE_SELECTION = [
    ("amount", "Importe (USD)"),
    ("percent", "Porcentaje"),
    ("number", "Número"),
]

# Indicador en ``cr.cache`` (no en el contexto, que controla el cliente RPC) de
# que una acción de estado del parámetro (validar / volver a «A validar») está
# en curso: solo entonces se admite escribir ``state`` (US-017, CA-10).
PARAMETER_TRANSITION_KEY = "erp_payroll_ec.parameter_transition"
PARAMETER_STATE_GROUP = "payroll.group_payroll_manager"
# Campos que definen el valor normativo: si cambian en un parámetro
# «Validado» fuera de una transición, vuelve a «A validar» (US-017, CA-10).
PARAMETER_REVALIDATE_FIELDS = ("value", "value_type", "date_from", "norm", "company_id")

PARAMETER_STATE_SELECTION = [
    ("to_validate", "A validar"),
    ("validated", "Validado"),
]


class ErpPayrollParameter(models.Model):
    """Parámetro normativo de nómina con vigencia por fecha (US-008, CA-1).

    Cada código puede tener varios valores; rige el de ``date_from`` más
    reciente que sea ``<=`` a la fecha consultada. Un registro sin empresa es
    común a todas las empresas; uno con empresa prevalece para esa empresa (la
    consulta ``_get_value`` la implementa la capa de negocio).

    Los porcentajes se guardan como porcentaje (9,45 = 9,45 %), no como
    fracción. ``value`` es ``Float`` con dígitos fijos, lo que en PostgreSQL se
    almacena como ``numeric`` (decimal exacto).
    """

    _name = "erp.payroll.parameter"
    _description = "Parámetro normativo de nómina"
    _inherit = ["mail.thread"]
    _order = "code, date_from desc, id desc"
    _rec_names_search = ["code", "name"]

    # Sin index=True propio: el índice de la restricción única
    # (code, date_from, company_id) empieza por code y cubre la consulta del
    # valor vigente (código = X, fecha <= Y, orden por fecha descendente).
    code = fields.Char(
        string="Código",
        required=True,
        tracking=True,
        help="Código técnico que usan las reglas del rol (p. ej. SBU, "
        "IESS_PERSONAL). Mayúsculas, dígitos y guion bajo.",
    )
    name = fields.Char(string="Nombre", required=True, tracking=True)
    value_type = fields.Selection(
        PARAMETER_VALUE_TYPE_SELECTION,
        string="Tipo de valor",
        required=True,
        default="amount",
        tracking=True,
        help="Importe en USD, porcentaje (se guarda 9,45 para 9,45 %) o número "
        "(divisores, días, meses).",
    )
    value = fields.Float(
        string="Valor",
        required=True,
        digits=(16, 4),
        tracking=True,
        # Sumar valores de parámetros distintos (porcentajes, importes,
        # números) no tiene sentido: sin total en la lista agrupada.
        aggregator=False,
    )
    date_from = fields.Date(
        string="Vigente desde",
        required=True,
        tracking=True,
        help="Fecha desde la que rige el valor, hasta el siguiente valor del "
        "mismo código.",
    )
    norm = fields.Text(
        string="Norma / fuente",
        required=True,
        tracking=True,
        help="Norma y artículo (o acuerdo, resolución) que respalda el valor.",
    )
    state = fields.Selection(
        PARAMETER_STATE_SELECTION,
        string="Estado",
        required=True,
        default="to_validate",
        tracking=True,
        # Un duplicado es un valor nuevo: vuelve a quedar «A validar».
        copy=False,
        help="«A validar»: valor por defecto pendiente de confirmación por el "
        "responsable de nómina o el contador. «Validado»: confirmado.",
    )
    note = fields.Text(string="Notas")
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        index="btree_not_null",
        ondelete="cascade",
        tracking=True,
        help="Vacío: el valor es común a todas las empresas.",
    )
    active = fields.Boolean(string="Activo", default=True, tracking=True)

    _sql_constraints = [
        (
            "code_date_company_uniq",
            "UNIQUE NULLS NOT DISTINCT (code, date_from, company_id)",
            "Ya existe un valor de ese parámetro con la misma fecha de vigencia "
            "para la misma empresa.",
        ),
        (
            "code_format_check",
            "CHECK (code ~ '^[A-Z][A-Z0-9_]{0,63}$')",
            "El código del parámetro debe empezar por una letra mayúscula y "
            "contener solo mayúsculas, dígitos y guion bajo (máximo 64).",
        ),
        (
            "value_positive_check",
            "CHECK (value >= 0)",
            "El valor del parámetro no puede ser negativo.",
        ),
        (
            "percent_range_check",
            "CHECK (value_type <> 'percent' OR value <= 100)",
            "Un porcentaje no puede ser mayor que 100.",
        ),
    ]

    # ------------------------------------------------------------------
    # Consulta (US-008, CA-1)
    # ------------------------------------------------------------------
    @api.model
    def _get_value(self, code, date, company=None):
        """Valor vigente de un parámetro normativo en una fecha.

        - Rige el valor activo con ``date_from`` más reciente que sea ``<=``
          ``date``. Un valor de la empresa prevalece sobre el común (sin
          empresa): si la empresa tiene algún valor vigente se usa el más
          reciente de la empresa; si no, el común más reciente.
        - Los porcentajes se devuelven tal cual se guardan (9,45 = 9,45 %).
        - Dentro de un cálculo de roles el resultado se guarda en la caché del
          cálculo (``PAYROLL_COMPUTE_CACHE_KEY``).

        :param code: código del parámetro (p. ej. ``"SBU"``)
        :param date: ``date``/``datetime`` o cadena ISO
        :param company: ``res.company`` (por defecto, la empresa actual)
        :return: ``float``
        :raises UserError: no hay valor vigente; el mensaje nombra el parámetro
            y la fecha.
        """
        date = fields.Date.to_date(date)
        company = company or self.env.company
        cache = self.env.cr.cache.get(PAYROLL_COMPUTE_CACHE_KEY)
        key = ("parameter", code, date, company.id)
        if cache is not None and key in cache:
            return cache[key]
        # sudo(): consulta de servidor de valores normativos para el cálculo
        # del rol; el filtro de empresa se aplica de forma explícita y solo se
        # devuelve el valor, nunca el registro.
        Parameter = self.sudo()
        records = Parameter.search_fetch(
            [
                ("code", "=", code),
                ("date_from", "<=", date),
                ("company_id", "in", [company.id, False]),
            ],
            ["value", "company_id"],
            order="date_from desc, id desc",
        )
        record = records.filtered("company_id")[:1] or records[:1]
        if not record:
            any_record = Parameter.with_context(active_test=False).search_fetch(
                [("code", "=", code)], ["name"], limit=1
            )
            raise UserError(
                _(
                    "No hay un valor vigente del parámetro de nómina «%(name)s» "
                    "(%(code)s) al %(date)s. Registre en Parámetros de nómina un "
                    "valor activo con «Vigente desde» igual o anterior a esa "
                    "fecha.",
                    name=any_record.name or code,
                    code=code,
                    date=format_date(self.env, date),
                )
            )
        value = record.value
        if cache is not None:
            cache[key] = value
        return value

    # ------------------------------------------------------------------
    # Estado: validación deliberada (US-017, CA-10)
    # ------------------------------------------------------------------
    # Regla: ``state`` solo cambia con ``action_validate`` /
    # ``action_set_to_validate`` (responsable de nómina). Un ``write`` directo
    # que cambie el estado (RPC, importación, statusbar clicable) se rechaza
    # con UserError, salvo ``env.su`` (procesos internos, migraciones). ``create``
    # admite el estado inicial (carga de datos e importación de valores ya
    # revisados por el responsable, único grupo con permiso de creación);
    # ``copy`` siempre deja «A validar». Cambiar el valor normativo de un
    # parámetro «Validado» lo devuelve a «A validar» (``write``).
    @contextmanager
    def _erp_state_transition(self):
        cache = self.env.cr.cache
        cache[PARAMETER_TRANSITION_KEY] = cache.get(PARAMETER_TRANSITION_KEY, 0) + 1
        try:
            yield
        finally:
            cache[PARAMETER_TRANSITION_KEY] -= 1
            if not cache[PARAMETER_TRANSITION_KEY]:
                cache.pop(PARAMETER_TRANSITION_KEY)

    def write(self, vals):
        """Protege el estado y revalida los parámetros cambiados.

        - ``state`` fuera de una transición (``_erp_state_transition``) y
          distinto del actual → ``UserError``; ``env.su`` está exento
          (procesos internos), como en ``hr.payslip``.
        - Un parámetro «Validado» cuyo valor, tipo, vigencia, norma o empresa
          (``PARAMETER_REVALIDATE_FIELDS``) cambia fuera de una transición
          vuelve a «A validar» y deja una nota en el chatter (además del
          seguimiento de los campos). No se revalida si el valor escrito es el
          mismo, ni cuando ``env.su`` fija el estado de forma explícita en la
          misma escritura.
        """
        in_transition = bool(self.env.cr.cache.get(PARAMETER_TRANSITION_KEY))
        if (
            "state" in vals
            and not in_transition
            and not self.env.su
            and any(param.state != vals["state"] for param in self)
        ):
            raise UserError(
                _(
                    "El estado de un parámetro de nómina no se cambia "
                    "directamente. Use el botón «Marcar como validado» (o «Volver "
                    "a A validar») del parámetro."
                )
            )
        to_check = self.browse()
        if (
            not in_transition
            and not ("state" in vals and self.env.su)
            and any(fname in vals for fname in PARAMETER_REVALIDATE_FIELDS)
        ):
            to_check = self.filtered(lambda param: param.state == "validated")
        before = {param.id: param._erp_normative_snapshot() for param in to_check}
        result = super().write(vals)
        changed = to_check.filtered(
            lambda param: param._erp_normative_snapshot() != before[param.id]
        )
        if changed:
            changed._erp_revalidate()
        return result

    def _erp_normative_snapshot(self):
        self.ensure_one()
        return tuple(self[fname] for fname in PARAMETER_REVALIDATE_FIELDS)

    def _erp_revalidate(self):
        """Devuelve a «A validar» los parámetros cuyo valor normativo cambió.
        El usuario ya pasó el control de escritura del ``write`` que lo
        provoca; el cambio de estado es consecuencia de ese cambio."""
        with self._erp_state_transition():
            self.write({"state": "to_validate"})
        for param in self:
            param.message_post(
                body=_(
                    "El parámetro vuelve a «A validar» porque cambió su valor, "
                    "tipo, vigencia, norma o empresa. El responsable de nómina "
                    "debe revisarlo y marcarlo de nuevo como validado."
                ),
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )

    def _erp_check_state_access(self):
        if self.env.su or self.env.user.has_group(PARAMETER_STATE_GROUP):
            return
        raise AccessError(
            _(
                "Solo el responsable de nómina puede cambiar el estado de los "
                "parámetros de nómina. Pida a su responsable que revise el valor."
            )
        )

    def _erp_set_state(self, state):
        self._erp_check_state_access()
        # Sin sudo: el acceso de escritura y las reglas de empresa del usuario
        # se aplican. Los que ya están en el estado destino se ignoran
        # (idempotente ante doble clic o reintento).
        params = self.filtered(lambda p: p.state != state)
        if params:
            with self._erp_state_transition():
                params.write({"state": state})
        return True

    def action_validate(self):
        """Marca los parámetros como «Validado» (botón «Marcar como validado»).

        - Permiso: ``payroll.group_payroll_manager`` (AccessError si no).
        - Admite lote; los ya validados no cambian (idempotente).
        - Traza: el cambio de estado queda en el chatter (``tracking``) con el
          usuario y la fecha.
        """
        return self._erp_set_state("validated")

    def action_set_to_validate(self):
        """Devuelve los parámetros a «A validar» (mismo permiso y reglas que
        ``action_validate``)."""
        return self._erp_set_state("to_validate")
