import {TimeOffCalendarController} from "@hr_holidays/views/calendar/calendar_controller";
import {_t} from "@web/core/l10n/translation";
import {patch} from "@web/core/utils/patch";

/**
 * Calendario de Ausencias (US-012, QA-UX): título de la ventana de la
 * solicitud. hr_holidays lo fija en JS («New Time Off» → «Nuevo tiempo
 * personal», «Time Off Request» → «Solicitud de tiempo personal»); las
 * traducciones de JS se combinan sin orden fijo entre módulos, así que se
 * reescribe aquí: «Solicitar ausencia» (nueva) y «Solicitud de ausencia»
 * (existente), como el menú y la acción.
 */
export function erpLeaveDialogTitle(props) {
  if (!props || props.resModel !== "hr.leave" || !("title" in props)) {
    return null;
  }
  return props.resId ? _t("Solicitud de ausencia") : _t("Solicitar ausencia");
}

patch(TimeOffCalendarController.prototype, {
  setup() {
    super.setup(...arguments);
    // CalendarController guarda displayDialog en la instancia (no en el
    // prototipo): se envuelve después de crearlo.
    const displayDialog = this.displayDialog;
    this.displayDialog = (DialogClass, props, options) => {
      const title = erpLeaveDialogTitle(props);
      return displayDialog(DialogClass, title ? {...props, title} : props, options);
    };
  },
});
