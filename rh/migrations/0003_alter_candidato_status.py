# Generated by Django 5.1.6 on 2025-02-24 12:06

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rh', '0002_alter_candidato_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='candidato',
            name='status',
            field=models.CharField(choices=[('em_andamento', 'Em Andamento'), ('documentos_pendentes', 'Documentos Pendentes'), ('documentos_invalidos', 'Documentos Inválidos'), ('concluido', 'Concluído')], default='em_andamento', max_length=50),
        ),
    ]
