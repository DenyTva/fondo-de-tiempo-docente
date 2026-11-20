"""Pruebas del correo institucional obligatorio (fuera del repositorio del sistema): antes
el backend dejaba crear usuarios sin correo (solo lo pedía el formulario) y en la base
quedaron dos así. Se ejecutan en la base temporal de pruebas de Django."""
from django.contrib.auth.models import User
from rest_framework import status

from fondos.tests.tests_usuarios_auditoria import UsuariosBaseTestCase


class CorreoObligatorioTests(UsuariosBaseTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.superuser)

    def test_no_se_crea_un_usuario_sin_correo(self):
        for email in (None, '', '   '):
            with self.subTest(email=email):
                datos = self.datos_usuario('sin_correo', 'iiisyp', self.carrera, 'SC-1')
                if email is None:
                    datos.pop('email')
                else:
                    datos['email'] = email

                respuesta = self.client.post('/api/usuarios/', datos, format='json')

                self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(str(respuesta.data['email'][0]), 'El correo institucional es obligatorio.')
                self.assertFalse(User.objects.filter(username='sin_correo').exists())

    def test_con_correo_se_crea(self):
        respuesta = self.client.post(
            '/api/usuarios/', self.datos_usuario('con_correo', 'iiisyp', self.carrera, 'SC-2'), format='json',
        )

        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)
        self.assertEqual(User.objects.get(username='con_correo').email, 'con_correo@uabjb.edu.bo')

    def test_al_editar_no_se_deja_el_correo_vacio(self):
        usuario = self.crear_usuario('editado', 'iiisyp', carrera=self.carrera, ci='SC-3')
        User.objects.filter(pk=usuario.pk).update(email='editado@uabjb.edu.bo')

        respuesta = self.client.patch(f'/api/usuarios/{usuario.pk}/', {'email': ''}, format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(str(respuesta.data['email'][0]), 'El correo institucional es obligatorio.')
        self.assertEqual(User.objects.get(pk=usuario.pk).email, 'editado@uabjb.edu.bo')
