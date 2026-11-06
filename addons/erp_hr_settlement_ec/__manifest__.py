{
    "name": "ERP Liquidación de haberes Ecuador",
    "summary": "Liquidación de haberes y finiquito de Ecuador: causas de "
    "salida, décimos y vacaciones pendientes, desahucio e indemnización por "
    "despido intempestivo, con parámetros configurables.",
    "version": "18.0.1.0.1",
    "category": "Human Resources/Payroll",
    "author": "LAARCOURIER EXPRESS S.A.",
    "license": "LGPL-3",
    "depends": [
        "account",
        "hr",
        "hr_contract",
        "hr_holidays",
        "mail",
        "payroll",
        "erp_payroll_ec",
        "erp_hr_holidays_ec",
        # Colores de marca ($erp-brand-*) del PDF de la liquidación.
        "erp_branding",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/erp_hr_settlement_ec_security.xml",
        "data/ir_sequence_data.xml",
        "data/erp_payroll_parameter_data.xml",
        "data/erp_hr_termination_cause_data.xml",
        "data/erp_hr_indemnity_bracket_data.xml",
        "report/erp_hr_settlement_report.xml",
        "views/erp_hr_termination_cause_views.xml",
        "views/erp_hr_indemnity_bracket_views.xml",
        "views/erp_hr_settlement_views.xml",
        "views/res_config_settings_views.xml",
        "views/erp_hr_settlement_menus.xml",
    ],
    "assets": {
        "web.report_assets_common": [
            "erp_hr_settlement_ec/static/src/scss/report_settlement.scss",
        ],
        # Tramos de indemnización: 0 se muestra «Sin tope».
        "web.assets_backend": [
            "erp_hr_settlement_ec/static/src/fields/*",
        ],
    },
    "uninstall_hook": "uninstall_hook",
    "installable": True,
    "application": False,
}
