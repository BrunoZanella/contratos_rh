# Generated by Django 5.1.6 on 2025-02-25 13:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rh', '0004_alter_candidato_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='candidato',
            name='ultima_tentativa_mensagem',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='candidato',
            name='status',
            field=models.CharField(choices=[('ativo', 'Ativo'), ('aguardando_inicio', 'Aguardando Início'), ('em_andamento', 'Em Andamento'), ('documentos_pendentes', 'Documentos Pendentes'), ('documentos_invalidos', 'Documentos Inválidos'), ('concluido', 'Concluído')], default='ativo', max_length=50),
        ),
    ]
