{
    "name": "ERP Ausencias Ecuador",
    "summary": "Vacaciones por antigüedad, licencias y permisos de ley de Ecuador "
    "sobre Ausencias (hr_holidays): tipos de ausencia, parámetros normativos y "
    "asignación anual de vacaciones.",
    "version": "18.0.1.0.0",
    "category": "Human Resources/Time Off",
    "author": "LAARCOURIER EXPRESS S.A.",
    "license": "LGPL-3",
    "depends": [
        "erp_hr_ec",
        "erp_payroll_ec",
        "hr_holidays",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/erp_hr_holidays_ec_security.xml",
        "data/erp_payroll_parameter_data.xml",
        "data/hr_leave_type_data.xml",
        "data/ir_cron_data.xml",
        "views/hr_leave_type_views.xml",
        "views/hr_leave_allocation_views.xml",
        "views/hr_leave_views.xml",
        "views/hr_employee_views.xml",
        "views/erp_hr_vacation_history_views.xml",
        "views/hr_holidays_terminology.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "erp_hr_holidays_ec/static/src/**/*",
        ],
    },
    "installable": True,
    "application": False,
}
