"""Pruebas de la revisión con un docente de doble carrera (fuera del repositorio del sistema):
plazos vencidos según los Arts. 15, 18 y 20, carrera escrita igual en el informe y en el
nombre del calendario, historial sin borradores ajenos para el Director y ?otra_carrera=1.
Se ejecutan en la base temporal de pruebas de Django."""
from datetime import date

from rest_framework import status

from fondos.models import CalendarioAcademico, Carrera, FondoTiempo
from fondos.tests.utilidades import forzar_campos
from fondos.utils.informe_texto import asignaturas_dictadas_html
from fondos.tests.tests_arreglos import BaseArreglos, calendario

PRESENTACION = date(2026, 10, 15)


def filas(datos):
    return datos.get('results', datos) if isinstance(datos, dict) else datos


class BaseRevision(BaseArreglos):
    def setUp(self):
        super().setUp()
        # Carrera registrada en minúscula, como "civil" en la base local.
        Carrera.objects.filter(pk=self.otra_carrera.pk).update(nombre='civil')
        CalendarioAcademico.objects.filter(pk=self.cal.pk).update(
            fecha_limite_programas_analiticos=date(2026, 3, 13), fecha_limite_presentacion_proyectos=date(2026, 3, 20),
        )
        self.cal_2 = calendario(self.carrera, periodo='2', inicio=date(2026, 8, 3), fin=date(2026, 12, 11))
        CalendarioAcademico.objects.filter(pk=self.cal_2.pk).update(
            fecha_limite_programas_analiticos=date(2026, 8, 14), fecha_limite_presentacion_proyectos=date(2026, 8, 21),
        )
        CalendarioAcademico.objects.filter(pk=self.cal_civil.pk).update(
            fecha_limite_programas_analiticos=date(2026, 3, 27), fecha_limite_presentacion_proyectos=date(2026, 4, 3),
        )

    def vencidos(self):
        fondo = FondoTiempo.objects.get(pk=self.fondo.pk)
        return [(v['plazo'], v['calendario'], v['fecha_limite']) for v in fondo.plazos_vencidos(PRESENTACION)]

    def proyecto(self):
        respuesta = self.como(self.jefe).post('/api/cargas-horarias/', {
            'docente': self.docente.pk, 'categoria': 'extension_universitaria', 'tipo_actividad': 'proyectos_extension',
            'titulo_actividad': 'Proyecto de extensión', 'horas': 24, 'gestion': 2026,
        }, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)


class PlazosVencidosTests(BaseRevision):
    def test_sin_proyectos_solo_el_programa_de_los_calendarios_con_clases(self):
        self.assertEqual(self.clase(self.jefe, self.materia, self.cal).status_code, status.HTTP_201_CREATED)

        # Ni el plazo de proyectos ni el Segundo Semestre, donde no tiene materias.
        self.assertEqual(self.vencidos(), [('programas analíticos', 'Primer Semestre 2026', '2026-03-13')])

    def test_con_proyecto_agrega_el_plazo_de_proyectos_del_primer_calendario(self):
        self.assertEqual(self.clase(self.jefe, self.materia, self.cal).status_code, status.HTTP_201_CREATED)
        self.proyecto()

        self.assertEqual(self.vencidos(), [
            ('programas analíticos', 'Primer Semestre 2026', '2026-03-13'),
            ('proyectos', 'Primer Semestre 2026', '2026-03-20'),
        ])

    def test_proyecto_sin_materias_solo_el_plazo_de_proyectos(self):
        self.proyecto()

        self.assertEqual(self.vencidos(), [('proyectos', 'Primer Semestre 2026', '2026-03-20')])

    def test_materia_de_otra_carrera_suma_el_programa_de_su_calendario(self):
        self.assertEqual(self.clase(self.jefe, self.materia, self.cal).status_code, status.HTTP_201_CREATED)
        respuesta = self.clase(self.jefe_civil, self.materia_civil, self.cal_civil, dia='martes', aula='C-1')
        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)

        self.assertCountEqual(self.vencidos(), [
            ('programas analíticos', 'Primer Semestre 2026', '2026-03-13'),
            ('programas analíticos', 'Primer Semestre 2026 · Civil', '2026-03-27'),
        ])

    def test_presentado_a_tiempo_no_hay_vencidos(self):
        self.assertEqual(self.clase(self.jefe, self.materia, self.cal).status_code, status.HTTP_201_CREATED)
        self.proyecto()
        fondo = FondoTiempo.objects.get(pk=self.fondo.pk)

        self.assertEqual(fondo.plazos_vencidos(date(2026, 3, 10)), [])


class CarreraEscritaIgualTests(BaseRevision):
    def test_el_informe_escribe_la_carrera_como_el_pdf(self):
        self.clase(self.jefe_civil, self.materia_civil, self.cal_civil, dia='martes', aula='C-1')

        texto = asignaturas_dictadas_html(FondoTiempo.objects.get(pk=self.fondo.pk))

        self.assertIn('<b>Topografía Aplicada</b> (Civil)', texto)
        self.assertNotIn('(civil)', texto)


class HistorialSinBorradoresAjenosTests(BaseRevision):
    def historial(self, usuario, fondo):
        respuesta = self.como(usuario).get('/api/historial/', {'fondo_tiempo': fondo.pk})
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        return filas(respuesta.data)

    def test_el_director_no_ve_el_historial_de_un_borrador_ajeno(self):
        otro = self.crear_docente('B1')
        respuesta = self.como(self.jefe).post('/api/fondos-tiempo/', {
            'docente': otro.pk, 'carrera': self.carrera.pk, 'gestion': 2026,
        }, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)
        fondo = FondoTiempo.objects.get(pk=respuesta.data['id'])

        self.assertEqual(self.historial(self.director, fondo), [])
        self.assertEqual([r['tipo_cambio'] for r in self.historial(self.jefe, fondo)], ['creacion'])

        # Presentado, el Director ya lo ve (con el nombre de usuario de respaldo).
        forzar_campos(FondoTiempo.objects.filter(pk=fondo.pk), estado='presentado_director')
        registros = self.historial(self.director, fondo)
        self.assertEqual([r['tipo_cambio'] for r in registros], ['creacion'])
        self.assertEqual(registros[0]['usuario_username'], self.jefe.username)


class OtraCarreraTests(BaseRevision):
    def test_lista_las_materias_asignadas_a_docentes_de_otra_carrera(self):
        self.assertEqual(self.clase(self.jefe, self.materia, self.cal).status_code, status.HTTP_201_CREATED)
        respuesta = self.clase(self.jefe_civil, self.materia_civil, self.cal_civil, dia='martes', aula='C-1')
        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)
        de_civil = respuesta.data['id']

        def lista(usuario):
            respuesta = self.como(usuario).get('/api/cargas-horarias/', {'otra_carrera': 1})
            self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
            return filas(respuesta.data)

        civil = lista(self.jefe_civil)
        self.assertEqual([c['id'] for c in civil], [de_civil])
        self.assertEqual(civil[0]['docente_nombre'], self.docente.nombre_completo)
        # Sistemas no asignó materias a otras carreras: la de Civil en su fondo no cuenta.
        self.assertEqual(lista(self.jefe), [])
        self.assertEqual([c['id'] for c in lista(self.superuser)], [de_civil])
