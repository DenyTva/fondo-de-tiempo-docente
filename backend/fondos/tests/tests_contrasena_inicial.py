"""Pruebas de contraseñas (fuera del repositorio del sistema): el cambio obligatorio del
primer ingreso aplica los validadores de Django y ya no existe la acción cambiar_password
de usuarios (sin uso en el frontend). Se ejecutan en la base temporal de pruebas de Django."""
from rest_framework import status

from fondos.tests.tests_arreglos import BaseArreglos


class ContrasenaInicialTests(BaseArreglos):
    ACTUAL = 'Antigua.Clave.2026'
    NUEVA = 'Nueva.Clave.Segura.2026'

    def setUp(self):
        super().setUp()
        self.usuario_docente.set_password(self.ACTUAL)
        self.usuario_docente.save()

    def assertContrasena(self, clave):
        self.usuario_docente.refresh_from_db()
        self.assertTrue(self.usuario_docente.check_password(clave))

    def test_el_primer_ingreso_aplica_los_validadores(self):
        cliente = self.como(self.usuario_docente)

        for debil in ('12345678', 'password', 'docente_sis1'):
            respuesta = cliente.post('/api/auth/cambiar-password-inicial/', {'password': debil}, format='json')
            self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST, debil)
        self.assertContrasena(self.ACTUAL)

        buena = cliente.post('/api/auth/cambiar-password-inicial/', {'password': self.NUEVA}, format='json')
        self.assertEqual(buena.status_code, status.HTTP_200_OK)
        self.assertContrasena(self.NUEVA)

    def test_ya_no_existe_la_accion_cambiar_password_de_usuarios(self):
        respuesta = self.como(self.superuser).post(
            f'/api/usuarios/{self.usuario_docente.pk}/cambiar_password/',
            {'password': self.NUEVA, 'password_confirm': self.NUEVA}, format='json',
        )

        self.assertEqual(respuesta.status_code, status.HTTP_404_NOT_FOUND)
        self.assertContrasena(self.ACTUAL)

    def test_mi_cuenta_ya_no_tiene_preferencias_ni_cambio_de_contrasena(self):
        cliente = self.como(self.usuario_docente)

        self.assertEqual(cliente.get('/api/mi-cuenta/preferencias/').status_code, status.HTTP_404_NOT_FOUND)
        respuesta = cliente.post('/api/mi-cuenta/cambiar-password/', {
            'password_actual': self.ACTUAL, 'password_nueva': self.NUEVA, 'password_confirmacion': self.NUEVA,
        }, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_404_NOT_FOUND)
        self.assertContrasena(self.ACTUAL)
        perfil = self.como(self.usuario_docente).get('/api/usuario/').data['perfil']
        self.assertNotIn('preferencias_interfaz', perfil)
