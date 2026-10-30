import logging
import re

from stdnum.ec import ci

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import SQL, float_compare, float_is_zero, index_exists

from .const import BENEFIT_SELECTION

_logger = logging.getLogger(__name__)

# Campo de res.company con la modalidad por defecto de cada beneficio.
BENEFIT_COMPANY_DEFAULT_FIELD = {
    "reserve_fund": "erp_default_reserve_fund_mode",
    "thirteenth": "erp_default_thirteenth_mode",
    "fourteenth": "erp_default_fourteenth_mode",
}
if set(BENEFIT_COMPANY_DEFAULT_FIELD) != {key for key, _label in BENEFIT_SELECTION}:
    raise RuntimeError("BENEFIT_COMPANY_DEFAULT_FIELD no cubre BENEFIT_SELECTION")

# Identificación escrita solo con dígitos y separadores habituales de cédula
# (``171003406-5``, ``1710 0340 65``).
_CEDULA_WITH_SEPARATORS_RE = re.compile(r"^[0-9][0-9 \-]*$")

# Etiqueta y ayuda de parent_id (US-010, CA-7), compartidas por hr.employee
# y hr.employee.public.
PARENT_ID_STRING = "Jefe inmediato"
PARENT_ID_HELP = (
    "Persona a la que reporta directamente el empleado; define la línea de "
    "supervisión y el organigrama."
)

