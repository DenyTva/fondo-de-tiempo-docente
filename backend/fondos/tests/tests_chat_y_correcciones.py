"""Pruebas del chat del fondo y de las correcciones (fuera del repositorio del sistema):
al reenviar (el informe el docente, el fondo la Jefatura) las observaciones pendientes se
resuelven solas con quién y cuándo; al finalizar no queda ninguna pendiente y el chat
queda en solo lectura; solicitar correcciones genera un solo aviso; el superusuario lee
la carga horaria; Director y Jefe completan el teléfono y el correo del docente. Evaluar y
finalizar son dos pasos: la evaluación (observación opcional) solo se guarda y se puede
cambiar; al finalizar, el docente recibe el resultado, que antes no ve, y con el informe
evaluado ya no se piden correcciones. El usuario sugerido está en tests_usuario_sugerido.py.
Se ejecutan en la base temporal de pruebas de Django."""
from unittest import mock

from rest_framework import status

from fondos.models import FondoTiempo, HistorialFondo, InformeFondo, MensajeObservacion, ObservacionFondo
from fondos.tests.utilidades import forzar_campos
from fondos.tests.tests_arreglos import BaseArreglos

INFORME = {'seccion_academica': '<p>Dicté las materias asignadas.</p>', 'conclusiones_generales': '<p>Se cumplió el plan.</p>'}
EVALUACION = {'cumplimiento': 'cumplido', 'evaluacion_director': 'Cumplió todas las actividades planificadas en la gestión.'}


class BaseChat(BaseArreglos):
    def setUp(self):
        super().setUp()
        InformeFondo.objects.create(fondo_tiempo=self.fondo, elaborado_por=self.usuario_docente, tipo='parcial')

    def estado(self, estado):
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado=estado)

    def pendientes(self):
        return ObservacionFondo.objects.filter(fondo_tiempo=self.fondo, resuelta=False)

    def observar_informe(self):
        self.estado('informe_presentado')
        respuesta = self.como(self.director).post(
            f'/api/fondos-tiempo/{self.fondo.pk}/observar-informe/', {'comentario': 'Falta detallar las tutorías.'}, format='json',
        )
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)


