from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ("gestion_clientes", "0021_alter_acudiente_options_alter_contrato_options_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterModelTable(name="acudiente", table="gestion_clientes_acudiente"),
                migrations.AlterModelTable(name="cuota", table="gestion_clientes_cuota"),
                migrations.AlterModelTable(name="estudiante", table="gestion_clientes_estudiante"),
                migrations.AlterModelTable(name="horario", table="gestion_clientes_horario"),
                migrations.AlterModelTable(name="nivel", table="gestion_clientes_nivel"),
                migrations.AlterModelTable(name="pago", table="gestion_clientes_pago"),
                migrations.AlterModelTable(name="pagoaplicacion", table="gestion_clientes_pagoaplicacion"),
                migrations.AlterModelTable(name="perfil", table="gestion_clientes_perfil"),
                migrations.AlterModelTable(name="sede", table="gestion_clientes_sede"),
            ],
        ),
    ]