"""Pruebas de "Docentes de otra carrera" (fuera del repositorio del sistema): el buscador no
deja fuera a quien tuvo un vínculo inactivo en la carrera del Jefe, informa las gestiones con
fondo vigente, y una carga en un fondo que ya no es editable responde con el estado del
fondo y no con las horas; sin escribir, lista los docentes disponibles de la gestión.
Se ejecutan en la base temporal de pruebas de Django."""
from rest_framework import status

from fondos.models import Docente, DocenteCarrera, FondoTiempo
from fondos.tests.utilidades import forzar_campos
from fondos.tests.tests_arreglos import BaseArreglos


class BuscadorOtraCarreraTests(BaseArreglos):
    def docente_llamado(self, ci, nombre, apellido, carrera=None):
        docente = self.crear_docente(ci, carrera=carrera)  # vínculo activo (Sistemas por defecto)
        Docente.objects.filter(pk=docente.pk).update(nombres=nombre, apellido_paterno=apellido)
        return docente

    def buscar(self, usuario, texto):
        respuesta = self.como(usuario).get('/api/docentes/buscar/', {'q': texto})
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        return {fila['id']: fila for fila in respuesta.data}

    def test_aparece_quien_tuvo_vinculo_inactivo_en_la_carrera_del_jefe(self):
        # Pasó de Civil a Sistemas: vínculo inactivo en Civil y activo en Sistemas.
        trasladado = self.docente_llamado('M1', 'Mixto', 'Trasladado')
        DocenteCarrera.objects.create(
            docente=trasladado, carrera=self.otra_carrera, categoria='catedratico',
            dedicacion='horario_40', activo=False,
        )
        # Con su vínculo activo en Civil sigue sin aparecer para el Jefe de Civil.
        de_civil = self.docente_llamado('M2', 'Mixto', 'Civil', carrera=self.otra_carrera)

        resultados = self.buscar(self.jefe_civil, 'Mixto')

        self.assertIn(trasladado.pk, resultados)
        self.assertNotIn(de_civil.pk, resultados)

    def test_informa_las_gestiones_con_fondo_vigente(self):
        sin_fondo = self.docente_llamado('M3', 'Mixto', 'Sinfondo')

        resultados = self.buscar(self.jefe_civil, 'Rojas')
        self.assertEqual(resultados[self.docente.pk]['gestiones_con_fondo'], [2026])

        resultados = self.buscar(self.jefe_civil, 'Sinfondo')
        self.assertEqual(resultados[sin_fondo.pk]['gestiones_con_fondo'], [])

        # Un fondo archivado no cuenta.
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado='finalizado', archivado=True)
        resultados = self.buscar(self.jefe_civil, 'Rojas')
        self.assertEqual(resultados[self.docente.pk]['gestiones_con_fondo'], [])


class MensajeDeFondoNoEditableTests(BaseArreglos):
    def setUp(self):
        super().setUp()
        # Sin horas libres: cualquier carga superaría las horas efectivas.
        FondoTiempo.objects.filter(pk=self.fondo.pk).update(horas_efectivas=0)

    def test_fondo_presentado_responde_con_su_estado_y_no_con_las_horas(self):
        forzar_campos(FondoTiempo.objects.filter(pk=self.fondo.pk), estado='presentado_director')

        materia_civil = self.clase(self.jefe_civil, self.materia_civil, self.cal_civil, aula='C-1')
        item = self.como(self.jefe).post('/api/cargas-horarias/', {
            'docente': self.docente.pk, 'categoria': 'gestion', 'tipo_actividad': 'reuniones',
            'titulo_actividad': 'Reuniones de la carrera', 'horas': 10, 'gestion': 2026,
        }, format='json')

        for respuesta in (materia_civil, item):
            with self.subTest(respuesta=respuesta.wsgi_request.path):
                self.assertEqual(respuesta.status_code, status.HTTP_403_FORBIDDEN)
                self.assertIn("El fondo está en estado 'Presentado a Director de Carrera'", str(respuesta.data))
                self.assertNotIn('horas efectivas', str(respuesta.data))

    def test_en_borrador_sin_horas_libres_sigue_el_mensaje_de_horas(self):
        respuesta = self.clase(self.jefe_civil, self.materia_civil, self.cal_civil, aula='C-1')

        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('superaría las horas efectivas', str(respuesta.data))


class ListaDisponiblesTests(BaseArreglos):
    """Lista de docentes disponibles sin escribir nada (?gestion=AAAA): activos, de otras
    carreras y con Fondo de Tiempo vigente en esa gestión; ?q filtra la misma lista."""

    def lista(self, usuario, **parametros):
        return self.como(usuario).get('/api/docentes/buscar/', parametros)

    def ids(self, respuesta):
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        return {fila['id'] for fila in respuesta.data}

    def test_sin_escribir_lista_los_de_otra_carrera_con_fondo_en_la_gestion(self):
        # self.docente (Sistemas) tiene su fondo 2026 (BaseArreglos).
        sin_fondo = self.crear_docente('L1')
        archivado = self.crear_docente('L2')
        fondo_archivado = FondoTiempo.objects.create(docente=archivado, carrera=self.carrera, gestion=2026)
        forzar_campos(FondoTiempo.objects.filter(pk=fondo_archivado.pk), estado='finalizado', archivado=True)
        de_civil = self.crear_docente('L3', carrera=self.otra_carrera)
        FondoTiempo.objects.create(docente=de_civil, carrera=self.otra_carrera, gestion=2026)

        disponibles = self.ids(self.lista(self.jefe_civil, gestion=2026))

        self.assertEqual(disponibles, {self.docente.pk})
        self.assertNotIn(sin_fondo.pk, disponibles)
        self.assertEqual(self.ids(self.lista(self.jefe_civil, gestion=2025)), set())
        # El buscador filtra la misma lista.
        self.assertEqual(self.ids(self.lista(self.jefe_civil, gestion=2026, q='Rojas')), {self.docente.pk})
        self.assertEqual(self.ids(self.lista(self.jefe_civil, gestion=2026, q='Zzz')), set())

    def test_gestion_invalida_y_solo_jefatura(self):
        self.assertEqual(self.lista(self.jefe_civil, gestion='abc').status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.lista(self.usuario_docente, gestion=2026).status_code, status.HTTP_403_FORBIDDEN)
