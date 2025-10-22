import logging
from django.conf import settings
from rh.models import AvaliacaoPeriodoExperiencia

logger = logging.getLogger(__name__)

def cria_pesquisa_satisfacao(avaliacao):
   """
   Recebe solicitação de avaliação via webhook e gera formulário de avaliação.
   """
   
   try:
      avaliacao_existent = AvaliacaoPeriodoExperiencia.objects.filter(
         
      )
      url_pesquisa = f"{settings.SITE_URL}/avaliacao/{avaliacao.token}/"

   except Exception as e:
      print(e)

