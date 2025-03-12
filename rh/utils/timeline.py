from django.utils import timezone
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
    # Calcular o tempo desde o último evento relacionado ao mesmo documento
    tempo_desde_evento_anterior = None
    
    if documento:
        # Buscar o último registro para este documento específico
        ultimo_registro = RegistroTempo.objects.filter(
            documento=documento
        ).order_by('-data_hora').first()
    else:
        # Buscar o último registro para este candidato
        ultimo_registro = RegistroTempo.objects.filter(
            candidato=candidato
        ).order_by('-data_hora').first()
    
    if ultimo_registro:
        tempo_desde_evento_anterior = timezone.now() - ultimo_registro.data_hora
    
    # Criar o novo registro
    registro = RegistroTempo.objects.create(
        candidato=candidato,
        documento=documento,
        tipo_evento=tipo_evento,
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
    if not duracao:
        return "N/A"
    
    segundos = duracao.total_seconds()
    
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