# Índice único parcial: identificación única entre empleados activos de una
# misma empresa (respaldo en BD de _check_erp_identification_unique).
IDENTIFICATION_UNIQUE_INDEX = "hr_employee_erp_identification_company_active_uniq"


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # Todos los campos nuevos llevan groups="hr.group_hr_user": no existen en
    # hr.employee.public y, sin ese grupo, el prefetch de un usuario sin acceso
    # a hr.employee intentaría leerlos (ver nota de hr.employee en el núcleo).
    erp_establishment_id = fields.Many2one(
        "erp.establishment",
        string="Establecimiento",
        index="btree_not_null",
        ondelete="restrict",
        tracking=True,
        check_company=True,
        groups="hr.group_hr_user",
        help="Establecimiento SRI donde trabaja el empleado. Define su región "
        "y su régimen de décimo cuarto sueldo.",
    )
    erp_region = fields.Selection(
        string="Región",
        related="erp_establishment_id.region",
        store=True,
        groups="hr.group_hr_user",
    )
    erp_decimo_cuarto_regime = fields.Selection(
        string="Régimen de décimo cuarto",
        related="erp_establishment_id.decimo_cuarto_regime",
        store=True,
        groups="hr.group_hr_user",
    )
    erp_disability = fields.Boolean(
        string="Discapacidad", tracking=True, groups="hr.group_hr_user"
    )
    erp_disability_percentage = fields.Float(
        string="Porcentaje de discapacidad",
        digits=(5, 2),
        tracking=True,
        groups="hr.group_hr_user",
        help="Porcentaje de discapacidad del carné (0-100).",
    )
    erp_disability_card = fields.Char(
        string="Número de carné de discapacidad", groups="hr.group_hr_user"
    )
    erp_disability_substitute = fields.Boolean(
        string="Sustituto de persona con discapacidad",
        tracking=True,
        groups="hr.group_hr_user",
    )
    erp_dependent_ids = fields.One2many(
        "erp.hr.dependent",
        "employee_id",
        string="Cargas familiares",
        groups="hr.group_hr_user",
    )
    erp_benefit_election_ids = fields.One2many(
        "erp.hr.benefit.election",
        "employee_id",
        string="Modalidad de décimos y fondos de reserva",
        groups="hr.group_hr_user",
    )
    # Dominio sobre el related almacenado field_active: el formulario muestra
    # solo los valores de datos activos y, como el ORM aplica el dominio del
    # One2many también al escribir (comando SET/replace), los valores de datos
    # archivados no se borran ni se desvinculan al guardar el empleado.
    erp_extra_value_ids = fields.One2many(
        "erp.hr.extra.value",
        "employee_id",
        string="Datos adicionales",
        domain=[("field_active", "=", True)],
        groups="hr.group_hr_user",
    )

    # US-010 (CA-7): el núcleo llama "Manager" ("Gerente" en español) a la
    # relación de supervisión directa; en la empresa es el "Jefe inmediato".
    # Solo cambian etiqueta y ayuda (cómputo, dominio y almacenamiento siguen
    # siendo los del núcleo). Se redefine aquí y en hr.employee.public, y no en
    # hr.employee.base: hr.employee.public redeclara parent_id con su propio
    # string en su clase, que prevalece sobre una extensión del modelo base.
    # hr.department.manager_id ("Gerente" del departamento) no cambia.
    parent_id = fields.Many2one(
        string=PARENT_ID_STRING,
        help=PARENT_ID_HELP,
    )

    # US-010: sin ``groups``, como ``coach_id`` (campo público). Por eso
    # también se declara en ``hr.employee.public`` (ver final del archivo):
    # un campo de hr.employee sin grupo que no exista en el perfil público
    # entraría en el prefetch de un usuario sin acceso a hr.employee y la
    # lectura fallaría con AccessError.
    erp_no_coach = fields.Boolean(
        string="Sin instructor",
        tracking=True,
        help="El empleado no necesita capacitación ni instructor asignado.",
    )

    _sql_constraints = [
        (
            "erp_disability_percentage_range",
            "CHECK(erp_disability_percentage IS NULL "
            "OR (erp_disability_percentage >= 0 "
            "AND erp_disability_percentage <= 100))",
            "El porcentaje de discapacidad debe estar entre 0 y 100.",
        ),
    ]

    # ------------------------------------------------------------------
    # Normalización en create/write
    # ------------------------------------------------------------------
    @api.model
    def _erp_normalize_identification(self, value):
        """Recorta espacios en los extremos y, si el valor solo tiene dígitos,
        espacios y guiones y queda en 10 dígitos (formato de cédula), quita
        los separadores: ``171003406-5`` -> ``1710034065``. Pasaportes y otros
        documentos solo se recortan."""
        if not isinstance(value, str):
            return value
        value = value.strip()
        if _CEDULA_WITH_SEPARATORS_RE.match(value):
            compact = re.sub(r"[ \-]", "", value)
            if len(compact) == 10:
                return compact
        return value or False

    @api.model
    def _erp_prepare_vals(self, vals):
        if "identification_id" in vals:
            vals["identification_id"] = self._erp_normalize_identification(
                vals["identification_id"]
            )
        # Sin discapacidad el porcentaje se limpia (no se valida): el
        # formulario puede ocultarlo al desmarcar la casilla sin dejar un
        # valor huérfano que bloquee el guardado.
        if "erp_disability" in vals and not vals["erp_disability"]:
            vals["erp_disability_percentage"] = 0.0
        # Rango antes de llegar a la BD: en create el INSERT (y su CHECK SQL)
        # ocurre antes que las @api.constrains.
        percentage = vals.get("erp_disability_percentage") or 0.0
        if (
            float_compare(percentage, 0.0, precision_digits=2) < 0
            or float_compare(percentage, 100.0, precision_digits=2) > 0
        ):
            raise ValidationError(
                _(
                    "El porcentaje de discapacidad debe estar entre 0 y 100 "
                    "(recibido: %(percentage)s).",
                    percentage=percentage,
                )
            )
        self._erp_prepare_coach_vals(vals)
        return vals

    @api.model
    def _erp_prepare_coach_vals(self, vals):
        """Coherencia entre ``coach_id`` y ``erp_no_coach`` (US-010, CA-4).

        Modifica ``vals`` en sitio: el llamador (``_erp_prepare_vals``) ya
        trabaja sobre una copia.

        - Instructor explícito (``coach_id`` verdadero): quita la marca, aunque
          venga ``erp_no_coach = True`` en los mismos valores (prevalece el
          instructor).
        - Marca sin instructor explícito: vacía el instructor. Al ir
          ``coach_id`` en los valores, el ORM no lo recalcula con el Gerente
          aunque ``parent_id`` cambie en la misma escritura.
        - ``coach_id = False`` sin la marca en los valores no la toca: borrar
          el instructor de un empleado "Sin instructor" lo deja igual; para
          dejarlo "sin asignar" hay que escribir ``erp_no_coach = False``
          (lo hace el widget del formulario).
        """
        if vals.get("coach_id"):
            vals["erp_no_coach"] = False
        elif vals.get("erp_no_coach"):
            vals["coach_id"] = False
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._erp_prepare_vals(dict(vals)) for vals in vals_list]
        # Unicidad antes del INSERT: el índice único parcial de la BD daría un
        # error técnico en lugar del mensaje en español.
        default_company_id = self.env.context.get(
            "default_company_id", self.env.company.id
        )
        default_active = self.env.context.get("default_active", True)
        self._erp_check_identification_unique_pairs(
            [
                (
                    vals.get("identification_id"),
                    vals.get("company_id") or default_company_id,
                )
                for vals in vals_list
                if vals.get("active", default_active)
            ]
        )
        return super().create(vals_list)

    def write(self, vals):
        vals = self._erp_prepare_vals(dict(vals))
        if {"identification_id", "company_id", "active"} & set(vals):
            # Unicidad antes del UPDATE (ver create).
            self._erp_check_identification_unique_pairs(
                [
                    (
                        vals.get("identification_id", employee.identification_id),
                        vals.get("company_id", employee.company_id.id),
                    )
                    for employee in self
                    if vals.get("active", employee.active)
                ],
                exclude_ids=self.ids,
            )
        return super().write(vals)

    def init(self):
        """Índice único parcial ``(identification_id, company_id)`` para los
        empleados activos con identificación.

        Si la BD ya tiene duplicados (datos anteriores a US-007) el índice no
        se puede crear: se registra un aviso y se omite para no romper la
        instalación ni la actualización; la validación Python sigue
        impidiendo duplicados nuevos. Al depurar los duplicados, actualizar el
        módulo crea el índice.
        """
        super().init()
        cr = self.env.cr
        if index_exists(cr, IDENTIFICATION_UNIQUE_INDEX):
            return
        cr.execute(
            SQL(
                "SELECT identification_id, company_id FROM %s "
                "WHERE active AND identification_id IS NOT NULL "
                "GROUP BY identification_id, company_id HAVING count(*) > 1 "
                "LIMIT 1",
                SQL.identifier(self._table),
            )
        )
        if cr.fetchone():
            _logger.warning(
                "No se crea el índice único %s: hay empleados activos con la "
                "misma identificación en la misma empresa. Depure los "
                "duplicados y actualice el módulo erp_hr_ec.",
                IDENTIFICATION_UNIQUE_INDEX,
            )
            return
        cr.execute(
            SQL(
                "CREATE UNIQUE INDEX IF NOT EXISTS %s ON %s "
                "(identification_id, company_id) "
                "WHERE active AND identification_id IS NOT NULL",
                SQL.identifier(IDENTIFICATION_UNIQUE_INDEX),
                SQL.identifier(self._table),
            )
        )

    # ------------------------------------------------------------------
    # Instructor (US-010)
    # ------------------------------------------------------------------
    @api.depends("parent_id")
    def _compute_coach(self):
        """Los empleados "Sin instructor" no reciben el Gerente como
        instructor; el resto sigue el comportamiento estándar de Odoo.

        No depende de ``erp_no_coach``: marcarla ya vacía el instructor en
        create/write/onchange, y desmarcarla no debe rellenarlo con el Gerente
        (el usuario lo deja "sin asignar" o elige uno). La marca que se lee es
        la del registro en ese momento, también si se escribe junto con
        ``parent_id``.
        """
        no_coach = self.filtered("erp_no_coach")
        no_coach.coach_id = False
        # super() sobre el resto: el cálculo del núcleo asigna el Gerente.
        return super(HrEmployee, self - no_coach)._compute_coach()

    @api.onchange("erp_no_coach")
    def _onchange_erp_no_coach(self):
        """Formulario: marcar "Sin instructor" vacía el instructor."""
        for employee in self:
            if employee.erp_no_coach:
                employee.coach_id = False

    @api.onchange("coach_id")
    def _onchange_coach_id_erp_no_coach(self):
        """Formulario: elegir un instructor quita la marca."""
        for employee in self:
            if employee.coach_id:
                employee.erp_no_coach = False

    # ------------------------------------------------------------------
    # Validaciones
    # ------------------------------------------------------------------
    @api.constrains("identification_id", "country_id")
    def _check_erp_identification_ecuador(self):
        """Valida la cédula ecuatoriana (provincia y dígito verificador):

        - nacionalidad Ecuador: siempre;
        - sin nacionalidad: si la identificación tiene exactamente 10 dígitos
          (formato de cédula). Un extranjero debe indicar su nacionalidad para
          registrar otro documento de 10 dígitos.
        """
        for employee in self:
            identification = employee.identification_id
            if not identification:
                continue
            country = employee.country_id
            must_be_cedula = country.code == "EC" or (
                not country and len(identification) == 10 and identification.isdigit()
            )
            if must_be_cedula and not ci.is_valid(identification):
                raise ValidationError(
                    _(
                        "La cédula «%(cedula)s» de %(employee)s no es válida "
                        "(10 dígitos con provincia y dígito verificador "
                        "correctos). Si el empleado no es ecuatoriano, indique "
                        "su nacionalidad y registre su pasaporte o documento.",
                        cedula=identification,
                        employee=employee.name,
                    )
                )

    @api.constrains("identification_id", "company_id", "active")
    def _check_erp_identification_unique(self):
        """Identificación única entre empleados activos de la misma empresa
        (create y write ya lo comprueban antes de escribir; esta restricción
        cubre cualquier otra vía)."""
        self._erp_check_identification_unique_pairs(
            [
                (employee.identification_id, employee.company_id.id)
                for employee in self
                if employee.active
            ],
            exclude_ids=self.ids,
        )

    @api.model
    def _erp_check_identification_unique_pairs(self, pairs, exclude_ids=()):
        """Comprueba que los pares ``(identificación, empresa)`` de empleados
        activos no se repitan en el lote ni frente a otros empleados activos.

        Una sola búsqueda por lote. El mensaje no revela el otro empleado: el
        usuario podría no tener acceso a él.

        :param pairs: tuplas ``(identification_id, company_id)`` ya
            normalizadas; se ignoran las que no tienen identificación
        :param exclude_ids: ids que se están escribiendo
        :raises ValidationError: identificación repetida
        """
        seen = set()
        for pair in pairs:
            if not pair[0]:
                continue
            if pair in seen:
                raise ValidationError(
                    self._erp_duplicate_identification_message(pair[0])
                )
            seen.add(pair)
        if not seen:
            return
        # sudo: la unicidad debe considerar todos los empleados activos de la
        # empresa aunque el usuario no los vea; solo se comparan identificación
        # y empresa, y nada del otro empleado se devuelve al usuario.
        others = (
            self.sudo()
            .with_context(active_test=True)
            .search_fetch(
                [
                    ("identification_id", "in", list({key[0] for key in seen})),
                    ("company_id", "in", list({key[1] for key in seen})),
                    ("id", "not in", list(exclude_ids)),
                ],
                ["identification_id", "company_id"],
            )
        )
        for other in others:
            if (other.identification_id, other.company_id.id) in seen:
                raise ValidationError(
                    self._erp_duplicate_identification_message(other.identification_id)
                )

    @api.model
    def _erp_duplicate_identification_message(self, identification):
        return _(
            "La identificación «%(identification)s» ya está registrada en otro "
            "empleado activo de la empresa.",
            identification=identification,
        )

    @api.constrains("erp_disability", "erp_disability_percentage")
    def _check_erp_disability_percentage(self):
        for employee in self:
            percentage = employee.erp_disability_percentage or 0.0
            if (
                float_compare(percentage, 0.0, precision_digits=2) < 0
                or float_compare(percentage, 100.0, precision_digits=2) > 0
            ):
                raise ValidationError(
                    _(
                        "El porcentaje de discapacidad de %(employee)s debe estar "
                        "entre 0 y 100 (recibido: %(percentage)s).",
                        employee=employee.name,
                        percentage=percentage,
                    )
                )
            is_zero = float_is_zero(percentage, precision_digits=2)
            if employee.erp_disability and is_zero:
                raise ValidationError(
                    _(
                        "%(employee)s tiene discapacidad: indique el porcentaje "
                        "del carné (mayor que 0 y hasta 100).",
                        employee=employee.name,
                    )
                )
            if not employee.erp_disability and not is_zero:
                raise ValidationError(
                    _(
                        "%(employee)s no tiene marcada la discapacidad: marque "
                        "Discapacidad o deje el porcentaje en 0.",
                        employee=employee.name,
                    )
                )

    @api.constrains("erp_establishment_id", "company_id")
    def _check_erp_establishment_company(self):
        """El establecimiento debe ser de la empresa del empleado.

        ``hr.employee`` no activa ``_check_company_auto``, por lo que el
        ``check_company=True`` del campo no se valida solo en el servidor.
        """
        self._check_company(["erp_establishment_id"])

    @api.constrains("erp_establishment_id")
    def _check_erp_establishment_active(self):
        """Solo se dispara al asignar o cambiar el establecimiento: un
        empleado cuyo establecimiento se archiva después puede seguir
        editándose."""
        for employee in self:
            establishment = employee.erp_establishment_id
            if establishment and not establishment.active:
                raise ValidationError(
                    _(
                        "El establecimiento %(establishment)s está archivado y no "
                        "se puede asignar a %(employee)s. Elija un "
                        "establecimiento activo.",
                        establishment=establishment.display_name,
                        employee=employee.name,
                    )
                )

    # ------------------------------------------------------------------
    # Consulta para nómina (US-008)
    # ------------------------------------------------------------------
    def _get_benefit_mode(self, benefit, date):
        """Modalidad vigente de un beneficio para el empleado en una fecha.

        Contrato (lo consume la nómina, US-008):

        - ``benefit``: ``"reserve_fund"`` (fondos de reserva), ``"thirteenth"``
          (décimo tercero) o ``"fourteenth"`` (décimo cuarto).
        - ``date``: ``datetime.date``/``datetime`` o cadena ISO ``AAAA-MM-DD``.
        - Devuelve ``"monthly"`` (mensualizado) o ``"accumulated"``
          (acumulado): la modalidad de la elección del empleado para ese
          beneficio con la ``date_from`` más reciente que sea ``<= date``; si
          no hay ninguna, el valor por defecto de la empresa del empleado
          (``res.company.erp_default_<beneficio>_mode``).
        - Un solo empleado (``ensure_one``). No depende de los permisos del
          usuario que llama: lee las elecciones con ``sudo``, acotado a este
          empleado y beneficio.

        :raises ValueError: beneficio desconocido o fecha vacía.
        """
        self.ensure_one()
        if benefit not in BENEFIT_COMPANY_DEFAULT_FIELD:
            raise ValueError(
                f"Beneficio desconocido: {benefit!r}; use uno de "
                f"{sorted(BENEFIT_COMPANY_DEFAULT_FIELD)}"
            )
        date = fields.Date.to_date(date)
        if not date:
            raise ValueError("La fecha es obligatoria para consultar la modalidad.")
        # sudo: consulta de servidor para la nómina, cuyo usuario puede no
        # tener el grupo de RRHH que protege las elecciones.
        election = (
            self.env["erp.hr.benefit.election"]
            .sudo()
            .search_fetch(
                [
                    ("employee_id", "=", self.id),
                    ("benefit", "=", benefit),
                    ("date_from", "<=", date),
                ],
                ["mode"],
                order="date_from desc, id desc",
                limit=1,
            )
        )
        if election:
            return election.mode
        return self.sudo().company_id[BENEFIT_COMPANY_DEFAULT_FIELD[benefit]]


class HrEmployeePublic(models.Model):
    _inherit = "hr.employee.public"

    # Columna de la vista SQL del perfil público (US-010): ver la nota de
    # erp_no_coach en hr.employee. Permite además filtrar el directorio.
    erp_no_coach = fields.Boolean(string="Sin instructor", readonly=True)
    # Etiqueta "Jefe inmediato" (ver parent_id en hr.employee).
    parent_id = fields.Many2one(string=PARENT_ID_STRING, help=PARENT_ID_HELP)
