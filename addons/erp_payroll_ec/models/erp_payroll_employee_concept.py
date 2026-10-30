from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.misc import format_date


class ErpPayrollEmployeeConcept(models.Model):
    """Asignación de un concepto fijo a un empleado con importe y vigencia
    (US-008, CA-7).

    El solapamiento de vigencias del mismo concepto y empleado lo valida la
    capa de negocio (``ValidationError``); la BD garantiza importe positivo y
    rango de fechas coherente.
    """

    _name = "erp.payroll.employee.concept"
    _description = "Concepto de nómina asignado al empleado"
    _inherit = ["mail.thread"]
    _order = "employee_id, concept_id, date_from desc, id desc"
    _check_company_auto = True

    # index=True: el rol busca las asignaciones vigentes de un lote de
    # empleados (employee_id IN (...) y fechas).
    employee_id = fields.Many2one(
        "hr.employee",
        string="Empleado",
        required=True,
        index=True,
        ondelete="cascade",
        tracking=True,
    )
    # index=True: FK con ondelete=restrict (la comprobación al borrar un
    # concepto busca por esta columna) y filtro por concepto en la interfaz.
    concept_id = fields.Many2one(
        "erp.payroll.concept",
        string="Concepto",
        required=True,
        index=True,
        ondelete="restrict",
        check_company=True,
        tracking=True,
        domain="[('amount_kind', '=', 'fixed')]",
    )
    concept_type = fields.Selection(related="concept_id.concept_type", string="Tipo")
    amount = fields.Monetary(
        string="Importe",
        required=True,
        currency_field="currency_id",
        tracking=True,
        help="Importe mensual en positivo; el tipo del concepto indica si es "
        "ingreso o descuento.",
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Moneda",
    )
    date_from = fields.Date(string="Vigente desde", required=True, tracking=True)
    date_to = fields.Date(
        string="Vigente hasta",
        tracking=True,
        help="Vacío: sin fecha de fin.",
    )
    company_id = fields.Many2one(
        related="employee_id.company_id",
        store=True,
        precompute=True,
        index=True,
        string="Empresa",
    )
    active = fields.Boolean(string="Activo", default=True, tracking=True)
    note = fields.Text(string="Notas")

    _sql_constraints = [
        (
            "amount_positive_check",
            "CHECK (amount > 0)",
            "El importe del concepto asignado debe ser mayor que cero.",
        ),
        (
            "date_range_check",
            "CHECK (date_to IS NULL OR date_to >= date_from)",
            "La fecha «Vigente hasta» no puede ser anterior a «Vigente desde».",
        ),
    ]

    # ------------------------------------------------------------------
    # Validaciones (US-008, CA-7)
    # ------------------------------------------------------------------
    @api.constrains("concept_id")
    def _check_erp_fixed_concept(self):
        """Solo se asignan conceptos fijos; los variables se registran como
        entradas del rol."""
        for assignment in self:
            if assignment.concept_id.amount_kind != "fixed":
                raise ValidationError(
                    _(
                        "El concepto «%(concept)s» es variable: no se asigna al "
                        "empleado, se registra como entrada en cada rol de pagos.",
                        concept=assignment.concept_id.name,
                    )
                )

    @api.constrains("employee_id", "concept_id", "date_from", "date_to", "active")
    def _check_erp_no_overlap(self):
        """Un empleado no puede tener dos asignaciones activas del mismo
        concepto con vigencias que se solapen (ambas fechas incluidas; sin
        fecha de fin = sin límite). Una sola búsqueda para todo el lote."""
        active = self.filtered("active")
        if not active:
            return
        candidates = self.search(
            [
                ("employee_id", "in", active.employee_id.ids),
                ("concept_id", "in", active.concept_id.ids),
            ]
        )
        by_key = defaultdict(list)
        for record in candidates:
            by_key[(record.employee_id.id, record.concept_id.id)].append(record)
        for assignment in active:
            for other in by_key[(assignment.employee_id.id, assignment.concept_id.id)]:
                if other == assignment or not assignment._erp_overlaps(other):
                    continue
                raise ValidationError(
                    _(
                        "%(employee)s ya tiene asignado el concepto «%(concept)s» "
                        "con una vigencia que se solapa (desde "
                        "%(date_from)s%(until)s). "
                        "Cierre la asignación anterior con «Vigente hasta» o "
                        "ajuste las fechas.",
                        employee=assignment.employee_id.name,
                        concept=assignment.concept_id.name,
                        date_from=format_date(self.env, other.date_from),
                        until=(
                            _(" hasta %s", format_date(self.env, other.date_to))
                            if other.date_to
                            else _(", sin fecha de fin")
                        ),
                    )
                )

    def _erp_overlaps(self, other):
        """``True`` si las vigencias de ``self`` y ``other`` comparten algún
        día."""
        self.ensure_one()
        starts_before_other_ends = not other.date_to or self.date_from <= other.date_to
        other_starts_before_end = not self.date_to or other.date_from <= self.date_to
        return starts_before_other_ends and other_starts_before_end

    def _erp_is_in_force(self, date_from, date_to):
        """``True`` si la asignación está vigente algún día de
        ``date_from``-``date_to`` (ambos incluidos)."""
        self.ensure_one()
        return self.date_from <= date_to and (
            not self.date_to or self.date_to >= date_from
        )
