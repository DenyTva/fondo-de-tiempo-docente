"""Pruebas de terminar la designación de un Jefe de Estudios (fuera del repositorio del
sistema): con uso operativo, deja el cargo y conserva su rol de docente, su cuenta y su
historial; no pasa a un rol que no tenía; y el Director no designa a quien ya tiene datos.
Designar Jefe a un docente de tiempo horario de su carrera cuenta su vínculo una sola vez (antes
se contaba por cada rol y se rechazaba con "excede su fondo de tiempo contractual (20/10)").
Se ejecutan en la base temporal de pruebas de Django."""
from django.contrib.auth.models import User
from rest_framework import status

from fondos.models import AsignacionCarrera, FondoTiempo, HistorialFondo, PerfilUsuario
from fondos.serializers import usuario_tiene_uso_de_rol
from fondos.tests.tests_usuarios_auditoria import UsuariosBaseTestCase, con_resolucion_jefe
from fondos.tests.tests_arreglos import BaseArreglos


class BaseDesignaciones(BaseArreglos):
    def setUp(self):
        super().setUp()
        # Uso operativo del Jefe: crea un fondo (queda en el historial como su autor).
        otro_docente = self.crear_docente('B1')
        respuesta = self.como(self.jefe).post('/api/fondos-tiempo/', {
            'docente': otro_docente.pk, 'carrera': self.carrera.pk, 'gestion': 2026,
        }, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)
        self.fondo_del_jefe = FondoTiempo.objects.get(pk=respuesta.data['id'])
        self.assertTrue(usuario_tiene_uso_de_rol(self.jefe, PerfilUsuario.objects.get(user=self.jefe)))

    def asignacion(self, usuario, rol):
        return AsignacionCarrera.objects.get(user=usuario, carrera=self.carrera, rol=rol)

    def nuevo_jefe(self, usuario_que_designa):
        datos = self.datos_usuario('nuevo_jefe', 'jefe_estudios', self.carrera, 'NJ-1', asignaciones=[])
        return self.como(usuario_que_designa).post('/api/usuarios/', con_resolucion_jefe(datos), format='multipart')


class TerminarDesignacionTests(BaseDesignaciones):
    def setUp(self):
        super().setUp()
        # El Jefe también es docente de la carrera (rol principal: Jefe de Estudios).
        self.ficha_jefe = self.crear_docente('J1', usuario=self.jefe, dedicacion='tiempo_completo')
        AsignacionCarrera.objects.create(user=self.jefe, carrera=self.carrera, rol='docente', docente=self.ficha_jefe)
        PerfilUsuario.objects.filter(user=self.jefe).update(docente=self.ficha_jefe)

    def test_el_jefe_docente_deja_el_cargo_y_se_designa_otro_con_el_historial_intacto(self):
        historial_antes = list(HistorialFondo.objects.filter(usuario=self.jefe).values_list('id', 'tipo_cambio'))
        # Con el cargo ocupado no se designa a otro.
        self.assertEqual(self.nuevo_jefe(self.director).status_code, status.HTTP_400_BAD_REQUEST)

        respuesta = self.como(self.director).patch(f'/api/usuarios/{self.jefe.pk}/', {
            'rol': 'docente', 'carrera': self.carrera.pk, 'asignaciones': [], 'docente': self.ficha_jefe.pk,
        }, format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        self.jefe.refresh_from_db()
        self.assertTrue(self.jefe.is_active)
        self.assertEqual(PerfilUsuario.objects.get(user=self.jefe).rol, 'docente')
        # El cargo no se borra: queda inactivo y su historial dice quién lo dio de baja.
        cargo = self.asignacion(self.jefe, 'jefe_estudios')
        self.assertFalse(cargo.activo)
        ultimo = cargo.history.order_by('-history_date', '-history_id').first()
        self.assertEqual((ultimo.activo, ultimo.history_user), (False, self.director))
        self.assertTrue(self.asignacion(self.jefe, 'docente').activo)
        # Sus fondos y su historial siguen como estaban.
        self.assertEqual(list(HistorialFondo.objects.filter(usuario=self.jefe).values_list('id', 'tipo_cambio')), historial_antes)
        self.assertTrue(FondoTiempo.objects.filter(pk=self.fondo_del_jefe.pk).exists())

        respuesta = self.nuevo_jefe(self.director)

        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED, respuesta.data)
        jefes_activos = AsignacionCarrera.objects.filter(carrera=self.carrera, rol='jefe_estudios', activo=True)
        self.assertEqual(list(jefes_activos.values_list('user__username', flat=True)), ['nuevo_jefe'])


