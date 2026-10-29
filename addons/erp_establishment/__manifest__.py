{
    "name": "ERP Establecimientos SRI",
    "summary": "Catálogo de establecimientos SRI de la empresa con su región "
    "geográfica y régimen de décimo cuarto sueldo.",
    "version": "18.0.1.0.0",
    "category": "Hidden",
    "author": "LAARCOURIER EXPRESS S.A.",
    "license": "LGPL-3",
    "depends": [
        "erp_base",
        "base_import",
    ],
    "data": [
        "security/erp_establishment_security.xml",
        "security/ir.model.access.csv",
        "views/erp_establishment_views.xml",
    ],
    "installable": True,
    "application": False,
}
