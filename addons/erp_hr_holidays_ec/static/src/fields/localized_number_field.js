import {Component} from "@odoo/owl";
import {registry} from "@web/core/registry";
import {formatFloat} from "@web/core/utils/numbers";
import {standardFieldProps} from "@web/views/fields/standard_field_props";

/**
 * Número guardado como texto (p. ej. los saldos «7.5» que hr_holidays calcula
 * con "%g" en allocation_remaining_display / allocation_display) mostrado con
 * el formato del idioma del usuario: «7,5» en es_EC (US-012, QA-UX).
 * Solo lectura; si el texto no es un número se muestra tal cual.
 */
export function formatLocalizedNumber(value) {
  if (value === false || value === null || value === undefined || value === "") {
    return "";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return String(value);
  }
  return formatFloat(number, {digits: [16, 2], trailingZeros: false});
}

export class ErpLocalizedNumberField extends Component {
  static template = "erp_hr_holidays_ec.LocalizedNumberField";
  static props = {...standardFieldProps};

  get formattedValue() {
    return formatLocalizedNumber(this.props.record.data[this.props.name]);
  }
}

registry.category("fields").add("erp_localized_number", {
  component: ErpLocalizedNumberField,
  displayName: "Número con formato local",
  supportedTypes: ["char"],
});
