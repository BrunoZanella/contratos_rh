# rh/utils/timeline.py
from django.utils import timezone
from datetime import timedelta # Importar timedelta explicitamente
from ..models import RegistroTempo

def registrar_evento(candidato, tipo_evento, documento=None, status_anterior=None, status_novo=None, observacoes=None):
    """
    Registra um evento na timeline do candidato
    
    Args:
        candidato: Objeto Candidato
        tipo_evento: Tipo do evento (conforme TIPO_EVENTO_CHOICES)
        documento: Objeto Documento (opcional)
        status_anterior: Status anterior (opcional)
        status_novo: Novo status (opcional)
        observacoes: Observações adicionais (opcional)
    
    Returns:
        Objeto RegistroTempo criado
    """
    # Captura o tempo atual uma única vez para consistência
    current_time = timezone.now() 

    tempo_desde_evento_anterior = None
    
    # Define o filtro base para buscar o último registro
    filter_kwargs = {'candidato': candidato}
    if documento:
        filter_kwargs['documento'] = documento
    
    # Buscar o último registro para este documento/candidato
    # Excluir registros muito recentes para evitar auto-referência ou race conditions
    # A exclusão é feita para garantir que o "último registro" seja realmente um evento *anterior*
    ultimo_registro = RegistroTempo.objects.filter(
        **filter_kwargs
    ).exclude(
        data_hora__gte=current_time - timedelta(microseconds=1) # Exclui registros no mesmo instante ou futuro
    ).order_by('-data_hora').first()
    
    if ultimo_registro:
        # Calcula a duração. Garante que a duração seja sempre não negativa.
        # Se o tempo do evento anterior for igual ou posterior ao tempo atual,
        # a duração será 0 segundos.
        tempo_desde_evento_anterior = max(timedelta(seconds=0), current_time - ultimo_registro.data_hora)
    
    # Criar o novo registro
    registro = RegistroTempo.objects.create(
        candidato=candidato,
        documento=documento,
        tipo_evento=tipo_evento,
        data_hora=current_time, # Usa o tempo capturado para o novo registro
        status_anterior=status_anterior,
        status_novo=status_novo,
        tempo_desde_evento_anterior=tempo_desde_evento_anterior,
        observacoes=observacoes
    )
    
    return registro

def formatar_duracao(duracao):
    """
    Formata uma duração para exibição amigável
    
    Args:
        duracao: objeto timedelta
    
    Returns:
        String formatada (ex: "2 dias, 3 horas, 45 minutos")
    """
    # Adiciona uma verificação explícita para booleanos ou outros tipos inesperados
    if not duracao or isinstance(duracao, bool):
        return "N/A"
    
    segundos = duracao.total_seconds()
    
    # Garante que não haja formatação para durações negativas, embora a função registrar_evento já deva evitar isso.
    if segundos < 0:
        return "N/A (Tempo Inválido)" # Ou "0 segundos" se preferir
    
    # Menos de um minuto
    if segundos < 60:
        return f"{int(segundos)} segundos"
    
    # Menos de uma hora
    if segundos < 3600:
        minutos = int(segundos / 60)
        segundos_restantes = int(segundos % 60)
        if segundos_restantes == 0:
            return f"{minutos} minutos"
        return f"{minutos}min {segundos_restantes}s"
    
    # Menos de um dia
    if segundos < 86400:
        horas = int(segundos / 3600)
        minutos = int((segundos % 3600) / 60)
        if minutos == 0:
            return f"{horas} horas"
        return f"{horas}h {minutos}min"
    
    # Mais de um dia
    dias = int(segundos / 86400)
    horas = int((segundos % 86400) / 3600)
    if horas == 0:
        return f"{dias} dias"
    return f"{dias} dias, {horas}h"
