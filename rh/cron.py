from django.utils import timezone
from datetime import timedelta
from .models import Candidato
from .views import enviar_mensagem_boas_vindas

def tentar_reenviar_mensagens():
    # Pega todos os candidatos ativos que não receberam mensagem ou cuja última tentativa foi há mais de 1 hora
    uma_hora_atras = timezone.now() - timedelta(hours=1)
    candidatos = Candidato.objects.filter(
        status='ativo',
        mensagem_enviada=False,
        ultima_tentativa_mensagem__lte=uma_hora_atras
    )

    for candidato in candidatos:
        try:
            enviar_mensagem_boas_vindas(candidato)
            candidato.status = 'em_andamento'
            candidato.mensagem_enviada = True
            candidato.save()
            print(f"Mensagem enviada com sucesso para {candidato.nome}")
        except Exception as e:
            candidato.ultima_tentativa_mensagem = timezone.now()
            candidato.save()
            print(f"Erro ao enviar mensagem para {candidato.nome}: {str(e)}")