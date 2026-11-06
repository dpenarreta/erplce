import {_t} from "@web/core/l10n/translation";
import {registry} from "@web/core/registry";
import {FloatField, floatField} from "@web/views/fields/float/float_field";
import {IntegerField, integerField} from "@web/views/fields/integer/integer_field";

/**
 * Límites donde 0 significa «sin tope» (US-013, tramos de indemnización:
 * «Hasta (años)» y «Máximo (meses)»).
 *
 * En lectura (columnas de lista y formulario sin edición) muestra «Sin tope»
 * en lugar de «0» / «0,00»; al editar, el campo sigue siendo numérico y se
 * escribe 0 como siempre (el modelo y su ayuda no cambian).
 */
export function noLimitLabel() {
  return _t("Sin tope");
}

export class NoLimitIntegerField extends IntegerField {
  get formattedValue() {
    if (this.props.readonly && this.value === 0) {
      return noLimitLabel();
    }
    return super.formattedValue;
  }
}

export class NoLimitFloatField extends FloatField {
  get formattedValue() {
    if (this.props.readonly && this.value === 0) {
      return noLimitLabel();
    }
    return super.formattedValue;
  }
}

registry.category("fields").add("erp_no_limit_integer", {
  ...integerField,
  component: NoLimitIntegerField,
  displayName: _t("Entero (0 = sin tope)"),
});

registry.category("fields").add("erp_no_limit_float", {
  ...floatField,
  component: NoLimitFloatField,
  displayName: _t("Decimal (0 = sin tope)"),
});
