"""Pruebas de caja negra del Capítulo IV (fuera del repositorio del sistema).

Se ejecutan contra la API en la base temporal de pruebas de Django; no tocan la base local.
Los casos de documentos (CN-24 y CN-25) leen el PDF con pypdf, que no está en el sistema: se
instala solo en el contenedor temporal de la prueba (ver PENDIENTES.md).
"""
import io
import zipfile
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status

from fondos.models import (
    CalendarioAcademico, CargaHoraria, Docente, FondoTiempo, InformeFondo, Materia, PerfilUsuario,
    ProgramaAnalitico,
)
from fondos.tests.tests_usuarios_auditoria import UsuariosBaseTestCase
from fondos.tests.utilidades import forzar_campos

PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n'


def calendario(carrera, gestion, periodo, inicio, fin, dias_feriado=3):
    return CalendarioAcademico.objects.create(
        carrera=carrera, gestion=gestion, periodo=periodo, dias_feriados_gestion=dias_feriado,
        fecha_inicio=inicio, fecha_fin=fin,
        fecha_inicio_presentacion_proyectos=inicio, fecha_limite_presentacion_proyectos=fin,
    )


@override_settings(MEDIA_ROOT='/tmp/test_media_cap4')
class BaseCap4(UsuariosBaseTestCase):
    """Carrera, Jefe, Director, docente de 10 h/sem, materia de 4 h/sem y calendarios 2026 y 2027."""

    def setUp(self):
        super().setUp()
        self.jefe = self.crear_usuario('jefe_prueba', 'jefe_estudios', carrera=self.carrera)
        self.director = self.crear_usuario('director_prueba', 'director', carrera=self.carrera, is_staff=True)
        self.usuario_docente = self.crear_usuario('docente_prueba', 'docente', carrera=self.carrera, ci='P1')
        self.docente = self.crear_docente('P1', usuario=self.usuario_docente, dedicacion='horario_40')  # 10 h/sem
        PerfilUsuario.objects.filter(user=self.usuario_docente).update(docente=self.docente)
        self.materia = Materia.objects.create(
            nombre='Materia de prueba', sigla='PRU-101', carrera=self.carrera, semestre=1,
            horas_teoricas=3, horas_practicas=1,  # 4 h/sem
        )
        self.cal_semestre = calendario(self.carrera, 2026, '1', date(2026, 3, 2), date(2026, 7, 10))
        self.cal_anual = calendario(self.carrera, 2027, 'anual', date(2027, 2, 1), date(2027, 12, 10))
        self.fondo = FondoTiempo.objects.create(docente=self.docente, carrera=self.carrera, gestion=2026)
        self.fondo_anual = FondoTiempo.objects.create(docente=self.docente, carrera=self.carrera, gestion=2027)

    def _clase(self, cal):
        # La carga la registra el Jefe de Estudios de la carrera (el superusuario no la modifica).
        self.client.force_authenticate(self.jefe)
        return self.client.post('/api/cargas-horarias/', {
            'docente': self.docente.pk, 'materia': self.materia.pk, 'calendario': cal.pk,
            'categoria': 'academica', 'tipo_actividad': 'clases_aula', 'paralelo': 'A',
            'dia_semana': 'lunes', 'hora_inicio': '08:00', 'hora_fin': '12:00', 'aula': 'A-1', 'horas': 1,
        }, format='json')

    def _presentar(self, usuario, fondo=None):
        self.client.force_authenticate(usuario)
        return self.client.patch(f'/api/fondos-tiempo/{(fondo or self.fondo).pk}/presentar-a-director/', {}, format='json')

    def _completar(self, fondo, con_programa=True):
        """Clase de 4 h/sem más una actividad de investigación que completa las horas efectivas."""
        respuesta = self._clase(self.cal_semestre)
        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)
        fondo.refresh_from_db()
        CargaHoraria.objects.create(
            fondo=fondo, docente=self.docente, categoria='investigacion', tipo_actividad='participacion_iic_cis',
            titulo_actividad='Ítem', horas=int(fondo.horas_efectivas) - 80,
        )
        if con_programa:
            ProgramaAnalitico.objects.create(
                fondo=fondo, materia=self.materia, calendario=self.cal_semestre,
                archivo=SimpleUploadedFile('programa.pdf', PDF, content_type='application/pdf'),
            )


