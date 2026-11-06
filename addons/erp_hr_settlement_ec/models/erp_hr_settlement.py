from collections import defaultdict
from contextlib import contextmanager
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare, float_round
from odoo.tools.misc import format_date, formatLang

from odoo.addons.erp_payroll_ec.models.hr_payslip import (
    EMPLOYEE_PARTNER_ACCOUNT_TYPES,
    days_30,
)

from .const import (
    DEFAULT_ACCOUNT_CODES,
    EXPENSE_ACCOUNT_FIELDS,
    INDEMNITY_YEAR_FRACTION_AS_FULL,
    LINE_D13,
    LINE_D14,
    LINE_INDEMNITY,
    LINE_OTHER_DEDUCTION,
    LINE_OTHER_INCOME,
    LINE_PROVISION_CODES,
    LINE_SEQUENCES,
    LINE_SEVERANCE_BONUS,
    LINE_VAC_PENDING,
    LINE_VAC_PROPORTIONAL,
    PAYROLL_MANAGER_GROUP,
    REMUNERATION_LINE_CODES,
    SETTLEMENT_DELETABLE_STATES,
    SETTLEMENT_LINE_CODE_SELECTION,
    SETTLEMENT_SEQUENCE_CODE,
    SETTLEMENT_STATE_SELECTION,
    SETTLEMENT_TRANSITION_KEY,
    SEVERANCE_BONUS_PROPORTIONAL_FRACTION,
    SEVERANCE_BONUS_RATE,
    VACATION_DAY_BASE_MONTHS,
    VACATION_DAY_DIVISOR,
    VACATION_PROPORTIONAL_DIVISOR,
)

# Campos que solo cambian las acciones de la liquidación (_erp_transition).
SETTLEMENT_PROTECTED_FIELDS = frozenset(
    {"state", "move_id", "reversal_move_id", "name"}
)
# Estados bloqueados y campos que admiten.
SETTLEMENT_LOCKED_STATES = ("done", "cancel")
SETTLEMENT_LOCKED_WRITABLE_FIELDS = frozenset({"note", "message_main_attachment_id"})
# Campos que invalidan el cálculo: una liquidación calculada vuelve a borrador.
SETTLEMENT_RECOMPUTE_FIELDS = frozenset(
    {
        "employee_id",
        "contract_id",
        "date_departure",
        "cause_id",
        "date_entry",
        "last_wage",
        "company_id",
    }
)
# Régimen de cada provisión de décimo cuarto (explicación del rubro).
PROVISION_REGIME_LABELS = {
    "D14_PROV_COSTA": " (Costa / Galápagos)",
    "D14_PROV_SIERRA": " (Sierra / Amazonía)",
}


