{
    "name": "ERP RRHH Ecuador",
    "summary": "Datos de empleados exigidos en Ecuador: establecimiento, "
    "discapacidad, cargas familiares, modalidad de décimos y fondos de "
    "reserva, datos adicionales configurables y tipos de contrato.",
    "version": "18.0.1.0.0",
    "category": "Human Resources/Employees",
    "author": "LAARCOURIER EXPRESS S.A.",
    "license": "LGPL-3",
    "depends": [
        "erp_establishment",
        "hr",
        "hr_contract",
    ],
    "data": [
        "security/erp_hr_ec_security.xml",
        "security/ir.model.access.csv",
        "data/hr_contract_type_data.xml",
        "views/erp_hr_extra_field_views.xml",
        "views/hr_employee_views.xml",
        "views/hr_contract_type_views.xml",
        "views/res_config_settings_views.xml",
        "views/erp_establishment_views.xml",
        "views/erp_hr_ec_menus.xml",
    ],
    "installable": True,
    "application": False,
}
