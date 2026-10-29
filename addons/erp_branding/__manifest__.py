{
    "name": "ERP Branding",
    "summary": "Marca corporativa (nombre, logo, favicon, colores) del cliente web",
    "version": "18.0.1.0.0",
    "category": "Hidden/Tools",
    "author": "LAARCOURIER EXPRESS S.A.",
    "license": "LGPL-3",
    "depends": ["web"],
    "data": [
        "data/ir_config_parameter_data.xml",
        "views/webclient_templates.xml",
    ],
    "assets": {
        # Must be loaded BEFORE the core variables: both use !default, so the
        # first definition wins.
        "web._assets_primary_variables": [
            (
                "before",
                "web/static/src/scss/primary_variables.scss",
                "erp_branding/static/src/scss/primary_variables.scss",
            ),
        ],
        "web.assets_backend": [
            "erp_branding/static/src/scss/webclient.scss",
            "erp_branding/static/src/js/title_service_patch.js",
        ],
        "web.assets_frontend": [
            "erp_branding/static/src/scss/login.scss",
        ],
    },
    "installable": True,
    "application": False,
}
