{
    "name": "ERP Branding",
    "summary": "Marca corporativa (nombre, logo, favicon, colores) del cliente web",
    "version": "18.0.1.1.0",
    "category": "Hidden/Tools",
    "author": "LAARCOURIER EXPRESS S.A.",
    "license": "LGPL-3",
    # web_editor: reads the frontend palette ($o-color-palettes in
    # primary_variables.scss) from which the frontend $primary / $secondary,
    # links and button states are derived (login, portal, error pages).
    # Without it those pages fall back to Bootstrap's defaults and the
    # palette would only apply when another module installs web_editor. It is
    # a core module, already installed by portal (and so in erp_dev), with no
    # menus or data visible to users: declaring it makes the palette and its
    # contrast tests deterministic.
    "depends": ["web", "auth_signup", "web_editor"],
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