@override_settings(MEDIA_ROOT='/tmp/test_media_cap4')
class CajaNegraCap4(BaseCap4):
    def test_cn01_clases_semestral_por_20_semanas(self):
        respuesta = self._clase(self.cal_semestre)
        print('\nCN01', respuesta.status_code, respuesta.data.get('horas'))
        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)
        self.assertEqual(respuesta.data['horas'], 80)

    def test_cn02_clases_anual_por_40_semanas(self):
        respuesta = self._clase(self.cal_anual)
        print('\nCN02', respuesta.status_code, respuesta.data.get('horas'))
        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)
        self.assertEqual(respuesta.data['horas'], 160)

    def test_cn03_presentar_con_suma_distinta(self):
        self._clase(self.cal_semestre)
        ProgramaAnalitico.objects.create(
            fondo=self.fondo, materia=self.materia, calendario=self.cal_semestre,
            archivo=SimpleUploadedFile('programa.pdf', PDF, content_type='application/pdf'),
        )
        respuesta = self._presentar(self.jefe)
        self.fondo.refresh_from_db()
        print('\nCN03', self.fondo.horas_efectivas, respuesta.status_code, respuesta.data, self.fondo.estado)
        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('exactamente', respuesta.data['error'])
        self.assertEqual(self.fondo.estado, 'borrador')

    def test_cn04_presentar_sin_programa_analitico(self):
        self._completar(self.fondo, con_programa=False)
        respuesta = self._presentar(self.jefe)
        self.fondo.refresh_from_db()
        print('\nCN04', respuesta.status_code, respuesta.data, self.fondo.estado)
        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('programa analítico', respuesta.data['error'])
        self.assertEqual(self.fondo.estado, 'borrador')

    def test_cn05_presentar_completo(self):
        self._completar(self.fondo)
        respuesta = self._presentar(self.jefe)
        self.fondo.refresh_from_db()
        print('\nCN05', self.fondo.total_asignado, self.fondo.horas_efectivas, respuesta.status_code, self.fondo.estado)
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        self.assertEqual(self.fondo.estado, 'presentado_director')

    def test_cn06_docente_no_presenta_su_fondo(self):
        self._completar(self.fondo)
        respuesta = self._presentar(self.usuario_docente)
        self.fondo.refresh_from_db()
        print('\nCN06', respuesta.status_code, self.fondo.estado)
        self.assertEqual(respuesta.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.fondo.estado, 'borrador')

    def test_cn07_aprobar_un_fondo_en_ejecucion(self):
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado='en_ejecucion')
        self.client.force_authenticate(self.director)
        respuesta = self.client.post(f'/api/fondos-tiempo/{self.fondo.pk}/aprobar/', {}, format='json')
        self.fondo.refresh_from_db()
        print('\nCN07', respuesta.status_code, respuesta.data, self.fondo.estado)
        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.fondo.estado, 'en_ejecucion')

    def test_cn08_horas_del_fondo(self):
        print('\nCN08', self.fondo.horas_semana, self.fondo.contrato_horas, self.fondo.horas_vacacion,
              self.fondo.horas_feriados, self.fondo.horas_efectivas)
        self.assertEqual(self.fondo.horas_semana, Decimal('10'))
        self.assertEqual(self.fondo.contrato_horas, 520)


def logo_png():
    from PIL import Image
    salida = io.BytesIO()
    Image.new('RGB', (64, 64), '#1e3a8a').save(salida, format='PNG')
    return SimpleUploadedFile('logo.png', salida.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT='/tmp/test_media_cap4')
class DocumentosCap4(BaseCap4):
    """CN-24 y CN-25: el fondo en PDF y el informe en Word se generan con los datos del fondo."""

    def setUp(self):
        super().setUp()
        # Los documentos usan el nombre de la cuenta de usuario y de la ficha.
        Docente.objects.filter(pk=self.docente.pk).update(nombres='Docente', apellido_paterno='Prueba Uno')
        User.objects.filter(pk=self.usuario_docente.pk).update(first_name='Docente', last_name='Prueba Uno')
        User.objects.filter(pk=self.director.pk).update(first_name='Director', last_name='De Prueba')
        self.carrera.resolucion_ministerial = 'HCU-PRUEBA-001/2020'
        self.carrera.fecha_resolucion = date(2020, 1, 15)
        self.carrera.set_logo_carrera(logo_png())
        self.carrera.save()
        director = self.crear_docente('P-DIR', usuario=self.director)
        Docente.objects.filter(pk=director.pk).update(nombres='Director', apellido_paterno='De Prueba')
        PerfilUsuario.objects.filter(user=self.director).update(docente=director)
        self._completar(self.fondo)

    def test_cn24_pdf_del_fondo(self):
        from pypdf import PdfReader
        self.client.force_authenticate(self.jefe)
        respuesta = self.client.get(f'/api/fondos-tiempo/{self.fondo.pk}/pdf-oficial/')
        contenido = b''.join(respuesta.streaming_content)
        texto = ' '.join(pagina.extract_text() for pagina in PdfReader(io.BytesIO(contenido)).pages)
        print('\nCN24', respuesta.status_code, respuesta['Content-Type'], len(contenido), contenido[:5],
              'nombre' if 'Docente Prueba Uno' in texto else 'SIN NOMBRE', 'gestion' if '2026' in texto else 'SIN GESTION')
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')
        self.assertTrue(contenido.startswith(b'%PDF'))
        self.assertGreater(len(contenido), 1000)
        self.assertIn('Docente Prueba Uno', texto)
        self.assertIn('2026', texto)

    def test_cn25_word_del_informe(self):
        from docx import Document
        InformeFondo.objects.create(
            fondo_tiempo=self.fondo, elaborado_por=self.usuario_docente, tipo='parcial',
            seccion_academica='<p>Se dictaron las asignaturas planificadas.</p>',
        )
        self.client.force_authenticate(self.usuario_docente)
        respuesta = self.client.get(f'/api/fondos-tiempo/{self.fondo.pk}/word-informe/')
        contenido = b''.join(respuesta.streaming_content)
        documento = Document(io.BytesIO(contenido))
        partes = [p.text for p in documento.paragraphs]
        partes += [celda.text for tabla in documento.tables for fila in tabla.rows for celda in fila.cells]
        texto = ' '.join(partes)
        print('\nCN25', respuesta.status_code, respuesta['Content-Type'], len(contenido),
              zipfile.is_zipfile(io.BytesIO(contenido)),
              'nombre' if 'Docente Prueba Uno' in texto else 'SIN NOMBRE', 'gestion' if '2026' in texto else 'SIN GESTION')
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertEqual(
            respuesta['Content-Type'], 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(contenido)))
        self.assertGreater(len(contenido), 1000)
        self.assertIn('Docente Prueba Uno', texto)
        self.assertIn('2026', texto)
        self.assertIn('Se dictaron las asignaturas planificadas.', texto)
