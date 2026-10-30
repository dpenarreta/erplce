import {TimeOffDashboard} from "@hr_holidays/dashboard/time_off_dashboard";
import {patch} from "@web/core/utils/patch";

/**
 * Tablero de Ausencias (US-012, QA-UX): el saldo de vacaciones lo calcula
 * Talento Humano por antigüedad, así que el enlace nativo «Nueva solicitud de
 * asignación» (o «Otorgar tiempo» desde la ficha del empleado) se sustituye por
 * «Ver mis saldos» / «Ver saldos del empleado» (plantilla
 * time_off_dashboard_patch.xml), que abre el detalle por periodo.
 *
 * Las reglas de registro de hr_holidays deciden qué saldos ve cada usuario
 * (empleado: los suyos; jefe: su equipo; Talento Humano: todos).
 */
export const ERP_MY_BALANCES_ACTION = "hr_holidays.hr_leave_allocation_action_my";
export const ERP_VACATION_PERIODS_ACTION =
  "erp_hr_holidays_ec.action_erp_vacation_periods";

export function erpBalancesAction(employeeId) {
  if (employeeId) {
    return {
      action: ERP_VACATION_PERIODS_ACTION,
      options: {additionalContext: {search_default_employee_id: employeeId}},
    };
  }
  return {action: ERP_MY_BALANCES_ACTION, options: {}};
}

patch(TimeOffDashboard.prototype, {
  async erpOpenBalances() {
    const {action, options} = erpBalancesAction(this.props.employeeId);
    await this.actionService.doAction(action, options);
  },
});
