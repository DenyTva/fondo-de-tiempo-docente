"""Pruebas de los arreglos de doble carrera, fondos archivados y comparador (fuera del
repositorio del sistema). Se ejecutan en la base temporal de pruebas de Django; los
casos de PDF leen el texto con pypdf, instalado solo en el contenedor temporal."""
import io
from datetime import date

from django.test import override_settings
from rest_framework import status

from fondos.models import CalendarioAcademico, CargaHoraria, FondoTiempo, HistorialFondo, Materia, PerfilUsuario
from fondos.tests.tests_usuarios_auditoria import UsuariosBaseTestCase
from fondos.utils.informe_gestion_pdf import InformeGestionCarreraPDF, datos_informe_gestion
from fondos.utils.pdf_generator import FondoPDFGenerator
from fondos.tests.utilidades import forzar_campos


def calendario(carrera, gestion=2026, periodo='1', inicio=date(2026, 3, 2), fin=date(2026, 7, 10)):
    return CalendarioAcademico.objects.create(
        carrera=carrera, gestion=gestion, periodo=periodo, dias_feriados_gestion=3,
        fecha_inicio=inicio, fecha_fin=fin,
        fecha_inicio_presentacion_proyectos=inicio, fecha_limite_presentacion_proyectos=fin,
    )


def texto_pdf(buffer):
    from pypdf import PdfReader
    return '\n'.join(pagina.extract_text() or '' for pagina in PdfReader(io.BytesIO(buffer.getvalue())).pages)


@override_settings(MEDIA_ROOT='/tmp/test_media_arreglos')
class BaseArreglos(UsuariosBaseTestCase):
    """Sistemas (carrera del fondo) y Civil (otra carrera), con sus Jefes y Directores, un
    docente de Sistemas de tiempo completo y una materia de 4 h/sem en cada carrera."""

    def setUp(self):
        super().setUp()
        self.jefe = self.crear_usuario('jefe_sis', 'jefe_estudios', carrera=self.carrera)
        self.jefe_civil = self.crear_usuario('jefe_civ', 'jefe_estudios', carrera=self.otra_carrera)
        self.director = self.crear_usuario('dir_sis', 'director', carrera=self.carrera, is_staff=True)
        self.usuario_docente = self.crear_usuario('docente_sis', 'docente', carrera=self.carrera, ci='A1')
        self.docente = self.crear_docente('A1', usuario=self.usuario_docente, dedicacion='tiempo_completo')
        PerfilUsuario.objects.filter(user=self.usuario_docente).update(docente=self.docente)
        self.cal = calendario(self.carrera)
        self.cal_civil = calendario(self.otra_carrera)
        self.materia = Materia.objects.create(
            nombre='Programación I', sigla='SIS-101', carrera=self.carrera, semestre=1,
            horas_teoricas=3, horas_practicas=1,
        )
        self.materia_civil = Materia.objects.create(
            nombre='Topografía Aplicada', sigla='CIV-201', carrera=self.otra_carrera, semestre=2,
            horas_teoricas=2, horas_practicas=2,
        )
        self.fondo = FondoTiempo.objects.create(docente=self.docente, carrera=self.carrera, gestion=2026)

    def como(self, usuario):
        self.client.force_authenticate(usuario)
        return self.client

    def clase(self, usuario, materia, cal, dia='lunes', aula='A-1'):
        return self.como(usuario).post('/api/cargas-horarias/', {
            'docente': self.docente.pk, 'materia': materia.pk, 'calendario': cal.pk,
            'categoria': 'academica', 'tipo_actividad': 'clases_aula', 'paralelo': 'A',
            'dia_semana': dia, 'hora_inicio': '08:00', 'hora_fin': '10:00', 'aula': aula, 'horas': 1,
        }, format='json')

    def archivar(self, usuario=None, fondo=None):
        return self.como(usuario or self.jefe).delete(f'/api/fondos-tiempo/{(fondo or self.fondo).pk}/')


