{
    "name": "ERP Base Ecuador",
    "summary": "Configuración base de la instancia para Ecuador: localización "
    "contable l10n_ec, idioma es_EC, zona horaria y moneda USD.",
    "version": "18.0.1.0.1",
    "category": "Technical",
    "author": "LAARCOURIER EXPRESS S.A.",
    "license": "LGPL-3",
    "depends": [
        "base",
        "auth_signup",
        "l10n_ec",
    ],
    "data": [
        "data/auth_signup_data.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
