"""Pruebas de la gestión del calendario académico (fuera del repositorio del sistema): la
gestión es el año de sus fechas. Antes se guardó un calendario de gestión 2024 con fechas
del 02/02/2026 al 27/11/2026. Se ejecutan en la base temporal de pruebas de Django."""
from datetime import date

from django.core.exceptions import ValidationError
from rest_framework import status

from fondos.models import CalendarioAcademico
from fondos.tests.tests_usuarios_auditoria import UsuariosBaseTestCase


def datos_calendario(carrera, gestion, inicio, fin, periodo='anual'):
    return {
        'carrera': carrera.pk, 'gestion': gestion, 'periodo': periodo,
        'fecha_inicio': inicio.isoformat(), 'fecha_fin': fin.isoformat(),
        'fecha_inicio_presentacion_proyectos': inicio.isoformat(),
        'fecha_limite_presentacion_proyectos': date(inicio.year, 3, 31).isoformat(),
        'fecha_limite_programas_analiticos': date(inicio.year, 3, 14).isoformat(),
        'dias_feriados_gestion': 14,
    }


class GestionDelCalendarioTests(UsuariosBaseTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.superuser)

    def test_no_se_crea_un_calendario_con_fechas_de_otro_anio(self):
        respuesta = self.client.post('/api/calendarios/', datos_calendario(
            self.carrera, 2024, date(2026, 2, 2), date(2026, 11, 27),
        ), format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            str(respuesta.data['fecha_inicio'][0]),
            'La fecha de inicio (02/02/2026) no es de la gestión 2024: las fechas del calendario deben estar dentro del año 2024.',
        )
        self.assertIn('La fecha de finalización (27/11/2026) no es de la gestión 2024', str(respuesta.data['fecha_fin'][0]))
        self.assertFalse(CalendarioAcademico.objects.exists())

    def test_tampoco_si_solo_una_fecha_es_de_otro_anio(self):
        respuesta = self.client.post('/api/calendarios/', datos_calendario(
            self.carrera, 2026, date(2026, 2, 2), date(2027, 1, 15),
        ), format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(set(respuesta.data), {'fecha_fin'})

    def test_con_gestion_y_fechas_del_mismo_anio_se_crea(self):
        respuesta = self.client.post('/api/calendarios/', datos_calendario(
            self.carrera, 2026, date(2026, 2, 2), date(2026, 11, 27),
        ), format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)

    def test_al_editar_no_se_cambia_la_gestion_a_otro_anio_y_si_se_corrige(self):
        bien = CalendarioAcademico.objects.create(**{
            **datos_calendario(self.otra_carrera, 2026, date(2026, 2, 2), date(2026, 11, 27)),
            'carrera': self.otra_carrera,
        })
        respuesta = self.client.patch(f'/api/calendarios/{bien.pk}/', {'gestion': 2024}, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(CalendarioAcademico.objects.get(pk=bien.pk).gestion, 2026)

        # Un calendario guardado antes de la validación (como el de Civil) se corrige editando la gestión.
        mal = CalendarioAcademico.objects.create(**{
            **datos_calendario(self.carrera, 2024, date(2026, 2, 2), date(2026, 11, 27)),
            'carrera': self.carrera,
        })
        respuesta = self.client.patch(f'/api/calendarios/{mal.pk}/', {'gestion': 2026}, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        self.assertEqual(CalendarioAcademico.objects.get(pk=mal.pk).gestion, 2026)

    def test_clean_del_modelo_valida_la_gestion(self):
        datos = {**datos_calendario(self.carrera, 2024, date(2026, 2, 2), date(2026, 11, 27)), 'carrera': self.carrera}
        calendario = CalendarioAcademico(**datos)

        with self.assertRaises(ValidationError) as error:
            calendario.full_clean()
        self.assertEqual(set(error.exception.message_dict), {'fecha_inicio', 'fecha_fin'})

        calendario.gestion = 2026
        calendario.full_clean()
