"""Pruebas de Mi cuenta (fuera del repositorio del sistema): GET /api/mi-cuenta/ es de solo
lectura y devuelve solo los datos del usuario autenticado (último ingreso, designaciones y,
para el docente, su fondo de la gestión actual, las carreras donde dicta y los próximos
plazos). Se ejecutan en la base temporal de pruebas de Django."""
from datetime import date

from django.utils import timezone
from rest_framework import status

from fondos.mi_cuenta import datos_mi_cuenta
from fondos.models import CalendarioAcademico, FondoTiempo
from fondos.tests.utilidades import forzar_campos
from fondos.tests.tests_arreglos import BaseArreglos

URL = '/api/mi-cuenta/'


class MiCuentaTests(BaseArreglos):
    def setUp(self):
        super().setUp()
        CalendarioAcademico.objects.filter(pk=self.cal.pk).update(
            fecha_limite_programas_analiticos=date(2026, 3, 13), fecha_limite_presentacion_proyectos=date(2026, 3, 20),
        )
        CalendarioAcademico.objects.filter(pk=self.cal_civil.pk).update(
            fecha_limite_programas_analiticos=date(2026, 3, 27), fecha_limite_presentacion_proyectos=date(2026, 3, 10),
        )

    def test_sin_sesion_no_responde_y_es_solo_lectura(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(URL).status_code, status.HTTP_401_UNAUTHORIZED)

        cliente = self.como(self.usuario_docente)
        for metodo in ('post', 'patch', 'put', 'delete'):
            self.assertEqual(getattr(cliente, metodo)(URL, {}, format='json').status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_docente_ve_su_fondo_y_las_carreras_donde_dicta(self):
        self.assertEqual(self.clase(self.jefe, self.materia, self.cal).status_code, status.HTTP_201_CREATED)
        respuesta = self.clase(self.jefe_civil, self.materia_civil, self.cal_civil, dia='martes', aula='C-1')
        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)

        docente = datos_mi_cuenta(self.usuario_docente, hoy=date(2026, 3, 1))['docente']

        self.assertEqual(docente['fondo_actual']['id'], self.fondo.pk)
        self.assertEqual([(c['carrera'], c['propia'], [m['sigla'] for m in c['materias']]) for c in docente['carreras_donde_dicta']], [
            ('Sistemas', True, ['SIS-101']),
            ('Civil', False, ['CIV-201']),
        ])

    def test_proximos_plazos_solo_los_que_no_vencieron(self):
        self.clase(self.jefe, self.materia, self.cal)
        self.clase(self.jefe_civil, self.materia_civil, self.cal_civil, dia='martes', aula='C-1')

        plazos = datos_mi_cuenta(self.usuario_docente, hoy=date(2026, 3, 15))['docente']['proximos_plazos']

        # Vencidos: programas de Sistemas (13/03) y proyectos de Civil (10/03); quedan
        # proyectos de Sistemas (20/03) y programas de Civil (27/03).
        self.assertEqual([(p['plazo'], p['fecha']) for p in plazos], [
            ('proyectos', '2026-03-20'),
            ('programas analíticos', '2026-03-27'),
        ])
        self.assertEqual(plazos[1]['calendario'], 'Primer Semestre 2026 · Civil')

    def test_fondo_archivado_no_es_el_actual(self):
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), archivado=True)

        docente = datos_mi_cuenta(self.usuario_docente, hoy=date(2026, 3, 1))['docente']

        self.assertIsNone(docente['fondo_actual'])
        self.assertEqual(docente['carreras_donde_dicta'], [])
        # Sin fondo, los plazos salen de los calendarios de la carrera de su vínculo.
        self.assertEqual([p['fecha'] for p in docente['proximos_plazos']], ['2026-03-13', '2026-03-20'])

    def test_cada_usuario_ve_solo_lo_suyo(self):
        FondoTiempo.objects.filter(pk=self.fondo.pk).update(gestion=timezone.localdate().year)

        del_docente = self.como(self.usuario_docente).get(URL, {'user': self.jefe.pk, 'docente': 999})
        self.assertEqual(del_docente.status_code, status.HTTP_200_OK)
        self.assertEqual(del_docente.data['docente']['id'], self.docente.pk)
        self.assertEqual(del_docente.data['docente']['fondo_actual']['id'], self.fondo.pk)
        self.assertEqual(del_docente.data['designaciones'], [])

        del_jefe = self.como(self.jefe).get(URL, {'user': self.usuario_docente.pk})
        self.assertIsNone(del_jefe.data['docente'])
        self.assertEqual([(d['rol'], d['carrera_nombre']) for d in del_jefe.data['designaciones']], [('jefe_estudios', 'Sistemas')])

    def test_designacion_con_fecha_y_sin_resolucion(self):
        designacion = self.como(self.director).get(URL).data['designaciones'][0]

        self.assertEqual(designacion['rol_display'], 'Director de Carrera')
        self.assertEqual(designacion['desde'], timezone.localdate().isoformat())
        self.assertIsNone(designacion['resolucion_consejo'])

    def test_ultimo_ingreso_es_el_del_inicio_de_sesion(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post('/api/token/', {'username': 'docente_sis', 'password': 'x'}, format='json').status_code, status.HTTP_200_OK)
        self.usuario_docente.refresh_from_db()

        respuesta = self.como(self.usuario_docente).get(URL)

        self.assertIsNotNone(self.usuario_docente.last_login)
        self.assertEqual(respuesta.data['ultimo_ingreso'], self.usuario_docente.last_login)
