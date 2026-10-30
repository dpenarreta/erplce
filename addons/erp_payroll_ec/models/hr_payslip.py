import logging
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL, float_is_zero, index_exists
from odoo.tools.misc import format_date, formatLang

from odoo.addons.erp_hr_ec.models.hr_employee import BENEFIT_COMPANY_DEFAULT_FIELD
from odoo.addons.payroll_account.models.hr_payslip import (
    HrPayslip as PayrollAccountHrPayslip,
)

from .erp_payroll_parameter import PAYROLL_COMPUTE_CACHE_KEY

_logger = logging.getLogger(__name__)

# Índice único parcial contra roles duplicados (US-008, CA-8): un solo rol
# vigente por empleado, estructura y periodo. Quedan fuera los roles anulados
# (state = 'cancel'), los reembolsos (credit_note) y los roles ya reembolsados
# (refunded_id), para poder emitir el rol corregido tras un reembolso. La
# estructura vacía cuenta como un valor más (COALESCE) para que dos roles sin
# estructura del mismo periodo también choquen. La capa de negocio valida lo
# mismo antes, con mensaje en español; el índice es la garantía final.
PAYSLIP_UNIQUE_PERIOD_INDEX = "hr_payslip_erp_unique_period_idx"
PAYSLIP_UNIQUE_PERIOD_COLUMNS = SQL(
    "employee_id, COALESCE(struct_id, 0), date_from, date_to"
)
PAYSLIP_UNIQUE_PERIOD_WHERE = SQL(
    "state <> 'cancel' AND credit_note IS NOT TRUE AND refunded_id IS NULL"
)
# Campos que forman la clave del índice o deciden si un rol entra en él.
PAYSLIP_UNIQUE_PERIOD_FIELDS = frozenset(
    {
        "employee_id",
        "struct_id",
        "date_from",
        "date_to",
        "state",
        "credit_note",
        "refunded_id",
    }
)

# Estados de contrato que admiten un rol de pagos cuando el contrato está
# asignado explícitamente al rol: "open" (En curso) y "close" (Expirado; p. ej.
# el último rol de un contrato que terminó dentro del periodo).
PAYSLIP_EXPLICIT_CONTRACT_STATES = ("open", "close")
# Contratos del empleado que entran en el rol además del asignado
# (``_get_employee_contracts``): los "open" y "close" que se solapan con el
# periodo. OCA solo usa los "open" cuando el rol no tiene contrato; aquí se
# incluye también el expirado para pagar los días del contrato anterior en
# una renovación a mitad de mes. La validación usa el mismo criterio.
PAYSLIP_IMPLICIT_CONTRACT_STATES = ("open", "close")

# Indicadores en ``cr.cache`` (no en el contexto, que controla el cliente RPC):
# - transición de estado en curso (acciones del rol, ``_erp_transition``);
# - contrato de la pasada actual del motor (``get_lines_dict``);
# - duplicado de rol sin copiar las líneas calculadas (``copy``).
PAYSLIP_TRANSITION_KEY = "erp_payroll_ec.payslip_transition"
PAYSLIP_SINGLE_CONTRACT_KEY = "erp_payroll_ec.payslip_single_contract"
PAYSLIP_SKIP_LINE_COPY_KEY = "erp_payroll_ec.payslip_skip_line_copy"
# Campos que solo cambian las acciones del rol (calcular, confirmar, anular,
# volver a borrador, reembolso).
PAYSLIP_PROTECTED_FIELDS = frozenset({"state", "move_id", "credit_note", "refunded_id"})
# Campos editables de un rol confirmado: nota interna, pagado y las
# preferencias de visualización de la pestaña de líneas (no afectan importes).
PAYSLIP_DONE_WRITABLE_FIELDS = frozenset(
    {"note", "paid", "hide_child_lines", "hide_invisible_lines"}
)
# Estructura cuyo rol se calcula por mes natural.
EC_MONTHLY_STRUCTURE_CODE = "EC_MONTHLY"
# Ajustes del motor OCA.
PREVENT_COMPUTE_ON_CONFIRM_PARAM = "payroll.prevent_compute_on_confirm"
ALLOW_CANCEL_PAYSLIPS_PARAM = "payroll.allow_cancel_payslips"
PAYROLL_MANAGER_GROUP = "payroll.group_payroll_manager"

# Reglas de la estructura «Rol mensual Ecuador» (data/hr_payroll_structure_data.xml).
# Regla de conceptos propios -> tipo de concepto que suma.
CONCEPT_RULES = {"INC_OTHER": "income", "DED_OTHER": "deduction"}
# Regla de beneficio -> (beneficio de erp_hr_ec, modalidad en la que aplica).
BENEFIT_RULES = {
    "FR_PAID": ("reserve_fund", "monthly"),
    "FR_ACCRUED": ("reserve_fund", "accumulated"),
    "D13_PAID": ("thirteenth", "monthly"),
    "D13_PROV": ("thirteenth", "accumulated"),
    "D14_PAID": ("fourteenth", "monthly"),
    "D14_PROV_COSTA": ("fourteenth", "accumulated"),
    "D14_PROV_SIERRA": ("fourteenth", "accumulated"),
}
# Provisión de décimo cuarto -> régimen del establecimiento (erp_establishment).
FOURTEENTH_REGIME_RULES = {
    "D14_PROV_COSTA": "costa_galapagos",
    "D14_PROV_SIERRA": "sierra_amazonia",
}
IESS_RULES = {"IESS_PERSONAL": "IESS_PERSONAL", "IESS_PATRONAL": "IESS_PATRONAL"}
ALWAYS_APPLY_RULES = ("BASIC", "GROSS", "NET")
EC_RULE_CODES = frozenset(
    {*CONCEPT_RULES, *BENEFIT_RULES, *IESS_RULES, *ALWAYS_APPLY_RULES}
)
# Tipos de cuenta en los que el apunte lleva al empleado como tercero.
EMPLOYEE_PARTNER_ACCOUNT_TYPES = (
    "asset_receivable",
    "liability_current",
    "liability_payable",
)


