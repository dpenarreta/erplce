"""Registro de cuentas desactivado en el login (US-017, CA-2)."""

from urllib.parse import urlsplit

from odoo.tests import HttpCase, tagged
from odoo.tools import convert_file


@tagged("post_install", "-at_install")
class TestErpBaseSignupDisabled(HttpCase):
    def test_parameters(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        self.assertEqual(get_param("auth_signup.invitation_scope"), "b2b")
        self.assertEqual(get_param("auth_signup.reset_password"), "True")
        self.assertEqual(self.env["res.users"]._get_signup_invitation_scope(), "b2b")

    # Las rutas de auth_signup son multidioma: la primera respuesta puede ser
    # la redirección de idioma (/web/signup -> /<idioma>/web/signup), por eso
    # se siguen las redirecciones y se comprueba la URL final.
    def _path(self, url):
        return urlsplit(url).path

    def test_signup_route_without_token_redirects_to_login(self):
        for url in ("/web/signup", "/web/signup?redirect=https://ejemplo.invalid/"):
            with self.subTest(url=url):
                response = self.url_open(url)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(self._path(response.url).endswith("/web/login"))
                # Sin redirección abierta: no se propaga ningún parámetro.
                self.assertFalse(urlsplit(response.url).query, response.url)
                self.assertTrue(response.history)
                self.assertTrue(
                    all(step.status_code == 303 for step in response.history)
                )
                self.assertNotIn('name="confirm_password"', response.text)
                self.assertIn('name="password"', response.text)

    def test_signup_with_valid_invitation_token(self):
        """Una invitación con token válido sigue mostrando el formulario."""
        partner = self.env["res.partner"].create(
            {"name": "Begoña Núñez (invitada)", "email": "begona.nunez@ejemplo.ec"}
        )
        partner.signup_prepare()
        token = partner._generate_signup_token()
        response = self.url_open(f"/web/signup?token={token}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self._path(response.url).endswith("/web/signup"))
        self.assertIn('name="confirm_password"', response.text)
        self.assertIn("begona.nunez@ejemplo.ec", response.text)

    def test_signup_with_invalid_token_not_redirected(self):
        """Un token inválido no se trata como «sin token»: el formulario
        estándar informa el error (no se redirige al login)."""
        response = self.url_open("/web/signup?token=token-invalido-ñ")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self._path(response.url).endswith("/web/signup"))

    def test_login_page_without_signup_link_keeps_reset(self):
        response = self.url_open("/web/login")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("/web/signup", response.text)
        self.assertIn("/web/reset_password", response.text)
        reset = self.url_open("/web/reset_password")
        self.assertEqual(reset.status_code, 200)
        self.assertIn('name="login"', reset.text)

    def test_update_reapplies_b2b_but_respects_reset_password(self):
        """Si alguien activa el registro libre, actualizar erp_base lo vuelve a
        cerrar (noupdate="0"); «Restablecer contraseña» solo se activa al
        instalar (noupdate="1"): si el administrador lo desactiva, se respeta."""
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("auth_signup.invitation_scope", "b2c")
        ICP.set_param("auth_signup.reset_password", "False")
        convert_file(
            self.env,
            "erp_base",
            "data/auth_signup_data.xml",
            {},
            mode="update",
            noupdate=False,
        )
        self.assertEqual(ICP.get_param("auth_signup.invitation_scope"), "b2b")
        self.assertEqual(ICP.get_param("auth_signup.reset_password"), "False")

    def test_install_enables_reset_password(self):
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("auth_signup.reset_password", "False")
        convert_file(
            self.env,
            "erp_base",
            "data/auth_signup_data.xml",
            {},
            mode="init",
            noupdate=False,
        )
        self.assertEqual(ICP.get_param("auth_signup.reset_password"), "True")
        self.assertEqual(ICP.get_param("auth_signup.invitation_scope"), "b2b")
