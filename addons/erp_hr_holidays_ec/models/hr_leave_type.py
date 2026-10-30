from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import formatLang


class HrLeaveType(models.Model):
    """Tipo de ausencia con los atributos de Ecuador (US-012, CA-2).

    Se reutilizan los campos nativos de ``hr_holidays`` en lugar de duplicarlos:

    - «Pagado»: ``unpaid`` (nativo, «Sin sueldo»). Lo usan también las entradas
      de trabajo y la nómina; un segundo booleano «Pagado» crearía dos fuentes
      de verdad.
    - «Requiere aprobación de RRHH»: ``leave_validation_type = 'both'`` (jefe
      del empleado y responsable de ausencias); ``'manager'`` = solo el jefe.
    - «Requiere saldo»: ``requires_allocation``; unidad: ``request_unit``.
    - «Permite adjunto»: ``support_document`` (nativo, solo muestra el campo de
      adjuntos); «Adjunto obligatorio»: ``erp_attachment_required`` (nuevo, lo
      exige la capa de negocio).
    """

    _inherit = "hr.leave.type"

    erp_is_annual_vacation = fields.Boolean(
        string="Vacaciones anuales",
        copy=False,
        help="Marca el tipo de las vacaciones anuales del Código del Trabajo: "
        "su saldo se asigna cada año de servicio según la antigüedad. Solo "
        "puede haber un tipo activo así por empresa y debe requerir asignación.",
    )
    erp_max_duration_param_code = fields.Char(
        string="Código de duración máxima",
        help="Código del parámetro de nómina (Parámetros de nómina) con la "
        "duración máxima por solicitud, en la unidad del tipo (días u horas). "
        "Vacío: sin máximo legal.",
    )
    erp_attachment_required = fields.Boolean(
        string="Adjunto obligatorio",
        help="La solicitud debe llevar un documento de respaldo (p. ej. "
        "certificado médico). Requiere «Documento de respaldo» activado.",
    )
    erp_max_duration_display = fields.Char(
        string="Duración máxima por solicitud",
        compute="_compute_erp_max_duration_display",
        help="Valor vigente hoy del parámetro de nómina indicado en «Código de "
        "duración máxima», en la unidad del tipo. «(a validar)»: el valor aún "
        "no lo ha confirmado Talento Humano o el contador.",
    )

    _sql_constraints = [
        (
            "erp_max_duration_param_code_format_check",
            "CHECK (erp_max_duration_param_code IS NULL "
            "OR erp_max_duration_param_code ~ '^[A-Z][A-Z0-9_]{0,63}$')",
            "El código de duración máxima debe ser un código de parámetro de "
            "nómina: empieza por una letra mayúscula y contiene solo "
            "mayúsculas, dígitos y guion bajo.",
        ),
        (
            "erp_attachment_requires_support_check",
            "CHECK (erp_attachment_required IS NOT TRUE OR support_document)",
            "Para exigir un adjunto, active también «Documento de respaldo» en "
            "el tipo de ausencia.",
        ),
        (
            "erp_annual_vacation_allocation_check",
            "CHECK (erp_is_annual_vacation IS NOT TRUE "
            "OR requires_allocation = 'yes')",
            "El tipo de vacaciones anuales debe requerir asignación (saldo).",
        ),
        (
            # Un solo tipo activo de vacaciones anuales por empresa (o común):
            # la asignación automática necesita saber cuál usar. EXCLUDE con
            # WHERE equivale a un índice único parcial y permite traducir la
            # violación con este mensaje.
            "erp_annual_vacation_company_uniq",
            "EXCLUDE USING btree ((COALESCE(company_id, 0)) WITH =) "
            "WHERE (erp_is_annual_vacation AND active)",
            "Ya existe un tipo de ausencia activo marcado como «Vacaciones "
            "anuales» para esta empresa. Archive el anterior antes de marcar "
            "otro.",
        ),
    ]

    # ------------------------------------------------------------------
    # Presentación (QA-UX): duración máxima legible
    # ------------------------------------------------------------------
    @api.depends("erp_max_duration_param_code", "request_unit")
    @api.depends_context("company")
    def _compute_erp_max_duration_display(self):
        """«84 días (a validar)», «2 horas por día» o «Sin valor vigente
        (CÓDIGO)»: valor del parámetro vigente hoy para la empresa actual
        (el de la empresa prevalece sobre el común, como ``_get_value``)."""
        codes = set(self.mapped("erp_max_duration_param_code")) - {False}
        chosen = {}
        if codes:
            company = self.env.company
            # sudo(): los encargados de ausencias no leen parámetros de
            # nómina; solo se muestran valor y estado del vigente.
            records = (
                self.env["erp.payroll.parameter"]
                .sudo()
                .search_fetch(
                    [
                        ("code", "in", list(codes)),
                        ("date_from", "<=", fields.Date.context_today(self)),
                        ("company_id", "in", [company.id, False]),
                    ],
                    ["code", "value", "state", "company_id"],
                    order="date_from desc, id desc",
                )
            )
            for code in codes:
                candidates = records.filtered(lambda r, c=code: r.code == c)
                record = candidates.filtered("company_id")[:1] or candidates[:1]
                if record:
                    chosen[code] = record
        for leave_type in self:
            code = leave_type.erp_max_duration_param_code
            if not code:
                leave_type.erp_max_duration_display = False
                continue
            record = chosen.get(code)
            if not record:
                leave_type.erp_max_duration_display = _(
                    "Sin valor vigente (%(code)s)", code=code
                )
                continue
            digits = 0 if float(record.value).is_integer() else 2
            unit = (
                _("horas por día") if leave_type.request_unit == "hour" else _("días")
            )
            text = f"{formatLang(self.env, record.value, digits=digits)} {unit}"
            if record.state == "to_validate":
                text = f"{text} {_('(a validar)')}"
            leave_type.erp_max_duration_display = text

    # ------------------------------------------------------------------
    # Validaciones (US-012, CA-2)
    # ------------------------------------------------------------------
    @api.constrains("erp_attachment_required", "leave_validation_type")
    def _check_erp_attachment_requires_approval(self):
        """El adjunto obligatorio se exige al aprobar: un tipo sin aprobación
        (las solicitudes se validan solas al crearse) no tiene ese paso."""
        for leave_type in self:
            if (
                leave_type.erp_attachment_required
                and leave_type.leave_validation_type == "no_validation"
            ):
                raise ValidationError(
                    _(
                        "El tipo «%(type)s» exige adjunto, que se comprueba al "
                        "aprobar: elija un tipo de aprobación (jefe, Talento "
                        "Humano o ambos) o quite «Adjunto obligatorio».",
                        type=leave_type.name,
                    )
                )

    @api.constrains("erp_max_duration_param_code")
    def _check_erp_max_duration_param_exists(self):
        """El código de duración máxima debe corresponder a un parámetro de
        nómina existente; si no, cada solicitud del tipo fallaría."""
        codes = set(
            self.filtered("erp_max_duration_param_code").mapped(
                "erp_max_duration_param_code"
            )
        )
        if not codes:
            return
        # sudo(): solo se comprueba que el código existe (los encargados de
        # ausencias no leen parámetros de nómina); no se devuelve el registro.
        found = set(
            self.env["erp.payroll.parameter"]
            .sudo()
            .with_context(active_test=False)
            .search_fetch([("code", "in", list(codes))], ["code"])
            .mapped("code")
        )
        missing = sorted(codes - found)
        if missing:
            raise ValidationError(
                _(
                    "No existe el parámetro de nómina %(codes)s indicado como "
                    "duración máxima. Créelo en Parámetros de nómina o corrija "
                    "el código.",
                    codes=", ".join(missing),
                )
            )

    @api.constrains("erp_is_annual_vacation", "request_unit")
    def _check_erp_annual_vacation_unit(self):
        """Las vacaciones anuales se asignan y se piden en días: la
        generación por antigüedad calcula días."""
        for leave_type in self:
            if leave_type.erp_is_annual_vacation and leave_type.request_unit == "hour":
                raise ValidationError(
                    _(
                        "El tipo «%(type)s» es de vacaciones anuales: debe "
                        "pedirse en días o medios días, no en horas.",
                        type=leave_type.name,
                    )
                )
