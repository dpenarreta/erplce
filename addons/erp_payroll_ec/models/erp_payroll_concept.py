from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

CONCEPT_TYPE_SELECTION = [
    ("income", "Ingreso"),
    ("deduction", "Descuento"),
]

CONCEPT_AMOUNT_KIND_SELECTION = [
    ("fixed", "Fijo"),
    ("variable", "Variable"),
]


class ErpPayrollConcept(models.Model):
    """Catálogo de bonos y descuentos propios de la empresa (US-008, CA-7).

    Se entrega vacío: lo llena el responsable de nómina. Un concepto fijo se
    asigna a empleados con importe y vigencia (``erp.payroll.employee.concept``);
    uno variable se registra como entrada del rol (``hr.payslip.input``) con
    su código, por eso el código tiene formato de código de regla/entrada.
    """

    _name = "erp.payroll.concept"
    _description = "Concepto de nómina (bono o descuento)"
    _inherit = ["mail.thread"]
    _order = "concept_type, name, id"
    _check_company_auto = True

    name = fields.Char(string="Nombre", required=True, tracking=True)
    # Sin index=True propio: lo cubre el índice de la restricción única
    # (code, company_id).
    code = fields.Char(
        string="Código",
        required=True,
        tracking=True,
        help="Código de la entrada del rol. Mayúsculas, dígitos y guion bajo, "
        "empezando por letra (p. ej. BONO_ALIMENTACION).",
    )
    concept_type = fields.Selection(
        CONCEPT_TYPE_SELECTION,
        string="Tipo",
        required=True,
        default="income",
        tracking=True,
    )
    amount_kind = fields.Selection(
        CONCEPT_AMOUNT_KIND_SELECTION,
        string="Importe",
        required=True,
        default="fixed",
        tracking=True,
        help="Fijo: se asigna al empleado con importe y vigencia y entra en "
        "cada rol. Variable: se registra como entrada en cada rol.",
    )
    iess_base = fields.Boolean(
        string="Suma a base IESS",
        tracking=True,
        help="Solo ingresos: el importe forma parte de la materia gravada "
        "para los aportes al IESS y los fondos de reserva.",
    )
    thirteenth_base = fields.Boolean(
        string="Suma a base de décimo tercero",
        tracking=True,
        help="Solo ingresos: el importe forma parte de la base del décimo "
        "tercer sueldo.",
    )
    account_debit_id = fields.Many2one(
        "account.account",
        string="Cuenta deudora",
        ondelete="restrict",
        check_company=True,
        tracking=True,
        help="Opcional. Si se deja vacía se usa la cuenta de la regla del rol.",
    )
    account_credit_id = fields.Many2one(
        "account.account",
        string="Cuenta acreedora",
        ondelete="restrict",
        check_company=True,
        tracking=True,
        help="Opcional. Si se deja vacía se usa la cuenta de la regla del rol.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        index=True,
        ondelete="cascade",
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(string="Activo", default=True, tracking=True)
    note = fields.Text(string="Notas")
    employee_concept_ids = fields.One2many(
        "erp.payroll.employee.concept",
        "concept_id",
        string="Asignaciones",
    )

    _sql_constraints = [
        (
            "code_company_uniq",
            "UNIQUE(code, company_id)",
            "Ya existe un concepto de nómina con ese código en la empresa.",
        ),
        (
            "code_format_check",
            "CHECK (code ~ '^[A-Z][A-Z0-9_]{0,31}$')",
            "El código del concepto debe empezar por una letra mayúscula y "
            "contener solo mayúsculas, dígitos y guion bajo (máximo 32).",
        ),
        (
            "deduction_without_base_check",
            "CHECK (concept_type = 'income' OR "
            "(NOT COALESCE(iess_base, FALSE) "
            "AND NOT COALESCE(thirteenth_base, FALSE)))",
            "Un descuento no puede sumar a la base IESS ni a la base del décimo "
            "tercero.",
        ),
    ]

    # ------------------------------------------------------------------
    # Interfaz
    # ------------------------------------------------------------------
    @api.onchange("concept_type")
    def _onchange_concept_type(self):
        """Al cambiar el tipo se vacía lo que deja de aplicar: un descuento no
        suma a las bases ni usa «Cuenta deudora»; un ingreso no usa «Cuenta
        acreedora» (ver ``_check_erp_concept_accounts``)."""
        for concept in self:
            if concept.concept_type == "deduction":
                concept.iess_base = False
                concept.thirteenth_base = False
                concept.account_debit_id = False
            elif concept.concept_type == "income":
                concept.account_credit_id = False

    # ------------------------------------------------------------------
    # Validaciones (US-008, CA-7 / CA-10)
    # ------------------------------------------------------------------
    @api.constrains("concept_type", "account_debit_id", "account_credit_id")
    def _check_erp_concept_accounts(self):
        """Cada tipo de concepto usa una sola cuenta propia, con su sentido
        contable natural:

        - Ingreso: «Cuenta deudora» (el gasto que se carga).
        - Descuento: «Cuenta acreedora» (el pasivo o la cuenta por cobrar que
          se abona con lo descontado).

        Si el concepto no tiene cuenta, su importe va a la cuenta de la regla
        del rol (Otros ingresos / Otros descuentos).
        """
        for concept in self:
            if concept.concept_type == "income" and concept.account_credit_id:
                raise ValidationError(
                    _(
                        "El concepto de ingreso «%(name)s» solo admite «Cuenta "
                        "deudora» (cuenta de gasto). Deje vacía la «Cuenta "
                        "acreedora».",
                        name=concept.name,
                    )
                )
            if concept.concept_type == "deduction" and concept.account_debit_id:
                raise ValidationError(
                    _(
                        "El concepto de descuento «%(name)s» solo admite «Cuenta "
                        "acreedora» (la cuenta que se abona con lo descontado). "
                        "Deje vacía la «Cuenta deudora».",
                        name=concept.name,
                    )
                )

    @api.constrains("amount_kind")
    def _check_erp_amount_kind_assignments(self):
        """Un concepto con asignaciones fijas activas no puede pasar a
        variable (las asignaciones dejarían de calcularse sin aviso)."""
        variable = self.filtered(lambda concept: concept.amount_kind == "variable")
        if not variable:
            return
        assignments = self.env["erp.payroll.employee.concept"].search(
            [("concept_id", "in", variable.ids)]
        )
        if assignments:
            raise ValidationError(
                _(
                    "El concepto «%(name)s» tiene asignaciones fijas a empleados: "
                    "no puede pasar a variable. Archive o elimine antes sus "
                    "asignaciones.",
                    name=assignments[0].concept_id.name,
                )
            )
