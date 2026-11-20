"""Pruebas del usuario sugerido y del inicio de sesión sin distinguir mayúsculas (fuera del
repositorio del sistema): tres sugerencias distintas de patrones al azar, en minúsculas, sin
tildes ni ñ, de 4 a 20 caracteres y sin usuarios existentes; "Ver otras" no repite mientras
haya otras; el usuario entra con cualquier combinación de mayúsculas y no se crean dos
usuarios que solo se diferencien en ellas. Se ejecutan en la base temporal de pruebas de Django."""
import re

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APIClient

from fondos.tests.tests_arreglos import BaseArreglos

URL = '/api/usuarios/sugerir-usuario/'
FORMATO = re.compile(r'^[a-z0-9]{4,20}$')
# Los nueve patrones para "William Chao Rivero" (con dos apellidos y un nombre).
PATRONES_CHAO = {'wchao', 'wilchao', 'willchao', 'chaow', 'chaowil', 'williamc', 'wilchariv', 'wcrivero', 'wchaor'}


class SugerenciasTests(BaseArreglos):
    def sugerencias(self, nombre, excluir=(), usuario=None):
        respuesta = self.como(usuario or self.director).get(URL, {'nombre': nombre, 'excluir': ','.join(excluir)})
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        return respuesta.data['sugerencias']

    def test_tres_distintas_en_minusculas_sin_tildes_ni_enie(self):
        for nombre in ('William Chao Rivero', 'Ana María Peña Ávila', 'Íñigo Núñez', 'Al Li'):
            for _ in range(5):
                lista = self.sugerencias(nombre)
                with self.subTest(nombre=nombre, lista=lista):
                    self.assertEqual(len(lista), 3)
                    self.assertEqual(len(set(lista)), 3)
                    for usuario in lista:
                        self.assertRegex(usuario, FORMATO)

    def test_ver_otras_no_repite_mientras_haya_y_recorre_los_patrones(self):
        vistas = []
        for _ in range(3):
            lista = self.sugerencias('William Chao Rivero', excluir=vistas)
            self.assertFalse(set(lista) & set(vistas), (lista, vistas))
            vistas += lista
        self.assertEqual(set(vistas), PATRONES_CHAO)
        # Agotadas, vuelve a mostrar tres de las mismas.
        self.assertTrue(set(self.sugerencias('William Chao Rivero', excluir=vistas)) <= PATRONES_CHAO)

    def test_no_sugiere_usuarios_existentes_sin_distinguir_mayusculas(self):
        User.objects.create_user('WChao', password='x')
        User.objects.create_user('ChaoW', password='x')
        vistas = []
        for _ in range(3):
            vistas += self.sugerencias('William Chao Rivero', excluir=vistas)
        self.assertNotIn('wchao', vistas)
        self.assertNotIn('chaow', vistas)

    def test_si_todos_existen_agrega_un_numero(self):
        for usuario in PATRONES_CHAO:
            User.objects.create_user(usuario, password='x')
        lista = self.sugerencias('William Chao Rivero')
        self.assertEqual(len(lista), 3)
        for usuario in lista:
            self.assertRegex(usuario, r'^[a-z]{3,18}\d{2}$')
            self.assertFalse(User.objects.filter(username__iexact=usuario).exists())

    def test_hasta_20_caracteres(self):
        for usuario in self.sugerencias('Maximiliano Bartolomé Fernándezvillaverde Ochoaguzmán'):
            self.assertRegex(usuario, FORMATO)

    def test_sin_apellido_no_hay_sugerencias(self):
        self.assertEqual(self.sugerencias('Ana'), [])

    def test_solo_quien_crea_usuarios(self):
        self.assertEqual(self.como(self.usuario_docente).get(URL, {'nombre': 'Ana Rojas'}).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(len(self.sugerencias('Ana Rojas', usuario=self.superuser)), 3)


class InicioSesionSinMayusculasTests(BaseArreglos):
    def entrar(self, usuario, contrasena='x'):
        return APIClient().post('/api/token/', {'username': usuario, 'password': contrasena}, format='json')

    def test_entra_con_cualquier_combinacion_de_mayusculas(self):
        for escrito in (self.director.username, self.director.username.upper(), self.director.username.title()):
            with self.subTest(escrito=escrito):
                respuesta = self.entrar(escrito)
                self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
                self.assertEqual(respuesta.data['username'], self.director.username)
        self.assertEqual(self.entrar(self.director.username.upper(), 'otra').status_code, status.HTTP_401_UNAUTHORIZED)

    def test_no_se_crea_ni_se_renombra_a_uno_que_solo_cambia_en_mayusculas(self):
        cliente = self.como(self.superuser)
        datos = self.datos_usuario(self.director.username.upper(), 'iiisyp', self.carrera, 'MAY-1')
        respuesta = cliente.post('/api/usuarios/', datos, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('username', respuesta.data)

        libre = self.crear_usuario('sin_registros', 'iiisyp', carrera=self.carrera, ci='MAY-2')
        respuesta = cliente.patch(f'/api/usuarios/{libre.pk}/', {'username': self.director.username.upper()}, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('sin distinguir mayúsculas', str(respuesta.data['username'][0]))
        self.assertEqual(User.objects.get(pk=libre.pk).username, 'sin_registros')
        # Cambiar solo las mayúsculas del propio usuario sí se permite.
        respuesta = cliente.patch(f'/api/usuarios/{libre.pk}/', {'username': 'Sin_Registros'}, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)

    def test_si_dos_cuentas_solo_se_diferencian_en_mayusculas_pide_el_exacto(self):
        User.objects.create_user(self.director.username.upper(), password='x')
        self.assertEqual(self.entrar(self.director.username.title()).status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.entrar(self.director.username).status_code, status.HTTP_200_OK)
