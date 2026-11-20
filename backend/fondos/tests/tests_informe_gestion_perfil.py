"""Pruebas del informe de gestión y del perfil del docente (fuera del repositorio del
sistema): el informe no incluye fondos en borrador y lo indica en la introducción, muestra
la evaluación de un fondo evaluado sin finalizar con "(sin finalizar)", lleva el encabezado
institucional del PDF del fondo y la firma del Director de Carrera; el docente
lee su ficha con antigüedad y vacación según la regla actual, sin poder editarla.
Se ejecutan en la base temporal de pruebas de Django."""
from datetime import date

from rest_framework import status

from fondos.models import DatosLaborales, FondoTiempo, InformeFondo
from fondos.tests.utilidades import forzar_campos
from fondos.utils.informe_gestion_pdf import InformeGestionCarreraPDF, datos_informe_gestion
from fondos.tests.tests_arreglos import BaseArreglos, texto_pdf


class InformeGestionTests(BaseArreglos):
    def setUp(self):
        super().setUp()
        # Un fondo presentado y el de self.docente en borrador.
        self.presentado = FondoTiempo.objects.create(docente=self.crear_docente('P1'), carrera=self.carrera, gestion=2026)
        forzar_campos(FondoTiempo.objects.filter(pk=self.presentado.pk), estado='presentado_director')

    def test_no_incluye_borradores_y_los_cuenta_en_la_introduccion(self):
        datos = datos_informe_gestion(self.carrera, 2026)

        self.assertEqual(len(datos['filas']), 1)
        self.assertEqual(datos['filas'][0]['estado'], 'Presentado a Director de Carrera')
        self.assertEqual(datos['borradores_excluidos'], 1)
        texto = ' '.join(texto_pdf(InformeGestionCarreraPDF.generar(self.carrera, 2026)).split())
        self.assertIn('de 2 fondos de la gestión, 2 quedan sin finalizar, incluido 1 en borrador que no se lista.', texto)
        self.assertNotIn('No se incluye', texto)

    def test_sin_borradores_no_los_menciona(self):
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado='presentado_director')

        self.assertEqual(datos_informe_gestion(self.carrera, 2026)['borradores_excluidos'], 0)
        self.assertNotIn('en borrador', texto_pdf(InformeGestionCarreraPDF.generar(self.carrera, 2026)))

    def test_evaluado_sin_finalizar_muestra_el_resultado_y_sigue_pendiente(self):
        forzar_campos(FondoTiempo.objects.filter(pk=self.presentado.pk), estado='informe_evaluado')
        InformeFondo.objects.create(
            fondo_tiempo=self.presentado, elaborado_por=self.director, tipo='parcial', estado='aprobado', cumplimiento='parcial',
        )

        datos = datos_informe_gestion(self.carrera, 2026)

        self.assertEqual(datos['filas'][0]['evaluacion'], 'Cumplimiento Parcial (sin finalizar)')
        self.assertEqual((datos['pendientes'], datos['es_final']), (2, False))
        forzar_campos(FondoTiempo.objects.filter(pk=self.presentado.pk), estado='finalizado')
        self.assertEqual(datos_informe_gestion(self.carrera, 2026)['filas'][0]['evaluacion'], 'Cumplimiento Parcial')

    def test_encabezado_institucional_y_firma_del_director(self):
        texto = texto_pdf(InformeGestionCarreraPDF.generar(self.carrera, 2026))

        self.assertIn('INFORME DE GESTIÓN', texto)
        self.assertIn('CARRERA DE SISTEMAS', texto)
        self.assertIn('Universidad Autónoma del Beni José Ballivián', texto)
        self.assertIn('Carrera de Sistemas', texto)
        self.assertIn('DIRECTOR(A) DE CARRERA', texto)
        self.assertIn(self.director.username, texto)  # sin nombre completo: su usuario

    def test_lo_descarga_el_director_y_no_el_jefe(self):
        url = f'/api/carreras/{self.carrera.pk}/informe-gestion/?gestion=2026'

        self.assertEqual(self.como(self.director).get(url).status_code, status.HTTP_200_OK)
        self.assertEqual(self.como(self.jefe).get(url).status_code, status.HTTP_403_FORBIDDEN)


class PerfilDelDocenteTests(BaseArreglos):
    def test_lee_su_ficha_con_antiguedad_y_vacacion_segun_la_regla(self):
        hoy = date.today()
        DatosLaborales.objects.filter(pk=self.docente.datos_laborales_id).update(fecha_ingreso=date(hoy.year - 6, 1, 1))

        respuesta = self.como(self.usuario_docente).get(f'/api/docentes/{self.docente.pk}/')

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertEqual(respuesta.data['antiguedad'], 6)
        self.assertEqual(respuesta.data['dias_vacacion'], 20)  # 20 días desde 5 años
        self.assertEqual([v['carrera_nombre'] for v in respuesta.data['vinculos']], ['Sistemas'])

    def test_no_ve_otras_fichas_ni_edita_la_suya(self):
        otro = self.crear_docente('X1')
        cliente = self.como(self.usuario_docente)

        self.assertEqual(cliente.get(f'/api/docentes/{otro.pk}/').status_code, status.HTTP_404_NOT_FOUND)
        respuesta = cliente.patch(f'/api/docentes/{self.docente.pk}/', {'telefono': '70000000'}, format='json')
        self.assertIn(respuesta.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
