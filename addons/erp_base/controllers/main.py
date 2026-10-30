from odoo import http
from odoo.http import request

from odoo.addons.auth_signup.controllers.main import AuthSignupHome

LOGIN_URL = "/web/login"


class ErpAuthSignupHome(AuthSignupHome):
    @http.route()
    def web_auth_signup(self, *args, **kw):
        """Registro de cuentas (US-017, CA-2).

        - Acceso: público (ruta de ``auth_signup``).
        - Sin token de invitación y con el registro libre desactivado
          (``auth_signup.invitation_scope = b2b``, el caso del ERP interno):
          redirige al inicio de sesión (303 a ``/web/login``) en lugar del 404
          genérico del portal. No se propaga ningún parámetro de la petición
          (sin redirección abierta).
        - Con token (invitación o reinicio) o con registro libre activado:
          comportamiento estándar de ``auth_signup``; un token inválido lo
          sigue informando su formulario.
        """
        qcontext = self.get_auth_signup_qcontext()
        if not qcontext.get("token") and not qcontext.get("signup_enabled"):
            return request.redirect(LOGIN_URL, code=303)
        return super().web_auth_signup(*args, **kw)
