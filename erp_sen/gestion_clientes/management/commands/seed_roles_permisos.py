from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils.text import slugify

from gestion_clientes.models import Rol, Permiso, RolPermiso, UsuarioRol


class Command(BaseCommand):
    help = "Crea roles y permisos base del ERP SEN y asigna roles iniciales."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email-superuser",
            type=str,
            default="",
            help="Email del usuario al que se le asignará Super Usuario (opcional)."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        # =========================
        # 1) Definir permisos (codigo)
        # =========================
        permisos_base = [
            # Inicio / navegación
            ("ver_inicio", "Ver inicio"),
            ("ver_dashboard", "Ver dashboard"),

            # Estudiantes
            ("listar_estudiantes", "Listar estudiantes"),
            ("ver_detalle_estudiante", "Ver detalle de estudiante"),
            ("buscar_estudiante", "Buscar estudiante (sin listados)"),

            # Contratos
            ("crear_contrato", "Crear contrato"),

            # CxC / pagos
            ("ver_cartera", "Ver cartera (CxC)"),
            ("registrar_pago", "Registrar pago"),
            ("anular_pago", "Anular pago"),

            # Ingresos
            ("registrar_ingreso", "Registrar ingreso"),
            ("ver_reporte_ingresos", "Ver reporte de ingresos"),

            # Seguridad / administración
            ("admin_roles_permisos", "Administrar roles y permisos"),
            ("admin_usuarios_roles", "Administrar usuarios y roles"),
        ]

        # =========================
        # 2) Crear permisos
        # =========================
        perm_objs = {}
        for code, nombre in permisos_base:
            obj, _ = Permiso.objects.get_or_create(codigo=code, defaults={"nombre": nombre})
            # Si ya existía pero nombre cambió, lo mantenemos alineado
            if obj.nombre != nombre:
                obj.nombre = nombre
                obj.save(update_fields=["nombre"])
            perm_objs[code] = obj
        # =========================
        # 3) Definir roles y permisos por rol
        # =========================
        # NOTA: El modelo Rol tiene un campo `codigo` (único). En MySQL,
        # si intentamos crear roles sin codigo, Django insertará '' y chocará
        # con el unique constraint. Por eso generamos un codigo estable.
        def rol_code_from_nombre(nombre: str) -> str:
            base = slugify(nombre)  # e.g. "super-usuario"
            base = base.replace("-", "_")
            return (base or "rol")[:50]

        roles_base = [
            (
                "super_usuario",
                "Super Usuario",
                [
                    "ver_inicio",
                    "ver_dashboard",
                    "listar_estudiantes",
                    "ver_detalle_estudiante",
                    "buscar_estudiante",
                    "crear_contrato",
                    "ver_cartera",
                    "registrar_pago",
                    "anular_pago",
                    "registrar_ingreso",
                    "ver_reporte_ingresos",
                    "admin_roles_permisos",
                    "admin_usuarios_roles",
                ],
            ),
            (
                "ceo",
                "CEO",
                [
                    "ver_inicio",
                    "ver_dashboard",
                    "listar_estudiantes",
                    "ver_detalle_estudiante",
                    "buscar_estudiante",
                    "ver_cartera",
                    "ver_reporte_ingresos",
                ],
            ),
            (
                "cfo",
                "CFO",
                [
                    "ver_inicio",
                    "ver_dashboard",
                    "listar_estudiantes",
                    "ver_detalle_estudiante",
                    "buscar_estudiante",
                    "ver_cartera",
                    "registrar_pago",
                    "anular_pago",
                    "registrar_ingreso",
                    "ver_reporte_ingresos",
                ],
            ),
            (
                "coordinador_sede",
                "Coordinador de sede",
                [
                    "ver_inicio",
                    "ver_dashboard",
                    "listar_estudiantes",
                    "ver_detalle_estudiante",
                    "buscar_estudiante",
                    "crear_contrato",
                    "ver_cartera",
                    "registrar_pago",
                    "ver_reporte_ingresos",
                ],
            ),
            (
                "secretaria",
                "Secretaria",
                [
                    "ver_inicio",
                    "listar_estudiantes",
                    "ver_detalle_estudiante",
                    "buscar_estudiante",
                    "crear_contrato",
                    "ver_cartera",
                    "registrar_pago",
                    "registrar_ingreso",
                ],
            ),
        ]

        rol_objs = {}
        for rol_codigo, rol_nombre, permisos in roles_base:
            # Si por alguna razón quieres derivarlo del nombre, queda listo:
            rol_codigo = (rol_codigo or rol_code_from_nombre(rol_nombre))

            rol, created = Rol.objects.get_or_create(
                codigo=rol_codigo,
                defaults={"nombre": rol_nombre}
            )
            # Si ya existía pero el nombre cambió, lo mantenemos alineado
            if rol.nombre != rol_nombre:
                rol.nombre = rol_nombre
                rol.save(update_fields=["nombre"])

            rol_objs[rol_nombre] = rol

            # Enlace RolPermiso (sin duplicar por constraint)
            for code in permisos:
                RolPermiso.objects.get_or_create(rol=rol, permiso=perm_objs[code])

        # Nota: este comando NO elimina permisos/roles antiguos; solo crea/actualiza los definidos aquí.
        # =========================
        # 4) Asignar Super Usuario a un usuario por email (opcional)
        # =========================
        email = (options.get("email_superuser") or "").strip().lower()
        if email:
            User = get_user_model()
            try:
                user = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f"No existe usuario con email {email}. Se creó roles/permisos pero no se asignó Super Usuario."
                ))
            else:
                UsuarioRol.objects.get_or_create(
                    usuario=user,
                    rol=rol_objs["Super Usuario"],
                    defaults={"activo": True},
                )
                self.stdout.write(self.style.SUCCESS(
                    f"Asignado rol 'Super Usuario' a {user.email}"
                ))

        self.stdout.write(self.style.SUCCESS("Seed roles/permisos finalizado OK."))