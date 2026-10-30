import {
  Many2OneAvatarUserField,
  many2OneAvatarUserField,
} from "@mail/views/web/fields/many2one_avatar_user_field/many2one_avatar_user_field";
import {AvatarMany2XAutocomplete} from "@web/views/fields/relational_utils";
import {_t} from "@web/core/l10n/translation";
import {registry} from "@web/core/registry";
import {insertNoCoachOption} from "./coach_no_coach_options";

/**
 * Instructor del empleado con la opción "Sin instructor" (US-010).
 *
 * "Sin instructor" no es un empleado: es la marca booleana ``erp_no_coach``
 * del empleado. Contrato con el servidor (erp_hr_ec/models/hr_employee.py):
 * - elegir "Sin instructor": {erp_no_coach: true, coach_id: false};
 * - elegir un empleado: coach_id = id (el onchange/servidor quita la marca);
 * - borrar el campo con la marca puesta, o en edición múltiple de la lista:
 *   {coach_id: false, erp_no_coach: false} (queda "sin asignar").
 */
export const NO_COACH_FIELD = "erp_no_coach";

export class ErpCoachMany2XAutocomplete extends AvatarMany2XAutocomplete {
  static props = {
    ...AvatarMany2XAutocomplete.props,
    erpSelectNoCoach: {type: Function, optional: true},
    erpHasValue: {type: Boolean, optional: true},
  };

  get optionsSource() {
    return {
      ...super.optionsSource,
      optionTemplate: "erp_hr_ec.CoachMany2XAutocompleteOption",
    };
  }

  async loadOptionsSource(request) {
    const options = await super.loadOptionsSource(request);
    const selectNoCoach = this.props.erpSelectNoCoach;
    if (!selectNoCoach) {
      return options;
    }
    return insertNoCoachOption(
      options,
      {
        label: _t("Sin instructor"),
        erpNoCoach: true,
        classList: "o_m2o_dropdown_option o_erp_no_coach_option",
        action: () => selectNoCoach(),
      },
      {request, hasValue: Boolean(this.props.erpHasValue)}
    );
  }
}

export class ErpCoachMany2OneField extends Many2OneAvatarUserField {
  static template = "erp_hr_ec.CoachMany2OneField";
  static components = {
    ...Many2OneAvatarUserField.components,
    Many2XAutocomplete: ErpCoachMany2XAutocomplete,
  };

  /** El registro trae la marca y el campo actualiza el registro directamente. */
  get erpCanUseNoCoach() {
    return (
      NO_COACH_FIELD in this.props.record.data &&
      !this.props.update &&
      !("value" in this.props)
    );
  }

  get erpIsNoCoach() {
    return (
      this.erpCanUseNoCoach &&
      !this.value &&
      Boolean(this.props.record.data[NO_COACH_FIELD])
    );
  }

  get erpNoCoachLabel() {
    return _t("Sin instructor");
  }

  get displayName() {
    return this.erpIsNoCoach ? this.erpNoCoachLabel : super.displayName;
  }

  get Many2XAutocompleteProps() {
    const props = super.Many2XAutocompleteProps;
    if (this.erpCanUseNoCoach && !this.erpIsNoCoach) {
      props.erpSelectNoCoach = () => this.erpSelectNoCoach();
      props.erpHasValue = Boolean(this.value);
    }
    return props;
  }

  erpSelectNoCoach() {
    this.state.isFloating = false;
    return this.props.record.update({
      [this.props.name]: false,
      [NO_COACH_FIELD]: true,
    });
  }

  updateRecord(value) {
    // Borrar el campo de un empleado "Sin instructor" lo deja sin asignar. En
    // edición múltiple de la lista se envía siempre la marca a false: las
    // demás filas seleccionadas pueden tenerla aunque la editada no.
    const record = this.props.record;
    const multiEdit = record.selected && record.model.multiEdit;
    if (!value && this.erpCanUseNoCoach && (record.data[NO_COACH_FIELD] || multiEdit)) {
      return this.props.record.update({
        [this.props.name]: false,
        [NO_COACH_FIELD]: false,
      });
    }
    return super.updateRecord(value);
  }
}

export const erpCoachMany2OneField = {
  ...many2OneAvatarUserField,
  component: ErpCoachMany2OneField,
  displayName: _t("Instructor con opción Sin instructor"),
  // La vista también declara el campo (invisible); readonly: false para que
  // la marca se guarde aunque una vista no lo declare.
  fieldDependencies: [{name: NO_COACH_FIELD, type: "boolean", readonly: false}],
};

registry.category("fields").add("erp_coach_many2one", erpCoachMany2OneField);