class RolNuevoConUsoTests(BaseDesignaciones):
    def test_un_jefe_con_uso_no_pasa_a_director(self):
        # Director de la carrera inactivo: el cargo único no es lo que lo impide.
        User.objects.filter(pk=self.director.pk).update(is_active=False)

        respuesta = self.como(self.superuser).patch(f'/api/usuarios/{self.jefe.pk}/', {
            'rol': 'director', 'carrera': self.carrera.pk, 'asignaciones': [],
        }, format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('ya tiene registros asociados', str(respuesta.data['rol']))
        self.assertEqual(PerfilUsuario.objects.get(user=self.jefe).rol, 'jefe_estudios')
        self.assertTrue(self.asignacion(self.jefe, 'jefe_estudios').activo)
        self.assertFalse(AsignacionCarrera.objects.filter(user=self.jefe, rol='director').exists())


class DirectorDesignaConDatosTests(BaseDesignaciones):
    def test_el_director_no_designa_jefe_a_quien_tiene_datos(self):
        # Cargo libre: el Jefe actual ya terminó su designación.
        AsignacionCarrera.objects.filter(user=self.jefe, rol='jefe_estudios').update(activo=False)
        # El docente tiene su fondo de tiempo: datos registrados.
        cuerpo = con_resolucion_jefe({
            'rol': 'docente', 'carrera': self.carrera.pk, 'docente': self.docente.pk,
            'asignaciones': [{'rol': 'jefe_estudios', 'carrera': self.carrera.pk}],
        })

        respuesta = self.como(self.director).patch(f'/api/usuarios/{self.usuario_docente.pk}/', cuerpo, format='multipart')

        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Solo el superusuario puede agregar asignaciones', str(respuesta.data['asignaciones']))
        self.assertFalse(AsignacionCarrera.objects.filter(user=self.usuario_docente, rol='jefe_estudios').exists())


class DesignarJefeADocenteTests(UsuariosBaseTestCase):
    """Editar usuario: el Director designa Jefe de Estudios a un docente de su carrera, que conserva
    su rol docente. Las horas de su vínculo se cuentan una vez por carrera, no una por rol."""

    def setUp(self):
        super().setUp()
        self.director = self.crear_usuario('dir_sis', 'director', carrera=self.carrera, is_staff=True)
        self.usuario = self.crear_usuario('docente_horario', 'docente', carrera=self.carrera, ci='DH-1')
        self.ficha = self.crear_docente('DH-1', usuario=self.usuario, dedicacion='horario_40')
        PerfilUsuario.objects.filter(user=self.usuario).update(docente=self.ficha)
        AsignacionCarrera.objects.filter(user=self.usuario, rol='docente').update(docente=self.ficha)

    def editar(self, actor, carrera_jefe, carrera_docente):
        """Lo que envía la ventana Editar usuario al designar Jefe y conservar el rol docente."""
        datos = {
            'username': self.usuario.username, 'email': 'docente.horario@uabjb.edu.bo',
            'first_name': 'Ana', 'last_name': 'Rojas', 'ci': 'DH-1', 'is_active': True,
            'rol': 'jefe_estudios', 'carrera': carrera_jefe.pk,
            'asignaciones': [{'rol': 'docente', 'carrera': carrera_docente.pk, 'docente': self.ficha.pk}],
        }
        return self.como(actor).put(f'/api/usuarios/{self.usuario.pk}/', con_resolucion_jefe(datos), format='multipart')

    def como(self, usuario):
        self.client.force_authenticate(usuario)
        return self.client

    def test_el_director_designa_jefe_a_un_docente_de_horario_de_su_carrera(self):
        respuesta = self.editar(self.director, self.carrera, self.carrera)

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK, respuesta.data)
        activos = set(AsignacionCarrera.objects.filter(user=self.usuario, activo=True).values_list('rol', flat=True))
        self.assertEqual(activos, {'jefe_estudios', 'docente'})
        self.assertEqual(PerfilUsuario.objects.get(user=self.usuario).rol, 'jefe_estudios')

    def test_con_dos_carreras_se_suman_las_horas_de_cada_una(self):
        # Por la API no se llega aquí: un usuario tiene todos sus roles en una carrera y un docente
        # un solo vínculo (DocenteCarrera.clean). Con datos de versiones anteriores (dos vínculos),
        # la validación sigue sumando las horas de cada carrera: 40 + 20 = 60 frente a 40.
        from rest_framework import serializers as drf_serializers
        from fondos.models import DocenteCarrera
        from fondos.serializers import _validar_fondo_tiempo_contractual_doble_rol
        DocenteCarrera.objects.filter(docente=self.ficha, carrera=self.carrera).update(dedicacion='tiempo_completo')
        DocenteCarrera.objects.bulk_create([DocenteCarrera(
            docente=self.ficha, carrera=self.otra_carrera, categoria='catedratico', dedicacion='medio_tiempo',
        )])
        bloques = [
            {'rol': 'jefe_estudios', 'carrera': self.otra_carrera.pk},
            {'rol': 'docente', 'carrera': self.carrera.pk, 'docente': self.ficha.pk},
        ]

        with self.assertRaises(drf_serializers.ValidationError) as error:
            _validar_fondo_tiempo_contractual_doble_rol(bloques, docente_por_defecto=self.ficha)
        self.assertIn('(60/40 horas)', str(error.exception.detail))
        # La misma carrera dos veces cuenta una sola vez.
        _validar_fondo_tiempo_contractual_doble_rol(
            [{'rol': 'jefe_estudios', 'carrera': self.carrera.pk}, {'rol': 'docente', 'carrera': self.carrera.pk}],
            docente_por_defecto=self.ficha,
        )
