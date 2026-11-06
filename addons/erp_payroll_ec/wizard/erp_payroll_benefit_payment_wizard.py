from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import format_date, formatLang

from ..models.const import (
    ACCRUED_PAY_BY_BENEFIT,
    ACCRUED_PAY_RULES,
    ACCRUED_PAY_SELECTION,
)

PAYROLL_MANAGER_GROUP = "payroll.group_payroll_manager"
BENEFIT_SELECTION = [
    ("thirteenth", "Décimo tercer sueldo"),
    ("fourteenth", "Décimo cuarto sueldo"),
]
REGIME_SELECTION = [
    ("costa_galapagos", "Costa / Galápagos"),
    ("sierra_amazonia", "Sierra / Amazonía"),
]


class ErpPayrollBenefitPaymentWizard(models.TransientModel):
    """Asistente «Pago de décimos» (US-013, CA-1 a CA-4).

    Genera un lote (``hr.payslip.run``) con un rol de la estructura «Pago de
    décimos acumulados» por cada empleado con provisiones pendientes del
    décimo y periodo elegidos, y lo calcula. Solo el responsable de nómina.

    Entrada:

    - ``benefit``: décimo tercero o décimo cuarto;
    - ``regime``: régimen del décimo cuarto (obligatorio solo para él);
    - ``year``: año de pago (décimo tercero 2026 = periodo del 01/12/2025 al
      30/11/2026 con los parámetros de partida);
    - ``payment_date``: fecha del pago y del asiento (por defecto, la de los
      parámetros del décimo);
    - ``journal_id``: diario del lote (opcional; el asiento de cada rol usa
      el diario de su contrato, como el rol mensual).

    Salida (``action_generate``): notificación con el resumen (roles creados,
    empleados omitidos y motivo) que abre el lote al cerrarse; el resumen
    queda también en el historial del lote y en ``summary``.

    Errores (``UserError`` en español): parámetros de periodo sin vigencia o
    no válidos, régimen faltante, ninguna provisión pendiente o ningún
    empleado procesable (no se crea un lote vacío). Sin el grupo responsable
    de nómina: ``AccessError``.
    """

    _name = "erp.payroll.benefit.payment.wizard"
    _description = "Asistente de pago de décimos acumulados"

    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        default=lambda self: self.env.company,
        # Solo las empresas activas en el selector de empresas del usuario
        # (la generación lo comprueba también en el servidor).
        domain=lambda self: [("id", "in", self.env.companies.ids)],
    )
    benefit = fields.Selection(
        BENEFIT_SELECTION,
        string="Décimo",
        required=True,
        default="thirteenth",
        help="Décimo acumulado que se paga.",
    )
    regime = fields.Selection(
        REGIME_SELECTION,
        string="Régimen",
        help="Régimen del décimo cuarto: se pagan solo las provisiones "
        "calculadas con este régimen (el periodo y la fecha de pago dependen "
        "de él).",
    )
    year = fields.Integer(
        string="Año de pago",
        required=True,
        default=lambda self: fields.Date.context_today(self).year,
        help="Año en que se paga el décimo. El periodo de cálculo termina en "
        "este año (p. ej. décimo tercero 2026: del 1 de diciembre de 2025 al "
        "30 de noviembre de 2026, según los parámetros de nómina).",
    )
    pay_code = fields.Selection(
        ACCRUED_PAY_SELECTION,
        string="Regla de pago",
        compute="_compute_period",
    )
    date_start = fields.Date(
        string="Periodo desde",
        compute="_compute_period",
        help="Primer día del periodo de cálculo (parámetros de nómina).",
    )
    date_end = fields.Date(
        string="Periodo hasta",
        compute="_compute_period",
        help="Último día del periodo de cálculo (parámetros de nómina).",
    )
    period_message = fields.Char(
        string="Aviso del periodo",
        compute="_compute_period",
        help="Motivo por el que no se puede calcular el periodo (p. ej. un "
        "parámetro sin vigencia).",
    )
    payment_date = fields.Date(
        string="Fecha de pago",
        compute="_compute_payment_date",
        store=True,
        readonly=False,
        help="Fecha del pago y del asiento contable de los roles. Por "
        "defecto, la fecha de pago de los parámetros del décimo.",
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Diario del lote",
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        help="Diario del lote. Vacío: el diario general por defecto. El "
        "asiento de cada rol usa el diario de nómina de su contrato.",
    )
    created_count = fields.Integer(string="Roles creados", readonly=True)
    skipped_count = fields.Integer(string="Empleados omitidos", readonly=True)
    summary = fields.Text(string="Resumen", readonly=True)
    payslip_run_id = fields.Many2one(
        "hr.payslip.run", string="Lote generado", readonly=True
    )

    # ------------------------------------------------------------------
    # Periodo
    # ------------------------------------------------------------------
    def _get_pay_code(self):
        self.ensure_one()
        regime = self.regime if self.benefit == "fourteenth" else None
        return ACCRUED_PAY_BY_BENEFIT.get((self.benefit, regime))

    @api.depends("benefit", "regime", "year", "company_id")
    def _compute_period(self):
        Payslip = self.env["hr.payslip"]
        for wizard in self:
            wizard.update(
                {
                    "pay_code": False,
                    "date_start": False,
                    "date_end": False,
                    "period_message": False,
                }
            )
            pay_code = wizard._get_pay_code()
            if not pay_code:
                wizard.period_message = _(
                    "Elija el régimen del décimo cuarto (Costa / Galápagos o "
                    "Sierra / Amazonía)."
                )
                continue
            wizard.pay_code = pay_code
            try:
                start, end, _payment = Payslip._erp_get_benefit_period(
                    pay_code, wizard.year, wizard.company_id
                )
            except UserError as error:
                wizard.period_message = error.args[0]
                continue
            wizard.date_start = start
            wizard.date_end = end

    @api.depends("benefit", "regime", "year", "company_id")
    def _compute_payment_date(self):
        Payslip = self.env["hr.payslip"]
        for wizard in self:
            pay_code = wizard._get_pay_code()
            payment = False
            if pay_code:
                try:
                    payment = Payslip._erp_get_benefit_period(
                        pay_code, wizard.year, wizard.company_id
                    )[2]
                except UserError:
                    payment = False
            wizard.payment_date = payment

    # ------------------------------------------------------------------
    # Generación
    # ------------------------------------------------------------------
    def action_generate(self):
        """Genera y calcula el lote de roles de pago del décimo (ver la
        documentación de la clase).

        Empleados omitidos (no detienen el lote):

        - con un rol no anulado (ni reembolsado) de la estructura «Pago de
          décimos acumulados» del mismo periodo: ya se generó su pago;
        - sin contrato en curso o expirado que se solape con el periodo.

        :return: acción de notificación que abre el lote generado
        """
        self.ensure_one()
        if not self.env.su and not self.env.user.has_group(PAYROLL_MANAGER_GROUP):
            raise AccessError(
                _(
                    "Solo el responsable de nómina puede generar el pago de "
                    "décimos acumulados."
                )
            )
        if not self.env.su and self.company_id not in self.env.companies:
            raise AccessError(
                _(
                    "No puede generar el pago de décimos de la empresa "
                    "%(company)s: actívela en el selector de empresas.",
                    # sudo(): solo el nombre, para el mensaje.
                    company=self.company_id.sudo().name,
                )
            )
        pay_code = self._get_pay_code()
        if not pay_code:
            raise UserError(
                _(
                    "Elija el régimen del décimo cuarto (Costa / Galápagos o "
                    "Sierra / Amazonía) antes de generar el pago."
                )
            )
        Payslip = self.env["hr.payslip"]
        company = self.company_id
        date_start, date_end, default_payment = Payslip._erp_get_benefit_period(
            pay_code, self.year, company
        )
        payment_date = self.payment_date or default_payment
        benefit_label = dict(ACCRUED_PAY_SELECTION)[pay_code]
        period = _(
            "del %(date_from)s al %(date_to)s",
            date_from=format_date(self.env, date_start),
            date_to=format_date(self.env, date_end),
        )
        structure = self.env.ref("erp_payroll_ec.structure_ec_benefit_pay")
        _benefit, _regime, provision_codes = ACCRUED_PAY_RULES[pay_code]
        # sudo(): misma política que el cálculo y la confirmación del rol de
        # pago (hr.payslip._erp_get_accrued_provision_lines): se buscan todas
        # las provisiones pendientes de la empresa aunque las reglas de
        # registro oculten algún rol; solo se leen empleado e importe.
        pending = (
            self.env["hr.payslip.line"]
            .sudo()
            ._erp_get_pending_provision_lines(
                provision_codes, date_from=date_start, date_to=date_end
            )
            .filtered(lambda line: line.slip_id.company_id == company)
        )
        currency = company.currency_id
        totals = defaultdict(float)
        for line in pending:
            totals[line.employee_id] += line.total
        employees = self.env["hr.employee"].browse(
            [
                employee.id
                for employee, total in totals.items()
                if not currency.is_zero(total)
            ]
        )
        if not employees:
            raise UserError(
                _(
                    "No hay provisiones de %(benefit)s pendientes de pago en el "
                    "periodo %(period)s (año de pago %(year)s). No se creó "
                    "ningún lote.",
                    benefit=benefit_label,
                    period=period,
                    year=self.year,
                )
            )
        skipped = []
        existing = self._get_existing_payslips(
            employees, structure, date_start, date_end
        )
        for employee in employees.filtered(lambda e: e.id in existing):
            skipped.append(
                self.env._(
                    "- %(employee)s: ya tiene el rol de pago %(payslip)s de este "
                    "periodo",
                    employee=employee.name,
                    payslip=existing[employee.id],
                )
            )
        employees = employees.filtered(lambda e: e.id not in existing)
        contracts = Payslip._erp_get_period_contracts(employees, date_start, date_end)
        for employee in employees.filtered(lambda e: e.id not in contracts):
            skipped.append(
                self.env._(
                    "- %(employee)s: sin contrato que cubra el periodo",
                    employee=employee.name,
                )
            )
        employees = employees.filtered(lambda e: e.id in contracts)
        if not employees:
            raise UserError(
                _(
                    "No se generó ningún rol de pago de %(benefit)s del periodo "
                    "%(period)s:\n%(details)s",
                    benefit=benefit_label,
                    period=period,
                    details="\n".join(skipped),
                )
            )
        run_name = _(
            "Pago de %(benefit)s %(year)s",
            benefit=benefit_label.lower(),
            year=self.year,
        )
        run = self.env["hr.payslip.run"].create(
            {
                "name": run_name,
                "date_start": date_start,
                "date_end": date_end,
                "struct_id": structure.id,
                "company_id": company.id,
                "journal_id": self._get_run_journal(contracts.values()).id,
            }
        )
        payslips = Payslip.create(
            [
                {
                    "name": _(
                        "%(run)s – %(employee)s", run=run_name, employee=employee.name
                    ),
                    "employee_id": employee.id,
                    "contract_id": contracts[employee.id].id,
                    "struct_id": structure.id,
                    "date_from": date_start,
                    "date_to": date_end,
                    "date": payment_date,
                    "company_id": company.id,
                    "payslip_run_id": run.id,
                    "erp_benefit_pay_code": pay_code,
                }
                for employee in employees
            ]
        )
        payslips.compute_sheet()
        total = sum(
            payslips.line_ids.filtered(lambda line: line.code == pay_code).mapped(
                "total"
            )
        )
        summary = _(
            "%(benefit)s %(year)s, periodo %(period)s, fecha de pago "
            "%(payment)s: %(count)s roles creados por %(total)s.",
            benefit=benefit_label,
            year=self.year,
            period=period,
            payment=format_date(self.env, payment_date),
            count=len(payslips),
            total=formatLang(self.env, total, currency_obj=currency),
        )
        if skipped:
            summary += "\n" + _(
                "Empleados omitidos (%(count)s):\n%(details)s",
                count=len(skipped),
                details="\n".join(skipped),
            )
        run.message_post(body=summary)
        self.write(
            {
                "created_count": len(payslips),
                "skipped_count": len(skipped),
                "summary": summary,
                "payslip_run_id": run.id,
            }
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Pago de décimos generado"),
                "message": summary,
                "type": "warning" if skipped else "success",
                "sticky": bool(skipped),
                "next": {
                    "type": "ir.actions.act_window",
                    "res_model": "hr.payslip.run",
                    "res_id": run.id,
                    "views": [(False, "form")],
                    "target": "current",
                },
            },
        }

    def _get_run_journal(self, contracts):
        """Diario del lote: el elegido, el de nómina de los contratos o el
        diario general de la empresa. Se pasa siempre al crear el lote: el
        valor por defecto de ``payroll_account`` busca diarios con los
        permisos del usuario y el responsable de nómina no es contador.

        sudo(): solo se busca el diario general de la empresa.
        """
        self.ensure_one()
        journal = self.journal_id or next(
            (contract.journal_id for contract in contracts if contract.journal_id),
            self.env["account.journal"],
        )
        if not journal:
            journal = (
                self.env["account.journal"]
                .sudo()
                .search(
                    [("type", "=", "general"), ("company_id", "=", self.company_id.id)],
                    limit=1,
                )
            )
        if not journal:
            raise UserError(
                _(
                    "No hay un diario general en la empresa %(company)s para el "
                    "lote de pago de décimos. Indique el diario en el asistente "
                    "o en los contratos.",
                    company=self.company_id.name,
                )
            )
        return journal

    @api.model
    def _get_existing_payslips(self, employees, structure, date_start, date_end):
        """Roles no anulados ni reembolsados de la estructura de pago de
        décimos del mismo periodo, por empleado (evita el pago doble y el
        índice único de roles por periodo).

        sudo(): la comprobación debe ver los roles de todo el personal; solo
        se leen empleado y número.

        :return: ``{employee_id: número o nombre del rol}``
        """
        existing = (
            self.env["hr.payslip"]
            .sudo()
            .search_fetch(
                [
                    ("employee_id", "in", employees.ids),
                    ("struct_id", "=", structure.id),
                    ("date_from", "=", date_start),
                    ("date_to", "=", date_end),
                    ("state", "!=", "cancel"),
                    ("credit_note", "!=", True),
                    ("refunded_id", "=", False),
                ],
                ["employee_id", "number", "name"],
            )
        )
        return {slip.employee_id.id: slip.number or slip.name for slip in existing}