class ChoquesConArchivadosTests(BaseArreglos):
    def test_el_fondo_nuevo_reasigna_la_clase_del_archivado_en_su_horario_y_aula(self):
        self.assertEqual(self.clase(self.jefe, self.materia, self.cal).status_code, status.HTTP_201_CREATED)
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado='rechazado')
        self.assertEqual(self.archivar().status_code, status.HTTP_200_OK)
        respuesta = self.como(self.jefe).post('/api/fondos-tiempo/', {
            'docente': self.docente.pk, 'carrera': self.carrera.pk, 'gestion': 2026,
        }, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)

        respuesta = self.clase(self.jefe, self.materia, self.cal)

        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)
        self.assertEqual(CargaHoraria.objects.filter(materia=self.materia).count(), 2)

    def test_los_choques_entre_fondos_vigentes_se_siguen_rechazando(self):
        self.assertEqual(self.clase(self.jefe, self.materia, self.cal).status_code, status.HTTP_201_CREATED)

        respuesta = self.clase(self.jefe_civil, self.materia_civil, self.cal_civil, aula='C-1')

        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Choque de docente', str(respuesta.data))


class ArchivarYRestaurarTests(BaseArreglos):
    def test_solo_se_archivan_fondos_aprobados_finalizados_o_rechazados(self):
        for estado in ['borrador', 'observado', 'presentado_director', 'en_ejecucion', 'informe_presentado']:
            with self.subTest(estado=estado):
                forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado=estado)
                respuesta = self.archivar()
                self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn('No se puede archivar', respuesta.data['error'])
        for estado in ['aprobado_director', 'finalizado', 'rechazado']:
            with self.subTest(estado=estado):
                forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado=estado, archivado=False)
                self.assertEqual(self.archivar().status_code, status.HTTP_200_OK)
                self.assertTrue(FondoTiempo.objects.get(pk=self.fondo.pk).archivado)

    def test_un_fondo_archivado_no_se_vuelve_a_archivar(self):
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado='finalizado', archivado=True)
        self.assertEqual(self.archivar().status_code, status.HTTP_400_BAD_REQUEST)

    def test_archivar_y_restaurar_quedan_en_el_historial_sin_generar_avisos(self):
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado='aprobado_director')
        self.assertEqual(self.archivar().status_code, status.HTTP_200_OK)
        respuesta = self.como(self.director).post(f'/api/fondos-tiempo/{self.fondo.pk}/restaurar/')
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)

        registros = HistorialFondo.objects.filter(fondo_tiempo=self.fondo, tipo_cambio='archivado').order_by('id')
        self.assertEqual(
            [(r.usuario, r.descripcion) for r in registros],
            [(self.jefe, 'Fondo archivado (estado: Aprobado por Director de Carrera).'),
             (self.director, 'Fondo restaurado (estado: Aprobado por Director de Carrera).')],
        )
        # Sin estado anterior ni nuevo: no se confunden con "fondo aprobado" en los avisos.
        self.assertFalse(registros.exclude(estado_anterior='', estado_nuevo='').exists())
        respuesta = self.como(self.usuario_docente).get('/api/fondos-tiempo/novedades/')
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertNotIn('archivado', str(respuesta.data))
        self.assertNotIn('aprobado', str(respuesta.data))

    def test_el_director_no_restaura_un_borrador_ajeno_archivado(self):
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado='borrador', archivado=True)

        respuesta = self.como(self.director).post(f'/api/fondos-tiempo/{self.fondo.pk}/restaurar/')

        self.assertEqual(respuesta.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(FondoTiempo.objects.get(pk=self.fondo.pk).archivado)
        # El Jefe de Estudios de la carrera sí lo restaura.
        respuesta = self.como(self.jefe).post(f'/api/fondos-tiempo/{self.fondo.pk}/restaurar/')
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)

    def test_restaurar_con_fondo_vigente_devuelve_el_motivo_en_error(self):
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado='rechazado', archivado=True)
        FondoTiempo.objects.create(docente=self.docente, carrera=self.carrera, gestion=2026)

        respuesta = self.como(self.jefe).post(f'/api/fondos-tiempo/{self.fondo.pk}/restaurar/')

        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('ya tiene otro Fondo de Tiempo vigente', respuesta.data['error'])

    def test_un_archivado_descarga_el_word_del_informe_y_su_checklist(self):
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado='finalizado', archivado=True)
        cliente = self.como(self.usuario_docente)

        word = cliente.get(f'/api/fondos-tiempo/{self.fondo.pk}/word-informe/')
        checklist = cliente.get(f'/api/fondos-tiempo/{self.fondo.pk}/checklist-salud-pdf/')

        self.assertEqual(word.status_code, status.HTTP_200_OK)
        self.assertEqual(checklist.status_code, status.HTTP_200_OK)
        # Otro docente sigue sin acceso.
        otro = self.crear_usuario('otro_doc', 'docente', carrera=self.carrera, ci='A2')
        PerfilUsuario.objects.filter(user=otro).update(docente=self.crear_docente('A2'))
        self.assertEqual(
            self.como(otro).get(f'/api/fondos-tiempo/{self.fondo.pk}/word-informe/').status_code,
            status.HTTP_404_NOT_FOUND,
        )