def days_30(date_from, date_to, month_days):
    """Días de ``date_from`` a ``date_to`` (ambos incluidos) con la convención
    laboral de mes de ``month_days`` días (comercial 30/360).

    Se recorre cada mes natural del intervalo; en cada uno cuenta como día
    inicial ``min(día, month_days)`` y como día final ``month_days`` si el
    tramo llega al último día del mes (31 o 28/29 de febrero) o
    ``min(día, month_days)`` si no. Así, con 30 días base:

    - mes completo = 30 (enero, abril o febrero);
    - ingreso el 16 de enero = 15 (16 al 30); el día 31 no suma;
    - ingreso el 31 de enero = 1; salida el 15 = 15; salida el 30 de un mes
      de 31 días = 30;
    - febrero: ingreso el 15 = 16 (15 al «30»); salida el 27 = 27; salida el
      último día (28/29) = 30.

    :return: ``int`` (0 si ``date_from > date_to``)
    """
    total = 0
    cursor = date_from
    while cursor <= date_to:
        month_end = cursor + relativedelta(day=31)
        segment_end = min(date_to, month_end)
        first_day = min(cursor.day, month_days)
        last_day = (
            month_days if segment_end == month_end else min(segment_end.day, month_days)
        )
        total += max(last_day - first_day + 1, 0)
        cursor = month_end + timedelta(days=1)
    return total


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    # Régimen de décimo cuarto del empleado, visible en el rol (US-008, CA-6).
    # - compute_sudo=True (explícito; es el valor por defecto de un related):
    #   el campo del empleado tiene groups="hr.group_hr_user"; el usuario de
    #   nómina lo hereda hoy por grupo implicado, pero el rol no debe depender
    #   de ello. Solo se recorre employee_id del propio rol (que el usuario ya
    #   puede leer) y se devuelve un valor de selección.
    # - groups explícito: si no, el related copiaría hr.group_hr_user.
    # - No almacenado: muestra el régimen actual del establecimiento; el
    #   régimen con el que se calculó un rol queda en el código de su línea de
    #   provisión (D14_PROV_COSTA / D14_PROV_SIERRA). Almacenarlo obligaría a
    #   recalcularlo en los roles confirmados al cambiar el establecimiento.
    erp_decimo_cuarto_regime = fields.Selection(
        related="employee_id.erp_decimo_cuarto_regime",
        string="Régimen de décimo cuarto",
        compute_sudo=True,
        groups="payroll.group_payroll_user",
    )

    def init(self):
        """Crea el índice único parcial ``PAYSLIP_UNIQUE_PERIOD_INDEX``.

        Si la BD ya tiene roles duplicados (anteriores a US-008) el índice no se
        puede crear: se registra un aviso y se omite para no romper la
        instalación ni la actualización; la validación de negocio sigue
        impidiendo duplicados nuevos. Al depurarlos, actualizar el módulo crea
        el índice.
        """
        super().init()
        cr = self.env.cr
        if index_exists(cr, PAYSLIP_UNIQUE_PERIOD_INDEX):
            return
        cr.execute(
            SQL(
                "SELECT 1 FROM %s WHERE %s GROUP BY %s HAVING count(*) > 1 LIMIT 1",
                SQL.identifier(self._table),
                PAYSLIP_UNIQUE_PERIOD_WHERE,
                PAYSLIP_UNIQUE_PERIOD_COLUMNS,
            )
        )
        if cr.fetchone():
            _logger.warning(
                "No se crea el índice único %s: hay roles de pagos no anulados "
                "duplicados (mismo empleado, estructura y periodo). Anule los "
                "duplicados y actualice el módulo erp_payroll_ec.",
                PAYSLIP_UNIQUE_PERIOD_INDEX,
            )
            return
        cr.execute(
            SQL(
                "CREATE UNIQUE INDEX IF NOT EXISTS %s ON %s (%s) WHERE %s",
                SQL.identifier(PAYSLIP_UNIQUE_PERIOD_INDEX),
                SQL.identifier(self._table),
                PAYSLIP_UNIQUE_PERIOD_COLUMNS,
                PAYSLIP_UNIQUE_PERIOD_WHERE,
            )
        )

    # ------------------------------------------------------------------
    # Rol duplicado (US-008, CA-8)
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """Valida, antes de insertar:

        - que un rol nuevo nazca en borrador, sin asiento ni rol reembolsado
          (``_erp_check_create_allowed``);
        - que no se cree un segundo rol no anulado del mismo empleado,
          estructura y periodo (mensaje en español en lugar del error del
          índice único)."""
        self._erp_check_create_allowed(vals_list)
        self._erp_check_duplicate_period([(self.browse(), vals) for vals in vals_list])
        return super().create(vals_list)

    def write(self, vals):
        """Valida, antes de escribir:

        - campos protegidos y rol confirmado (``_erp_check_write_allowed``);
        - rol duplicado cuando cambia algún campo de la clave (empleado,
          estructura, periodo) o de las condiciones del índice (estado,
          reembolso). Un cambio solo de estado que no saca a ningún rol de
          «anulado» no puede crear un duplicado (el rol ya estaba en el
          índice o sale de él) y no se comprueba: así calcular o confirmar un
          lote no hace una búsqueda por rol.
        """
        self._erp_check_write_allowed(vals)
        if self._erp_write_needs_duplicate_check(vals):
            self._erp_check_duplicate_period([(slip, vals) for slip in self])
        return super().write(vals)

    def _erp_write_needs_duplicate_check(self, vals):
        key_fields = PAYSLIP_UNIQUE_PERIOD_FIELDS.intersection(vals)
        if not key_fields:
            return False
        if key_fields == {"state"}:
            return vals["state"] != "cancel" and any(
                slip.state == "cancel" for slip in self
            )
        return True

    # ------------------------------------------------------------------
    # Transiciones de estado (US-008, CA-8)
    # ------------------------------------------------------------------
    def _erp_in_transition(self):
        return bool(self.env.cr.cache.get(PAYSLIP_TRANSITION_KEY))

    @contextmanager
    def _erp_transition(self):
        """Marca en ``cr.cache`` que una acción del rol (calcular, confirmar,
        anular, volver a borrador, reembolso) está en curso: solo entonces se
        escriben los campos protegidos (``PAYSLIP_PROTECTED_FIELDS``) y los de
        un rol confirmado. Se usa ``cr.cache`` y no el contexto porque el
        contexto lo controla el cliente RPC. Admite anidamiento (el reembolso
        confirma el rol copiado).

        Alcance del marcador: es **por cursor** (``cr.cache`` vive lo que
        vive el cursor de la petición, no se comparte entre peticiones ni
        entre usuarios) y se retira en ``finally``: si la acción falla (p. ej.
        ``compute_sheet`` con ``UserError``), el contador vuelve a su valor y
        el resto del mismo cursor sigue con la guarda activa. Un cambio de
        usuario (``with_user``) dentro del mismo cursor durante la acción sí
        lo comparte, por eso solo se abre alrededor del código de la acción,
        nunca alrededor de código que ejecute el cliente."""
        cache = self.env.cr.cache
        cache[PAYSLIP_TRANSITION_KEY] = cache.get(PAYSLIP_TRANSITION_KEY, 0) + 1
        try:
            yield
        finally:
            cache[PAYSLIP_TRANSITION_KEY] -= 1
            if not cache[PAYSLIP_TRANSITION_KEY]:
                cache.pop(PAYSLIP_TRANSITION_KEY)

    @contextmanager
    def _erp_cache_flag(self, key):
        cache = self.env.cr.cache
        previous = cache.get(key)
        cache[key] = True
        try:
            yield
        finally:
            if previous is None:
                cache.pop(key, None)
            else:
                cache[key] = previous

    def _erp_field_labels(self, field_names):
        return ", ".join(
            sorted(
                f"«{self._fields[name]._description_string(self.env)}»"
                for name in field_names
            )
        )

    @api.model
    def _erp_check_create_allowed(self, vals_list):
        """Fuera de una acción del rol, un rol nuevo nace en borrador, sin
        asiento y sin rol reembolsado. ``credit_note`` sí se admite (lotes de
        reembolso de OCA): el rol se calcula y confirma con el flujo normal.
        ``env.su`` (procesos internos, migraciones) no se restringe."""
        if self.env.su or self._erp_in_transition():
            return
        for vals in vals_list:
            if (
                vals.get("state") not in (None, False, "draft")
                or vals.get("move_id")
                or vals.get("refunded_id")
            ):
                raise UserError(
                    _(
                        "Un rol de pagos nuevo se crea en borrador, sin asiento "
                        "contable ni rol reembolsado: el estado y el asiento los "
                        "fijan las acciones Calcular, Confirmar, Anular y "
                        "Reembolso."
                    )
                )

    def _erp_check_write_allowed(self, vals):
        """Fuera de una acción del rol (``_erp_transition``):

        - ``state``, ``move_id``, ``credit_note`` y ``refunded_id`` no se
          escriben (``UserError``), tampoco el responsable de nómina;
        - un rol confirmado solo admite ``PAYSLIP_DONE_WRITABLE_FIELDS`` (nota
          interna, pagado y preferencias de visualización).

        ``env.su`` no se restringe: lo usan procesos internos (migraciones,
        scripts de soporte) que asumen la responsabilidad del cambio; ningún
        usuario de nómina llega aquí con ``su``.
        """
        if not self or self.env.su or self._erp_in_transition():
            return
        protected = PAYSLIP_PROTECTED_FIELDS.intersection(vals)
        if protected:
            raise UserError(
                _(
                    "Los campos %(fields)s del rol de pagos no se modifican "
                    "directamente: cambian solo con las acciones del rol "
                    "(Calcular, Confirmar, Anular, Volver a borrador y "
                    "Reembolso).",
                    fields=self._erp_field_labels(protected),
                )
            )
        done = self.filtered(lambda slip: slip.state == "done")
        locked = set(vals) - PAYSLIP_DONE_WRITABLE_FIELDS
        if done and locked:
            raise UserError(
                _(
                    "El rol de pagos confirmado %(payslips)s no se puede "
                    "modificar (%(fields)s): solo admite la nota interna y la "
                    "marca de pagado. Para corregirlo, emita un reembolso o "
                    "anúlelo.",
                    payslips=", ".join(done.mapped(lambda s: s.number or s.name or "")),
                    fields=self._erp_field_labels(locked),
                )
            )

    def copy(self, default=None):
        """Duplica el rol.

        - Nunca copia ``refunded_id`` (el rol nuevo no ha sido reembolsado).
        - Fuera de una acción del rol (el usuario pulsa «Duplicar») no copia
          las líneas calculadas: el rol nuevo nace en borrador y se calcula
          con el flujo normal. Así el usuario de nómina, que no escribe
          líneas, duplica sin error de permisos, y un borrador nunca lleva
          importes que no salen de su propio cálculo. Las entradas variables
          y los días trabajados sí se copian.
        - Dentro de ``refund_sheet`` (reembolso, solo responsable) se copian
          las líneas: el reembolso invierte exactamente el rol original.
        """
        default = dict(default or {})
        default.setdefault("refunded_id", False)
        if self._erp_in_transition():
            return super().copy(default)
        with self._erp_cache_flag(PAYSLIP_SKIP_LINE_COPY_KEY):
            return super().copy(default)

    def _erp_check_duplicate_period(self, items):
        """Lanza ``UserError`` si alguno de los roles resultantes de ``items``
        choca con otro del lote o de la BD en el índice
        ``PAYSLIP_UNIQUE_PERIOD_INDEX``.

        :param items: lista de ``(rol existente o vacío, vals)``
        """
        defaults = {}
        if any(not record for record, _vals in items):
            defaults = self.default_get(
                ["date_from", "date_to", "state", "struct_id", "credit_note"]
            )
        keys = []
        for record, vals in items:

            def value(fname, record=record, vals=vals):
                if fname in vals:
                    result = vals[fname]
                elif record:
                    result = record[fname]
                else:
                    result = defaults.get(fname)
                return result.id if isinstance(result, models.BaseModel) else result

            if (
                value("state") == "cancel"
                or value("credit_note")
                or value("refunded_id")
                or not value("employee_id")
            ):
                continue
            keys.append(
                (
                    record.id,
                    (
                        value("employee_id"),
                        value("struct_id") or 0,
                        fields.Date.to_date(value("date_from")),
                        fields.Date.to_date(value("date_to")),
                    ),
                )
            )
        if not keys:
            return
        counts = Counter(key for _record_id, key in keys)
        conflicts = {key for key, count in counts.items() if count > 1}
        # sudo(): la comprobación debe ver todos los roles del empleado aunque
        # las reglas de registro del usuario (departamento, empresas activas)
        # oculten alguno, para que nunca salte el error técnico del índice;
        # solo se leen la clave y los nombres del propio periodo.
        existing = (
            self.sudo()
            .with_context(active_test=False)
            .search_fetch(
                [
                    ("employee_id", "in", list({key[0] for _rid, key in keys})),
                    ("date_from", "in", list({key[2] for _rid, key in keys})),
                    ("state", "!=", "cancel"),
                    ("credit_note", "!=", True),
                    ("refunded_id", "=", False),
                    ("id", "not in", [rid for rid, _key in keys if rid]),
                ],
                ["employee_id", "struct_id", "date_from", "date_to"],
            )
        )
        existing_keys = {
            (
                slip.employee_id.id,
                slip.struct_id.id or 0,
                slip.date_from,
                slip.date_to,
            )
            for slip in existing
        }
        conflicts |= {key for _rid, key in keys if key in existing_keys}
        if not conflicts:
            return
        Employee = self.env["hr.employee"].sudo()
        Structure = self.env["hr.payroll.structure"].sudo()
        details = "\n".join(
            self.env._(
                "- %(employee)s: del %(date_from)s al %(date_to)s, estructura "
                "«%(structure)s»",
                employee=Employee.browse(employee_id).name,
                date_from=format_date(self.env, date_from),
                date_to=format_date(self.env, date_to),
                structure=Structure.browse(struct_id).name
                if struct_id
                else self.env._("ninguna"),
            )
            for employee_id, struct_id, date_from, date_to in sorted(
                conflicts, key=lambda key: (key[0], key[2], key[1])
            )
        )
        raise UserError(
            _(
                "Ya existe un rol de pagos no anulado del mismo empleado, "
                "estructura y periodo:\n%(details)s\n\nAnule el rol existente (o "
                "emita su reembolso) antes de registrar otro.",
                details=details,
            )
        )

    # ------------------------------------------------------------------
    # Cálculo (US-008, CA-2 a CA-9)
    # ------------------------------------------------------------------
    def compute_sheet(self):
        """Calcula los roles de pagos.

        Validaciones, en lote y antes de escribir:

        - rol confirmado o anulado: no se recalcula (``UserError``);
        - contrato vigente en el periodo (US-006, CA-4);
        - periodo dentro de un mes natural en «Rol mensual Ecuador»;
        - permiso de escritura del usuario sobre los roles (ACL y reglas de
          registro de ``hr.payslip``): ``check_access('write')``.

        Sustituye el cuerpo de ``compute_sheet`` de OCA (borra las líneas y
        las vuelve a crear desde ``get_lines_dict``) para escribir las líneas
        con ``sudo()``: las líneas del rol son de solo lectura para el usuario
        de nómina (CA-8), pero él sí calcula (CA-9). El cálculo de las reglas
        se ejecuta con el usuario real; solo el borrado y la creación de
        líneas van con ``sudo()``, después de comprobar su permiso sobre el
        rol. Durante el cálculo se usa una caché de parámetros, conceptos y
        modalidades (``_erp_compute_scope``).

        Acceso: usuario de nómina (``payroll.group_payroll_user``).
        """
        self._erp_check_recomputable()
        self._check_contract_in_period()
        self._erp_check_period_in_month()
        self.check_access("write")
        PayslipLine = self.env["hr.payslip.line"]
        with self._erp_transition(), self._erp_compute_scope():
            self._erp_prefetch_contracts()
            self._erp_prefetch_assignments()
            self._erp_prefetch_benefit_modes()
            for payslip in self:
                number = payslip.number or self.env["ir.sequence"].next_by_code(
                    "salary.slip"
                )
                lines_vals = list(payslip.get_lines_dict().values())
                # sudo(): las líneas son de solo lectura para el usuario de
                # nómina; ya se comprobó su permiso de escritura sobre el rol
                # (check_access) y las líneas salen del cálculo, no de él.
                payslip.line_ids.sudo().unlink()
                PayslipLine.sudo().create(
                    [dict(vals, slip_id=payslip.id) for vals in lines_vals]
                )
                payslip.write(
                    {
                        "number": number,
                        "state": "verify",
                        "compute_date": fields.Date.today(),
                    }
                )
        return True

    def _erp_check_lines_editable(self):
        """Las líneas de un rol confirmado no se crean, modifican ni borran
        (tampoco el responsable de nómina): un rol confirmado se corrige con un
        reembolso o anulándolo. Las de un rol anulado no se bloquean aquí para
        no impedir su borrado; ya no se recalcula (``_erp_check_recomputable``).
        """
        locked = self.filtered(lambda slip: slip.state == "done")
        if locked:
            raise UserError(
                _(
                    "No se pueden modificar las líneas de un rol de pagos "
                    "confirmado: %(payslips)s.",
                    payslips=", ".join(
                        locked.mapped(lambda slip: slip.number or slip.name or "")
                    ),
                )
            )

    def _erp_check_recomputable(self):
        """Un rol confirmado o anulado no se recalcula."""
        locked = self.filtered(lambda slip: slip.state in ("done", "cancel"))
        if locked:
            raise UserError(
                _(
                    "No se puede recalcular un rol de pagos confirmado o anulado: "
                    "%(payslips)s. Un rol confirmado se corrige con un reembolso "
                    "o anulándolo; uno anulado debe volver a borrador.",
                    payslips=", ".join(
                        locked.mapped(lambda s: s.number or s.name or "")
                    ),
                )
            )

    @contextmanager
    def _erp_compute_scope(self):
        """Abre la caché del cálculo en ``cr.cache`` (si no hay una abierta) y
        la cierra al terminar, también si el cálculo falla."""
        cache = self.env.cr.cache
        owner = PAYROLL_COMPUTE_CACHE_KEY not in cache
        if owner:
            cache[PAYROLL_COMPUTE_CACHE_KEY] = {}
        try:
            yield cache[PAYROLL_COMPUTE_CACHE_KEY]
        finally:
            if owner:
                cache.pop(PAYROLL_COMPUTE_CACHE_KEY, None)

    def _erp_memo(self, key, compute):
        """Devuelve ``compute()`` guardándolo en la caché del cálculo si hay
        una abierta (fuera de un cálculo se calcula siempre)."""
        cache = self.env.cr.cache.get(PAYROLL_COMPUTE_CACHE_KEY)
        if cache is None:
            return compute()
        if key not in cache:
            cache[key] = compute()
        return cache[key]

    def _erp_check_period_in_month(self):
        """El rol de la estructura «Rol mensual Ecuador» (o de una estructura
        hija) cubre días de un único mes natural: el prorrateo por días, los
        parámetros (vigentes al final del periodo) y los conceptos fijos
        (importe mensual) se calculan por mes."""
        invalid = self.filtered(
            lambda slip: slip.date_from
            and slip.date_to
            and (slip.date_from.year, slip.date_from.month)
            != (slip.date_to.year, slip.date_to.month)
            and EC_MONTHLY_STRUCTURE_CODE
            in (slip.struct_id or slip.contract_id.struct_id)
            .get_structure_with_parents()
            .mapped("code")
        )
        if not invalid:
            return
        details = "\n".join(
            self.env._(
                "- %(employee)s: del %(date_from)s al %(date_to)s",
                employee=slip.employee_id.name,
                date_from=format_date(self.env, slip.date_from),
                date_to=format_date(self.env, slip.date_to),
            )
            for slip in invalid
        )
        raise UserError(
            _(
                "El rol mensual de Ecuador se calcula por mes natural y estos "
                "roles abarcan más de un mes:\n%(details)s\n\nAjuste las fechas "
                "para que el periodo empiece y termine dentro del mismo mes "
                "(un rol por mes).",
                details=details,
            )
        )

    # --- Varios contratos en un rol --------------------------------------
    def get_lines_dict(self):
        """Líneas del rol: una pasada del motor OCA por cada contrato.

        OCA recorre todos los contratos de un rol en una sola pasada con una
        lista negra de reglas común: una regla que no aplica al primer
        contrato (p. ej. IESS en un contrato sin relación laboral) quedaba
        vetada también para los siguientes, y las sumas por categoría
        (``categories``) se acumulaban entre contratos. Aquí cada contrato se
        evalúa en su propia llamada a OCA, con ``_get_employee_contracts``
        reducido a ese contrato (``PAYSLIP_SINGLE_CONTRACT_KEY``): lista
        negra, categorías y resultados de reglas propios del contrato.

        OCA identifica cada línea por ``<código>-<id del contrato>``: un rol
        con dos contratos tiene, p. ej., dos líneas BASIC, GROSS y NET (una por
        contrato). El neto del rol es la suma de sus líneas NET y el asiento
        recoge todas las líneas (``_erp_prepare_move_vals``), así que cuadra
        igual que con un contrato. ``payroll.contracts.count`` en el código de
        una regla vale 1 en cada pasada.
        """
        lines_dict = {}
        for payslip in self:
            contracts = payslip._erp_get_contracts()
            slip_lines = {}
            if len(contracts) <= 1:
                slip_lines.update(super(HrPayslip, payslip).get_lines_dict())
            else:
                for contract in contracts.sorted(lambda c: (c.date_start, c.id)):
                    with payslip._erp_single_contract(contract):
                        slip_lines.update(super(HrPayslip, payslip).get_lines_dict())
            payslip._erp_check_lines_net(slip_lines)
            lines_dict.update(slip_lines)
        return lines_dict

    def _erp_check_lines_net(self, lines):
        """Neto del rol completo (US-008, CA-7): la suma de las líneas NET de
        todas las pasadas de contrato no puede ser negativa.

        Se valida sobre el rol y no por contrato: en una renovación el día
        30/31 el contrato nuevo cubre un solo día y su NET puede ser negativo
        (p. ej. un descuento fijo de 100 sobre 33,33 de sueldo) aunque el neto
        total del empleado sea positivo. Solo en «Rol mensual Ecuador» (o una
        estructura hija), la que define la regla NET de Ecuador.

        :param lines: ``dict`` de ``get_lines_dict`` de este rol
        :raises UserError: neto total negativo (antes de escribir líneas)
        """
        self.ensure_one()
        if not self._erp_is_ec_monthly():
            return
        currency = self.company_id.currency_id or self.env.company.currency_id
        net = currency.round(
            sum(
                currency.round(vals.get("total") or 0.0)
                for vals in lines.values()
                if vals.get("code") == "NET"
            )
        )
        self._erp_check_net(net, currency)

    def _erp_is_ec_monthly(self):
        self.ensure_one()
        return EC_MONTHLY_STRUCTURE_CODE in (
            (self.struct_id or self.contract_id.struct_id)
            .get_structure_with_parents()
            .mapped("code")
        )

    @contextmanager
    def _erp_single_contract(self, contract):
        self.ensure_one()
        cache = self.env.cr.cache
        selected = cache.setdefault(PAYSLIP_SINGLE_CONTRACT_KEY, {})
        selected[self.id] = contract.id
        try:
            yield
        finally:
            selected.pop(self.id, None)
            if not selected:
                cache.pop(PAYSLIP_SINGLE_CONTRACT_KEY, None)

    def _get_employee_contracts(self):
        """Contratos del rol (motor OCA): el asignado más los del empleado en
        curso o expirados que se solapan con el periodo
        (``_erp_get_contracts``). Durante la pasada de un contrato
        (``get_lines_dict``) solo ese contrato."""
        contracts = self.env["hr.contract"]
        selected = self.env.cr.cache.get(PAYSLIP_SINGLE_CONTRACT_KEY) or {}
        for payslip in self:
            slip_contracts = payslip._erp_get_contracts()
            if payslip.id in selected:
                slip_contracts = slip_contracts.filtered(
                    lambda c, cid=selected[payslip.id]: c.id == cid
                )
            contracts |= slip_contracts
        return contracts

    # --- Datos del rol --------------------------------------------------
    def _erp_get_contracts(self):
        """Todos los contratos del rol, del inicio más reciente al más antiguo
        (``onchange_employee`` de OCA asigna al rol el primero)."""
        self.ensure_one()
        return self._erp_memo(("contracts", self.id), self._erp_compute_contracts)

    def _erp_compute_contracts(self, candidates=None):
        """Contrato asignado al rol más los contratos del empleado
        ``PAYSLIP_IMPLICIT_CONTRACT_STATES`` vigentes algún día del periodo
        (p. ej. renovación a mitad de mes: el expirado hasta el 15 y el nuevo
        desde el 16). ``candidates``: contratos ya buscados en lote
        (``_erp_prefetch_contracts``)."""
        self.ensure_one()
        Contract = self.env["hr.contract"]
        if not self.employee_id or not self.date_from or not self.date_to:
            return self.contract_id
        if candidates is None:
            candidates = Contract.search(
                [
                    ("employee_id", "=", self.employee_id.id),
                    ("state", "in", PAYSLIP_IMPLICIT_CONTRACT_STATES),
                    ("date_start", "<=", self.date_to),
                    "|",
                    ("date_end", "=", False),
                    ("date_end", ">=", self.date_from),
                ]
            )
        contracts = self.contract_id | candidates.filtered(
            lambda c: c.employee_id == self.employee_id
            and self._contract_overlaps_period(c)
        )
        return contracts.sorted(lambda c: (c.date_start, c.id), reverse=True)

    def _erp_prefetch_contracts(self):
        """Carga en la caché del cálculo los contratos de todos los roles de
        ``self`` con una sola búsqueda."""
        cache = self.env.cr.cache.get(PAYROLL_COMPUTE_CACHE_KEY)
        if cache is None or not self:
            return
        candidates = self.env["hr.contract"].search(
            [
                ("employee_id", "in", self.employee_id.ids),
                ("state", "in", PAYSLIP_IMPLICIT_CONTRACT_STATES),
                ("date_start", "<=", max(self.mapped("date_to"))),
                "|",
                ("date_end", "=", False),
                ("date_end", ">=", min(self.mapped("date_from"))),
            ]
        )
        for slip in self:
            cache[("contracts", slip.id)] = slip._erp_compute_contracts(candidates)

    def _erp_get_main_contract(self):
        """Contrato que recibe los conceptos fijos (y las entradas sin
        contrato del rol): el de inicio más reciente de los contratos del rol
        (en una renovación a mitad de mes, el contrato nuevo). Así un concepto
        fijo se carga una sola vez por rol."""
        self.ensure_one()
        return self._erp_get_contracts()[:1]

    def _erp_param(self, code):
        """Valor del parámetro ``code`` vigente al final del periodo del rol,
        para su empresa."""
        self.ensure_one()
        return self.env["erp.payroll.parameter"]._get_value(
            code, self.date_to, self.company_id
        )

    def _erp_param_positive(self, code):
        """Parámetro que se usa como divisor o número de días/meses: debe ser
        mayor que cero."""
        value = self._erp_param(code)
        if value <= 0:
            raise UserError(
                _(
                    "El parámetro de nómina %(code)s vigente al %(date)s debe ser "
                    "mayor que cero para calcular el rol.",
                    code=code,
                    date=format_date(self.env, self.date_to),
                )
            )
        return value

    def _erp_month_days(self):
        return int(self._erp_param_positive("MONTH_DAYS"))

    def _erp_currency(self, contract):
        return contract.company_id.currency_id or self.company_id.currency_id

    def _erp_has_labor_relationship(self, contract):
        """Relación laboral del contrato (IESS, fondos de reserva y décimos).
        Un contrato sin tipo se trata como relación laboral (la opción
        conservadora: no omite aportes)."""
        return (
            not contract.contract_type_id
            or contract.contract_type_id.erp_labor_relationship
        )

    def _erp_get_benefit_mode(self, benefit):
        """Modalidad del beneficio vigente al final del periodo del rol."""
        self.ensure_one()
        return self._erp_memo(
            ("benefit_mode", self.id, benefit),
            lambda: self.employee_id._get_benefit_mode(benefit, self.date_to),
        )

    def _erp_get_fourteenth_regime(self):
        """Régimen de décimo cuarto del establecimiento del empleado; sin
        establecimiento el rol no se puede calcular."""
        self.ensure_one()
        regime = self.employee_id.erp_decimo_cuarto_regime
        if not regime:
            raise UserError(
                _(
                    "No se puede calcular el rol de %(employee)s: el empleado no "
                    "tiene establecimiento asignado y sin él no se conoce su "
                    "régimen de décimo cuarto sueldo (Costa / Sierra). Asigne su "
                    "establecimiento en la ficha del empleado.",
                    employee=self.employee_id.name,
                )
            )
        return regime

    def _erp_get_contract_period(self, contract):
        """Tramo del periodo del rol cubierto por el contrato:
        ``(desde, hasta)`` o ``None``."""
        self.ensure_one()
        date_from = max(self.date_from, contract.date_start)
        date_to = min(self.date_to, contract.date_end or self.date_to)
        if date_from > date_to:
            return None
        return date_from, date_to

    def _erp_get_worked_days(self, contract):
        """Días del periodo cubiertos por el contrato (convención de
        ``days_30`` con el parámetro MONTH_DAYS)."""
        period = self._erp_get_contract_period(contract)
        if not period:
            return 0
        return days_30(*period, self._erp_month_days())

    def _erp_get_reserve_fund_days(self, contract):
        """Días del periodo con derecho a fondos de reserva.

        El derecho nace el día en que se cumplen RESERVE_FUND_MIN_MONTHS meses
        desde ``first_contract_date`` del empleado (o el inicio del contrato si
        no la hay): ingreso el 15/01/2025 con 12 meses -> derecho desde el
        15/01/2026. En el mes en que se cumple, los fondos son proporcionales a
        los días con derecho (convención de ``days_30``).
        """
        self.ensure_one()
        period = self._erp_get_contract_period(contract)
        if not period:
            return 0
        start_date = self.employee_id.first_contract_date or contract.date_start
        months = int(self._erp_param("RESERVE_FUND_MIN_MONTHS"))
        right_from = start_date + relativedelta(months=months)
        date_from = max(period[0], right_from)
        if date_from > period[1]:
            return 0
        return days_30(date_from, period[1], self._erp_month_days())

    # --- Conceptos propios ---------------------------------------------
    def _erp_prefetch_assignments(self):
        """Carga en la caché del cálculo, con una sola búsqueda, las
        asignaciones fijas activas de todos los empleados de ``self``."""
        if not self:
            return
        assignments = self.env["erp.payroll.employee.concept"].search(
            [
                ("employee_id", "in", self.employee_id.ids),
                ("date_from", "<=", max(self.mapped("date_to"))),
                "|",
                ("date_to", "=", False),
                ("date_to", ">=", min(self.mapped("date_from"))),
            ]
        )
        cache = self.env.cr.cache.get(PAYROLL_COMPUTE_CACHE_KEY)
        if cache is None:
            return
        by_employee = defaultdict(lambda: assignments.browse())
        for assignment in assignments:
            by_employee[assignment.employee_id.id] |= assignment
        for slip in self:
            cache[slip._erp_assignments_cache_key()] = by_employee[
                slip.employee_id.id
            ].filtered(
                lambda a, slip=slip: a.date_from <= slip.date_to
                and (not a.date_to or a.date_to >= slip.date_from)
            )

    def _erp_assignments_cache_key(self):
        # El periodo forma parte de la clave: dos roles del mismo empleado en
        # el mismo cálculo (meses distintos) no comparten asignaciones.
        return ("assignments", self.employee_id.id, self.date_from, self.date_to)

    def _erp_prefetch_benefit_modes(self):
        """Carga en la caché del cálculo la modalidad de cada beneficio de
        cada rol de ``self`` con una sola búsqueda de elecciones. Mismo
        criterio que ``hr.employee._get_benefit_mode`` (elección con la
        ``date_from`` más reciente ``<=`` fin del periodo; si no hay, el valor
        por defecto de la empresa del empleado)."""
        cache = self.env.cr.cache.get(PAYROLL_COMPUTE_CACHE_KEY)
        if cache is None or not self:
            return
        # sudo(): mismo criterio que _get_benefit_mode: la nómina lee las
        # elecciones aunque el usuario no tenga el grupo de RRHH que las
        # protege; solo se leen empleado, beneficio, modalidad y fecha.
        elections = (
            self.env["erp.hr.benefit.election"]
            .sudo()
            .search_fetch(
                [
                    ("employee_id", "in", self.employee_id.ids),
                    ("date_from", "<=", max(self.mapped("date_to"))),
                ],
                ["employee_id", "benefit", "mode", "date_from"],
                order="date_from desc, id desc",
            )
        )
        by_key = defaultdict(list)
        for election in elections:
            by_key[(election.employee_id.id, election.benefit)].append(election)
        for slip in self:
            company = slip.employee_id.sudo().company_id
            for benefit, default_field in BENEFIT_COMPANY_DEFAULT_FIELD.items():
                mode = next(
                    (
                        election.mode
                        for election in by_key[(slip.employee_id.id, benefit)]
                        if election.date_from <= slip.date_to
                    ),
                    company[default_field],
                )
                cache[("benefit_mode", slip.id, benefit)] = mode

    def _erp_get_assignments(self):
        """Asignaciones fijas vigentes algún día del periodo del rol, de
        conceptos activos de la empresa del rol."""
        self.ensure_one()
        assignments = self._erp_memo(
            self._erp_assignments_cache_key(),
            lambda: self.env["erp.payroll.employee.concept"].search(
                [
                    ("employee_id", "=", self.employee_id.id),
                    ("date_from", "<=", self.date_to),
                    "|",
                    ("date_to", "=", False),
                    ("date_to", ">=", self.date_from),
                ]
            ),
        )
        return assignments.filtered(
            lambda a: a.concept_id.active
            and a.concept_id.amount_kind == "fixed"
            and a.concept_id.company_id == self.company_id
            and a._erp_is_in_force(self.date_from, self.date_to)
        )

    def _erp_get_input_concepts(self):
        """Valida las entradas del rol con importe y devuelve
        ``{código: concepto}``.

        Cada entrada con importe debe tener el código de un concepto variable
        activo de la empresa del rol y un importe positivo (el tipo del
        concepto da el signo).
        """
        self.ensure_one()
        inputs = self.input_line_ids.filtered(lambda line: line.amount)
        if not inputs:
            return {}
        codes = set(inputs.mapped("code"))
        concepts = self.env["erp.payroll.concept"].search(
            [("code", "in", list(codes)), ("company_id", "=", self.company_id.id)]
        )
        by_code = {
            concept.code: concept
            for concept in concepts
            if concept.amount_kind == "variable"
        }
        unknown = sorted(codes - set(by_code))
        if unknown:
            raise UserError(
                _(
                    "Las entradas del rol de %(employee)s usan códigos que no son "
                    "conceptos variables activos de la empresa: %(codes)s. "
                    "Registre el concepto variable en el catálogo o corrija el "
                    "código de la entrada.",
                    employee=self.employee_id.name,
                    codes=", ".join(unknown),
                )
            )
        negative = inputs.filtered(lambda line: line.amount < 0)
        if negative:
            raise UserError(
                _(
                    "Las entradas del rol de %(employee)s deben tener importe "
                    "positivo (el tipo del concepto indica si es ingreso o "
                    "descuento): %(codes)s.",
                    employee=self.employee_id.name,
                    codes=", ".join(sorted(set(negative.mapped("code")))),
                )
            )
        return by_code

    def _erp_get_concept_amounts(self, contract):
        """Importes de los conceptos propios del rol para ``contract``:
        ``{erp.payroll.concept: importe con signo}`` (ingresos en positivo,
        descuentos en negativo, redondeados a la moneda).

        - Asignaciones fijas: importe mensual completo si la asignación está
          vigente algún día del periodo (no se prorratea por días); van al
          contrato principal del rol (``_erp_get_main_contract``).
        - Entradas variables (``hr.payslip.input``): al contrato de la entrada
          o, si no es uno de los contratos del rol, al principal.
        """
        self.ensure_one()
        return self._erp_memo(
            ("concepts", self.id, contract.id),
            lambda: self._erp_compute_concept_amounts(contract),
        )

    def _erp_compute_concept_amounts(self, contract):
        self.ensure_one()
        currency = self._erp_currency(contract)
        is_main = contract == self._erp_get_main_contract()
        totals = defaultdict(float)
        if is_main:
            for assignment in self._erp_get_assignments():
                totals[assignment.concept_id] += assignment.amount
        concepts_by_code = self._erp_memo(
            ("input_concepts", self.id), self._erp_get_input_concepts
        )
        contracts = self._erp_get_contracts()
        for line in self.input_line_ids.filtered(lambda line: line.amount):
            if line.contract_id == contract or (
                is_main and line.contract_id not in contracts
            ):
                totals[concepts_by_code[line.code]] += line.amount
        return {
            concept: currency.round(
                amount if concept.concept_type == "income" else -amount
            )
            for concept, amount in totals.items()
        }

    # --- Bases -----------------------------------------------------------
    def _erp_get_basic(self, contract):
        """Sueldo del contrato prorrateado por días: sueldo × días / MONTH_DAYS
        (mes completo = sueldo íntegro)."""
        self.ensure_one()

        def compute():
            month_days = self._erp_month_days()
            days = self._erp_get_worked_days(contract)
            return self._erp_currency(contract).round(contract.wage * days / month_days)

        return self._erp_memo(("basic", self.id, contract.id), compute)

    def _erp_get_base(self, contract, flag):
        """Base de aportación (``flag='iess_base'``) o de décimo tercero
        (``flag='thirteenth_base'``): sueldo + ingresos propios marcados.
        Los fondos de reserva y los décimos no forman base."""
        concepts = self._erp_get_concept_amounts(contract)
        return self._erp_currency(contract).round(
            self._erp_get_basic(contract)
            + sum(
                amount
                for concept, amount in concepts.items()
                if concept.concept_type == "income" and concept[flag]
            )
        )

    # --- Contrato de las reglas ----------------------------------------
    def _erp_rule_applies(self, code, contract):
        """Condición de las reglas de «Rol mensual Ecuador».

        - BASIC, GROSS, NET: siempre.
        - INC_OTHER / DED_OTHER: si hay conceptos propios de ese tipo.
        - IESS, fondos de reserva y décimos: solo con relación laboral
          (``hr.contract.type.erp_labor_relationship``).
        - Fondos de reserva: con días con derecho en el periodo
          (``_erp_get_reserve_fund_days``) y según la modalidad.
        - Décimos: según la modalidad vigente al final del periodo; las
          provisiones de décimo cuarto, además, según el régimen del
          establecimiento (sin establecimiento -> ``UserError``).

        :return: ``bool``
        """
        self.ensure_one()
        if code in ALWAYS_APPLY_RULES:
            return True
        if code in CONCEPT_RULES:
            concept_type = CONCEPT_RULES[code]
            return any(
                amount and concept.concept_type == concept_type
                for concept, amount in self._erp_get_concept_amounts(contract).items()
            )
        if code not in EC_RULE_CODES:
            self._erp_raise_unknown_rule(code)
        if not self._erp_has_labor_relationship(contract):
            return False
        if code in IESS_RULES:
            return True
        benefit, mode = BENEFIT_RULES[code]
        regime = benefit == "fourteenth" and self._erp_get_fourteenth_regime()
        if benefit == "reserve_fund" and not self._erp_get_reserve_fund_days(contract):
            return False
        if self._erp_get_benefit_mode(benefit) != mode:
            return False
        if code in FOURTEENTH_REGIME_RULES:
            return regime == FOURTEENTH_REGIME_RULES[code]
        return True

    def _erp_rule_amount(self, code, contract, categories, result_rules):
        """Importe de las reglas de «Rol mensual Ecuador», redondeado a la
        moneda de la empresa, con el signo del motor (descuentos en negativo).

        ``categories`` (sumas por categoría del contrato en curso) se usa en
        los totales (GROSS, NET) para que incluyan cualquier regla que el
        responsable añada a la estructura; ``result_rules`` forma parte del
        contrato de las reglas y no se usa en el cálculo actual.

        Fórmulas (parámetros vigentes al final del periodo):

        - BASIC = sueldo × días / MONTH_DAYS (``_erp_get_basic``).
        - INC_OTHER / DED_OTHER = suma de conceptos propios del tipo.
        - FR = base IESS × RESERVE_FUND_RATE / 100 × días con derecho / días
          trabajados.
        - D13 = base D13 / THIRTEENTH_DIVISOR.
        - D14 = SBU / FOURTEENTH_MONTHS × tasa de jornada × días / MONTH_DAYS.
        - IESS_PERSONAL = −base IESS × IESS_PERSONAL / 100;
          IESS_PATRONAL = base IESS × IESS_PATRONAL / 100.
        - GROSS = BASIC + ALW; NET = GROSS + DED (el neto negativo del rol
          completo -> ``UserError`` en ``_erp_check_lines_net``).

        :return: ``float``
        """
        self.ensure_one()
        del result_rules  # Parte del contrato de las reglas; sin uso por ahora.
        currency = self._erp_currency(contract)
        if code == "BASIC":
            amount = self._erp_get_basic(contract)
        elif code in CONCEPT_RULES:
            concept_type = CONCEPT_RULES[code]
            amount = sum(
                amount
                for concept, amount in self._erp_get_concept_amounts(contract).items()
                if concept.concept_type == concept_type
            )
        elif code == "GROSS":
            amount = categories.BASIC + categories.ALW
        elif code == "NET":
            # El neto negativo se valida sobre el rol completo (suma de las
            # líneas NET de todos los contratos): ``_erp_check_lines_net``.
            amount = currency.round(categories.GROSS + categories.DED)
        elif code in IESS_RULES:
            rate = self._erp_param(IESS_RULES[code])
            amount = self._erp_get_base(contract, "iess_base") * rate / 100
            if code == "IESS_PERSONAL":
                amount = -currency.round(amount)
        elif code in ("FR_PAID", "FR_ACCRUED"):
            amount = self._erp_get_reserve_fund_amount(contract)
        elif code in ("D13_PAID", "D13_PROV"):
            amount = self._erp_get_base(
                contract, "thirteenth_base"
            ) / self._erp_param_positive("THIRTEENTH_DIVISOR")
        elif code in ("D14_PAID", *FOURTEENTH_REGIME_RULES):
            amount = self._erp_get_fourteenth_amount(contract)
        else:
            self._erp_raise_unknown_rule(code)
        return currency.round(amount)

    def _erp_raise_unknown_rule(self, code):
        raise UserError(
            _(
                "La regla con código %(code)s no es una regla del rol de Ecuador: "
                "revise la condición y el importe configurados en la regla.",
                code=code,
            )
        )

    def _erp_check_net(self, net, currency):
        if currency.compare_amounts(net, 0.0) < 0:
            raise UserError(
                _(
                    "El neto a recibir de %(employee)s en el rol del %(date_from)s "
                    "al %(date_to)s es negativo (%(net)s): los descuentos superan "
                    "los ingresos. Revise los descuentos asignados y las entradas "
                    "del rol.",
                    employee=self.employee_id.name,
                    date_from=format_date(self.env, self.date_from),
                    date_to=format_date(self.env, self.date_to),
                    net=formatLang(self.env, net, currency_obj=currency),
                )
            )

    def _erp_get_reserve_fund_amount(self, contract):
        worked_days = self._erp_get_worked_days(contract)
        if not worked_days:
            return 0.0
        right_days = self._erp_get_reserve_fund_days(contract)
        rate = self._erp_param("RESERVE_FUND_RATE")
        base = self._erp_get_base(contract, "iess_base")
        return base * rate / 100 * right_days / worked_days

    def _erp_get_fourteenth_amount(self, contract):
        sbu = self._erp_param("SBU")
        months = self._erp_param_positive("FOURTEENTH_MONTHS")
        rate = self._erp_get_work_time_rate(contract)
        days = self._erp_get_worked_days(contract)
        return sbu / months * rate * days / self._erp_month_days()

    def _erp_get_work_time_rate(self, contract):
        """Tasa de jornada del contrato para el décimo cuarto
        (``resource.calendar._erp_get_work_time_rate``). Sin jornada, o sin
        horas de tiempo completo en la jornada ni máximo semanal en la
        empresa, la tasa no se puede calcular: ``UserError`` en lugar de un
        décimo cuarto de 0 silencioso."""
        calendar = contract.resource_calendar_id
        if not calendar:
            raise UserError(
                _(
                    "No se puede calcular el décimo cuarto de %(employee)s: el "
                    "contrato «%(contract)s» no tiene jornada de trabajo. "
                    "Asigne la jornada en el contrato.",
                    employee=self.employee_id.name,
                    contract=contract.name,
                )
            )
        company = contract.company_id or self.company_id
        if float_is_zero(
            calendar.full_time_required_hours, precision_digits=2
        ) and float_is_zero(company.erp_max_weekly_hours, precision_digits=2):
            raise UserError(
                _(
                    "No se puede calcular el décimo cuarto de %(employee)s: la "
                    "jornada «%(calendar)s» no indica las horas de tiempo "
                    "completo y la empresa %(company)s no tiene configurado el "
                    "máximo de horas semanales. Configure uno de los dos.",
                    employee=self.employee_id.name,
                    calendar=calendar.name,
                    company=company.name,
                )
            )
        return calendar._erp_get_work_time_rate(company)

    # ------------------------------------------------------------------
    # Lotes (US-008, CA-8)
    # ------------------------------------------------------------------
    @api.model
    def _erp_get_period_contracts(self, employees, date_from, date_to):
        """Contrato de cada empleado que cubre el periodo: en curso o expirado
        (``PAYSLIP_EXPLICIT_CONTRACT_STATES``), vigente algún día del periodo;
        si hay varios, el de inicio más reciente. Una sola búsqueda.

        :return: ``{employee_id: hr.contract}`` (sin clave si no hay)
        """
        contracts = self.env["hr.contract"].search(
            [
                ("employee_id", "in", employees.ids),
                ("state", "in", PAYSLIP_EXPLICIT_CONTRACT_STATES),
                ("date_start", "<=", date_to),
                "|",
                ("date_end", "=", False),
                ("date_end", ">=", date_from),
            ],
            order="date_start desc, id desc",
        )
        result = {}
        for contract in contracts:
            result.setdefault(contract.employee_id.id, contract)
        return result

    def get_payslip_vals(
        self, date_from, date_to, employee_id=False, contract_id=False, struct_id=False
    ):
        """Valores del rol que genera el asistente de lotes.

        OCA toma ``employee.contract_id`` (contrato actual) sin mirar el
        periodo; aquí se pasa el contrato que cubre el periodo
        (``_erp_get_period_contracts``), p. ej. el contrato terminado de un
        lote atrasado o el anterior a una renovación. Los demás contratos del
        periodo entran igualmente en el cálculo (``_get_employee_contracts``).

        El asistente de lotes pasa en el contexto
        ``erp_period_contract_ids`` (``{empleado: contrato}``) el mapa ya
        calculado para todo el lote, y así no se busca por empleado; un
        contrato del mapa que no sea del empleado se ignora (se busca).
        """
        if (
            employee_id
            and date_from
            and date_to
            and not contract_id
            and not self.env.context.get("contract")
        ):
            employee = self.env["hr.employee"].browse(employee_id)
            contract = self.env["hr.contract"]
            known = self.env.context.get("erp_period_contract_ids") or {}
            if known.get(employee_id):
                contract = contract.browse(known[employee_id]).exists()
                if contract.employee_id != employee:
                    contract = self.env["hr.contract"]
            if not contract:
                contract = self._erp_get_period_contracts(
                    employee,
                    fields.Date.to_date(date_from),
                    fields.Date.to_date(date_to),
                ).get(employee.id)
            if contract:
                return super(
                    HrPayslip, self.with_context(contract=True)
                ).get_payslip_vals(
                    date_from,
                    date_to,
                    employee_id=employee_id,
                    contract_id=contract.id,
                    struct_id=struct_id,
                )
        return super().get_payslip_vals(
            date_from,
            date_to,
            employee_id=employee_id,
            contract_id=contract_id,
            struct_id=struct_id,
        )

    # ------------------------------------------------------------------
    # Confirmación y contabilización (US-008, CA-8 a CA-10)
    # ------------------------------------------------------------------
    def _erp_check_payroll_manager(self, message):
        if not self.env.su and not self.env.user.has_group(PAYROLL_MANAGER_GROUP):
            raise AccessError(message)

    def action_payslip_done(self):
        """Confirma los roles y genera un único asiento cuadrado por rol.

        - Solo el responsable de nómina confirma (``AccessError``).
        - Un rol ya confirmado no se confirma otra vez (no hay doble asiento)
          y uno anulado debe volver a borrador antes (``UserError``).
        - Sin recálculo (``without_compute_sheet`` o
          ``payroll.prevent_compute_on_confirm``) se valida igualmente el
          contrato del periodo (US-006), salvo en reembolsos.
        - Funciona en lote (varios roles a la vez, un asiento por rol): el
          recálculo se hace aquí, sobre todos los roles, y se llama a OCA con
          ``without_compute_sheet`` porque ``payroll`` lee
          ``prevent_compute_on_confirm`` como si hubiera un solo rol
          (``Expected singleton``).
        - El asiento lo genera ``_erp_create_account_moves`` y no
          ``payroll_account``: ``super(PayrollAccountHrPayslip, self)`` salta
          todas las clases del MRO desde la siguiente a esta hasta la de
          ``payroll_account`` incluida (la de ``payroll`` y las anteriores sí
          se ejecutan), porque ``payroll_account`` añade una línea de ajuste
          cuando el asiento no cuadra, no reparte los conceptos propios en sus
          cuentas y exige al usuario permisos de contabilidad. Si otro módulo
          redefine ``action_payslip_done`` en ese tramo (entre
          ``erp_payroll_ec`` y ``payroll_account``) su código no se
          ejecutaría: lo vigila ``test_mro_no_override_skipped``.
        """
        self._erp_check_payroll_manager(
            _(
                "Solo el responsable de nómina puede confirmar roles de pagos. "
                "Pida a un responsable de nómina que revise y confirme el rol."
            )
        )
        done = self.filtered(lambda slip: slip.state == "done")
        if done:
            raise UserError(
                _(
                    "El rol de pagos ya está confirmado y contabilizado: "
                    "%(payslips)s. No se vuelve a confirmar.",
                    payslips=", ".join(done.mapped(lambda s: s.number or s.name or "")),
                )
            )
        cancelled = self.filtered(lambda slip: slip.state == "cancel")
        if cancelled:
            raise UserError(
                _(
                    "El rol de pagos está anulado: %(payslips)s. Páselo a borrador "
                    "y recalcúlelo antes de confirmarlo.",
                    payslips=", ".join(
                        cancelled.mapped(lambda s: s.number or s.name or "")
                    ),
                )
            )
        with self._erp_transition():
            if self._will_compute_on_confirm():
                self.compute_sheet()
            else:
                # Sin recálculo se validan igualmente contrato y periodo
                # (compute_sheet() ya lo hace cuando recalcula).
                originals = self.filtered(lambda slip: not slip.credit_note)
                originals._check_contract_in_period()
                originals._erp_check_period_in_month()
            res = super(
                PayrollAccountHrPayslip, self.with_context(without_compute_sheet=True)
            ).action_payslip_done()
            self._erp_create_account_moves()
        return res

    def _erp_create_account_moves(self):
        """Crea y publica el asiento de cada rol (``_erp_prepare_move_vals``).

        sudo(): el responsable de nómina contabiliza el rol sin ser además
        contador (CA-9). Se limita a preparar (lee cuentas y diario), crear y
        publicar el asiento, cuyo contenido sale íntegro de las líneas del rol
        ya calculado y de las cuentas configuradas por contabilidad; el
        usuario no aporta datos al asiento. El permiso de confirmar ya se
        comprobó en ``action_payslip_done``.
        """
        for slip in self:
            move_vals = slip.sudo()._erp_prepare_move_vals()
            if not move_vals:
                _logger.info(
                    "El rol %s no generó apuntes contables.", slip.number or slip.id
                )
                continue
            move = self.env["account.move"].sudo().create(move_vals)
            move.action_post()
            slip.write({"move_id": move.id, "date": move_vals["date"]})

    def _erp_prepare_move_vals(self):
        """Valores del asiento del rol: un apunte por cuenta de cada línea
        (convención de ``payroll_account``: importe positivo en la cuenta
        deudora = debe, negativo = haber; al revés en la acreedora). Las líneas
        de conceptos propios se reparten en la cuenta de cada concepto
        (``_erp_get_concept_move_parts``). Los reembolsos (``credit_note``)
        invierten los signos.

        :return: ``dict`` para ``account.move.create`` o ``None`` si no hay
            apuntes
        :raises UserError: rol sin diario o asiento descuadrado (no se añade
            línea de ajuste)
        """
        self.ensure_one()
        # Rol sin contrato asignado (varios contratos en el periodo): diario
        # del contrato principal.
        journal = (
            self.journal_id
            or self.contract_id.journal_id
            or self._erp_get_main_contract().journal_id
        )
        if not journal:
            raise UserError(
                _(
                    "El rol de %(employee)s no tiene diario de nómina: indíquelo "
                    "en el contrato del empleado (pestaña de contabilidad).",
                    employee=self.employee_id.name,
                )
            )
        currency = self.company_id.currency_id or journal.company_id.currency_id
        date = self.date or self.date_to
        sign = -1 if self.credit_note else 1
        line_vals = []
        without_account = []
        for line in self.line_ids:
            amount = currency.round(sign * line.total)
            if currency.is_zero(amount):
                continue
            analytic = {}
            # Analítica del contrato de la línea (cada contrato del rol en su
            # centro de costo); la del contrato del rol solo como respaldo.
            contract_analytic = (
                line.contract_id.analytic_account_id
                or self.contract_id.analytic_account_id
            )
            if contract_analytic:
                analytic = {contract_analytic.id: 100}
            elif line.salary_rule_id.analytic_account_id:
                analytic = {line.salary_rule_id.analytic_account_id.id: 100}
            for concept, part_amount in self._erp_get_concept_move_parts(line, sign):
                part_amount = currency.round(part_amount)
                amount = currency.round(amount - part_amount)
                if concept.concept_type == "income":
                    vals = self._prepare_debit_line(
                        line, part_amount, date, concept.account_debit_id.id, analytic
                    )
                    account = concept.account_debit_id
                else:
                    vals = self._prepare_credit_line(
                        line, -part_amount, date, concept.account_credit_id.id, analytic
                    )
                    account = concept.account_credit_id
                vals.update(
                    name=concept.name,
                    partner_id=self._erp_get_partner_for_account(account),
                )
                line_vals.append(vals)
            if currency.is_zero(amount):
                continue
            debit_account = line.salary_rule_id.account_debit
            credit_account = line.salary_rule_id.account_credit
            if debit_account:
                line_vals.append(
                    self._prepare_debit_line(
                        line, amount, date, debit_account.id, analytic
                    )
                )
            if credit_account:
                line_vals.append(
                    self._prepare_credit_line(
                        line, amount, date, credit_account.id, analytic
                    )
                )
            if not debit_account and not credit_account:
                without_account.append(line)
        if not line_vals:
            return None
        for vals in line_vals:
            # payroll_account toma el diario del rol (vacío si el rol no tiene
            # contrato asignado); el apunte va en el diario del asiento.
            vals["journal_id"] = journal.id
        debit = sum(vals["debit"] for vals in line_vals)
        credit = sum(vals["credit"] for vals in line_vals)
        if currency.compare_amounts(debit, credit):
            raise UserError(
                _(
                    "El asiento del rol de %(employee)s no cuadra (debe %(debit)s, "
                    "haber %(credit)s). Revise las cuentas deudora y acreedora de "
                    "las reglas del rol%(rules)s y de los conceptos propios.",
                    employee=self.employee_id.name,
                    debit=formatLang(self.env, debit, currency_obj=currency),
                    credit=formatLang(self.env, credit, currency_obj=currency),
                    rules=(
                        _(
                            " (sin cuentas: %s)",
                            ", ".join(line.name for line in without_account),
                        )
                        if without_account
                        else ""
                    ),
                )
            )
        return {
            "narration": _("Rol de pagos de %s", self.employee_id.name),
            "ref": self.number,
            "journal_id": journal.id,
            "date": date,
            "line_ids": [fields.Command.create(vals) for vals in line_vals],
        }

    def _erp_get_concept_move_parts(self, line, sign):
        """Partes de una línea INC_OTHER / DED_OTHER que van a la cuenta propia
        del concepto (ingreso: «Cuenta deudora»; descuento: «Cuenta
        acreedora»). El resto de la línea va a las cuentas de la regla.

        Las partes salen de los conceptos del rol recalculados ahora; si ya no
        suman lo mismo que la línea (asignaciones o entradas cambiadas desde
        el cálculo) se pide recalcular, salvo en un reembolso, que no se puede
        recalcular: entonces toda la línea va a las cuentas de la regla.

        :return: lista de ``(erp.payroll.concept, importe con el signo del
            motor y del reembolso)``
        """
        concept_type = CONCEPT_RULES.get(line.code)
        if not concept_type or line.salary_rule_id.code != line.code:
            return []
        concepts = {
            concept: amount
            for concept, amount in self._erp_get_concept_amounts(
                line.contract_id
            ).items()
            if concept.concept_type == concept_type
        }
        currency = self.company_id.currency_id
        if currency.compare_amounts(sum(concepts.values()), line.total):
            if self.credit_note:
                return []
            raise UserError(
                _(
                    "Los conceptos propios del rol de %(employee)s cambiaron desde "
                    "su cálculo. Recalcule el rol antes de confirmarlo.",
                    employee=self.employee_id.name,
                )
            )
        account_field = (
            "account_debit_id" if concept_type == "income" else "account_credit_id"
        )
        return [
            (concept, sign * amount)
            for concept, amount in sorted(
                concepts.items(), key=lambda item: (item[0].name, item[0].id)
            )
            if concept[account_field] and amount
        ]

    def _erp_get_partner_for_account(self, account):
        """Tercero del apunte: el empleado en cuentas por cobrar y pasivos."""
        if account.account_type in EMPLOYEE_PARTNER_ACCOUNT_TYPES:
            return self._erp_get_employee_partner().id
        return False

    def _erp_get_employee_partner(self):
        """Contacto del empleado para los apuntes (mismo criterio que
        ``payroll_account``: contacto de trabajo o titular de su cuenta
        bancaria)."""
        self.ensure_one()
        employee = self.employee_id
        return employee.work_contact_id or employee.bank_account_id.partner_id

    # ------------------------------------------------------------------
    # Anulación (US-008, CA-10)
    # ------------------------------------------------------------------
    def action_payslip_cancel(self):
        """Anula roles. Un rol confirmado solo lo anula el responsable de
        nómina, si el ajuste ``payroll.allow_cancel_payslips`` lo permite, y
        su asiento se revierte (asiento de reversión enlazado y conciliado),
        nunca se borra. Si algún apunte del asiento está conciliado (p. ej.
        el pago del sueldo) no se anula (``_erp_check_moves_not_reconciled``).

        Igual que en ``action_payslip_done``, se saltan las clases del MRO
        desde la siguiente a esta hasta ``payroll_account`` incluida (borra el
        asiento si el diario no tiene bloqueo por hash) y se ejecuta la de
        ``payroll`` (validaciones de reembolso y estado).
        """
        done = self.filtered(lambda slip: slip.state == "done")
        if done:
            self._erp_check_payroll_manager(
                _("Solo el responsable de nómina puede anular un rol confirmado.")
            )
            # sudo(): lectura de un ajuste técnico del motor.
            allowed = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param(ALLOW_CANCEL_PAYSLIPS_PARAM)
            )
            if not allowed:
                raise UserError(
                    _(
                        "No se puede anular un rol de pagos confirmado: active "
                        "«Permitir anular roles» en los ajustes de nómina o "
                        "corrija el rol con un reembolso."
                    )
                )
            done._erp_check_moves_not_reconciled()
        with self._erp_transition():
            res = super(PayrollAccountHrPayslip, self).action_payslip_cancel()
            done._erp_reverse_account_moves()
        return res

    def _erp_check_moves_not_reconciled(self):
        """Un rol cuyo asiento tiene apuntes conciliados (p. ej. el pago del
        sueldo contra «Sueldos por pagar») no se anula: revertir el asiento
        dejaría el pago descuadrado. Contabilidad debe romper antes la
        conciliación.

        sudo(): solo lectura de la conciliación de los apuntes del asiento del
        propio rol (el responsable de nómina no es contador).
        """
        reconciled = self.filtered(
            lambda slip: slip.move_id
            and slip.move_id.sudo().line_ids.filtered(
                lambda ml: ml.matched_debit_ids or ml.matched_credit_ids
            )
        )
        if reconciled:
            raise UserError(
                _(
                    "No se puede anular el rol de pagos %(payslips)s: su asiento "
                    "contable tiene apuntes conciliados (por ejemplo, el pago del "
                    "sueldo). Pida a contabilidad que rompa la conciliación de "
                    "esos apuntes y vuelva a anular el rol.",
                    payslips=", ".join(
                        reconciled.mapped(lambda s: s.number or s.name or "")
                    ),
                )
            )

    def _erp_reverse_account_moves(self):
        """Revierte el asiento publicado de cada rol (fecha de hoy) o anula el
        borrador.

        sudo(): mismo criterio que la creación del asiento: el responsable de
        nómina revierte el asiento que generó el rol sin ser contador; solo se
        revierte el asiento enlazado al propio rol.
        """
        today = fields.Date.context_today(self)
        for slip in self.filtered("move_id"):
            move = slip.move_id.sudo()
            if move.state == "posted" and not move.reversal_move_ids:
                move._reverse_moves(
                    [
                        {
                            "date": today,
                            "ref": _("Reversión del rol %s", slip.number or slip.name),
                        }
                    ],
                    cancel=True,
                )
            elif move.state == "draft":
                move.button_cancel()

    def action_payslip_draft(self):
        """Solo un rol no confirmado vuelve a borrador; uno confirmado se anula
        antes (su asiento se revierte)."""
        if self.filtered(lambda slip: slip.state == "done"):
            raise UserError(
                _(
                    "Un rol de pagos confirmado no puede volver a borrador: "
                    "anúlelo primero (su asiento se revierte)."
                )
            )
        with self._erp_transition():
            return super().action_payslip_draft()

    def refund_sheet(self):
        """Reembolso de roles confirmados: solo el responsable de nómina
        (genera y contabiliza un rol de signo contrario)."""
        self._erp_check_payroll_manager(
            _("Solo el responsable de nómina puede emitir el reembolso de un rol.")
        )
        with self._erp_transition():
            return super().refund_sheet()

    # ------------------------------------------------------------------
    # Validación de contrato (US-006, CA-4)
    # ------------------------------------------------------------------
    def _will_compute_on_confirm(self):
        """Replica la condición de ``action_payslip_done`` de OCA leyendo el
        parámetro directamente (el campo calculado de OCA exige un solo
        registro)."""
        if self.env.context.get("without_compute_sheet"):
            return False
        # sudo(): solo lectura de un ajuste técnico del motor; los usuarios de
        # nómina no tienen acceso a ir.config_parameter.
        prevent = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(PREVENT_COMPUTE_ON_CONFIRM_PARAM)
        )
        return not prevent

    def _check_contract_in_period(self):
        """Lanza ``UserError`` si algún rol de ``self`` tiene asignado un
        contrato de otro empleado o no tiene contrato vigente en su periodo."""
        foreign = self._get_payslips_with_foreign_contract()
        if foreign:
            details = "\n".join(
                self.env._(
                    "- Rol de %(employee)s: el contrato «%(contract)s» pertenece "
                    "a %(owner)s",
                    employee=slip.employee_id.name,
                    contract=slip.contract_id.name,
                    owner=slip.contract_id.employee_id.name,
                )
                for slip in foreign
            )
            raise UserError(
                _(
                    "No se puede calcular ni confirmar el rol de pagos: el contrato "
                    "asignado no pertenece al empleado del rol:\n%(details)s\n\n"
                    "Asigne a cada rol un contrato del propio empleado.",
                    details=details,
                )
            )
        invalid = self._get_payslips_without_valid_contract()
        if not invalid:
            return
        details = "\n".join(
            self.env._(
                "- %(employee)s: del %(date_from)s al %(date_to)s",
                employee=slip.employee_id.name,
                date_from=format_date(self.env, slip.date_from),
                date_to=format_date(self.env, slip.date_to),
            )
            for slip in invalid
        )
        raise UserError(
            _(
                "No se puede calcular ni confirmar el rol de pagos: estos empleados "
                "no tienen un contrato vigente en el periodo del rol:\n"
                "%(details)s\n\n"
                "Registre un contrato en curso que cubra el periodo, asigne al "
                "rol el contrato correcto o corrija las fechas del rol.",
                details=details,
            )
        )

    def _get_payslips_with_foreign_contract(self):
        """Roles cuyo contrato asignado es de otro empleado."""
        return self.filtered(
            lambda slip: slip.contract_id
            and slip.contract_id.employee_id != slip.employee_id
        )

    def _get_payslips_without_valid_contract(self):
        """Devuelve los roles de ``self`` sin contrato vigente en su periodo.

        - Rol con contrato asignado: el contrato debe estar en un estado de
          ``PAYSLIP_EXPLICIT_CONTRACT_STATES`` y solaparse con el periodo.
        - Rol sin contrato: el empleado debe tener algún contrato de
          ``PAYSLIP_IMPLICIT_CONTRACT_STATES`` que se solape con el periodo
          (mismo criterio que el motor). Se resuelve con una sola búsqueda para
          todo el lote y se filtra en memoria por empleado y periodo.

        :return: recordset ``hr.payslip`` (vacío si todos son válidos).
        """
        with_contract = self.filtered("contract_id")
        valid_with_contract = with_contract.filtered(
            lambda slip: slip.contract_id.state in PAYSLIP_EXPLICIT_CONTRACT_STATES
            and slip._contract_overlaps_period(slip.contract_id)
        )
        invalid = with_contract - valid_with_contract

        without_contract = self - with_contract
        if not without_contract:
            return invalid
        contracts = self.env["hr.contract"].search(
            [
                ("employee_id", "in", without_contract.employee_id.ids),
                ("state", "in", PAYSLIP_IMPLICIT_CONTRACT_STATES),
                ("date_start", "<=", max(without_contract.mapped("date_to"))),
                "|",
                ("date_end", "=", False),
                ("date_end", ">=", min(without_contract.mapped("date_from"))),
            ]
        )
        contracts_by_employee = defaultdict(list)
        for contract in contracts:
            contracts_by_employee[contract.employee_id.id].append(contract)
        for slip in without_contract:
            if not any(
                slip._contract_overlaps_period(contract)
                for contract in contracts_by_employee[slip.employee_id.id]
            ):
                invalid |= slip
        return invalid

    def _contract_overlaps_period(self, contract):
        """``True`` si ``contract`` está vigente en algún día del periodo del
        rol (``date_from``-``date_to``, ambos incluidos)."""
        self.ensure_one()
        return contract.date_start <= self.date_to and (
            not contract.date_end or contract.date_end >= self.date_from
        )
