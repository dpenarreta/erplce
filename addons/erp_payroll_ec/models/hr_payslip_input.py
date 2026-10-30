from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HrPayslipInput(models.Model):
    """Entradas variables del rol enlazadas al catálogo de conceptos
    (US-008, CA-7).

    El cálculo del rol sigue usando ``code`` (``hr.payslip._erp_get_input_concepts``
    valida que sea un concepto variable activo de la empresa); ``erp_concept_id``
    permite elegir el concepto en la interfaz y se mantiene coherente con
    ``code``:

    - si se indica el concepto, el código (y la descripción, si no se da otra)
      se toman de él;
    - si solo se indica el código, se enlaza el concepto variable activo de la
      empresa del rol con ese código, si existe (si no, queda sin concepto y el
      cálculo informa del código desconocido).
    """

    _inherit = "hr.payslip.input"

    # Empresa del rol: la necesita el dominio check_company de erp_concept_id
    # (hr.payslip.input de OCA no tiene company_id). No almacenado.
    company_id = fields.Many2one(
        related="payslip_id.company_id",
        string="Empresa",
    )
    erp_concept_id = fields.Many2one(
        "erp.payroll.concept",
        string="Concepto",
        index="btree_not_null",
        ondelete="restrict",
        check_company=True,
        domain="[('amount_kind', '=', 'variable')]",
        help="Concepto variable del catálogo de nómina. Al elegirlo se rellenan "
        "el código y la descripción de la entrada.",
    )

    # ------------------------------------------------------------------
    # Interfaz
    # ------------------------------------------------------------------
    @api.onchange("erp_concept_id")
    def _onchange_erp_concept_id(self):
        for line in self.filtered("erp_concept_id"):
            line.code = line.erp_concept_id.code
            line.name = line.erp_concept_id.name

    # ------------------------------------------------------------------
    # Coherencia concepto / código
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Integridad: entradas de un rol confirmado (US-008, CA-8)
    # ------------------------------------------------------------------
    @api.model
    def _erp_check_payslips_editable(self, payslips):
        """Las entradas de un rol confirmado no se crean, modifican ni borran:
        el rol ya está contabilizado con ellas (se corrige con un reembolso o
        anulándolo)."""
        locked = payslips.filtered(lambda slip: slip.state == "done")
        if locked:
            raise UserError(
                _(
                    "No se pueden modificar las entradas de un rol de pagos "
                    "confirmado: %(payslips)s. Corríjalo con un reembolso o "
                    "anulándolo.",
                    payslips=", ".join(
                        locked.mapped(lambda slip: slip.number or slip.name or "")
                    ),
                )
            )

    def unlink(self):
        self._erp_check_payslips_editable(self.payslip_id)
        return super().unlink()

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        self._erp_check_payslips_editable(
            self.env["hr.payslip"].browse(
                {vals["payslip_id"] for vals in vals_list if vals.get("payslip_id")}
            )
        )
        Concept = self.env["erp.payroll.concept"]
        to_link = []
        for vals in vals_list:
            if vals.get("erp_concept_id"):
                self._erp_sync_from_concept(
                    vals, Concept.browse(vals["erp_concept_id"])
                )
            elif vals.get("code") and vals.get("payslip_id"):
                to_link.append(vals)
        if to_link:
            payslips = self.env["hr.payslip"].browse(
                {vals["payslip_id"] for vals in to_link}
            )
            concepts = self._erp_find_variable_concepts(
                {vals["code"] for vals in to_link}, payslips.company_id
            )
            company_by_slip = {slip.id: slip.company_id.id for slip in payslips}
            for vals in to_link:
                concept = concepts.get(
                    (company_by_slip[vals["payslip_id"]], vals["code"])
                )
                if concept:
                    vals["erp_concept_id"] = concept.id
        return super().create(vals_list)

    def write(self, vals):
        payslips = self.payslip_id
        if vals.get("payslip_id"):
            payslips |= self.env["hr.payslip"].browse(vals["payslip_id"])
        self._erp_check_payslips_editable(payslips)
        if vals.get("erp_concept_id"):
            vals = dict(vals)
            self._erp_sync_from_concept(
                vals, self.env["erp.payroll.concept"].browse(vals["erp_concept_id"])
            )
            return super().write(vals)
        if "code" in vals and "erp_concept_id" not in vals and self:
            return self._erp_write_relinking(vals)
        return super().write(vals)

    @api.model
    def _erp_sync_from_concept(self, vals, concept):
        """Completa ``vals`` con el código del concepto y, si no se indica otra
        descripción, con su nombre (la descripción puede detallar el concepto,
        p. ej. «Comisión de ventas – enero»)."""
        vals["code"] = concept.code
        if not vals.get("name"):
            vals["name"] = concept.name

    def _erp_write_relinking(self, vals):
        """Escribe un código nuevo enlazando, en el mismo ``write``, el concepto
        variable de la empresa de cada entrada con ese código (o ninguno), para
        que la validación de coherencia vea ya el enlace correcto. La descripción
        no se toca."""
        concepts = self._erp_find_variable_concepts(
            {vals["code"]} if vals["code"] else set(), self.company_id
        )
        groups = defaultdict(lambda: self.browse())
        for line in self:
            concept = concepts.get((line.company_id.id, vals["code"]))
            groups[concept.id if concept else False] |= line
        for concept_id, lines in groups.items():
            super(HrPayslipInput, lines).write(dict(vals, erp_concept_id=concept_id))
        return True

    @api.model
    def _erp_find_variable_concepts(self, codes, companies):
        """``{(empresa, código): concepto}`` de los conceptos variables activos
        con esos códigos en esas empresas (una sola búsqueda)."""
        if not codes or not companies:
            return {}
        concepts = self.env["erp.payroll.concept"].search(
            [
                ("code", "in", list(codes)),
                ("company_id", "in", companies.ids),
                ("amount_kind", "=", "variable"),
            ]
        )
        return {(concept.company_id.id, concept.code): concept for concept in concepts}

    @api.constrains("erp_concept_id", "code", "payslip_id")
    def _check_erp_concept(self):
        """El concepto enlazado debe ser variable, de la empresa del rol y con
        el mismo código que la entrada."""
        for line in self.filtered("erp_concept_id"):
            concept = line.erp_concept_id
            if concept.amount_kind != "variable":
                raise ValidationError(
                    _(
                        "El concepto «%(concept)s» es fijo: no se registra como "
                        "entrada del rol, se asigna al empleado con importe y "
                        "vigencia.",
                        concept=concept.name,
                    )
                )
            if concept.company_id != line.payslip_id.company_id:
                raise ValidationError(
                    _(
                        "El concepto «%(concept)s» es de otra empresa "
                        "(%(company)s) que el rol de pagos de %(employee)s.",
                        concept=concept.name,
                        company=concept.company_id.name,
                        employee=line.payslip_id.employee_id.name,
                    )
                )
            if line.code != concept.code:
                raise ValidationError(
                    _(
                        "La entrada «%(name)s» tiene el código %(code)s, distinto "
                        "del código %(concept_code)s de su concepto «%(concept)s». "
                        "Elija de nuevo el concepto o corrija el código.",
                        name=line.name,
                        code=line.code,
                        concept_code=concept.code,
                        concept=concept.name,
                    )
                )
