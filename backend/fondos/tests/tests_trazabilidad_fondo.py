"""Pruebas de la trazabilidad del estado del fondo (fuera del repositorio del sistema): el
admin no edita los campos del flujo, update() no escribe estado ni archivado, y crear un
fondo (uno por uno o en la generación masiva) deja su registro 'creacion' en el historial.
Se ejecutan en la base temporal de pruebas de Django."""
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import RequestFactory
from rest_framework import status

from fondos.models import CalendarioAcademico, FondoTiempo, HistorialFondo
from fondos.serializers import FondoTiempoSerializer
from fondos.tests.utilidades import forzar_campos
from fondos.tests.tests_arreglos import BaseArreglos


class AdminFondoTiempoTests(BaseArreglos):
    def test_el_admin_muestra_los_campos_del_flujo_solo_en_lectura(self):
        modelo_admin = admin.site._registry[FondoTiempo]
        peticion = RequestFactory().get('/')
        peticion.user = self.superuser

        solo_lectura = set(modelo_admin.get_readonly_fields(peticion, self.fondo))
        formulario = modelo_admin.get_form(peticion, self.fondo)

        self.assertTrue(set(FondoTiempoSerializer.Meta.read_only_fields) <= solo_lectura)
        for campo in ('estado', 'archivado', 'aprobado_por', 'fecha_presentacion'):
            with self.subTest(campo=campo):
                self.assertIn(campo, solo_lectura)
                self.assertNotIn(campo, formulario.base_fields)


class UpdateSinFlujoTests(BaseArreglos):
    def test_update_no_cambia_estado_ni_archivado(self):
        for campos in ({'estado': 'presentado_director'}, {'archivado': True}, {'estado': 'borrador', 'archivado': True}):
            with self.subTest(campos=campos):
                with self.assertRaisesMessage(ValueError, 'no se cambia con update()'):
                    FondoTiempo.objects.filter(pk=self.fondo.pk).update(**campos)
                # Por el docente (manager relacionado) tampoco.
                with self.assertRaises(ValueError):
                    self.docente.fondos_tiempo.update(**campos)
        self.fondo.refresh_from_db()
        self.assertEqual((self.fondo.estado, self.fondo.archivado), ('borrador', False))

    def test_bulk_update_del_estado_tambien_se_rechaza(self):
        self.fondo.estado = 'presentado_director'

        # bulk_update() abre su transacción sin punto de guardado: el atomic() propio deja
        # usable la transacción de la prueba después del rechazo.
        with self.assertRaises(ValueError), transaction.atomic():
            FondoTiempo.objects.bulk_update([self.fondo], ['estado'])

        self.assertEqual(FondoTiempo.objects.get(pk=self.fondo.pk).estado, 'borrador')

    def test_update_de_otros_campos_sigue_funcionando(self):
        self.assertEqual(FondoTiempo.objects.filter(pk=self.fondo.pk).update(observaciones='Nota'), 1)
        self.assertEqual(FondoTiempo.objects.get(pk=self.fondo.pk).observaciones, 'Nota')

    def test_save_sigue_rechazando_las_transiciones_fuera_del_flujo(self):
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado='presentado_director')
        fondo = FondoTiempo.objects.get(pk=self.fondo.pk)
        fondo.estado = 'borrador'

        with self.assertRaises(ValidationError):
            fondo.save()


class RegistroDeCreacionTests(BaseArreglos):
    def setUp(self):
        super().setUp()
        # Docente de Sistemas sin fondo en 2026.
        self.otro_docente = self.crear_docente('B1')

    def assertCreacion(self, fondo, usuario, descripcion):
        registros = HistorialFondo.objects.filter(fondo_tiempo=fondo)
        self.assertEqual(registros.count(), 1)
        registro = registros.get()
        self.assertEqual(
            (registro.tipo_cambio, registro.usuario, registro.estado_anterior, registro.estado_nuevo),
            ('creacion', usuario, '', ''),
        )
        self.assertEqual(registro.descripcion, f'{descripcion} (gestión 2026, estado: Borrador).')

    def test_crear_un_fondo_registra_la_creacion_con_quien_lo_crea(self):
        respuesta = self.como(self.jefe).post('/api/fondos-tiempo/', {
            'docente': self.otro_docente.pk, 'carrera': self.carrera.pk, 'gestion': 2026,
        }, format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)
        self.assertCreacion(FondoTiempo.objects.get(pk=respuesta.data['id']), self.jefe, 'Fondo creado')

    def test_un_fondo_rechazado_al_crear_no_deja_registro(self):
        # Ya tiene fondo vigente en 2026: no se crea ni queda historial.
        respuesta = self.como(self.jefe).post('/api/fondos-tiempo/', {
            'docente': self.docente.pk, 'carrera': self.carrera.pk, 'gestion': 2026,
        }, format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(HistorialFondo.objects.filter(tipo_cambio='creacion').exists())

    def test_la_generacion_masiva_registra_cada_fondo_creado(self):
        CalendarioAcademico.objects.filter(pk=self.cal.pk).update(activo=True)

        respuesta = self.como(self.jefe).post('/api/fondos-tiempo/generar-masivo/')

        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)
        self.assertEqual(respuesta.data['creados'], 1)
        fondo = FondoTiempo.objects.get(docente=self.otro_docente, gestion=2026)
        self.assertCreacion(fondo, self.jefe, 'Fondo creado en la generación masiva')
        # El fondo que ya existía no recibe otro registro.
        self.assertFalse(HistorialFondo.objects.filter(fondo_tiempo=self.fondo).exists())

    def test_la_creacion_no_genera_avisos(self):
        self.como(self.jefe).post('/api/fondos-tiempo/', {
            'docente': self.otro_docente.pk, 'carrera': self.carrera.pk, 'gestion': 2026,
        }, format='json')

        for usuario in (self.director, self.usuario_docente):
            with self.subTest(usuario=usuario.username):
                respuesta = self.como(usuario).get('/api/fondos-tiempo/novedades/')
                self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
                self.assertEqual(respuesta.data['avisos'], [])
