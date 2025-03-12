from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from rh.models import Candidato
from rh.views import enviar_mensagem_boas_vindas

class Command(BaseCommand):
    help = 'Tenta reenviar mensagens de boas-vindas para candidatos ativos'

    def handle(self, *args, **options):
        # Pega todos os candidatos ativos que não receberam mensagem ou cuja última tentativa foi há mais de 1 hora
        uma_hora_atras = timezone.now() - timedelta(hours=1)
        candidatos = Candidato.objects.filter(
            status='ativo',
            mensagem_enviada=False
        ).filter(
            ultima_tentativa_mensagem__isnull=True
        ) | Candidato.objects.filter(
            status='ativo',
            mensagem_enviada=False,
            ultima_tentativa_mensagem__lte=uma_hora_atras
        )

        count_success = 0
        count_error = 0

        for candidato in candidatos:
            try:
                self.stdout.write(f"Tentando enviar mensagem para {candidato.nome}...")
                enviar_mensagem_boas_vindas(candidato)
                candidato.status = 'em_andamento'
                candidato.mensagem_enviada = True
                candidato.save()
                count_success += 1
                self.stdout.write(self.style.SUCCESS(f"Mensagem enviada com sucesso para {candidato.nome}"))
            except Exception as e:
                candidato.ultima_tentativa_mensagem = timezone.now()
                candidato.save()
                count_error += 1
                self.stdout.write(self.style.ERROR(f"Erro ao enviar mensagem para {candidato.nome}: {str(e)}"))
        
        self.stdout.write(self.style.SUCCESS(f"Processo concluído. Sucessos: {count_success}, Erros: {count_error}"))