class ErpHrSettlement(models.Model):
    """Liquidación de haberes de un contrato (US-013, CA-5 a CA-11).

    Estados: ``draft`` → ``computed`` → ``done`` / ``cancel`` (transiciones,
    cálculo, asiento y cierre de contrato: capa de negocio).

    Integridad en la BD:

    - ``contract_active_uniq``: una sola liquidación no anulada por contrato
      (exclusión btree parcial, equivale a un índice único parcial).
    - ``name_company_uniq``: número único por empresa una vez asignado
      (``name`` distinto de «/»).
    - ``done_net_check``: una liquidación confirmada no tiene neto negativo.
    - Fecha de salida dentro del contrato: ``_check_departure_date``.
    - Solo se eliminan liquidaciones en borrador o anuladas
      (``_unlink_except_not_draft``).
    """

    _name = "erp.hr.settlement"
    _description = "Liquidación de haberes"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_departure desc, id desc"
    _check_company_auto = True

    name = fields.Char(
        string="Número",
        required=True,
        readonly=True,
        copy=False,
        default="/",
        tracking=True,
        help="Número de la liquidación (secuencia «LIQ/AAAA/NNNN»).",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        index=True,
        ondelete="restrict",
        default=lambda self: self.env.company,
        tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        related="company_id.currency_id",
        store=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Empleado",
        required=True,
        index=True,
        ondelete="restrict",
        check_company=True,
        tracking=True,
        # Incluye archivados: la liquidación se consulta después de la salida.
        context={"active_test": False},
    )
    contract_id = fields.Many2one(
        "hr.contract",
        string="Contrato",
        required=True,
        # Sin index=True propio: lo cubre el índice de contract_active_uniq
        # (empieza por contract_id).
        ondelete="restrict",
        check_company=True,
        tracking=True,
        domain="[('employee_id', '=', employee_id)]",
        help="Contrato que termina con esta liquidación.",
    )
    date_departure = fields.Date(
        string="Fecha de salida",
        required=True,
        tracking=True,
        help="Último día de trabajo. Debe estar dentro del contrato; al "
        "confirmar pasa a ser la fecha de fin del contrato.",
    )
    cause_id = fields.Many2one(
        "erp.hr.termination.cause",
        string="Causa de salida",
        required=True,
        index=True,
        ondelete="restrict",
        tracking=True,
        help="Causa legal de la terminación: decide qué rubros se calculan.",
    )
    state = fields.Selection(
        SETTLEMENT_STATE_SELECTION,
        string="Estado",
        required=True,
        default="draft",
        copy=False,
        index=True,
        tracking=True,
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Diario",
        ondelete="restrict",
        check_company=True,
        help="Diario del asiento de la liquidación. Vacío: el del contrato.",
    )
    move_id = fields.Many2one(
        "account.move",
        string="Asiento contable",
        readonly=True,
        copy=False,
        index="btree_not_null",
        ondelete="restrict",
        check_company=True,
        tracking=True,
    )
    reversal_move_id = fields.Many2one(
        "account.move",
        string="Asiento de reversión",
        readonly=True,
        copy=False,
        index="btree_not_null",
        ondelete="restrict",
        check_company=True,
        tracking=True,
    )
    # --- Datos del servicio (instantánea al crear; editable en borrador) --
    date_entry = fields.Date(
        string="Fecha de ingreso",
        compute="_compute_date_entry",
        store=True,
        readonly=False,
        precompute=True,
        tracking=True,
        help="Fecha de ingreso a la empresa del empleado (la de la ficha o, "
        "si está vacía, la del primer contrato). Se guarda al elegir el "
        "empleado para que un reingreso posterior no la cambie.",
    )
    service_years = fields.Integer(
        string="Años de servicio",
        compute="_compute_service_time",
        store=True,
    )
    service_months = fields.Integer(
        string="Meses de servicio",
        compute="_compute_service_time",
        store=True,
        help="Meses además de los años completos.",
    )
    service_days = fields.Integer(
        string="Días de servicio",
        compute="_compute_service_time",
        store=True,
        help="Días además de los años y meses completos.",
    )
    service_display = fields.Char(
        string="Tiempo de servicio",
        compute="_compute_service_display",
        help="Años, meses y días de servicio desde la fecha de ingreso hasta "
        "la fecha de salida, ambas incluidas.",
    )
    service_total_days = fields.Integer(
        string="Días totales de servicio",
        compute="_compute_service_time",
        store=True,
        help="Días calendario desde la fecha de ingreso hasta la fecha de "
        "salida, ambas incluidas.",
    )
    last_wage = fields.Monetary(
        string="Última remuneración",
        currency_field="currency_id",
        tracking=True,
        help="Última remuneración mensual del empleado: base de la "
        "bonificación por desahucio y de la indemnización. La calcula "
        "«Calcular».",
    )
    # --- Rubros y totales -------------------------------------------------
    line_ids = fields.One2many(
        "erp.hr.settlement.line",
        "settlement_id",
        string="Rubros",
        copy=False,
    )
    total_income = fields.Monetary(
        string="Total ingresos",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )
    total_deduction = fields.Monetary(
        string="Total descuentos",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )
    net = fields.Monetary(
        string="Neto a recibir",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
        tracking=True,
    )
    # --- Enlaces de lo liquidado (los crea la confirmación) ---------------
    provision_payment_ids = fields.One2many(
        "erp.payroll.provision.payment",
        "settlement_id",
        string="Provisiones pagadas",
        readonly=True,
        help="Provisiones de décimos que paga esta liquidación.",
    )
    settled_allocation_ids = fields.One2many(
        "hr.leave.allocation",
        "erp_settlement_id",
        # Etiqueta distinta de settled_vacation_summary (la que ve el
        # usuario): dos campos con la misma etiqueta generan un aviso.
        string="Asignaciones de vacaciones liquidadas",
        readonly=True,
    )
    note = fields.Text(string="Observaciones")

    _sql_constraints = [
        (
            "contract_active_uniq",
            "EXCLUDE USING btree (contract_id WITH =) WHERE (state <> 'cancel')",
            "Ya existe una liquidación no anulada de este contrato. Anule la "
            "existente antes de registrar otra.",
        ),
        (
            "name_company_uniq",
            "EXCLUDE USING btree (company_id WITH =, name WITH =) "
            "WHERE (name <> '/')",
            "Ya existe una liquidación con ese número en la empresa.",
        ),
        (
            "totals_positive_check",
            "CHECK (COALESCE(total_income, 0) >= 0 "
            "AND COALESCE(total_deduction, 0) >= 0)",
            "Los totales de ingresos y descuentos de la liquidación no pueden "
            "ser negativos.",
        ),
        (
            "done_net_check",
            "CHECK (state <> 'done' OR COALESCE(net, 0) >= 0)",
            "El neto a recibir de una liquidación confirmada no puede ser "
            "negativo: los descuentos superan los ingresos.",
        ),
    ]

    # ------------------------------------------------------------------
    # Cálculos de apoyo (sin reglas de negocio)
    # ------------------------------------------------------------------
    @api.depends("employee_id")
    def _compute_date_entry(self):
        # Solo depende del empleado: la fecha queda fija aunque después
        # cambie la ficha (reingreso). compute_sudo (por defecto en campos
        # almacenados): la fecha de ingreso de la ficha es de RRHH.
        for settlement in self:
            settlement.date_entry = (
                settlement.employee_id._erp_get_entry_date()
                if settlement.employee_id
                else False
            )

    @api.depends("date_entry", "date_departure")
    def _compute_service_time(self):
        for settlement in self:
            entry = settlement.date_entry
            departure = settlement.date_departure
            if not entry or not departure or departure < entry:
                settlement.update(
                    {
                        "service_years": 0,
                        "service_months": 0,
                        "service_days": 0,
                        "service_total_days": 0,
                    }
                )
                continue
            delta = relativedelta(departure + timedelta(days=1), entry)
            settlement.update(
                {
                    "service_years": delta.years,
                    "service_months": delta.months,
                    "service_days": delta.days,
                    "service_total_days": (departure - entry).days + 1,
                }
            )

    @api.depends("service_years", "service_months", "service_days")
    def _compute_service_display(self):
        """Tiempo de servicio legible («3 años, 2 meses y 5 días»), con
        singular y plural correctos; se muestran siempre las tres partes."""
        for settlement in self:
            years = settlement.service_years
            months = settlement.service_months
            days = settlement.service_days
            settlement.service_display = _(
                "%(years)s, %(months)s y %(days)s",
                years=(_("%s año", years) if years == 1 else _("%s años", years)),
                months=(_("%s mes", months) if months == 1 else _("%s meses", months)),
                days=_("%s día", days) if days == 1 else _("%s días", days),
            )

    @api.depends("line_ids.amount", "line_ids.line_type", "currency_id")
    def _compute_totals(self):
        for settlement in self:
            lines = settlement.line_ids
            income = sum(
                lines.filtered(lambda line: line.line_type == "income").mapped("amount")
            )
            deduction = sum(
                lines.filtered(lambda line: line.line_type == "deduction").mapped(
                    "amount"
                )
            )
            # La empresa (obligatoria) siempre tiene moneda; el respaldo cubre
            # un registro nuevo aún sin empresa en un formulario.
            currency = settlement.currency_id or self.env.company.currency_id
            settlement.total_income = currency.round(income)
            settlement.total_deduction = currency.round(deduction)
            settlement.net = currency.round(income - deduction)

    # ------------------------------------------------------------------
    # Integridad
    # ------------------------------------------------------------------
    @api.constrains("employee_id", "contract_id", "date_departure")
    def _check_departure_date(self):
        """El contrato es del empleado y la fecha de salida está dentro del
        contrato: no antes de su inicio ni después de su fin (si lo tiene)
        (US-013, CA-5)."""
        for settlement in self:
            contract = settlement.contract_id
            if contract.employee_id != settlement.employee_id:
                raise ValidationError(
                    _(
                        "El contrato «%(contract)s» no es de %(employee)s. Elija "
                        "un contrato del empleado de la liquidación.",
                        contract=contract.name,
                        employee=settlement.employee_id.name,
                    )
                )
            departure = settlement.date_departure
            if departure < contract.date_start:
                raise ValidationError(
                    _(
                        "La fecha de salida (%(departure)s) no puede ser anterior "
                        "al inicio del contrato «%(contract)s» (%(start)s).",
                        departure=format_date(self.env, departure),
                        contract=contract.name,
                        start=format_date(self.env, contract.date_start),
                    )
                )
            if contract.date_end and departure > contract.date_end:
                raise ValidationError(
                    _(
                        "La fecha de salida (%(departure)s) no puede ser posterior "
                        "al fin del contrato «%(contract)s» (%(end)s).",
                        departure=format_date(self.env, departure),
                        contract=contract.name,
                        end=format_date(self.env, contract.date_end),
                    )
                )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_not_draft(self):
        """Solo se eliminan liquidaciones en borrador o anuladas; una
        calculada vuelve a borrador o se anula antes, y una confirmada se
        anula (su asiento se revierte)."""
        locked = self.filtered(
            lambda settlement: settlement.state not in SETTLEMENT_DELETABLE_STATES
        )
        if locked:
            raise UserError(
                _(
                    "Solo se pueden eliminar liquidaciones en borrador o "
                    "anuladas: %(settlements)s. Anule la liquidación antes de "
                    "eliminarla.",
                    settlements=", ".join(
                        locked.mapped(lambda s: s.name or s.employee_id.name or "")
                    ),
                )
            )

    # ------------------------------------------------------------------
    # Campos calculados para la vista (DEV-2)
    # ------------------------------------------------------------------
    # Resumen de los periodos de vacaciones liquidados (US-013): la vista lo
    # muestra en lugar de ``settled_allocation_ids`` para no exponer
    # hr.leave.allocation a quien no tiene permisos de ausencias.
    settled_vacation_days = fields.Float(
        string="Días de vacaciones liquidados",
        compute="_compute_settled_vacation",
        compute_sudo=True,
        digits=(16, 2),
        help="Días quitados del saldo de vacaciones al confirmar la "
        "liquidación (se devuelven si se anula).",
    )
    settled_vacation_summary = fields.Text(
        string="Periodos de vacaciones liquidados",
        compute="_compute_settled_vacation",
        compute_sudo=True,
        help="Periodos de vacaciones cuyo saldo pagó esta liquidación y días "
        "liquidados de cada uno.",
    )

    @api.depends("state", "settled_allocation_ids")
    def _compute_settled_vacation(self):
        for settlement in self:
            allocations = settlement.settled_allocation_ids
            settlement.settled_vacation_days = sum(
                allocations.mapped("erp_settled_days")
            )
            settlement.settled_vacation_summary = (
                "\n".join(
                    _(
                        "%(period)s: %(days)s días",
                        period=allocation.name,
                        days=formatLang(
                            self.env, allocation.erp_settled_days, digits=2
                        ),
                    )
                    for allocation in allocations.sorted(
                        lambda a: (a.date_from or fields.Date.today(), a.id)
                    )
                )
                or False
            )

    @api.depends("name", "employee_id")
    def _compute_display_name(self):
        for settlement in self:
            if settlement.name and settlement.name != "/":
                settlement.display_name = settlement.name
            elif settlement.employee_id:
                settlement.display_name = _(
                    "Liquidación de %(employee)s (sin número)",
                    employee=settlement.employee_id.name,
                )
            else:
                settlement.display_name = _("Nueva liquidación")

    # ------------------------------------------------------------------
    # Transiciones de estado (US-013, CA-5 a CA-10)
    # ------------------------------------------------------------------
    # draft -> computed (Calcular) -> done (Confirmar, responsable) -> cancel
    # (Anular, responsable). Volver a borrador: desde calculada o anulada.
    # ``state``, ``move_id``, ``reversal_move_id`` y ``name`` solo cambian
    # dentro de una acción (``_erp_transition``); una liquidación confirmada
    # o anulada solo admite observaciones.
    def _erp_in_transition(self):
        return bool(self.env.cr.cache.get(SETTLEMENT_TRANSITION_KEY))

    @contextmanager
    def _erp_transition(self):
        """Marca en ``cr.cache`` (por cursor; no en el contexto, que controla
        el cliente RPC) que una acción de la liquidación está en curso. Se
        retira en ``finally`` aunque la acción falle. Admite anidamiento."""
        cache = self.env.cr.cache
        cache[SETTLEMENT_TRANSITION_KEY] = cache.get(SETTLEMENT_TRANSITION_KEY, 0) + 1
        try:
            yield
        finally:
            cache[SETTLEMENT_TRANSITION_KEY] -= 1
            if not cache[SETTLEMENT_TRANSITION_KEY]:
                cache.pop(SETTLEMENT_TRANSITION_KEY)

    def _erp_field_labels(self, field_names):
        return ", ".join(
            sorted(
                f"«{self._fields[name]._description_string(self.env)}»"
                for name in field_names
            )
        )

    @api.model_create_multi
    def create(self, vals_list):
        """Una liquidación nace en borrador, sin asientos; no puede haber
        dos liquidaciones no anuladas del mismo contrato (mensaje en español
        antes de la restricción de la BD)."""
        if not self.env.su and not self._erp_in_transition():
            for vals in vals_list:
                if (
                    vals.get("state") not in (None, False, "draft")
                    or vals.get("move_id")
                    or vals.get("reversal_move_id")
                ):
                    raise UserError(
                        _(
                            "Una liquidación nueva se crea en borrador y sin "
                            "asiento: el estado y el asiento los fijan las "
                            "acciones Calcular, Confirmar y Anular."
                        )
                    )
        self._erp_check_duplicate_contract(
            [
                vals.get("contract_id")
                for vals in vals_list
                if vals.get("state", "draft") != "cancel"
            ]
        )
        return super().create(vals_list)

    def write(self, vals):
        """Fuera de una acción de la liquidación:

        - ``state``, asientos y número no se escriben (``UserError``);
        - una liquidación confirmada o anulada solo admite observaciones;
        - cambiar el empleado, contrato, fecha de salida, causa, fecha de
          ingreso o última remuneración de una liquidación calculada la
          devuelve a borrador (sus rubros ya no valen: hay que recalcular).
        """
        if not self or self.env.su or self._erp_in_transition():
            return super().write(vals)
        protected = SETTLEMENT_PROTECTED_FIELDS.intersection(vals)
        if protected:
            raise UserError(
                _(
                    "Los campos %(fields)s de la liquidación no se modifican "
                    "directamente: cambian solo con las acciones Calcular, "
                    "Confirmar, Anular y Volver a borrador.",
                    fields=self._erp_field_labels(protected),
                )
            )
        locked = self.filtered(lambda s: s.state in SETTLEMENT_LOCKED_STATES)
        changed = set(vals) - SETTLEMENT_LOCKED_WRITABLE_FIELDS
        if locked and changed:
            raise UserError(
                _(
                    "La liquidación %(settlements)s está confirmada o anulada y "
                    "no se puede modificar (%(fields)s). Para corregirla, "
                    "anúlela (si está confirmada) y vuelva a borrador.",
                    settlements=", ".join(locked.mapped("display_name")),
                    fields=self._erp_field_labels(changed),
                )
            )
        if "contract_id" in vals:
            self._erp_check_duplicate_contract(
                [vals["contract_id"]]
                * len(self.filtered(lambda s: s.state != "cancel")),
                exclude=self,
            )
        stale = self.browse()
        if SETTLEMENT_RECOMPUTE_FIELDS.intersection(vals):
            stale = self.filtered(lambda s: s.state == "computed")
        res = super().write(vals)
        if stale:
            with self._erp_transition():
                stale.write({"state": "draft"})
            for settlement in stale:
                settlement.message_post(
                    body=_(
                        "Se cambiaron datos de la liquidación calculada: vuelve "
                        "a borrador. Pulse «Calcular» de nuevo."
                    )
                )
        return res

    def _erp_check_duplicate_contract(self, contract_ids, exclude=None):
        """No puede haber dos liquidaciones no anuladas del mismo contrato
        (US-013, CA-5). Mensaje en español antes de la restricción
        ``contract_active_uniq`` de la BD.

        sudo(): la comprobación debe ver las liquidaciones de otras empresas o
        de registros que el usuario no ve; solo se leen número y empleado.
        """
        contract_ids = [cid for cid in contract_ids if cid]
        if not contract_ids:
            return
        duplicated_in_batch = {
            cid for cid in contract_ids if contract_ids.count(cid) > 1
        }
        domain = [("contract_id", "in", contract_ids), ("state", "!=", "cancel")]
        if exclude:
            domain.append(("id", "not in", exclude.ids))
        existing = self.sudo().search(domain, limit=1)
        if not existing and not duplicated_in_batch:
            return
        contract = existing.contract_id or self.env["hr.contract"].sudo().browse(
            next(iter(duplicated_in_batch))
        )
        raise UserError(
            _(
                "Ya existe una liquidación no anulada del contrato «%(contract)s»"
                "%(existing)s. Anule la existente antes de registrar otra.",
                contract=contract.name,
                existing=(_(" (%s)", existing.display_name) if existing else ""),
            )
        )

    def _erp_check_state(self, allowed, message):
        invalid = self.filtered(lambda s: s.state not in allowed)
        if invalid:
            raise UserError(
                message % {"settlements": ", ".join(invalid.mapped("display_name"))}
            )

    def _erp_check_manager(self, message):
        if not self.env.su and not self.env.user.has_group(PAYROLL_MANAGER_GROUP):
            raise AccessError(message)

    # ------------------------------------------------------------------
    # Calcular (US-013, CA-6, CA-7)
    # ------------------------------------------------------------------
    def action_compute(self):
        """Calcula los rubros de la liquidación según la causa de salida.

        - Estados: borrador o calculada (recalcular) -> calculada.
        - Acceso: usuario de nómina (permiso de escritura sobre la
          liquidación).
        - Regenera los rubros no manuales (``_erp_prepare_computation``) y la
          última remuneración; los rubros manuales se conservan (CA-7).
        - Neto negativo: ``UserError`` (no se guarda nada).
        """
        self._erp_check_state(
            ("draft", "computed"),
            _(
                "Solo se calcula una liquidación en borrador o ya calculada: "
                "%(settlements)s. Una liquidación anulada vuelve antes a "
                "borrador; una confirmada no se recalcula."
            ),
        )
        self.check_access("write")
        Line = self.env["erp.hr.settlement.line"]
        for settlement in self:
            values = settlement._erp_prepare_computation()
            with settlement._erp_transition():
                settlement.line_ids.filtered(lambda line: not line.is_manual).unlink()
                Line.create(
                    [
                        dict(vals, settlement_id=settlement.id)
                        for vals in values["lines"]
                    ]
                )
                settlement.write(
                    {"last_wage": values["last_wage"], "state": "computed"}
                )
            settlement._erp_check_net()
        return True

    def _erp_check_net(self):
        for settlement in self:
            currency = settlement.currency_id
            if currency.compare_amounts(settlement.net, 0.0) < 0:
                raise UserError(
                    _(
                        "El neto a recibir de la liquidación de %(employee)s es "
                        "negativo (%(net)s): los descuentos superan los "
                        "ingresos. Revise los rubros manuales de descuento.",
                        employee=settlement.employee_id.name,
                        net=formatLang(self.env, settlement.net, currency_obj=currency),
                    )
                )

    def _erp_param(self, code):
        """Parámetro normativo vigente a la fecha de salida, de la empresa de
        la liquidación."""
        self.ensure_one()
        return self.env["erp.payroll.parameter"]._get_value(
            code, self.date_departure, self.company_id
        )

    def _erp_param_positive(self, code):
        value = self._erp_param(code)
        if value <= 0:
            raise UserError(
                _(
                    "El parámetro de nómina %(code)s vigente al %(date)s debe ser "
                    "mayor que cero para calcular la liquidación.",
                    code=code,
                    date=format_date(self.env, self.date_departure),
                )
            )
        return value

    def _erp_amount(self, amount):
        return formatLang(self.env, amount, currency_obj=self.currency_id)

    def _erp_number(self, value, digits=2):
        return formatLang(self.env, value, digits=digits)

    def _erp_entry(self):
        self.ensure_one()
        return self.date_entry or self.contract_id.date_start

    def _erp_monthly_payslips_domain(self):
        """Roles mensuales vigentes del empleado: confirmados, no reembolsos
        ni reembolsados (salvo reembolso anulado), de la empresa de la
        liquidación (mismo criterio que las provisiones pendientes)."""
        self.ensure_one()
        return [
            ("employee_id", "=", self.employee_id.id),
            ("company_id", "=", self.company_id.id),
            ("state", "=", "done"),
            ("credit_note", "=", False),
            "|",
            ("refunded_id", "=", False),
            ("refunded_id.state", "=", "cancel"),
        ]

    def _erp_get_remuneration_history(self):
        """Remuneración mensual del empleado desde la fecha de ingreso hasta
        la salida, según sus roles mensuales confirmados (estructura «Rol
        mensual Ecuador» o hija).

        Remuneración del mes = sueldo del periodo (``BASIC``) + ingresos
        propios (``INC_OTHER``) de conceptos con «Cuenta como remuneración»
        marcado (US-013, CA-14): se resta la parte de viáticos, reembolsos y
        otros ingresos no remunerativos
        (``hr.payslip._erp_get_non_remuneration_income_map``, en lote para
        todos los roles). Sin décimos ni
        fondos de reserva (interpretación a validar).

        sudo(): el cálculo necesita todo el historial del empleado aunque las
        reglas de registro del usuario oculten algún rol (p. ej. de otro
        departamento); solo se leen importes y fechas.

        :return: ``{(año, mes): {"amount", "excluded", "date_from",
            "date_to"}}`` ordenado por mes (``amount``: remuneración ya sin
            lo excluido; ``excluded``: ingresos no remunerativos excluidos)
        """
        self.ensure_one()
        entry = self._erp_entry()
        slips = (
            self.env["hr.payslip"]
            .sudo()
            .search(
                self._erp_monthly_payslips_domain()
                + [
                    ("date_from", "<=", self.date_departure),
                    ("date_to", ">=", entry),
                ],
                order="date_from, id",
            )
            .filtered(lambda slip: slip._erp_is_ec_monthly())
        )
        # Una sola reconstrucción en lote para todos los roles (sin consultas
        # por rol).
        excluded_by_slip = slips._erp_get_non_remuneration_income_map()
        history = {}
        for slip in slips:
            key = (slip.date_from.year, slip.date_from.month)
            gross = sum(
                line.total
                for line in slip.line_ids
                if line.code in REMUNERATION_LINE_CODES
            )
            excluded = excluded_by_slip[slip.id]
            month = history.setdefault(
                key,
                {
                    "amount": 0.0,
                    "excluded": 0.0,
                    "date_from": slip.date_from,
                    "date_to": slip.date_to,
                },
            )
            month["amount"] += gross - excluded
            month["excluded"] += excluded
            month["date_from"] = min(month["date_from"], slip.date_from)
            month["date_to"] = max(month["date_to"], slip.date_to)
        return dict(sorted(history.items()))

    def _erp_excluded_note(self, excluded):
        """Frase de la explicación de un rubro cuando se excluyeron ingresos
        que no son remuneración (CA-14); vacía si no se excluyó nada."""
        if self.currency_id.is_zero(excluded):
            return ""
        return " " + _(
            "Se excluyeron %(amount)s de ingresos que no son remuneración "
            "(conceptos con «Cuenta como remuneración» desmarcado, como "
            "viáticos o reembolsos de gastos).",
            amount=self._erp_amount(excluded),
        )

    def _erp_compute_last_wage(self, history):
        """Última remuneración mensual (base de la bonificación por desahucio
        y de la indemnización; aparece en el PDF).

        Fuente: la remuneración (sueldo e ingresos propios que cuentan como
        remuneración, CA-14) del último rol mensual confirmado de un mes
        completo de servicio (del día 1 al último día del mes, entre el
        ingreso y la salida). Si no hay ninguno (p. ej. menos de un mes de
        servicio), el sueldo mensual del contrato.

        :return: ``(importe, descripción de la fuente)``
        """
        self.ensure_one()
        entry = self._erp_entry()
        full_months = [
            month
            for month in history.values()
            if month["date_from"].day == 1
            and month["date_to"] == month["date_from"] + relativedelta(day=31)
            and month["date_from"] >= entry
            and month["date_to"] <= self.date_departure
        ]
        if full_months:
            month = full_months[-1]
            source = _(
                "remuneración del rol mensual de %(month)s",
                month=format_date(self.env, month["date_from"], date_format="MMMM y"),
            )
            if not self.currency_id.is_zero(month["excluded"]):
                source = _(
                    "%(origin)s, sin %(excluded)s de ingresos que no son "
                    "remuneración",
                    origin=source,
                    excluded=self._erp_amount(month["excluded"]),
                )
            return self.currency_id.round(month["amount"]), source
        return (
            self.currency_id.round(self.contract_id.wage),
            _(
                "sueldo mensual del contrato: no hay un rol mensual confirmado "
                "de un mes completo"
            ),
        )

    def _erp_get_last_payslips(self):
        """Roles mensuales confirmados cuyo periodo incluye la fecha de salida
        (CA-8). sudo(): ver el rol aunque las reglas de registro lo oculten.
        """
        self.ensure_one()
        return (
            self.env["hr.payslip"]
            .sudo()
            .search(
                self._erp_monthly_payslips_domain()
                + [
                    ("date_from", "<=", self.date_departure),
                    ("date_to", ">=", self.date_departure),
                ]
            )
            .filtered(lambda slip: slip._erp_is_ec_monthly())
        )

    def _erp_prepare_computation(self):
        """Valores de «Calcular» (sin escribir nada): rubros no manuales y
        última remuneración, según los indicadores ``pays_*`` de la causa y
        los parámetros vigentes a la fecha de salida.

        :return: ``{"last_wage": float, "lines": [vals], "vacation_allocations":
            [(hr.leave.allocation, días)]}``
        """
        self.ensure_one()
        cause = self.cause_id
        history = self._erp_get_remuneration_history()
        last_wage, wage_source = self._erp_compute_last_wage(history)
        last_month_missing = not self._erp_get_last_payslips()
        lines = []
        allocations = []
        if cause.pays_thirteenth:
            lines += self._erp_prepare_provision_line(LINE_D13, last_month_missing)
        if cause.pays_fourteenth:
            lines += self._erp_prepare_provision_line(LINE_D14, last_month_missing)
        if cause.pays_pending_vacation:
            vacation_lines, allocations = self._erp_prepare_pending_vacation_line(
                history
            )
            lines += vacation_lines
        if cause.pays_proportional_vacation:
            lines += self._erp_prepare_proportional_vacation_line(
                history, last_month_missing
            )
        if cause.pays_severance_bonus:
            lines += self._erp_prepare_severance_bonus_line(last_wage, wage_source)
        if cause.pays_unfair_dismissal_indemnity:
            lines += self._erp_prepare_indemnity_line(last_wage, wage_source)
        return {
            "last_wage": last_wage,
            "lines": lines,
            "vacation_allocations": allocations,
        }

    def _erp_line_vals(self, code, amount, base, quantity, explanation, **vals):
        return {
            "code": code,
            "name": dict(SETTLEMENT_LINE_CODE_SELECTION)[code],
            "sequence": LINE_SEQUENCES[code],
            "amount": self.currency_id.round(amount),
            "base": self.currency_id.round(base),
            "quantity": float_round(quantity, precision_digits=4),
            "explanation": explanation,
            "is_manual": False,
            **vals,
        }

    def _erp_prepare_provision_line(self, code, last_month_missing):
        """Décimo tercero o cuarto pendiente (CA-6.1, CA-6.2): provisiones
        mensuales de roles confirmados no pagadas (CA-3) hasta la fecha de
        salida, de cualquier periodo de cálculo (modalidad acumulada: en la
        mensual no hay provisiones). El décimo cuarto suma ambos regímenes
        (cada provisión lleva el suyo).

        La proporción del último mes no se calcula aquí: la paga la provisión
        del rol mensual de ese mes, que es obligatorio para confirmar (CA-8);
        si aún no está confirmado, la explicación lo indica y la confirmación
        exige recalcular.

        sudo(): ver todas las provisiones del empleado aunque las reglas de
        registro oculten algún rol; solo se leen importes y meses.
        """
        provisions = (
            self.env["hr.payslip.line"]
            .sudo()
            ._erp_get_pending_provision_lines(
                LINE_PROVISION_CODES[code],
                employees=self.employee_id,
                date_to=self.date_departure,
            )
            .filtered(lambda line: line.slip_id.company_id == self.company_id)
        )
        if not provisions:
            return []
        amount = self.currency_id.round(sum(provisions.mapped("total")))
        details = "; ".join(
            _(
                "%(month)s%(regime)s: %(amount)s",
                month=format_date(self.env, line.date_from, date_format="MMMM y"),
                regime=PROVISION_REGIME_LABELS.get(line.code, ""),
                amount=self._erp_amount(line.total),
            )
            for line in provisions
        )
        explanation = _(
            "Suma de %(count)s provisiones mensuales no pagadas hasta la fecha "
            "de salida (%(details)s) = %(amount)s.",
            count=len(provisions),
            details=details,
            amount=self._erp_amount(amount),
        )
        if last_month_missing:
            explanation += " " + _(
                "No incluye el mes de la salida: su rol mensual aún no está "
                "confirmado. Al confirmarlo, vuelva a calcular."
            )
        return [
            self._erp_line_vals(
                code,
                amount,
                amount,
                len(provisions),
                explanation,
                provision_line_ids=[Command.set(provisions.ids)],
            )
        ]

    def _erp_prorated_remuneration(self, history, date_from):
        """Remuneración percibida de ``date_from`` a la fecha de salida según
        ``history``: cada mes entra en proporción a sus días dentro del
        intervalo (convención de mes de 30 días, parámetro MONTH_DAYS,
        ``days_30``), sobre los días que pagó su rol (desde el ingreso hasta
        la salida).

        :return: ``(remuneración, ingresos no remunerativos excluidos, días
            cubiertos por roles confirmados)``
        """
        self.ensure_one()
        entry = self._erp_entry()
        departure = self.date_departure
        month_days = int(self._erp_param_positive("MONTH_DAYS"))
        remuneration = excluded = 0.0
        covered = 0
        for month in history.values():
            if month["date_to"] < date_from:
                continue
            start = max(month["date_from"], entry)
            end = min(month["date_to"], departure)
            worked = days_30(start, end, month_days)
            if not worked:
                continue
            part = days_30(max(date_from, start), end, month_days)
            if not part:
                continue
            remuneration += month["amount"] * part / worked
            excluded += month["excluded"] * part / worked
            covered += part
        return remuneration, excluded, covered

    def _erp_vacation_day_value(self, history):
        """Valor del día de vacaciones no gozadas (CA-6.3).

        Ventana: el año móvil de remuneración percibida inmediatamente
        anterior a la fecha de salida, de ``VACATION_DAY_BASE_MONTHS`` meses
        (p. ej. 12 meses y salida el 15/04/2026 -> del 16/04/2025 al
        15/04/2026). Los meses parciales entran en proporción a sus días
        dentro de la ventana con la convención de 30 días
        (``_erp_prorated_remuneration``)::

            valor del día = remuneración de la ventana
                            × (VACATION_DAY_BASE_MONTHS × MONTH_DAYS)
                            / (VACATION_DAY_DIVISOR × días cubiertos)

        Con la ventana completa cubierta por roles confirmados (360 días con
        12 meses de 30) equivale a «remuneración del último año / divisor»
        (12 meses / 360). Con menos historial (ingreso reciente, roles
        anteriores al sistema) se promedia sobre los días disponibles en
        lugar de tratar los que faltan como cero. Remuneración: sueldo e
        ingresos que cuentan como remuneración (CA-14). Interpretación a
        validar con el asesor laboral.

        :return: ``(valor del día, explicación)``
        """
        base_months = int(self._erp_param_positive(VACATION_DAY_BASE_MONTHS))
        divisor = self._erp_param_positive(VACATION_DAY_DIVISOR)
        month_days = int(self._erp_param_positive("MONTH_DAYS"))
        departure = self.date_departure
        window_start = departure + timedelta(days=1) - relativedelta(months=base_months)
        window_days = base_months * month_days
        total, excluded, covered = self._erp_prorated_remuneration(
            history, window_start
        )
        if not covered:
            raise UserError(
                _(
                    "No se puede calcular el valor del día de vacaciones de "
                    "%(employee)s: no hay roles mensuales confirmados entre el "
                    "%(start)s y la fecha de salida (%(departure)s).",
                    employee=self.employee_id.name,
                    start=format_date(self.env, window_start),
                    departure=format_date(self.env, departure),
                )
            )
        day_value = total * window_days / (divisor * covered)
        if covered >= window_days:
            explanation = _(
                "Valor del día = remuneración percibida en el año anterior a la "
                "salida, del %(start)s al %(end)s (%(total)s), / %(divisor)s = "
                "%(day)s.",
                start=format_date(self.env, window_start),
                end=format_date(self.env, departure),
                total=self._erp_amount(total),
                divisor=self._erp_number(divisor),
                day=self._erp_number(day_value, 4),
            )
        else:
            explanation = _(
                "Valor del día = remuneración percibida del %(start)s al %(end)s "
                "según los roles mensuales confirmados (%(total)s, %(covered)s "
                "de %(window)s días con rol) × %(window)s / (%(divisor)s × "
                "%(covered)s) = %(day)s.",
                start=format_date(self.env, window_start),
                end=format_date(self.env, departure),
                total=self._erp_amount(total),
                covered=covered,
                window=window_days,
                divisor=self._erp_number(divisor),
                day=self._erp_number(day_value, 4),
            )
        explanation += " " + _(
            "Los meses parciales cuentan en proporción a sus días (mes de "
            "%(month_days)s días); criterio a validar con el asesor laboral.",
            month_days=month_days,
        )
        explanation += self._erp_excluded_note(excluded)
        return day_value, explanation

    def _erp_prepare_pending_vacation_line(self, history):
        """Vacaciones no gozadas (CA-6.3): saldo de los periodos vigentes a
        la fecha de salida (``hr.employee._erp_get_settlement_vacation_balance``)
        × valor del día (``_erp_vacation_day_value``).

        :return: ``([vals], [(hr.leave.allocation, días)])``
        """
        balance = self.employee_id._erp_get_settlement_vacation_balance(
            self.date_departure
        )
        days = float_round(sum(days for _allocation, days in balance), 2)
        if float_compare(days, 0.0, precision_digits=2) <= 0:
            return [], []
        day_value, day_explanation = self._erp_vacation_day_value(history)
        amount = self.currency_id.round(days * day_value)
        periods = "; ".join(
            _(
                "%(period)s: %(days)s",
                period=allocation.name,
                days=self._erp_number(period_days),
            )
            for allocation, period_days in balance
        )
        explanation = _(
            "Saldo de vacaciones no gozadas a la fecha de salida: %(days)s días "
            "(%(periods)s). %(day_value)s Importe = %(days)s × %(value)s = "
            "%(amount)s.",
            days=self._erp_number(days),
            periods=periods,
            day_value=day_explanation,
            value=self._erp_number(day_value, 4),
            amount=self._erp_amount(amount),
        )
        return (
            [
                self._erp_line_vals(
                    LINE_VAC_PENDING, amount, day_value, days, explanation
                )
            ],
            balance,
        )

    def _erp_current_service_year_start(self):
        """Inicio del año de servicio en curso a la fecha de salida (último
        aniversario de la fecha de ingreso que no la supera)."""
        entry = self._erp_entry()
        completed = relativedelta(self.date_departure, entry).years
        return entry + relativedelta(years=completed)

    def _erp_prepare_proportional_vacation_line(self, history, last_month_missing):
        """Vacaciones proporcionales del año de servicio en curso (CA-6.4):

            remuneraciones del año de servicio en curso
            / VACATION_PROPORTIONAL_DIVISOR

        Remuneraciones: las de los roles mensuales confirmados desde el último
        aniversario hasta la salida; el mes del aniversario entra en
        proporción a los días posteriores a él (convención de 30 días,
        parámetro MONTH_DAYS, ``_erp_prorated_remuneration``). Solo cuenta
        lo que es remuneración (CA-14). El periodo del año en curso aún no
        tiene asignación de vacaciones (nace en el aniversario).
        """
        departure = self.date_departure
        year_start = self._erp_current_service_year_start()
        month_days = int(self._erp_param_positive("MONTH_DAYS"))
        remuneration, excluded, _covered = self._erp_prorated_remuneration(
            history, year_start
        )
        divisor = self._erp_param_positive(VACATION_PROPORTIONAL_DIVISOR)
        amount = self.currency_id.round(remuneration / divisor)
        if self.currency_id.is_zero(amount):
            return []
        days = days_30(year_start, departure, month_days)
        explanation = _(
            "Año de servicio en curso: del %(start)s al %(end)s (%(days)s días). "
            "Remuneraciones de ese periodo según los roles mensuales "
            "confirmados: %(remuneration)s. Vacaciones proporcionales = "
            "%(remuneration)s / %(divisor)s = %(amount)s.",
            start=format_date(self.env, year_start),
            end=format_date(self.env, departure),
            days=days,
            remuneration=self._erp_amount(remuneration),
            divisor=self._erp_number(divisor),
            amount=self._erp_amount(amount),
        )
        explanation += self._erp_excluded_note(excluded)
        if last_month_missing:
            explanation += " " + _(
                "No incluye el mes de la salida: su rol mensual aún no está "
                "confirmado. Al confirmarlo, vuelva a calcular."
            )
        return [
            self._erp_line_vals(
                LINE_VAC_PROPORTIONAL, amount, remuneration, days, explanation
            )
        ]

    def _erp_service_year_fraction(self):
        """Fracción del año de servicio en curso: días desde el último
        aniversario hasta la salida (incluida) / días de ese año de servicio
        (365 o 366)."""
        entry = self._erp_entry()
        anniversary = entry + relativedelta(years=self.service_years)
        next_anniversary = entry + relativedelta(years=self.service_years + 1)
        elapsed = (self.date_departure + timedelta(days=1) - anniversary).days
        return elapsed, (next_anniversary - anniversary).days

    def _erp_prepare_severance_bonus_line(self, last_wage, wage_source):
        """Bonificación por desahucio (CA-6.5):

            última remuneración × SEVERANCE_BONUS_RATE % × años de servicio

        Años: los completos más, si SEVERANCE_BONUS_PROPORTIONAL_FRACTION = 1,
        la fracción del año en curso en días (``_erp_service_year_fraction``).
        """
        rate = self._erp_param(SEVERANCE_BONUS_RATE)
        proportional = self._erp_param(SEVERANCE_BONUS_PROPORTIONAL_FRACTION)
        years = float(self.service_years)
        elapsed, year_days = self._erp_service_year_fraction()
        if proportional and elapsed:
            years += elapsed / year_days
            detail = _(
                "%(full)s años completos y %(elapsed)s de %(year_days)s días del "
                "año en curso",
                full=self.service_years,
                elapsed=elapsed,
                year_days=year_days,
            )
        else:
            detail = _("solo años completos")
        years = float_round(years, precision_digits=4)
        amount = self.currency_id.round(last_wage * rate / 100 * years)
        if self.currency_id.is_zero(amount):
            return []
        explanation = _(
            "Última remuneración mensual %(wage)s (%(origin)s) × %(rate)s %% × "
            "%(years)s años de servicio (%(detail)s) = %(amount)s.",
            wage=self._erp_amount(last_wage),
            origin=wage_source,
            rate=self._erp_number(rate),
            years=self._erp_number(years, 4),
            detail=detail,
            amount=self._erp_amount(amount),
        )
        return [
            self._erp_line_vals(
                LINE_SEVERANCE_BONUS, amount, last_wage, years, explanation
            )
        ]

    def _erp_prepare_indemnity_line(self, last_wage, wage_source):
        """Indemnización por despido intempestivo (CA-6.6):

            meses = meses fijos + meses por año × años, acotado a [mínimo,
            máximo] del tramo (``erp.hr.indemnity.bracket._get_bracket``)
            indemnización = última remuneración × meses

        Años: si INDEMNITY_YEAR_FRACTION_AS_FULL = 1, la fracción de año
        cuenta como año completo; si es 0, solo los años completos (el tramo
        se busca con los años exactos, para que menos de un año caiga en el
        primer tramo).
        """
        as_full = self._erp_param(INDEMNITY_YEAR_FRACTION_AS_FULL)
        elapsed, year_days = self._erp_service_year_fraction()
        full_years = self.service_years
        if elapsed and as_full:
            years = full_years + 1
            lookup_years = years
            rounding = _(" (la fracción de año cuenta como año completo)")
        else:
            years = full_years
            lookup_years = full_years + (elapsed / year_days if elapsed else 0)
            rounding = _(" (solo años completos)")
        bracket = self.env["erp.hr.indemnity.bracket"]._get_bracket(
            lookup_years, self.date_departure, self.company_id
        )
        months = bracket.fixed_months + bracket.months_per_year * years
        months = max(months, bracket.min_months)
        if bracket.max_months:
            months = min(months, bracket.max_months)
        amount = self.currency_id.round(last_wage * months)
        if self.currency_id.is_zero(amount):
            return []
        explanation = _(
            "Tramo «%(bracket)s»: %(fixed)s meses fijos + %(per_year)s meses × "
            "%(years)s años de servicio%(rounding)s, con mínimo %(min)s y "
            "máximo %(max)s = %(months)s meses. Indemnización = última "
            "remuneración mensual %(wage)s (%(origin)s) × %(months)s meses = "
            "%(amount)s.",
            bracket=bracket.name,
            fixed=self._erp_number(bracket.fixed_months),
            per_year=self._erp_number(bracket.months_per_year),
            years=years,
            rounding=rounding,
            min=self._erp_number(bracket.min_months),
            max=(
                self._erp_number(bracket.max_months)
                if bracket.max_months
                else _("sin tope")
            ),
            months=self._erp_number(months),
            wage=self._erp_amount(last_wage),
            origin=wage_source,
            amount=self._erp_amount(amount),
        )
        return [
            self._erp_line_vals(LINE_INDEMNITY, amount, last_wage, months, explanation)
        ]

    # ------------------------------------------------------------------
    # Confirmar (US-013, CA-8, CA-9)
    # ------------------------------------------------------------------
    def action_confirm(self):
        """Confirma la liquidación calculada (solo el responsable de nómina).

        En una sola transacción, por liquidación:

        1. CA-8: exige el rol mensual confirmado cuyo periodo incluye la
           fecha de salida, calculado con el contrato terminado en esa fecha.
        2. Recalcula en memoria y exige que coincida con lo guardado (rubros
           no manuales, provisiones y última remuneración): si cambió algo
           desde «Calcular», ``UserError`` (recalcular).
        3. Neto no negativo; ningún contrato del empleado posterior a la
           salida.
        4. Número (secuencia «LIQ/AAAA/NNNN») si aún no lo tiene.
        5. Marca las provisiones pagadas (``document_type='settlement'``,
           CA-3) y deja sin saldo los periodos de vacaciones liquidados
           (``erp_settlement_id``, ``erp_settled_days``), reversible.
        6. Asiento contable (``_erp_prepare_move_vals``), publicado.
        7. Cierra el contrato (fin = fecha de salida, estado «Expirado») y
           archiva al empleado con el motivo y la fecha de salida.
        """
        self._erp_check_manager(
            _(
                "Solo el responsable de nómina puede confirmar una liquidación. "
                "Pida a un responsable de nómina que la revise y la confirme."
            )
        )
        self._erp_check_state(
            ("computed",),
            _(
                "Solo se confirma una liquidación calculada: %(settlements)s. "
                "Pulse «Calcular» y revise los valores antes de confirmar."
            ),
        )
        self.check_access("write")
        for settlement in self:
            settlement._erp_confirm_one()
        return True

    def _erp_confirm_one(self):
        self.ensure_one()
        self._erp_check_last_payslip()
        values = self._erp_prepare_computation()
        self._erp_check_up_to_date(values)
        self._erp_check_net()
        self._erp_check_later_contracts()
        with self._erp_transition():
            vals = {"state": "done"}
            if not self.name or self.name == "/":
                # sudo(): secuencia técnica común; solo se obtiene el número.
                number = (
                    self.env["ir.sequence"]
                    .sudo()
                    .next_by_code(
                        SETTLEMENT_SEQUENCE_CODE,
                        sequence_date=fields.Date.context_today(self),
                    )
                )
                if not number:
                    raise UserError(
                        _(
                            "No existe la secuencia de liquidaciones (código "
                            "%(code)s). Pida al administrador que la restaure.",
                            code=SETTLEMENT_SEQUENCE_CODE,
                        )
                    )
                vals["name"] = number
            self.write(vals)
            self._erp_link_paid_provisions()
            self._erp_settle_vacation_periods(values["vacation_allocations"])
            move = self._erp_create_move()
            if move:
                self.write({"move_id": move.id})
            self._erp_close_contract_and_employee()
        self.message_post(
            body=_(
                "Liquidación confirmada. Contrato «%(contract)s» cerrado al "
                "%(departure)s y empleado archivado.",
                contract=self.contract_id.name,
                departure=format_date(self.env, self.date_departure),
            )
        )

    def _erp_check_last_payslip(self):
        """CA-8: el sueldo de los días trabajados del último mes se paga en el
        rol mensual. Debe existir un rol mensual confirmado cuyo periodo
        incluya la fecha de salida, y no puede haber pagado días posteriores a
        ella (contrato sin fin o con fin posterior a la salida cuando el rol
        llega más allá)."""
        self.ensure_one()
        departure = self.date_departure
        slips = self._erp_get_last_payslips()
        if not slips:
            raise UserError(
                _(
                    "Falta el rol mensual confirmado de %(employee)s del "
                    "%(date_from)s al %(date_to)s: el sueldo de los días "
                    "trabajados del último mes se paga en el rol mensual. "
                    "Registre la fecha de fin del contrato, calcule y confirme "
                    "ese rol antes de confirmar la liquidación.",
                    employee=self.employee_id.name,
                    date_from=format_date(self.env, departure.replace(day=1)),
                    date_to=format_date(self.env, departure),
                )
            )
        contract_end = self.contract_id.date_end
        overpaid = slips.filtered(
            lambda slip: slip.date_to > departure
            and (not contract_end or contract_end > departure)
        )
        if overpaid:
            raise UserError(
                _(
                    "El rol mensual %(payslip)s de %(employee)s llega hasta el "
                    "%(date_to)s y el contrato «%(contract)s» no termina en la "
                    "fecha de salida (%(departure)s): pudo pagar días no "
                    "trabajados. Registre en el contrato la fecha de fin "
                    "%(departure)s, anule y recalcule ese rol, y vuelva a "
                    "calcular la liquidación.",
                    payslip=overpaid[0].number or overpaid[0].name,
                    employee=self.employee_id.name,
                    date_to=format_date(self.env, overpaid[0].date_to),
                    contract=self.contract_id.name,
                    departure=format_date(self.env, departure),
                )
            )

    def _erp_check_up_to_date(self, values):
        """Lo guardado coincide con un cálculo nuevo (rubros no manuales,
        importes, provisiones incluidas y última remuneración)."""
        self.ensure_one()
        currency = self.currency_id

        def key(code, amount, provision_ids):
            return (code, currency.round(amount), tuple(sorted(provision_ids)))

        current = sorted(
            key(line.code, line.amount, line.provision_line_ids.ids)
            for line in self.line_ids
            if not line.is_manual
        )
        fresh = sorted(
            key(
                vals["code"],
                vals["amount"],
                vals["provision_line_ids"][0][2]
                if vals.get("provision_line_ids")
                else [],
            )
            for vals in values["lines"]
        )
        if current != fresh or currency.compare_amounts(
            self.last_wage, values["last_wage"]
        ):
            raise UserError(
                _(
                    "Los datos de la liquidación de %(employee)s cambiaron desde "
                    "el último cálculo (roles, provisiones, vacaciones, "
                    "parámetros o rubros calculados editados). Pulse «Calcular» "
                    "de nuevo y revise los valores antes de confirmar.",
                    employee=self.employee_id.name,
                )
            )

    def _erp_check_later_contracts(self):
        """Una liquidación termina la relación laboral: el empleado no puede
        tener otro contrato (borrador o en curso) que empiece después de la
        salida. sudo(): solo se leen fechas y nombres de contratos."""
        self.ensure_one()
        later = (
            self.env["hr.contract"]
            .sudo()
            .search(
                [
                    ("employee_id", "=", self.employee_id.id),
                    ("id", "!=", self.contract_id.id),
                    ("state", "in", ("draft", "open")),
                    ("date_start", ">", self.date_departure),
                ],
                limit=1,
            )
        )
        if later:
            raise UserError(
                _(
                    "%(employee)s tiene el contrato «%(contract)s», que empieza "
                    "el %(start)s, después de la fecha de salida. Una "
                    "liquidación termina la relación laboral y archiva al "
                    "empleado: revise o anule ese contrato antes de confirmar.",
                    employee=self.employee_id.name,
                    contract=later.name,
                    start=format_date(self.env, later.date_start),
                )
            )

    def _erp_link_paid_provisions(self):
        """Marca como pagadas por la liquidación las provisiones de sus
        rubros de décimos (CA-3, CA-9 d).

        sudo(): las marcas son datos derivados de la liquidación que se está
        confirmando (permiso del responsable ya comprobado); la restricción
        UNIQUE de la BD impide un pago doble."""
        vals_list = [
            {
                "payslip_line_id": provision.id,
                "amount": provision.total,
                "document_type": "settlement",
                "settlement_id": self.id,
            }
            for line in self.line_ids
            if line.code in LINE_PROVISION_CODES
            for provision in line.provision_line_ids
        ]
        if vals_list:
            self.env["erp.payroll.provision.payment"].sudo().create(vals_list)

    def _erp_settle_vacation_periods(self, balance):
        """Deja sin saldo los periodos de vacaciones pagados (CA-9 c): resta
        los días liquidados de ``number_of_days``, los guarda en
        ``erp_settled_days`` y marca la liquidación (se devuelven exactamente
        al anular, ``_erp_restore_vacation_periods``).

        sudo(): el responsable de nómina no gestiona ausencias; solo se
        ajustan los periodos que paga esta liquidación."""
        for allocation, days in balance:
            allocation = allocation.sudo()
            allocation.write(
                {
                    "number_of_days": float_round(
                        allocation.number_of_days - days, precision_digits=2
                    ),
                    "erp_settled_days": days,
                    "erp_settlement_id": self.id,
                }
            )

    def _erp_restore_vacation_periods(self):
        """Devuelve a cada periodo liquidado exactamente los días que se le
        quitaron y retira la marca (CA-10).

        sudo(): ver ``_erp_settle_vacation_periods``."""
        for allocation in self.sudo().settled_allocation_ids:
            allocation.write(
                {
                    "number_of_days": float_round(
                        allocation.number_of_days + allocation.erp_settled_days,
                        precision_digits=2,
                    ),
                    "erp_settled_days": 0.0,
                    "erp_settlement_id": False,
                }
            )

    def _erp_close_contract_and_employee(self):
        """Cierra el contrato (fin = fecha de salida, «Expirado») y archiva al
        empleado con el motivo de salida de la causa (si tiene) y la fecha de
        salida (CA-9 b).

        sudo(): el responsable de nómina no es gestor de contratos ni de
        empleados; solo se escriben los campos de la salida del contrato y
        del empleado de esta liquidación."""
        self.ensure_one()
        self.contract_id.sudo().write(
            {"date_end": self.date_departure, "state": "close"}
        )
        employee = self.employee_id.sudo()
        if employee.active:
            employee.with_context(no_wizard=True).action_archive()
        vals = {
            "departure_date": self.date_departure,
            "departure_description": _(
                "Liquidación de haberes %(number)s (%(cause)s).",
                number=self.name,
                cause=self.cause_id.name,
            ),
        }
        if self.cause_id.departure_reason_id:
            vals["departure_reason_id"] = self.cause_id.departure_reason_id.id
        employee.write(vals)

    # --- Asiento contable -------------------------------------------------
    def _erp_get_account(self, field_name):
        """Cuenta de gasto configurada en la empresa o, si está vacía, la del
        plan con el código por defecto (``DEFAULT_ACCOUNT_CODES``)."""
        company = self.company_id
        account = company[field_name]
        if not account:
            Account = self.env["account.account"].sudo().with_company(company)
            account = Account.search(
                [
                    *Account._check_company_domain(company),
                    ("code", "=", DEFAULT_ACCOUNT_CODES[field_name]),
                ],
                limit=1,
            )
        if not account:
            # Mismas etiquetas que el bloque «Cuentas de gasto de la
            # liquidación» de Ajustes › Nómina › Liquidación de haberes.
            labels = {
                "erp_settlement_vacation_account_id": _("Vacaciones"),
                "erp_settlement_severance_account_id": _("Desahucio"),
                "erp_settlement_indemnity_account_id": _("Indemnización"),
            }
            raise UserError(
                _(
                    "Configure la cuenta «%(label)s» (Cuentas de gasto de la "
                    "liquidación) en Ajustes › Nómina › Liquidación de haberes "
                    "para la empresa %(company)s: no está indicada y el plan "
                    "de cuentas no tiene la cuenta %(code)s.",
                    label=labels.get(field_name)
                    or company._fields[field_name]._description_string(self.env),
                    company=company.name,
                    code=DEFAULT_ACCOUNT_CODES[field_name],
                )
            )
        return account

    def _erp_get_rule_account(self, xmlid, field_name, label):
        rule = self.env.ref(xmlid, raise_if_not_found=False)
        account = rule and rule.sudo().with_company(self.company_id)[field_name]
        if not account:
            raise UserError(
                _(
                    "No hay cuenta contable para %(label)s: indíquela en el "
                    "rubro (rubros manuales), en los ajustes de liquidaciones o "
                    "en la regla del rol mensual correspondiente.",
                    label=label,
                )
            )
        return account

    def _erp_get_payable_account(self):
        return self.company_id.erp_settlement_payable_account_id or (
            self._erp_get_rule_account(
                "erp_payroll_ec.rule_ec_net",
                "account_credit",
                _("el neto por pagar de la liquidación"),
            )
        )

    def _erp_prepare_move_vals(self):
        """Valores del asiento de la liquidación (CA-9 a), con las
        convenciones del rol mensual: diario de la liquidación o del
        contrato, empleado como tercero en cuentas por cobrar y pasivos,
        analítica del contrato en las cuentas de gasto.

        - Décimos: debe de la cuenta de pasivo de cada provisión (la cuenta
          acreedora de la regla que la provisionó; sin gasto nuevo).
        - Vacaciones (no gozadas y proporcionales), desahucio e indemnización:
          debe de su cuenta de gasto (``_erp_get_account``).
        - Otro ingreso manual: debe de la cuenta del rubro o de la regla
          «Otros ingresos» del rol mensual.
        - Otro descuento manual: haber de la cuenta del rubro o de la regla
          «Otros descuentos» del rol mensual.
        - Neto: haber de la cuenta por pagar (ajustes o regla «Neto»).

        :return: ``dict`` para ``account.move.create`` o ``None`` (sin
            importes)
        :raises UserError: sin diario, sin cuenta o asiento descuadrado
        """
        self.ensure_one()
        journal = self.journal_id or self.contract_id.journal_id
        if not journal:
            raise UserError(
                _(
                    "La liquidación de %(employee)s no tiene diario: indíquelo en "
                    "la liquidación o en el contrato (pestaña de contabilidad).",
                    employee=self.employee_id.name,
                )
            )
        currency = self.currency_id
        employee = self.employee_id.sudo()
        partner = employee.work_contact_id or employee.bank_account_id.partner_id
        analytic = self.contract_id.analytic_account_id
        # (cuenta, descripción) -> [debe, haber]
        amounts = defaultdict(lambda: [0.0, 0.0])
        for line in self.line_ids:
            if currency.is_zero(line.amount):
                continue
            if line.code in LINE_PROVISION_CODES:
                for provision in line.provision_line_ids.sudo():
                    account = provision.salary_rule_id.with_company(
                        self.company_id
                    ).account_credit
                    if not account:
                        raise UserError(
                            _(
                                "La regla «%(rule)s» no tiene cuenta acreedora "
                                "(pasivo de la provisión) para la empresa "
                                "%(company)s.",
                                rule=provision.salary_rule_id.name,
                                company=self.company_id.name,
                            )
                        )
                    amounts[(account, line.name)][0] += provision.total
            elif line.code in EXPENSE_ACCOUNT_FIELDS:
                account = self._erp_get_account(EXPENSE_ACCOUNT_FIELDS[line.code])
                amounts[(account, line.name)][0] += line.amount
            elif line.code == LINE_OTHER_INCOME:
                account = line.account_id or self._erp_get_rule_account(
                    "erp_payroll_ec.rule_ec_inc_other",
                    "account_debit",
                    line.name,
                )
                amounts[(account, line.name)][0] += line.amount
            elif line.code == LINE_OTHER_DEDUCTION:
                account = line.account_id or self._erp_get_rule_account(
                    "erp_payroll_ec.rule_ec_ded_other",
                    "account_debit",
                    line.name,
                )
                amounts[(account, line.name)][1] += line.amount
        if not currency.is_zero(self.net):
            account = self._erp_get_payable_account()
            amounts[(account, _("Neto de la liquidación"))][1] += self.net
        if not amounts:
            return None
        date = self.date_departure
        line_vals = []
        for (account, label), (debit, credit) in amounts.items():
            balance = currency.round(debit - credit)
            if currency.is_zero(balance):
                continue
            vals = {
                "name": label,
                "account_id": account.id,
                "debit": balance if balance > 0 else 0.0,
                "credit": -balance if balance < 0 else 0.0,
                "partner_id": (
                    partner.id
                    if account.account_type in EMPLOYEE_PARTNER_ACCOUNT_TYPES
                    else False
                ),
                "date": date,
            }
            if analytic and account.account_type in ("expense", "expense_direct_cost"):
                vals["analytic_distribution"] = {analytic.id: 100}
            line_vals.append(vals)
        debit = sum(vals["debit"] for vals in line_vals)
        credit = sum(vals["credit"] for vals in line_vals)
        if currency.compare_amounts(debit, credit):
            raise UserError(
                _(
                    "El asiento de la liquidación de %(employee)s no cuadra (debe "
                    "%(debit)s, haber %(credit)s). Vuelva a calcular la "
                    "liquidación.",
                    employee=self.employee_id.name,
                    debit=self._erp_amount(debit),
                    credit=self._erp_amount(credit),
                )
            )
        return {
            "move_type": "entry",
            "journal_id": journal.id,
            "date": date,
            "ref": self.name,
            "narration": _(
                "Liquidación de haberes de %(employee)s",
                employee=self.employee_id.name,
            ),
            "line_ids": [Command.create(vals) for vals in line_vals],
        }

    def _erp_create_move(self):
        """Crea y publica el asiento. sudo(): el responsable de nómina
        contabiliza sin ser contador (mismo criterio que el rol mensual); el
        contenido sale íntegro de la liquidación calculada y de las cuentas
        configuradas."""
        move_vals = self.sudo()._erp_prepare_move_vals()
        if not move_vals:
            return self.env["account.move"]
        move = self.env["account.move"].sudo().create(move_vals)
        move.action_post()
        return move

    # ------------------------------------------------------------------
    # Anular y volver a borrador (US-013, CA-10)
    # ------------------------------------------------------------------
    def action_cancel(self):
        """Anula liquidaciones.

        - Confirmada: solo el responsable de nómina y si su asiento no tiene
          apuntes conciliados. Revierte el asiento (``reversal_move_id``),
          elimina las marcas de provisión pagada y devuelve los días de
          vacaciones liquidados. El contrato y el empleado no se reabren (lo
          indica el historial).
        - Borrador o calculada: se anula sin más.
        """
        self._erp_check_state(
            ("draft", "computed", "done"),
            _("La liquidación ya está anulada: %(settlements)s."),
        )
        done = self.filtered(lambda s: s.state == "done")
        if done:
            self._erp_check_manager(
                _(
                    "Solo el responsable de nómina puede anular una liquidación "
                    "confirmada."
                )
            )
            done._erp_check_moves_not_reconciled()
        self.check_access("write")
        for settlement in done:
            with settlement._erp_transition():
                reversal = settlement._erp_reverse_move()
                settlement.provision_payment_ids.sudo().unlink()
                settlement._erp_restore_vacation_periods()
                settlement.write(
                    {"state": "cancel", "reversal_move_id": reversal.id or False}
                )
            settlement.message_post(
                body=_(
                    "Liquidación anulada: el asiento se revirtió y las "
                    "provisiones de décimos y los días de vacaciones vuelven a "
                    "estar pendientes. El contrato «%(contract)s» y la ficha de "
                    "%(employee)s no se reabren solos: si la relación laboral "
                    "continúa, RRHH debe reabrir el contrato y desarchivar al "
                    "empleado.",
                    contract=settlement.contract_id.name,
                    employee=settlement.employee_id.name,
                )
            )
        with self._erp_transition():
            (self - done).write({"state": "cancel"})
        return True

    def _erp_check_moves_not_reconciled(self):
        """sudo(): solo lectura de la conciliación del asiento propio."""
        reconciled = self.filtered(
            lambda s: s.move_id
            and s.move_id.sudo().line_ids.filtered(
                lambda ml: ml.matched_debit_ids or ml.matched_credit_ids
            )
        )
        if reconciled:
            raise UserError(
                _(
                    "No se puede anular la liquidación %(settlements)s: su "
                    "asiento contable tiene apuntes conciliados (por ejemplo, el "
                    "pago al empleado). Pida a contabilidad que rompa la "
                    "conciliación y vuelva a anular.",
                    settlements=", ".join(reconciled.mapped("display_name")),
                )
            )

    def _erp_reverse_move(self):
        """Revierte el asiento publicado (fecha de hoy) o cancela el
        borrador. sudo(): mismo criterio que la creación del asiento.

        :return: asiento de reversión (vacío si no hay)"""
        self.ensure_one()
        move = self.move_id.sudo()
        if move.state == "posted":
            return move._reverse_moves(
                [
                    {
                        "date": fields.Date.context_today(self),
                        "ref": _("Reversión de la liquidación %s", self.name),
                    }
                ],
                cancel=True,
            )
        if move.state == "draft":
            move.button_cancel()
        return self.env["account.move"]

    def action_draft(self):
        """Vuelve a borrador una liquidación calculada o anulada. Desde
        «Anulada» se comprueba que el contrato no tenga otra liquidación no
        anulada y se desenlazan los asientos anteriores (quedan en el
        historial)."""
        self._erp_check_state(
            ("computed", "cancel"),
            _(
                "Solo vuelve a borrador una liquidación calculada o anulada: "
                "%(settlements)s. Una confirmada se anula primero."
            ),
        )
        self.check_access("write")
        cancelled = self.filtered(lambda s: s.state == "cancel")
        self._erp_check_duplicate_contract(cancelled.contract_id.ids, exclude=self)
        with self._erp_transition():
            cancelled.write(
                {"state": "draft", "move_id": False, "reversal_move_id": False}
            )
            (self - cancelled).write({"state": "draft"})
        return True
