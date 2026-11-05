{
    "name": "ERP Theme",
    "summary": "Tema del cliente web ERP LCE: menú lateral, tarjetas y uso en celular",
    "version": "18.0.1.0.2",
    "category": "Hidden/Tools",
    "author": "LAARCOURIER EXPRESS S.A.",
    "license": "LGPL-3",
    # The brand (colors, logo, login) stays in erp_branding; this module only
    # changes the layout of the backend web client and can be uninstalled to go
    # back to the standard layout keeping the brand.
    "depends": ["web", "mail", "erp_branding"],
    "assets": {
        # Top bar variables: loaded BEFORE the erp_branding palette (both use
        # !default, so the first definition wins) to turn the black navbar
        # into a light one now that the sidebar is the black surface.
        "web._assets_primary_variables": [
            (
                "before",
                "erp_branding/static/src/scss/primary_variables.scss",
                "erp_theme/static/src/scss/primary_variables.scss",
            ),
        ],
        "web.assets_backend": [
            "erp_theme/static/src/scss/fonts.scss",
            "erp_theme/static/src/scss/theme.scss",
            "erp_theme/static/src/sidebar/*",
            "erp_theme/static/src/navbar/*",
            "erp_theme/static/src/webclient/*",
            "erp_theme/static/src/form/*",
        ],
    },
    "installable": True,
    "application": False,
}