class ComparadorTests(BaseArreglos):
    def setUp(self):
        super().setUp()
        calendario(self.carrera, 2025, 'anual', date(2025, 2, 3), date(2025, 12, 5))
        self.fondo_2025 = FondoTiempo.objects.create(docente=self.docente, carrera=self.carrera, gestion=2025)

    def comparar(self, docente, gestion1, gestion2):
        # El comparador es solo para el superusuario, el Director y el Jefe de Estudios.
        return self.como(self.jefe).get(
            f'/api/fondos-tiempo/comparar/?docente={docente}&gestion1={gestion1}&gestion2={gestion2}'
        )

    def test_devuelve_las_gestiones_de_la_mas_antigua_a_la_mas_nueva(self):
        respuesta = self.comparar(self.docente.pk, 2026, 2025)

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertEqual([fondo['gestion'] for fondo in respuesta.data], [2025, 2026])
        self.assertEqual(len(respuesta.data[0]['categorias']), 7)

    def test_parametros_no_numericos_o_faltantes_dan_400(self):
        for docente, gestion1, gestion2 in [('abc', 2025, 2026), (self.docente.pk, 'x', 2026), (self.docente.pk, 2025, '')]:
            with self.subTest(docente=docente, gestion1=gestion1, gestion2=gestion2):
                respuesta = self.comparar(docente, gestion1, gestion2)
                self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn('numéricos', respuesta.data['error'])

    def test_si_falta_una_gestion_devuelve_solo_la_que_hay(self):
        respuesta = self.comparar(self.docente.pk, 2024, 2026)

        self.assertEqual([fondo['gestion'] for fondo in respuesta.data], [2026])


class DocumentosDobleCarreraTests(BaseArreglos):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.clase(self.jefe, self.materia, self.cal).status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            self.clase(self.jefe_civil, self.materia_civil, self.cal_civil, dia='martes', aula='C-1').status_code,
            status.HTTP_201_CREATED,
        )
        self.fondo.refresh_from_db()

    def test_pdf_del_fondo_marca_la_carrera_de_la_materia_ajena_en_el_encabezado(self):
        lineas = texto_pdf(FondoPDFGenerator.generar_reporte_individual(self.fondo)).splitlines()

        self.assertTrue(any(l.startswith('Topografía Aplicada (Civil)') and 'Hrs/Sem' in l for l in lineas), lineas)
        self.assertTrue(any(l.startswith('Programación I .') for l in lineas), lineas)

    def test_informe_de_gestion_lista_aparte_a_los_docentes_de_otras_carreras(self):
        # Presentado: los borradores no entran en el informe de gestión.
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado='presentado_director')
        civil = datos_informe_gestion(self.otra_carrera, 2026)

        self.assertEqual(civil['filas'], [])
        self.assertEqual(civil['total_asignado'], 0)
        self.assertEqual(civil['otras_carreras'], [{
            'docente': self.docente.nombre_completo, 'carrera_fondo': 'Sistemas',
            'materia': 'Topografía Aplicada', 'horas': 80, 'estado': 'Presentado a Director de Carrera',
        }])
        # Sistemas: sus totales siguen incluyendo las 160 h del fondo y no lista "otras carreras".
        sistemas = datos_informe_gestion(self.carrera, 2026)
        self.assertEqual(sistemas['total_asignado'], 160)
        self.assertEqual(sistemas['otras_carreras'], [])

        texto = texto_pdf(InformeGestionCarreraPDF.generar(self.otra_carrera, 2026))
        self.assertIn('Docentes de otras carreras con materias de esta carrera', texto)
        self.assertIn('Topografía Aplicada', texto)
        self.assertNotIn('Docentes de otras carreras', texto_pdf(InformeGestionCarreraPDF.generar(self.carrera, 2026)))

    def test_los_fondos_archivados_no_entran_en_el_bloque_de_otras_carreras(self):
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), archivado=True)

        self.assertEqual(datos_informe_gestion(self.otra_carrera, 2026)['otras_carreras'], [])
