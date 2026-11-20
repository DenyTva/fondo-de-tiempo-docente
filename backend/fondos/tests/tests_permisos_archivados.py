"""Pruebas de permisos de Fondos archivados y Comparar fondos (fuera del repositorio del
sistema): los consultan el superusuario, el Director, el Jefe de Estudios y el Instituto,
según el rol activo (X-Active-Assignment); restaurar no es del Instituto, y el Docente recibe
403 en todo. Se ejecutan en la base temporal de pruebas de Django."""
from rest_framework import status

from fondos.models import AsignacionCarrera, FondoTiempo
from fondos.tests.tests_arreglos import BaseArreglos
from fondos.tests.utilidades import forzar_campos


class PermisosArchivadosYComparadorTests(BaseArreglos):
    def setUp(self):
        super().setUp()
        self.instituto = self.crear_usuario('inst_sis', 'iiisyp', carrera=self.carrera)
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado='finalizado', archivado=True)

    def pedir(self, usuario, **cabeceras):
        cliente = self.como(usuario)
        return {
            'archivados': cliente.get('/api/fondos-tiempo/archivados/', **cabeceras),
            'comparar': cliente.get(
                f'/api/fondos-tiempo/comparar/?docente={self.docente.pk}&gestion1=2025&gestion2=2026', **cabeceras,
            ),
            'restaurar': cliente.post(f'/api/fondos-tiempo/{self.fondo.pk}/restaurar/', **cabeceras),
        }

    def test_el_instituto_consulta_pero_no_restaura(self):
        respuestas = self.pedir(self.instituto)

        self.assertEqual(respuestas['archivados'].status_code, status.HTTP_200_OK)
        self.assertEqual(respuestas['comparar'].status_code, status.HTTP_200_OK)
        self.assertEqual(respuestas['restaurar'].status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(FondoTiempo.objects.get(pk=self.fondo.pk).archivado)

    def test_docente_recibe_403_y_el_fondo_sigue_archivado(self):
        for usuario in [self.usuario_docente]:
            for accion, respuesta in self.pedir(usuario).items():
                with self.subTest(rol=usuario.perfil.rol, accion=accion):
                    self.assertEqual(respuesta.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(FondoTiempo.objects.get(pk=self.fondo.pk).archivado)

    def test_superusuario_director_y_jefe_ven_archivados_y_comparan(self):
        for usuario in [self.superuser, self.director, self.jefe]:
            cliente = self.como(usuario)
            with self.subTest(usuario=usuario.username):
                archivados = cliente.get('/api/fondos-tiempo/archivados/')
                self.assertEqual(archivados.status_code, status.HTTP_200_OK)
                self.assertEqual([fondo['id'] for fondo in archivados.data], [self.fondo.pk])
                comparar = cliente.get(
                    f'/api/fondos-tiempo/comparar/?docente={self.docente.pk}&gestion1=2025&gestion2=2026'
                )
                self.assertEqual(comparar.status_code, status.HTTP_200_OK)

    def test_el_superusuario_restaura(self):
        respuesta = self.como(self.superuser).post(f'/api/fondos-tiempo/{self.fondo.pk}/restaurar/')

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        self.assertFalse(FondoTiempo.objects.get(pk=self.fondo.pk).archivado)

    def test_decide_el_rol_activo_y_no_el_rol_base(self):
        # Jefe de Estudios que también es docente: con el rol Docente activo recibe 403.
        asignacion_jefe = AsignacionCarrera.objects.get(user=self.jefe)
        asignacion_docente = AsignacionCarrera.objects.create(
            user=self.jefe, carrera=self.carrera, rol='docente', docente=self.crear_docente('J1'),
        )

        for accion, respuesta in self.pedir(self.jefe, HTTP_X_ACTIVE_ASSIGNMENT=str(asignacion_docente.pk)).items():
            with self.subTest(rol_activo='docente', accion=accion):
                self.assertEqual(respuesta.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(FondoTiempo.objects.get(pk=self.fondo.pk).archivado)

        for accion, respuesta in self.pedir(self.jefe, HTTP_X_ACTIVE_ASSIGNMENT=str(asignacion_jefe.pk)).items():
            with self.subTest(rol_activo='jefe_estudios', accion=accion):
                self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        self.assertFalse(FondoTiempo.objects.get(pk=self.fondo.pk).archivado)