class ResolucionAlReenviarTests(BaseChat):
    def test_reenviar_el_informe_resuelve_las_observaciones_de_esa_ronda(self):
        self.observar_informe()
        self.assertEqual(self.pendientes().count(), 1)

        respuesta = self.como(self.usuario_docente).post(f'/api/fondos-tiempo/{self.fondo.pk}/presentar/', INFORME, format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        self.assertEqual(self.pendientes().count(), 0)
        observacion = ObservacionFondo.objects.get(fondo_tiempo=self.fondo)
        self.assertEqual(observacion.resuelta_por, self.usuario_docente)
        self.assertIsNotNone(observacion.fecha_resolucion)

    def test_reenviar_el_fondo_resuelve_las_observaciones_pendientes(self):
        self.estado('observado')
        ObservacionFondo.objects.create(fondo_tiempo=self.fondo)
        # Lo que no se prueba aquí (unidades completas y documentos) se da por cumplido.
        horas = self.fondo.horas_efectivas
        with mock.patch.object(FondoTiempo, 'total_asignado', new_callable=mock.PropertyMock, return_value=horas),                 mock.patch.object(FondoTiempo, 'programas_analiticos_faltantes', return_value=[]),                 mock.patch.object(FondoTiempo, 'documentos_actividad_faltantes', return_value=[]):
            respuesta = self.como(self.jefe).patch(f'/api/fondos-tiempo/{self.fondo.pk}/presentar-a-director/', {}, format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        self.assertEqual(self.pendientes().count(), 0)
        observacion = ObservacionFondo.objects.get(fondo_tiempo=self.fondo)
        self.assertEqual(observacion.resuelta_por, self.jefe)
        self.assertIsNotNone(observacion.fecha_resolucion)

    def test_al_finalizar_no_queda_ninguna_pendiente(self):
        self.estado('informe_presentado')
        pendiente = ObservacionFondo.objects.create(fondo_tiempo=self.fondo)

        evaluar = self.como(self.director).post(f'/api/fondos-tiempo/{self.fondo.pk}/evaluar-informe/', EVALUACION, format='json')
        self.assertEqual(evaluar.status_code, status.HTTP_200_OK, evaluar.data)
        self.assertEqual(self.pendientes().count(), 1)  # evaluado, el chat sigue abierto
        respuesta = self.como(self.director).post(f'/api/fondos-tiempo/{self.fondo.pk}/finalizar/', {}, format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        self.assertEqual(self.pendientes().count(), 0)
        # La pendiente y el hilo con la evaluación quedan resueltos, con quién y cuándo.
        for observacion in ObservacionFondo.objects.filter(fondo_tiempo=self.fondo):
            self.assertEqual(observacion.resuelta_por, self.director, observacion.pk)
            self.assertIsNotNone(observacion.fecha_resolucion)
        self.assertTrue(ObservacionFondo.objects.filter(pk=pendiente.pk, resuelta=True).exists())


class ChatFinalizadoTests(BaseChat):
    def setUp(self):
        super().setUp()
        self.observacion = ObservacionFondo.objects.create(fondo_tiempo=self.fondo)
        MensajeObservacion.objects.create(observacion=self.observacion, autor=self.director, texto='Revise la sección académica.')
        self.estado('finalizado')

    def test_se_lee_pero_no_se_escribe(self):
        lectura = self.como(self.usuario_docente).get(f'/api/observaciones/{self.observacion.pk}/')
        self.assertEqual(lectura.status_code, status.HTTP_200_OK)

        for usuario in (self.usuario_docente, self.jefe, self.director):
            respuesta = self.como(usuario).post(
                f'/api/observaciones/{self.observacion.pk}/agregar-mensaje/', {'texto': 'Un mensaje más'}, format='json',
            )
            self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST, (usuario.username, respuesta.data))
        self.assertEqual(self.observacion.mensajes.count(), 1)

        respuesta = self.como(self.usuario_docente).post(f'/api/observaciones/{self.observacion.pk}/marcar-resuelta/', {}, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)


class UnSoloAvisoTests(BaseChat):
    def test_solicitar_correcciones_genera_un_solo_aviso_para_el_docente(self):
        self.observar_informe()

        self.assertEqual(HistorialFondo.objects.filter(fondo_tiempo=self.fondo, estado_nuevo='en_ejecucion').count(), 1)
        avisos = self.como(self.usuario_docente).get('/api/fondos-tiempo/novedades/').data['avisos']
        del_fondo = [aviso for aviso in avisos if aviso['fondo_id'] == self.fondo.pk]
        self.assertEqual([(a['evento'], a['accion']) for a in del_fondo], [('informe_observado', 'Corregir')])


class EvaluarYFinalizarTests(BaseChat):
    """Evaluación de cumplimiento (Art. 19) y finalización, en dos pasos. Evaluar guarda el
    resultado (Cumplido, Cumplimiento parcial o Incumplido) y la observación opcional: el
    fondo pasa a "Informe evaluado" y la evaluación se puede cambiar. Finalizar cierra el fondo
    y recién entonces el docente recibe el resultado (aviso y chat) y lo ve en su informe."""

    def setUp(self):
        super().setUp()
        self.estado('informe_presentado')

    def evaluar(self, datos):
        return self.como(self.director).post(f'/api/fondos-tiempo/{self.fondo.pk}/evaluar-informe/', datos, format='json')

    def finalizar(self):
        return self.como(self.director).post(f'/api/fondos-tiempo/{self.fondo.pk}/finalizar/', {}, format='json')

    def avisos_del_docente(self):
        avisos = self.como(self.usuario_docente).get('/api/fondos-tiempo/novedades/').data['avisos']
        return [a['texto'] for a in avisos if a['fondo_id'] == self.fondo.pk]

    def informe_visto_por(self, usuario):
        return self.como(usuario).get(f'/api/fondos-tiempo/{self.fondo.pk}/').data['informe_actual']

    def test_evaluar_solo_guarda_el_resultado(self):
        respuesta = self.evaluar({'cumplimiento': 'parcial'})

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        self.fondo.refresh_from_db()
        self.assertEqual(self.fondo.estado, 'informe_evaluado')
        self.assertIsNone(self.fondo.fecha_finalizacion)
        detalle = self.como(self.director).get(f'/api/fondos-tiempo/{self.fondo.pk}/').data
        self.assertIsNotNone(detalle['evaluado_el'])  # "Tiempo en etapa" cuenta desde la evaluación
        self.assertIsNone(detalle['finalizado_el'])
        informe = InformeFondo.objects.get(fondo_tiempo=self.fondo)
        self.assertEqual((informe.cumplimiento, informe.evaluacion_director), ('parcial', ''))
        # Sin mensaje ni aviso al docente, y el historial no dice el resultado.
        self.assertFalse(MensajeObservacion.objects.filter(observacion__fondo_tiempo=self.fondo).exists())
        self.assertEqual(self.avisos_del_docente(), [])
        historial = HistorialFondo.objects.filter(fondo_tiempo=self.fondo).latest('id')
        self.assertEqual(
            (historial.tipo_cambio, historial.estado_nuevo, historial.descripcion),
            ('evaluacion', 'informe_evaluado', 'Informe evaluado, pendiente de finalización'),
        )

    def test_cambiar_la_evaluacion_antes_de_finalizar(self):
        self.evaluar({'cumplimiento': 'cumplido'})

        respuesta = self.evaluar({'cumplimiento': 'incumplido', 'evaluacion_director': 'Faltó la sección de investigación.'})

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        self.fondo.refresh_from_db()
        self.assertEqual(self.fondo.estado, 'informe_evaluado')
        informe = InformeFondo.objects.get(fondo_tiempo=self.fondo)
        self.assertEqual((informe.cumplimiento, informe.evaluacion_director), ('incumplido', 'Faltó la sección de investigación.'))
        self.assertEqual(HistorialFondo.objects.filter(fondo_tiempo=self.fondo).latest('id').descripcion, 'Evaluación del informe cambiada')

    def test_finalizar_envia_el_resultado_al_docente(self):
        self.evaluar({'cumplimiento': 'parcial'})

        respuesta = self.finalizar()

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        self.fondo.refresh_from_db()
        self.assertEqual(self.fondo.estado, 'finalizado')
        self.assertIsNotNone(self.fondo.fecha_finalizacion)
        detalle = self.como(self.director).get(f'/api/fondos-tiempo/{self.fondo.pk}/').data
        self.assertEqual((detalle['evaluado_el'], detalle['finalizado_el'] is not None), (None, True))
        esperado = 'Tu informe fue evaluado: Cumplimiento parcial. Tu fondo de tiempo 2026 quedó finalizado.'
        self.assertEqual(MensajeObservacion.objects.get(observacion__fondo_tiempo=self.fondo).texto, esperado)
        self.assertEqual(self.avisos_del_docente(), [esperado])

    def test_con_observacion_la_agrega_al_mensaje_al_finalizar(self):
        self.evaluar({'cumplimiento': 'incumplido', 'evaluacion_director': 'No presentó la sección de investigación.'})
        self.finalizar()

        self.assertEqual(
            MensajeObservacion.objects.get(observacion__fondo_tiempo=self.fondo).texto,
            'Tu informe fue evaluado: Incumplido. Tu fondo de tiempo 2026 quedó finalizado.\n\n'
            'Observación del Director: No presentó la sección de investigación.',
        )

    def test_el_docente_no_ve_el_resultado_hasta_finalizar(self):
        self.evaluar({'cumplimiento': 'incumplido', 'evaluacion_director': 'No presentó la sección de investigación.'})

        del_docente = self.informe_visto_por(self.usuario_docente)
        del_director = self.informe_visto_por(self.director)
        self.assertEqual((del_docente['cumplimiento'], del_docente['evaluacion_director']), ('', ''))
        self.assertEqual(del_director['cumplimiento'], 'incumplido')

        self.finalizar()
        self.assertEqual(self.informe_visto_por(self.usuario_docente)['cumplimiento'], 'incumplido')

    def test_con_el_informe_evaluado_no_se_piden_correcciones(self):
        self.evaluar({'cumplimiento': 'cumplido'})

        respuesta = self.como(self.director).post(
            f'/api/fondos-tiempo/{self.fondo.pk}/observar-informe/', {'comentario': 'Falta detallar las tutorías.'}, format='json',
        )

        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.fondo.refresh_from_db()
        self.assertEqual(self.fondo.estado, 'informe_evaluado')

    def test_no_se_finaliza_sin_evaluar_ni_se_cambia_la_evaluacion_finalizado(self):
        self.assertEqual(self.finalizar().status_code, status.HTTP_400_BAD_REQUEST)
        self.fondo.refresh_from_db()
        self.assertEqual(self.fondo.estado, 'informe_presentado')

        self.evaluar({'cumplimiento': 'cumplido'})
        self.finalizar()
        respuesta = self.evaluar({'cumplimiento': 'incumplido'})

        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(InformeFondo.objects.get(fondo_tiempo=self.fondo).cumplimiento, 'cumplido')

    def test_otro_resultado_se_rechaza(self):
        respuesta = self.evaluar({'cumplimiento': 'excelente'})

        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.fondo.refresh_from_db()
        self.assertEqual(self.fondo.estado, 'informe_presentado')


class SuperusuarioCargaHorariaTests(BaseArreglos):
    def test_el_superusuario_lee_docentes_y_cargas(self):
        cliente = self.como(self.superuser)

        self.assertEqual(cliente.get('/api/docentes/').status_code, status.HTTP_200_OK)
        self.assertEqual(cliente.get('/api/cargas-horarias/', {'docente': self.docente.pk}).status_code, status.HTTP_200_OK)
        self.assertEqual(cliente.get('/api/cargas-horarias/', {'otra_carrera': 1}).status_code, status.HTTP_200_OK)


class DatosContactoDocenteTests(BaseArreglos):
    def url(self, docente=None):
        return f'/api/docentes/{(docente or self.docente).pk}/datos-contacto/'

    def test_director_y_jefe_de_su_carrera_completan_telefono_y_correo(self):
        for usuario, telefono in ((self.director, '71234567'), (self.jefe, '+591 3 4621000')):
            respuesta = self.como(usuario).patch(self.url(), {'telefono': telefono, 'email': 'ana.rojas@uabjb.edu.bo'}, format='json')
            self.assertEqual(respuesta.status_code, status.HTTP_200_OK, (usuario.username, respuesta.data))
            self.assertEqual(respuesta.data['telefono'], telefono)
        self.docente.refresh_from_db()
        self.assertEqual(self.docente.email, 'ana.rojas@uabjb.edu.bo')

    def test_aunque_la_ficha_este_fija_por_su_historial(self):
        from fondos.tests.utilidades import forzar_campos
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado='aprobado_director')

        respuesta = self.como(self.jefe).patch(self.url(), {'telefono': '76543210'}, format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        # El resto de la ficha sigue siendo solo del superusuario.
        self.assertEqual(self.como(self.jefe).patch(f'/api/docentes/{self.docente.pk}/', {'telefono': '1'}, format='json').status_code, status.HTTP_403_FORBIDDEN)

    def test_ni_otra_carrera_ni_el_docente_ni_datos_invalidos(self):
        respuesta = self.como(self.jefe_civil).patch(self.url(), {'telefono': '71234567'}, format='json')
        self.assertIn(respuesta.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        respuesta = self.como(self.usuario_docente).patch(self.url(), {'telefono': '71234567'}, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_403_FORBIDDEN)
        respuesta = self.como(self.director).patch(self.url(), {'telefono': 'llamar al 7'}, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        respuesta = self.como(self.director).patch(self.url(), {'email': 'no-es-correo'}, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.docente.refresh_from_db()
        self.assertFalse(self.docente.telefono)
