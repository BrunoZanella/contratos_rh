from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Candidato, Documento
from .forms import CandidatoForm, DocumentoForm
from .whatsapp import enviar_mensagem_whatsapp
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from django.utils import timezone
from django.views.decorators.http import require_http_methods
import logging

from django.core.files.base import ContentFile
import base64
import os

from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import AuthenticationForm
from .forms import LoginForm, RegisterForm

from django.db.models import Count, Avg, F, ExpressionWrapper, fields, Q, Sum
from django.db.models.functions import TruncMonth
from datetime import timedelta
from dateutil.relativedelta import relativedelta

@login_required
def estatisticas(request):
    """
    View para exibir estatísticas e gráficos com dados reais utilizando a timeline
    para maior precisão e insights mais detalhados
    """
    from django.db.models import Count, Avg, F, ExpressionWrapper, fields, Q, Sum, Min, Max, StdDev
    from django.db.models.functions import TruncMonth, TruncDay, TruncWeek, ExtractWeekDay
    from datetime import timedelta
    from dateutil.relativedelta import relativedelta
    import json
    from .models import Candidato, Documento, RegistroTempo
    
    # Função auxiliar para formatar tempo
    def format_time(days):
        if days is None:
            return "N/A"
        total_minutes = days * 24 * 60
        if total_minutes < 60:
            return f"{int(total_minutes)} minutos"
        elif total_minutes < 1440:  # menos de 24 horas
            hours = int(total_minutes / 60)
            minutes = int(total_minutes % 60)
            return f"{hours} horas" if minutes == 0 else f"{hours}h {minutes}min"
        else:
            return f"{int(days)} dias"
    
    # Dados para o gráfico de pizza - Status dos Candidatos
    status_counts = Candidato.objects.values('status').annotate(
        total=Count('id')
    ).order_by('status')
    
    status_labels = []
    status_data = []
    status_colors = {
        'ativo': '#3B82F6',
        'aguardando_inicio': '#60A5FA',
        'em_andamento': '#93C5FD',
        'documentos_pendentes': '#F59E0B',
        'documentos_invalidos': '#EF4444',
        'concluido': '#10B981',
    }
    status_colors_array = []
    
    for item in status_counts:
        status_display = dict(Candidato.STATUS_CHOICES).get(item['status'], item['status'])
        status_labels.append(status_display)
        status_data.append(item['total'])
        status_colors_array.append(status_colors.get(item['status'], '#6B7280'))
    
    # NOVO: Usar a timeline para calcular tempos médios mais precisos por etapa
    # Tempo médio entre solicitação e recebimento de documentos
    tempo_solicitacao_recebimento = RegistroTempo.objects.filter(
        tipo_evento__in=['documento_solicitado', 'documento_recebido'],
        documento__isnull=False
    ).values('documento').annotate(
        min_data=Min('data_hora'),
        max_data=Max('data_hora')
    ).filter(
        min_data__lt=F('max_data')
    ).annotate(
        tempo=ExpressionWrapper(
            F('max_data') - F('min_data'),
            output_field=fields.DurationField()
        )
    ).aggregate(
        avg_tempo=Avg('tempo'),
        max_tempo=Max('tempo'),
        min_tempo=Min('tempo'),
        std_tempo=StdDev('tempo')
    )
    
    # Tempo médio entre recebimento e validação de documentos
    tempo_recebimento_validacao = RegistroTempo.objects.filter(
        tipo_evento__in=['documento_recebido', 'documento_validado'],
        documento__isnull=False
    ).values('documento').annotate(
        min_data=Min('data_hora'),
        max_data=Max('data_hora')
    ).filter(
        min_data__lt=F('max_data')
    ).annotate(
        tempo=ExpressionWrapper(
            F('max_data') - F('min_data'),
            output_field=fields.DurationField()
        )
    ).aggregate(
        avg_tempo=Avg('tempo'),
        max_tempo=Max('tempo'),
        min_tempo=Min('tempo'),
        std_tempo=StdDev('tempo')
    )
    
    # Tempo médio entre cadastro e conclusão do processo
    tempo_cadastro_conclusao = RegistroTempo.objects.filter(
        tipo_evento__in=['candidato_cadastrado', 'processo_concluido']
    ).values('candidato').annotate(
        min_data=Min('data_hora'),
        max_data=Max('data_hora')
    ).filter(
        min_data__lt=F('max_data')
    ).annotate(
        tempo=ExpressionWrapper(
            F('max_data') - F('min_data'),
            output_field=fields.DurationField()
        )
    ).aggregate(
        avg_tempo=Avg('tempo'),
        max_tempo=Max('tempo'),
        min_tempo=Min('tempo'),
        std_tempo=StdDev('tempo')
    )
    
    # Etapas do processo com tempos médios
    etapas_labels = ['Cadastro', 'Envio de Docs', 'Validação', 'Conclusão']
    
    etapas_data = [
        0,  # Cadastro é instantâneo
        tempo_solicitacao_recebimento['avg_tempo'].total_seconds() / 86400 if tempo_solicitacao_recebimento['avg_tempo'] else None,
        tempo_recebimento_validacao['avg_tempo'].total_seconds() / 86400 if tempo_recebimento_validacao['avg_tempo'] else None,
        tempo_cadastro_conclusao['avg_tempo'].total_seconds() / 86400 if tempo_cadastro_conclusao['avg_tempo'] else None,
    ]
    
    # Dados para variabilidade de tempo por etapa (novo gráfico)
    etapas_std_dev = [
        0,  # Cadastro é instantâneo
        tempo_solicitacao_recebimento['std_tempo'].total_seconds() / 86400 if tempo_solicitacao_recebimento['std_tempo'] else None,
        tempo_recebimento_validacao['std_tempo'].total_seconds() / 86400 if tempo_recebimento_validacao['std_tempo'] else None,
        tempo_cadastro_conclusao['std_tempo'].total_seconds() / 86400 if tempo_cadastro_conclusao['std_tempo'] else None,
    ]
    
    etapas_min = [
        0,  # Cadastro é instantâneo
        tempo_solicitacao_recebimento['min_tempo'].total_seconds() / 86400 if tempo_solicitacao_recebimento['min_tempo'] else None,
        tempo_recebimento_validacao['min_tempo'].total_seconds() / 86400 if tempo_recebimento_validacao['min_tempo'] else None,
        tempo_cadastro_conclusao['min_tempo'].total_seconds() / 86400 if tempo_cadastro_conclusao['min_tempo'] else None,
    ]
    
    etapas_max = [
        0,  # Cadastro é instantâneo
        tempo_solicitacao_recebimento['max_tempo'].total_seconds() / 86400 if tempo_solicitacao_recebimento['max_tempo'] else None,
        tempo_recebimento_validacao['max_tempo'].total_seconds() / 86400 if tempo_recebimento_validacao['max_tempo'] else None,
        tempo_cadastro_conclusao['max_tempo'].total_seconds() / 86400 if tempo_cadastro_conclusao['max_tempo'] else None,
    ]
    
    etapas_data_formatada = [format_time(dias) if dias is not None else "N/A" for dias in etapas_data]
    etapas_min_formatada = [format_time(dias) if dias is not None else "N/A" for dias in etapas_min]
    etapas_max_formatada = [format_time(dias) if dias is not None else "N/A" for dias in etapas_max]
    
    # Remover etapas sem dados
    valid_indices = [i for i, data in enumerate(etapas_data) if data is not None]
    etapas_labels = [etapas_labels[i] for i in valid_indices]
    etapas_data = [etapas_data[i] for i in valid_indices]
    etapas_std_dev = [etapas_std_dev[i] for i in valid_indices]
    etapas_min = [etapas_min[i] for i in valid_indices]
    etapas_max = [etapas_max[i] for i in valid_indices]
    
    # NOVO: Análise de gargalos - etapas que mais demoram
    etapas_gargalos = list(zip(etapas_labels, etapas_data))
    etapas_gargalos.sort(key=lambda x: x[1] if x[1] is not None else 0, reverse=True)
    gargalos_labels = [item[0] for item in etapas_gargalos[:3]]  # Top 3 gargalos
    gargalos_data = [item[1] for item in etapas_gargalos[:3]]
    
    # Dados para o gráfico de linha - Tendência de Cadastros
    primeiro_cadastro = Candidato.objects.order_by('data_cadastro').first()
    if primeiro_cadastro:
        data_inicio = primeiro_cadastro.data_cadastro.date()
    else:
        data_inicio = timezone.now().date()
    
    data_fim = timezone.now().date()
    
    # NOVO: Usar a timeline para tendências mais precisas
    cadastros_por_mes = RegistroTempo.objects.filter(
        tipo_evento='candidato_cadastrado',
        data_hora__date__gte=data_inicio,
        data_hora__date__lte=data_fim
    ).annotate(
        mes=TruncMonth('data_hora')
    ).values('mes').annotate(
        total=Count('id')
    ).order_by('mes')
    
    meses_completos = []
    dados_meses = []
    
    mes_atual = data_inicio.replace(day=1)
    while mes_atual <= data_fim:
        meses_completos.append(mes_atual.strftime('%b/%Y'))
        dados_meses.append(0)
        mes_atual += relativedelta(months=1)
    
    for item in cadastros_por_mes:
        mes_idx = meses_completos.index(item['mes'].strftime('%b/%Y'))
        dados_meses[mes_idx] = item['total']
    
    # NOVO: Tendência de conclusões por mês
    conclusoes_por_mes = RegistroTempo.objects.filter(
        tipo_evento='processo_concluido',
        data_hora__date__gte=data_inicio,
        data_hora__date__lte=data_fim
    ).annotate(
        mes=TruncMonth('data_hora')
    ).values('mes').annotate(
        total=Count('id')
    ).order_by('mes')
    
    dados_conclusoes = [0] * len(meses_completos)
    
    for item in conclusoes_por_mes:
        mes_idx = meses_completos.index(item['mes'].strftime('%b/%Y'))
        dados_conclusoes[mes_idx] = item['total']
    
    # NOVO: Taxa de conversão por mês (conclusões / cadastros)
    taxa_conversao_mensal = []
    for cadastros, conclusoes in zip(dados_meses, dados_conclusoes):
        if cadastros > 0:
            taxa_conversao_mensal.append(round((conclusoes / cadastros) * 100, 1))
        else:
            taxa_conversao_mensal.append(0)
    
    # Dados para o gráfico de linha - Tempo Médio de Conclusão por mês
    # CORRIGIDO: Não podemos usar Avg em um campo que já é um agregado
    tempo_medio_por_mes_raw = RegistroTempo.objects.filter(
        tipo_evento='processo_concluido',
        data_hora__date__gte=data_inicio,
        data_hora__date__lte=data_fim
    ).annotate(
        mes=TruncMonth('data_hora')
    ).values('mes', 'candidato', 'tempo_desde_evento_anterior')
    
    # Agora vamos processar manualmente para calcular a média por mês
    tempo_por_mes = {}
    for item in tempo_medio_por_mes_raw:
        mes_str = item['mes'].strftime('%b/%Y')
        if mes_str not in tempo_por_mes:
            tempo_por_mes[mes_str] = []
        
        if item['tempo_desde_evento_anterior']:
            tempo_por_mes[mes_str].append(item['tempo_desde_evento_anterior'].total_seconds())
    
    dados_tempo_medio = [None] * len(meses_completos)
    
    for i, mes in enumerate(meses_completos):
        if mes in tempo_por_mes and tempo_por_mes[mes]:
            # Calcular a média manualmente
            media_segundos = sum(tempo_por_mes[mes]) / len(tempo_por_mes[mes])
            dados_tempo_medio[i] = media_segundos / 86400  # Converter para dias
    
    # Estatísticas gerais
    total_candidatos = Candidato.objects.count()
    candidatos_concluidos = Candidato.objects.filter(status='concluido').count()
    taxa_conclusao = (candidatos_concluidos / total_candidatos * 100) if total_candidatos > 0 else 0
    
    docs_pendentes = Documento.objects.filter(status__in=['pendente', 'recebido']).count()
    docs_invalidos = Documento.objects.filter(status='invalido').count()
    
    # NOVO: Usar a timeline para tempo médio total mais preciso
    # CORRIGIDO: Não podemos usar Avg em um campo que já é um agregado
    tempo_total_raw = RegistroTempo.objects.filter(
        tipo_evento='processo_concluido'
    ).values('candidato', 'tempo_desde_evento_anterior')
    
    # Processar manualmente
    tempo_total_por_candidato = {}
    for item in tempo_total_raw:
        candidato_id = item['candidato']
        if candidato_id not in tempo_total_por_candidato:
            tempo_total_por_candidato[candidato_id] = 0
        
        if item['tempo_desde_evento_anterior']:
            tempo_total_por_candidato[candidato_id] += item['tempo_desde_evento_anterior'].total_seconds()
    
    # Calcular estatísticas
    tempos_totais = list(tempo_total_por_candidato.values())
    
    tempo_medio_total_segundos = sum(tempos_totais) / len(tempos_totais) if tempos_totais else None
    tempo_min_total_segundos = min(tempos_totais) if tempos_totais else None
    tempo_max_total_segundos = max(tempos_totais) if tempos_totais else None
    
    tempo_medio_total_dias = tempo_medio_total_segundos / 86400 if tempo_medio_total_segundos is not None else None
    tempo_min_total_dias = tempo_min_total_segundos / 86400 if tempo_min_total_segundos is not None else None
    tempo_max_total_dias = tempo_max_total_segundos / 86400 if tempo_max_total_segundos is not None else None
    
    tempo_medio_total_formatado = format_time(tempo_medio_total_dias)
    tempo_min_total_formatado = format_time(tempo_min_total_dias)
    tempo_max_total_formatado = format_time(tempo_max_total_dias)
    
    # NOVO: Taxa de rejeição de documentos mais precisa usando a timeline
    eventos_invalidacao = RegistroTempo.objects.filter(tipo_evento='documento_invalidado').count()
    eventos_validacao = RegistroTempo.objects.filter(tipo_evento='documento_validado').count()
    
    taxa_rejeicao_docs = (eventos_invalidacao / (eventos_invalidacao + eventos_validacao) * 100) if (eventos_invalidacao + eventos_validacao) > 0 else 0
    
    # NOVO: Tempo médio até primeira submissão usando a timeline
    tempo_primeira_submissao = RegistroTempo.objects.filter(
        tipo_evento='documento_recebido'
    ).values('candidato').annotate(
        primeira_submissao=Min('data_hora')
    ).annotate(
        tempo=ExpressionWrapper(
            F('primeira_submissao') - F('candidato__data_cadastro'),
            output_field=fields.DurationField()
        )
    ).aggregate(
        avg_tempo=Avg('tempo'),
        min_tempo=Min('tempo'),
        max_tempo=Max('tempo')
    )
    
    tempo_medio_primeira_submissao_dias = tempo_primeira_submissao['avg_tempo'].total_seconds() / 86400 if tempo_primeira_submissao['avg_tempo'] else None
    tempo_medio_primeira_submissao_formatado = format_time(tempo_medio_primeira_submissao_dias)
    
    # NOVO: Estatísticas de retrabalho - documentos que foram invalidados mais de uma vez
    retrabalho_docs = RegistroTempo.objects.filter(
        tipo_evento='documento_invalidado'
    ).values('documento').annotate(
        invalidacoes=Count('id')
    ).filter(invalidacoes__gt=1)
    
    total_docs_retrabalho = retrabalho_docs.count()
    media_invalidacoes = retrabalho_docs.aggregate(avg=Avg('invalidacoes'))['avg'] if retrabalho_docs.exists() else 0
    
    # NOVO: Documentos mais problemáticos (com mais invalidações)
    docs_problematicos = RegistroTempo.objects.filter(
        tipo_evento='documento_invalidado'
    ).values('documento__tipo').annotate(
        invalidacoes=Count('id')
    ).order_by('-invalidacoes')[:5]
    
    docs_problematicos_labels = [dict(Documento.TIPO_CHOICES).get(item['documento__tipo'], item['documento__tipo']) for item in docs_problematicos]
    docs_problematicos_data = [item['invalidacoes'] for item in docs_problematicos]
    
    # Novas estatísticas
    candidatos_ultimos_30_dias = RegistroTempo.objects.filter(
        tipo_evento='candidato_cadastrado',
        data_hora__gte=timezone.now() - timedelta(days=30)
    ).values('candidato').distinct().count()
    
    # NOVO: Candidatos concluídos nos últimos 30 dias
    concluidos_ultimos_30_dias = RegistroTempo.objects.filter(
        tipo_evento='processo_concluido',
        data_hora__gte=timezone.now() - timedelta(days=30)
    ).values('candidato').distinct().count()
    
    taxa_conversao_30_dias = (concluidos_ultimos_30_dias / candidatos_ultimos_30_dias * 100) if candidatos_ultimos_30_dias > 0 else 0
    
    # NOVO: Tempo médio por tipo de documento usando a timeline
    # CORRIGIDO: Não podemos usar Avg em um campo que já é um agregado
    tempo_por_tipo_raw = RegistroTempo.objects.filter(
        tipo_evento='documento_validado',
        documento__isnull=False
    ).values('documento__tipo', 'tempo_desde_evento_anterior')
    
    # Processar manualmente
    tempo_por_tipo = {}
    for item in tempo_por_tipo_raw:
        tipo = item['documento__tipo']
        if tipo not in tempo_por_tipo:
            tempo_por_tipo[tipo] = []
        
        if item['tempo_desde_evento_anterior']:
            tempo_por_tipo[tipo].append(item['tempo_desde_evento_anterior'].total_seconds())
    
    tempo_medio_tipo_labels = []
    tempo_medio_tipo_data = []
    
    for tipo, tempos in tempo_por_tipo.items():
        if tempos:
            tipo_display = dict(Documento.TIPO_CHOICES).get(tipo, tipo)
            tempo_medio_tipo_labels.append(tipo_display)
            tempo_medio_tipo_data.append(sum(tempos) / len(tempos) / 86400)  # Média em dias
    
    tempo_medio_tipo_data_formatada = [format_time(dias) for dias in tempo_medio_tipo_data]
    
    # NOVO: Distribuição de documentos por tipo
    documentos_por_tipo = Documento.objects.values('tipo').annotate(
        total=Count('id')
    ).order_by('-total')
    
    tipos_documentos_labels = [dict(Documento.TIPO_CHOICES).get(item['tipo'], item['tipo']) for item in documentos_por_tipo]
    tipos_documentos_data = [item['total'] for item in documentos_por_tipo]
    
# NOVO: Análise de eficiência por dia da semana
    eficiencia_dia_semana = RegistroTempo.objects.filter(
        tipo_evento='documento_validado'
    ).annotate(
        dia_semana=ExtractWeekDay('data_hora')
    ).values('dia_semana').annotate(
        validacoes=Count('id')
    ).order_by('dia_semana')
    
    # CORRIGIDO: Calcular o tempo médio por dia da semana manualmente
    tempo_por_dia_semana_raw = RegistroTempo.objects.filter(
        tipo_evento='documento_validado'
    ).annotate(
        dia_semana=ExtractWeekDay('data_hora')
    ).values('dia_semana', 'tempo_desde_evento_anterior')
    
    tempo_por_dia = {}
    for item in tempo_por_dia_semana_raw:
        dia = item['dia_semana']
        if dia not in tempo_por_dia:
            tempo_por_dia[dia] = []
        
        if item['tempo_desde_evento_anterior']:
            tempo_por_dia[dia].append(item['tempo_desde_evento_anterior'].total_seconds())
    
    # Definir os dias da semana na ordem correta (começando na segunda)
    dias_semana = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
    dias_semana_data = [0] * 7
    tempo_medio_dia_semana = [0] * 7
    
    # Detectar qual banco de dados está sendo usado e ajustar o mapeamento
    from django.db import connection
    db_vendor = connection.vendor
    
    for item in eficiencia_dia_semana:
        # Ajuste para o dia da semana baseado no banco de dados
        if db_vendor == 'postgresql':
            # PostgreSQL: 0 (domingo) a 6 (sábado)
            # Converter para 0 (segunda) a 6 (domingo)
            dia_idx = (item['dia_semana'] - 1) % 7
        elif db_vendor in ['mysql', 'sqlite']:
            # MySQL/SQLite: 1 (domingo) a 7 (sábado)
            # Converter para 0 (segunda) a 6 (domingo)
            dia_idx = (item['dia_semana'] - 2) % 7
        else:
            # Fallback genérico
            dia_idx = (item['dia_semana'] - 1) % 7
            
        dias_semana_data[dia_idx] = item['validacoes']
    
    for dia, tempos in tempo_por_dia.items():
        if tempos:
            # Aplicar a mesma lógica de conversão
            if db_vendor == 'postgresql':
                dia_idx = (dia - 1) % 7
            elif db_vendor in ['mysql', 'sqlite']:
                dia_idx = (dia - 2) % 7
            else:
                dia_idx = (dia - 1) % 7
                
            tempo_medio_dia_semana[dia_idx] = sum(tempos) / len(tempos) / 86400  # Média em dias
    
    # NOVO: Análise de funil de conversão com nomes significativos
    funil_etapas = [
        'Cadastro',
        'Primeiro Documento Recebido',
        'Todos Documentos Recebidos',
        'Todos Documentos Validados',
        'Processo Concluído'
    ]
    
    total_cadastros = RegistroTempo.objects.filter(
        tipo_evento='candidato_cadastrado'
    ).values('candidato').distinct().count()
    
    candidatos_com_docs = RegistroTempo.objects.filter(
        tipo_evento='documento_recebido'
    ).values('candidato').distinct().count()
    
    candidatos_todos_docs = Candidato.objects.annotate(
        docs_count=Count('documentos'),
        docs_recebidos=Count('documentos', filter=Q(documentos__status__in=['recebido', 'validado', 'invalido']))
    ).filter(docs_count=F('docs_recebidos')).count()
    
    candidatos_docs_validados = Candidato.objects.annotate(
        docs_count=Count('documentos'),
        docs_validados=Count('documentos', filter=Q(documentos__status='validado'))
    ).filter(docs_count=F('docs_validados')).count()
    
    funil_dados = [
        total_cadastros,
        candidatos_com_docs,
        candidatos_todos_docs,
        candidatos_docs_validados,
        candidatos_concluidos
    ]
    
    # Calcular taxas de conversão entre etapas do funil
    funil_taxas = []
    funil_conversao_labels = []
    
    for i in range(1, len(funil_dados)):
        if funil_dados[i-1] > 0:
            taxa = (funil_dados[i] / funil_dados[i-1]) * 100
        else:
            taxa = 0
        funil_taxas.append(round(taxa, 1))
        funil_conversao_labels.append(f"{funil_etapas[i-1]} → {funil_etapas[i]}")
    
    # NOVO: Oportunidades de melhoria dinâmicas baseadas em dados reais
    oportunidades_melhoria = []
    
    # 1. Verificar gargalos no processo
    if etapas_gargalos and len(etapas_gargalos) > 0 and etapas_gargalos[0][1] is not None and etapas_gargalos[0][1] > 1:
        oportunidades_melhoria.append({
            'titulo': 'Reduzir Tempo de ' + etapas_gargalos[0][0],
            'descricao': f'A etapa de {etapas_gargalos[0][0]} leva em média {format_time(etapas_gargalos[0][1])}. '
                        f'Considere otimizar este processo para reduzir o tempo total.',
            'cor': 'blue'
        })
    
    # 2. Verificar documentos problemáticos
    if docs_problematicos and len(docs_problematicos) > 0 and docs_problematicos_labels and len(docs_problematicos_labels) > 0:
        oportunidades_melhoria.append({
            'titulo': 'Melhorar Instruções para Documentos',
            'descricao': f'"{docs_problematicos_labels[0]}" é o documento mais problemático com {docs_problematicos_data[0]} invalidações. '
                        f'Forneça instruções mais claras para este documento.',
            'cor': 'yellow'
        })
    
    # 3. Verificar taxa de rejeição de documentos
    if taxa_rejeicao_docs > 20:
        oportunidades_melhoria.append({
            'titulo': 'Reduzir Taxa de Rejeição',
            'descricao': f'A taxa de rejeição de documentos é de {round(taxa_rejeicao_docs, 1)}%. '
                        f'Considere melhorar as instruções e exemplos para os candidatos.',
            'cor': 'red'
        })
    
    # 4. Verificar eficiência por dia da semana
    if dias_semana_data and len(dias_semana_data) > 0 and max(dias_semana_data) > 0:
        dia_mais_eficiente = dias_semana[dias_semana_data.index(max(dias_semana_data))]
        dia_menos_eficiente = dias_semana[dias_semana_data.index(min([x for x in dias_semana_data if x > 0] or [0]))]
        
        if dia_mais_eficiente != dia_menos_eficiente:
            oportunidades_melhoria.append({
                'titulo': 'Otimizar Distribuição de Trabalho',
                'descricao': f'A validação é mais frequente às {dia_mais_eficiente}s e menos frequente às {dia_menos_eficiente}s. '
                            f'Considere redistribuir a carga de trabalho durante a semana.',
                'cor': 'green'
            })
    
    # 5. Verificar taxa de conversão
    if taxa_conclusao < 50:
        oportunidades_melhoria.append({
            'titulo': 'Aumentar Taxa de Conclusão',
            'descricao': f'Apenas {round(taxa_conclusao, 1)}% dos candidatos concluem o processo. '
                        f'Implemente lembretes automáticos e acompanhamento proativo para aumentar esta taxa.',
            'cor': 'purple'
        })
    
    # 6. Verificar tempo médio de primeira submissão
    if tempo_medio_primeira_submissao_dias and tempo_medio_primeira_submissao_dias > 3:
        oportunidades_melhoria.append({
            'titulo': 'Acelerar Primeira Submissão',
            'descricao': f'Os candidatos levam em média {tempo_medio_primeira_submissao_formatado} para enviar o primeiro documento. '
                        f'Considere enviar lembretes mais frequentes no início do processo.',
            'cor': 'orange'
        })
    
    # NOVO: Melhorar os insights na página de resumo
    insights = []
    
    # 1. Gargalos do processo
    if etapas_gargalos and len(etapas_gargalos) > 0 and etapas_gargalos[0][1] is not None:
        etapa_gargalo = etapas_gargalos[0][0]
        tempo_gargalo = format_time(etapas_gargalos[0][1])
        insights.append({
            'titulo': 'Gargalos do Processo',
            'descricao': f'A etapa que mais demora é {etapa_gargalo} com média de {tempo_gargalo}.',
            'tipo': 'neutral'
        })
    else:
        insights.append({
            'titulo': 'Gargalos do Processo',
            'descricao': 'Não há dados suficientes para identificar gargalos no processo.',
            'tipo': 'neutral'
        })
    
    # 2. Retrabalho
    if total_docs_retrabalho > 0:
        insights.append({
            'titulo': 'Retrabalho',
            'descricao': f'{total_docs_retrabalho} documentos precisaram ser enviados mais de uma vez (média de {media_invalidacoes} tentativas).',
            'tipo': 'negative'
        })
    else:
        insights.append({
            'titulo': 'Retrabalho',
            'descricao': 'Não há documentos que precisaram ser enviados mais de uma vez.',
            'tipo': 'positive'
        })
    
    # 3. Conversão recente
    if candidatos_ultimos_30_dias > 0:
        insights.append({
            'titulo': 'Conversão Recente',
            'descricao': f'Nos últimos 30 dias, {taxa_conversao_30_dias}% dos candidatos concluíram o processo ({concluidos_ultimos_30_dias} de {candidatos_ultimos_30_dias}).',
            'tipo': 'positive' if taxa_conversao_30_dias > 50 else 'neutral'
        })
    else:
        insights.append({
            'titulo': 'Conversão Recente',
            'descricao': 'Não há dados de conversão para os últimos 30 dias.',
            'tipo': 'neutral'
        })
    
    context = {
        # Dados existentes
        'status_labels': json.dumps(status_labels),
        'status_data': json.dumps(status_data),
        'status_colors': json.dumps(status_colors_array),
        'etapas_labels': json.dumps(etapas_labels),
        'etapas_data': json.dumps(etapas_data),
        'etapas_data_formatada': json.dumps(etapas_data_formatada),
        'meses_labels': json.dumps(meses_completos),
        'cadastros_data': json.dumps(dados_meses),
        'tempo_medio_data': json.dumps(dados_tempo_medio),
        'tempo_medio_total': tempo_medio_total_formatado,
        'taxa_conclusao': round(taxa_conclusao, 1),
        'docs_pendentes': docs_pendentes,
        'docs_invalidos': docs_invalidos,
        'total_candidatos': total_candidatos,
        'candidatos_concluidos': candidatos_concluidos,
        'candidatos_ultimos_30_dias': candidatos_ultimos_30_dias,
        'taxa_conversao': round(taxa_conclusao, 1),
        'tipos_documentos_labels': json.dumps(tipos_documentos_labels),
        'tipos_documentos_data': json.dumps(tipos_documentos_data),
        'tempo_medio_tipo_labels': json.dumps(tempo_medio_tipo_labels),
        'tempo_medio_tipo_data': json.dumps(tempo_medio_tipo_data),
        'tempo_medio_tipo_data_formatada': json.dumps(tempo_medio_tipo_data_formatada),
        'taxa_rejeicao_docs': round(taxa_rejeicao_docs, 1),
        'tempo_medio_primeira_submissao': tempo_medio_primeira_submissao_formatado,
        
        # Novas estatísticas baseadas na timeline
        'etapas_std_dev': json.dumps(etapas_std_dev),
        'etapas_min': json.dumps(etapas_min),
        'etapas_max': json.dumps(etapas_max),
        'etapas_min_formatada': json.dumps(etapas_min_formatada),
        'etapas_max_formatada': json.dumps(etapas_max_formatada),
        'gargalos_labels': json.dumps(gargalos_labels),
        'gargalos_data': json.dumps(gargalos_data),
        'dados_conclusoes': json.dumps(dados_conclusoes),
        'taxa_conversao_mensal': json.dumps(taxa_conversao_mensal),
        'tempo_min_total': tempo_min_total_formatado,
        'tempo_max_total': tempo_max_total_formatado,
        'total_docs_retrabalho': total_docs_retrabalho,
        'media_invalidacoes': round(media_invalidacoes, 1) if media_invalidacoes else 0,
        'docs_problematicos_labels': json.dumps(docs_problematicos_labels),
        'docs_problematicos_data': json.dumps(docs_problematicos_data),
        'concluidos_ultimos_30_dias': concluidos_ultimos_30_dias,
        'taxa_conversao_30_dias': round(taxa_conversao_30_dias, 1),
        'dias_semana': json.dumps(dias_semana),
        'dias_semana_data': json.dumps(dias_semana_data),
        'tempo_medio_dia_semana': json.dumps(tempo_medio_dia_semana),
        'funil_etapas': json.dumps(funil_etapas),
        'funil_dados': json.dumps(funil_dados),
        'funil_taxas': json.dumps(funil_taxas),
        'funil_conversao_labels': json.dumps(funil_conversao_labels),
        
        # Oportunidades de melhoria dinâmicas
        'oportunidades_melhoria': oportunidades_melhoria,
        
        # Insights melhorados
        'insights': insights,
    }
    
    return render(request, 'estatisticas.html', context)


def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect('dashboard')
            else:
                messages.error(request, "Usuário ou senha inválidos.")
        else:
            messages.error(request, "Usuário ou senha inválidos.")
    else:
        form = LoginForm()
    return render(request, 'login.html', {'form': form})

def register_view(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Registro realizado com sucesso!")
            return redirect('dashboard')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = RegisterForm()
    return render(request, 'register.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('login')

@login_required
def dashboard(request):
    if request.method == 'POST':
        form = CandidatoForm(request.POST)
        if form.is_valid():
            candidato = form.save(commit=False)
            candidato.status = 'em_andamento'  # Inicia como em andamento
            candidato.save()
            
            # Lista de documentos necessários
            documentos_necessarios = [
                'rg', 'cpf', 'cnh', 'ctps', 
                'comprovante_residencia', 'titulo_eleitor', 
                'foto_rosto'
            ]
            
            # Dicionário com instruções específicas para cada tipo de documento
            instrucoes_documentos = {
                'rg': 'frente e verso (imagens separadas)',
                'cpf': 'foto do documento',
                'cnh': 'frente e verso',
                'ctps': 'página com foto e identificação',
                'comprovante_residencia': 'conta recente',
                'titulo_eleitor': 'frente do documento',
                'foto_rosto': 'selfie frontal bem iluminada',
                'outros': 'conforme solicitado'
            }
            
            # Gera a lista de documentos para a mensagem
            lista_documentos = ""
            contador = 1
            
            for tipo, nome in Documento.TIPO_CHOICES:
                if tipo in documentos_necessarios:
                    instrucao = instrucoes_documentos.get(tipo, '')
                    lista_documentos += f"{contador}. *{nome}* - {instrucao}\n"
                    contador += 1
            
            # Monta a mensagem completa
            mensagem = (
                f"Olá {candidato.nome}!\n\n"
                "*Bem-vindo ao processo de contratação!*\n\n"
                "*Documentos necessários:*\n"
                f"{lista_documentos}\n"
                "*Instruções:*\n"
                "• Envie cada documento *separadamente*\n"
                "• Use *fotos* claras e legíveis ou *PDF*\n"
                "• Aguarde confirmação após cada envio\n\n"
                "Dúvidas? Estamos à disposição para ajudar!"
            )
            
            # Adiciona o prefixo 55 ao número do telefone
            telefone_completo = f"55{candidato.telefone_limpo}"
            enviar_mensagem_whatsapp(telefone_completo, mensagem)
            
            # Cria os registros de documentos necessários
            for doc in documentos_necessarios:
                Documento.objects.create(
                    candidato=candidato,
                    tipo=doc,
                    status='pendente'
                )
            
            # Atualiza o status para documentos pendentes
            candidato.status = 'documentos_pendentes'
            candidato.save()
            
            messages.success(request, 'Candidato cadastrado com sucesso!')
            return redirect('detalhe_candidato', candidato_id=candidato.id)
    else:
        form = CandidatoForm()

    context = {
        'form': form,
        'ativos_count': Candidato.objects.filter(status='em_andamento').count(),
        'pendentes_count': Candidato.objects.filter(status='documentos_pendentes').count(),
        'invalidos_count': Candidato.objects.filter(status='documentos_invalidos').count(),
        'concluidos_count': Candidato.objects.filter(status='concluido').count(),
        'candidatos_recentes': Candidato.objects.all().order_by('-data_cadastro')[:5]
    }
    return render(request, 'dashboard.html', context)

@login_required
def editar_candidato(request, candidato_id):
    candidato = get_object_or_404(Candidato, id=candidato_id)
    
    if request.method == 'POST':
        form = CandidatoForm(request.POST, instance=candidato)
        if form.is_valid():
            form.save()
            messages.success(request, 'Informações atualizadas com sucesso!')
            return redirect('detalhe_candidato', candidato_id=candidato.id)
    else:
        form = CandidatoForm(instance=candidato)
    
    return render(request, 'editar_candidato.html', {
        'form': form,
        'candidato': candidato
    })


@login_required
def excluir_candidato(request, candidato_id):
    candidato = get_object_or_404(Candidato, id=candidato_id)
    if request.method == 'POST':
        candidato.delete()
        messages.success(request, 'Candidato excluído com sucesso!')
        return redirect('dashboard')
    return redirect('detalhe_candidato', candidato_id=candidato_id)


@login_required
def lista_candidatos(request):
    status = request.GET.get('status', 'em_andamento')
    candidatos = Candidato.objects.filter(status=status)
    
    context = {
        'candidatos': candidatos,
        'status_display': dict(Candidato.STATUS_CHOICES)[status]
    }
    return render(request, 'lista_candidatos.html', context)

@login_required
def detalhe_candidato(request, candidato_id):
    candidato = get_object_or_404(Candidato, id=candidato_id)
    return render(request, 'detalhe_candidato.html', {'candidato': candidato})


def atualizar_status_candidato(candidato):
    """
    Atualiza o status do candidato com base no status dos documentos
    """
    # Verifica se há documentos inválidos
    if candidato.documentos_invalidos > 0:
        candidato.status = 'documentos_invalidos'
    # Verifica se todos os documentos foram validados
    elif candidato.documentos_validados == candidato.total_documentos and candidato.total_documentos > 0:
        candidato.status = 'concluido'
    # Verifica se há documentos pendentes
    elif candidato.documentos_pendentes > 0:
        candidato.status = 'documentos_pendentes'
    # Caso contrário, está em andamento
    else:
        candidato.status = 'em_andamento'
    
    candidato.save()
    
@login_required
def documento_crud(request, candidato_id, documento_id=None):
    candidato = get_object_or_404(Candidato, id=candidato_id)
    documento = None if documento_id is None else get_object_or_404(Documento, id=documento_id, candidato=candidato)
    
    if request.method == 'POST':
        if 'delete' in request.POST:
            if documento:
                documento.delete()
                messages.success(request, 'Documento excluído com sucesso!')
                return redirect('detalhe_candidato', candidato_id=candidato.id)
        else:
            form = DocumentoForm(request.POST, request.FILES, instance=documento)
            if form.is_valid():
                # Se for uma edição, guarda o status anterior
                status_anterior = None
                if documento:
                    status_anterior = documento.status
                
                doc = form.save(commit=False)
                doc.candidato = candidato
                
                # Se o status for alterado para inválido
                if doc.status == 'invalido' and (not documento or documento.status != 'invalido'):
                    candidato.status = 'documentos_invalidos'
                    candidato.save()
                
                # Se o status for alterado para validado
                if doc.status == 'validado':
                    if not documento or documento.status != 'validado':
                        doc.data_validacao = timezone.now()
                
                # Se o status for alterado para recebido
                if doc.status == 'recebido':
                    if not documento or documento.status != 'recebido':
                        doc.data_envio = timezone.now()
                
                doc.save()
                
                # Se houve mudança de status, registra na timeline
                if documento and status_anterior != doc.status:
                    from .utils.timeline import registrar_evento
                    
                    # Determina o tipo de evento com base no novo status
                    if doc.status == 'recebido':
                        tipo_evento = 'documento_recebido'
                    elif doc.status == 'validado':
                        tipo_evento = 'documento_validado'
                    elif doc.status == 'invalido':
                        tipo_evento = 'documento_invalidado'
                    else:
                        tipo_evento = 'documento_solicitado'
                    
                    # Registra o evento na timeline
                    registrar_evento(
                        candidato=candidato,
                        tipo_evento=tipo_evento,
                        documento=doc,
                        status_anterior=status_anterior,
                        status_novo=doc.status,
                        observacoes=f"Status alterado manualmente por {request.user.username}"
                    )
                
                # Verifica se todos os documentos estão validados
                todos_validados = True
                for d in candidato.documentos.all():
                    if d.id != doc.id and d.status != 'validado':
                        todos_validados = False
                        break
                
                # Se todos os documentos estiverem validados, atualiza o status do candidato
                if todos_validados:
                    candidato.status = 'concluido'
                    candidato.save()
                
                messages.success(request, 'Documento salvo com sucesso!')
                return redirect('detalhe_candidato', candidato_id=candidato.id)
    else:
        form = DocumentoForm(instance=documento)
    
    # Se o documento existe, formata o tempo para os registros
    if documento:
        from .utils.timeline import formatar_duracao
        registros = documento.registros_tempo.all().order_by('-data_hora')
        for registro in registros:
            registro.tempo_formatado = formatar_duracao(registro.tempo_desde_evento_anterior)
    
    context = {
        'form': form,
        'candidato': candidato,
        'documento': documento,
        'is_new': documento is None
    }
    return render(request, 'documento_form.html', context)

@login_required
@require_http_methods(["POST"])
def atualizar_status_documento(request, candidato_id, documento_id):
    """
    View para atualizar o status de um documento via AJAX
    """
    # Verificar se é uma requisição AJAX
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Requisição inválida'}, status=400)
    
    try:
        candidato = get_object_or_404(Candidato, id=candidato_id)
        documento = get_object_or_404(Documento, id=documento_id, candidato=candidato)
        
        novo_status = request.POST.get('status')
        if novo_status not in dict(Documento.STATUS_CHOICES):
            return JsonResponse({'success': False, 'error': 'Status inválido'}, status=400)
        
        # Guardar o status anterior
        status_anterior = documento.status
        
        # Atualizar o status
        documento.status = novo_status
        
        # Se o status for alterado para validado
        if novo_status == 'validado':
            documento.data_validacao = timezone.now()
        # Se o status for alterado para recebido
        elif novo_status == 'recebido':
            documento.data_envio = timezone.now()
        
        documento.save()
        
        # Registrar o evento na timeline
        from .utils.timeline import registrar_evento
        
        # Determina o tipo de evento com base no novo status
        if novo_status == 'recebido':
            tipo_evento = 'documento_recebido'
        elif novo_status == 'validado':
            tipo_evento = 'documento_validado'
        elif novo_status == 'invalido':
            tipo_evento = 'documento_invalidado'
        else:
            tipo_evento = 'documento_solicitado'
        
        # Registra o evento na timeline
        registrar_evento(
            candidato=candidato,
            tipo_evento=tipo_evento,
            documento=documento,
            status_anterior=status_anterior,
            status_novo=novo_status,
            observacoes=f"Status alterado via interface web por {request.user.username}"
        )
        
        # Atualizar o status do candidato
        atualizar_status_candidato(candidato)
        
        return JsonResponse({'success': True})
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


from .utils.timeline import registrar_evento


@login_required
def timeline_candidato(request, candidato_id):
    """
    View para exibir a timeline de eventos do candidato
    """
    candidato = get_object_or_404(Candidato, id=candidato_id)
    registros = candidato.registros_tempo.all().order_by('-data_hora')
    
    from .utils.timeline import formatar_duracao
    
    # Formatar as durações para exibição
    for registro in registros:
        registro.tempo_formatado = formatar_duracao(registro.tempo_desde_evento_anterior)
    
    return render(request, 'timeline_candidato.html', {
        'candidato': candidato,
        'registros': registros
    })

@csrf_exempt
@require_http_methods(["POST"])
def webhook(request):

    from .utils.image_processor import ImageProcessor
    from django.core.files.base import ContentFile
    import requests
    import tempfile
    from PIL import Image  # Importa o módulo para manipulação de imagens
    import io  # Importa o módulo para manipulação de streams de bytes
    #from chamar_reconhecimento import analisar_arquivo


    try:
        body = json.loads(request.body.decode())
        
        if "data" not in body or "key" not in body.get("data", {}):
            return JsonResponse({'status': 'error', 'message': 'Invalid message format'}, status=400)

        data = body["data"]
        sender = data["key"]["remoteJid"].split('@')[0]
        is_from_me = data["key"].get("fromMe", False)
        push_name = data.get("pushName", "Unknown")

        telefone_webhook = ''.join(filter(str.isdigit, sender))
        if telefone_webhook.startswith('55'):
            telefone_webhook = telefone_webhook[2:]

        if not is_from_me:
            try:
                # Busca o candidato
                candidatos = Candidato.objects.all()
                candidato = None
                
                for c in candidatos:
                    numero_candidato = ''.join(filter(str.isdigit, c.telefone))
                    if numero_candidato[-8:] == telefone_webhook[-8:]:
                        candidato = c
                        break

                if candidato:
                    if "message" in data:
                        message_data = data["message"]
                        has_document = "documentMessage" in message_data
                        has_image = "imageMessage" in message_data
                        
                        if has_document or has_image:
                            # Determina o tipo de mídia e extrai informações
                            if has_document:
                                media_info = message_data["documentMessage"]
                                media_type = "documento"
                            else:
                                media_info = message_data["imageMessage"]
                                media_type = "imagem"

                            # Processa o documento
                            doc_pendente = candidato.documentos.filter(status='pendente').first()
                            
                            if doc_pendente:
                                
                                # Registra o evento de início do processamento
                                registrar_evento(
                                    candidato=candidato,
                                    tipo_evento='documento_recebido',
                                    documento=doc_pendente,
                                    status_anterior=doc_pendente.status,
                                    observacoes=f"Recebido {media_type} via WhatsApp"
                                )
                                
                                # Verifica se há base64 na mensagem
                                base64_data = (
                                    body.get("base64") or 
                                    data.get("base64") or 
                                    message_data.get("base64") or 
                                    media_info.get("base64")
                                )

                                if base64_data:
                                    try:
                                        # Decodifica o base64
                                        file_data = base64.b64decode(base64_data)
                                        
                                        # Se for imagem, verifica se é foto do rosto
                                        if has_image:
                                            # Criar imagem PIL a partir dos dados
                                            image = Image.open(io.BytesIO(file_data))
                                            
                                            # Processar imagem
                                            processor = ImageProcessor()
                                            is_valid, message = processor.validate_face_photo(image)
                                            
                                            print(f"Resultado da validação: {is_valid}, {message}")
                                            
                                            # Se for uma foto válida de rosto
                                            if is_valid:
                                                # Procurar documento específico de foto do rosto
                                                doc_foto, created = Documento.objects.get_or_create(
                                                    candidato=candidato,
                                                    tipo='foto_rosto',
                                                    defaults={'status': 'pendente'}
                                                )
                                                
                                                # Determina o nome do arquivo
                                                file_name = f"foto_rosto_{candidato.id}.jpg"
                                                
                                                # Salva o arquivo
                                                doc_foto.arquivo.save(
                                                    file_name,
                                                    ContentFile(file_data),
                                                    save=True
                                                )

                                                # Registra o evento de recebimento
                                                if created:
                                                    registrar_evento(
                                                        candidato=candidato,
                                                        tipo_evento='documento_recebido',
                                                        documento=doc_foto,
                                                        status_anterior='pendente',
                                                        status_novo='recebido',
                                                        observacoes="Foto do rosto recebida via WhatsApp"
                                                    )
                                                    
                                                # Atualiza status
                                                status_anterior = doc_foto.status                                                
                                                doc_foto.status = 'validado'
                                                doc_foto.data_envio = timezone.now()
                                                doc_foto.data_validacao = timezone.now()
                                                doc_foto.observacoes = "Foto do rosto validada automaticamente pela IA"
                                                doc_foto.save()

                                                # Registra o evento de validação
                                                registrar_evento(
                                                    candidato=candidato,
                                                    tipo_evento='documento_validado',
                                                    documento=doc_foto,
                                                    status_anterior=status_anterior,
                                                    status_novo='validado',
                                                    observacoes="Validação automática pela IA"
                                                )
                                                
                                                # Envia confirmação
                                                mensagem = (
                                                    "✅ Foto do rosto recebida e validada com sucesso!\n\n"
                                                    "Continue enviando os outros documentos necessários."
                                                )
                                                enviar_mensagem_whatsapp(sender, mensagem)
                                                return JsonResponse({'status': 'success'})
                                            else:
                                                # Se não for uma foto válida de rosto, continua com o processamento normal
                                                if doc_pendente.tipo == 'foto_rosto':
                                                    
                                                    # Registra o evento de invalidação
                                                    registrar_evento(
                                                        candidato=candidato,
                                                        tipo_evento='documento_invalidado',
                                                        documento=doc_pendente,
                                                        status_anterior=doc_pendente.status,
                                                        status_novo='invalido',
                                                        observacoes=f"Foto inválida: {message}"
                                                    )
                                                    
                                                    # Se estiver esperando foto do rosto, envia feedback
                                                    mensagem = (
                                                        "❌ A foto enviada não atende aos requisitos:\n"
                                                        f"{message}\n\n"
                                                        "Por favor, envie uma nova foto seguindo as orientações:\n"
                                                        "- Rosto bem iluminado\n"
                                                        "- Olhando para frente\n"
                                                        "- Sem óculos escuros ou chapéu\n"
                                                        "- Fundo neutro\n"
                                                        "- Não envie foto de documento"
                                                    )
                                                    enviar_mensagem_whatsapp(sender, mensagem)
                                                    return JsonResponse({'status': 'success'})

                                        # Determina o nome do arquivo para outros documentos
                                        if "fileName" in media_info and media_info["fileName"]:
                                            file_name = media_info["fileName"]
                                        else:
                                            extension = "jpg" if has_image else "pdf"
                                            file_name = f"{doc_pendente.tipo}_{candidato.id}.{extension}"
                                        
                                        # Salva o arquivo no documento
                                        doc_pendente.arquivo.save(
                                            file_name,
                                            ContentFile(file_data),
                                            save=True
                                        )
                                        
                                        # Importar o analisador de documentos
                                        from reconhecer_imagem import analisar_arquivo
                                        
                                        # NOVO: Reconhecer o tipo de documento usando a IA
                                        try:
                                            # Obter o caminho do arquivo salvo
                                            arquivo_path = doc_pendente.arquivo.path
                                            
                                            # Analisar o documento
                                            tipo_documento = analisar_arquivo(arquivo_path)
                                            print(f"Tipo de documento identificado: {tipo_documento}")
                                            
                                            # Mapear o tipo de documento para o formato do modelo
                                            tipo_mapeado = tipo_documento  # Inicialmente, assume o tipo retornado pela IA
                                            
                                            # Dicionário de mapeamento entre resposta da IA e valores do modelo
                                            mapeamento_tipos = {
                                                'RG': 'rg',
                                                'CPF': 'cpf',
                                                'CNH': 'cnh',
                                                'CARTEIRA DE TRABALHO': 'ctps',
                                                'CTPS': 'ctps',
                                                'COMPROVANTE DE RESIDÊNCIA': 'comprovante_residencia',
                                                'TÍTULO DE ELEITOR': 'titulo_eleitor',
                                                'TITULO DE ELEITOR': 'titulo_eleitor'
                                            }
                                            
                                            # Verificar se o tipo identificado está no mapeamento
                                            for chave, valor in mapeamento_tipos.items():
                                                if tipo_documento and (chave in tipo_documento.upper() or tipo_documento == valor):
                                                    tipo_mapeado = valor
                                                    break

                                            # Se não encontrou no mapeamento e não é um dos tipos válidos, define como 'outros'
                                            tipos_validos = set(mapeamento_tipos.values())
                                            if tipo_mapeado not in tipos_validos:
                                                tipo_mapeado = 'outros'

                                            # Atualizar o tipo do documento
                                            doc_pendente.tipo = tipo_mapeado
                                            doc_pendente.observacoes += f"\nTipo identificado pela IA: {tipo_documento}"
                                            doc_pendente.observacoes += f"\nTipo mapeado: {tipo_mapeado}"

                                        except Exception as e:
                                            print(f"Erro ao reconhecer documento: {str(e)}")
                                            # Em caso de erro, mantém o tipo original e adiciona uma observação
                                            doc_pendente.observacoes += f"\nErro ao tentar identificar o tipo: {str(e)}"
                                    except Exception as e:
                                        print(f"Erro ao processar imagem: {str(e)}")
                                        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
                                
                                # Atualiza o status do documento
                                # Buscar um documento do mesmo tipo que ainda não tenha um arquivo salvo
                                doc_pendente = candidato.documentos.filter(tipo=tipo_mapeado, arquivo="").first()

                                if not doc_pendente:
                                    # Se não encontrou um documento vazio, cria um novo
                                    doc_pendente = Documento.objects.create(
                                        candidato=candidato,
                                        tipo=tipo_mapeado,
                                        status='pendente'
                                    )

                                    # Registra o evento de criação do documento
                                    registrar_evento(
                                        candidato=candidato,
                                        tipo_evento='documento_solicitado',
                                        documento=doc_pendente,
                                        status_novo='pendente',
                                        observacoes=f"Documento {doc_pendente.get_tipo_display()} criado automaticamente"
                                    )
                                    
                                # Determina o nome do arquivo
                                if "fileName" in media_info and media_info["fileName"]:
                                    file_name = media_info["fileName"]
                                else:
                                    extension = "jpg" if has_image else "pdf"
                                    file_name = f"{doc_pendente.tipo}_{candidato.id}.{extension}"

                                # Salva o arquivo no documento identificado
                                doc_pendente.arquivo.save(
                                    file_name,
                                    ContentFile(file_data),
                                    save=True
                                )

                                # Atualiza status e observações
#                                doc_pendente.status = 'validado'

                                # Guarda o status anterior para o registro
                                status_anterior = doc_pendente.status
                                
                                # **NOVO: Se o tipo for 'outros', já define como inválido antes de salvar**
                                if tipo_mapeado == 'outros':
                                    doc_pendente.status = 'invalido'
                                    doc_pendente.observacoes += "\nTipo não reconhecido através da inteligência artificial."
                                    doc_pendente.data_envio = timezone.now()
                                    doc_pendente.data_validacao = timezone.now()
                                    doc_pendente.save()
                                    
                                    # Registra o evento de invalidação
                                    registrar_evento(
                                        candidato=candidato,
                                        tipo_evento='documento_invalidado',
                                        documento=doc_pendente,
                                        status_anterior=status_anterior,
                                        status_novo='invalido',
                                        observacoes="Tipo de documento não reconhecido pela IA"
                                    )
                                    
                                    # Atualiza o status do candidato para 'documentos_invalidos'
                                    status_anterior_candidato = candidato.status
                                    candidato.status = 'documentos_invalidos'
                                    candidato.save()
                                    
                                    # Registra a mudança de status do candidato
                                    registrar_evento(
                                        candidato=candidato,
                                        tipo_evento='documento_invalidado',
                                        status_anterior=status_anterior_candidato,
                                        status_novo=candidato.status,
                                        observacoes="Status atualizado devido a documento inválido"
                                    )
                                                              
                                else:
                                    # Se for um tipo válido, segue o fluxo normal
                                    doc_pendente.status = 'validado'
                                    doc_pendente.data_envio = timezone.now()
                                    doc_pendente.data_validacao = timezone.now()
                                    doc_pendente.observacoes += f"{media_type.capitalize()} recebido(a) via WhatsApp de {push_name}.\n\n{media_type.capitalize()} validado(a) através de inteligência artificial."
                                    doc_pendente.save()

                                    # Registra o evento de validação
                                    registrar_evento(
                                        candidato=candidato,
                                        tipo_evento='documento_validado',
                                        documento=doc_pendente,
                                        status_anterior=status_anterior,
                                        status_novo='validado',
                                        observacoes="Validação automática pela IA"
                                    )
                                    
                                try:
                                    # Envia confirmação
                                    mensagem = f"Documento recebido! Identificamos como: *{doc_pendente.get_tipo_display()}*. \nVamos analisar e retornaremos em breve."
                                    enviar_mensagem_whatsapp(sender, mensagem)

                                    # Verifica documentos pendentes
                                    docs_pendentes = candidato.documentos.filter(status='pendente')
                                    if docs_pendentes.exists():
                                        docs_texto = "\n".join([f"- {doc.get_tipo_display()}" 
                                                              for doc in docs_pendentes])
                                        mensagem = f"Ainda precisamos dos seguintes documentos:\n{docs_texto}"
                                        enviar_mensagem_whatsapp(sender, mensagem)
                                    else:
                                        mensagem = ("Ótimo! Todos os documentos foram recebidos. "
                                                  "Iremos analisar e entraremos em contato em breve.")
                                        enviar_mensagem_whatsapp(sender, mensagem)
                                        candidato.status = 'em_andamento'
                                        candidato.save()
                                        
                                        registrar_evento(
                                            candidato=candidato,
                                            tipo_evento='processo_concluido',
                                            status_anterior=status_anterior_candidato,
                                            status_novo=candidato.status,
                                            observacoes="Todos os documentos recebidos"
                                        )
                                        
                                except Exception as e:
                                    print(f"Erro ao enviar mensagem de resposta: {str(e)}")
                            else:
                                print("Nenhum documento pendente encontrado para o candidato")
                        else:
                            print("Mensagem não contém documento ou imagem")
                else:
                    print(f"Candidato não encontrado para o número: {telefone_webhook}")

            except Exception as e:
                print(f"Erro ao processar mensagem: {str(e)}")
                import traceback
                print(traceback.format_exc())
                return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

        return JsonResponse({'status': 'success'})

    except json.JSONDecodeError as e:
        print(f"Erro ao decodificar JSON: {str(e)}")
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        print(f"Erro não tratado: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)







@login_required
def novo_documento(request, candidato_id):
    candidato = get_object_or_404(Candidato, id=candidato_id)
    if request.method == 'POST':
        form = DocumentoForm(request.POST)
        if form.is_valid():
            documento = form.save(commit=False)
            documento.candidato = candidato
            documento.save()
            
            # Enviar solicitação do documento via WhatsApp
            tipo_documento = documento.get_tipo_display()
            mensagem = f"Olá {candidato.nome}, por favor, envie o documento: {tipo_documento}. Certifique-se de que a imagem está clara e legível."
            enviar_mensagem_whatsapp(candidato.telefone, mensagem)
            
            messages.success(request, 'Documento adicionado com sucesso e solicitação enviada via WhatsApp.')
            return redirect('detalhes_candidato', candidato_id=candidato.id)
    else:
        form = DocumentoForm()
    
    return render(request, 'novo_documento.html', {'form': form, 'candidato': candidato})







'''
@csrf_exempt
@require_http_methods(["POST"])
def webhook(request):
    try:
        body = json.loads(request.body.decode())
        
        if "data" not in body or "key" not in body.get("data", {}):
            return JsonResponse({'status': 'error', 'message': 'Invalid message format'}, status=400)

        data = body["data"]
        sender = data["key"]["remoteJid"].split('@')[0]
        is_from_me = data["key"].get("fromMe", False)
        push_name = data.get("pushName", "Unknown")

        telefone_webhook = ''.join(filter(str.isdigit, sender))
        if telefone_webhook.startswith('55'):
            telefone_webhook = telefone_webhook[2:]

        if not is_from_me:
            try:
                # Busca o candidato
                candidatos = Candidato.objects.all()
                candidato = None
                
                for c in candidatos:
                    numero_candidato = ''.join(filter(str.isdigit, c.telefone))
                    if numero_candidato[-8:] == telefone_webhook[-8:]:
                        candidato = c
                        break

                if candidato:
                    if "message" in data:
                        message_data = data["message"]
                        has_document = "documentMessage" in message_data
                        has_image = "imageMessage" in message_data
                        
                        if has_document or has_image:
                            # Determina o tipo de mídia e extrai informações
                            if has_document:
                                media_info = message_data["documentMessage"]
                                media_type = "documento"
                            else:
                                media_info = message_data["imageMessage"]
                                media_type = "imagem"

                            # Processa o documento
                            doc_pendente = candidato.documentos.filter(status='pendente').first()
                            
                            if doc_pendente:
                                # Verifica se há base64 na mensagem
                                base64_data = (
                                    body.get("base64") or 
                                    data.get("base64") or 
                                    message_data.get("base64") or 
                                    media_info.get("base64")
                                )

                                if base64_data:
                                    try:
                                        # Decodifica o base64
                                        file_data = base64.b64decode(base64_data)
                                        
                                        # Se for imagem, verifica se é foto do rosto
                                        if has_image:
                                            # Criar imagem PIL a partir dos dados
                                            image = Image.open(io.BytesIO(file_data))
                                            
                                            # Processar imagem
                                            processor = ImageProcessor()
                                            is_valid, message = processor.validate_face_photo(image)
                                            
                                            print(f"Resultado da validação: {is_valid}, {message}")
                                            
                                            # Se for uma foto válida de rosto
                                            if is_valid:
                                                # Procurar documento específico de foto do rosto
                                                doc_foto, created = Documento.objects.get_or_create(
                                                    candidato=candidato,
                                                    tipo='foto_rosto',
                                                    defaults={'status': 'pendente'}
                                                )
                                                
                                                # Determina o nome do arquivo
                                                file_name = f"foto_rosto_{candidato.id}.jpg"
                                                
                                                # Salva o arquivo
                                                doc_foto.arquivo.save(
                                                    file_name,
                                                    ContentFile(file_data),
                                                    save=True
                                                )
                                                
                                                # Atualiza status
                                                doc_foto.status = 'validado'
                                                doc_foto.data_envio = timezone.now()
                                                doc_foto.data_validacao = timezone.now()
                                                doc_foto.observacoes = "Foto do rosto validada automaticamente pela IA"
                                                doc_foto.save()
                                                
                                                # Envia confirmação
                                                mensagem = (
                                                    "✅ Foto do rosto recebida e validada com sucesso!\n\n"
                                                    "Continue enviando os outros documentos necessários."
                                                )
                                                enviar_mensagem_whatsapp(sender, mensagem)
                                                return JsonResponse({'status': 'success'})
                                            else:
                                                # Se não for uma foto válida de rosto, continua com o processamento normal
                                                if doc_pendente.tipo == 'foto_rosto':
                                                    # Se estiver esperando foto do rosto, envia feedback
                                                    mensagem = (
                                                        "❌ A foto enviada não atende aos requisitos:\n"
                                                        f"{message}\n\n"
                                                        "Por favor, envie uma nova foto seguindo as orientações:\n"
                                                        "- Rosto bem iluminado\n"
                                                        "- Olhando para frente\n"
                                                        "- Sem óculos escuros ou chapéu\n"
                                                        "- Fundo neutro\n"
                                                        "- Não envie foto de documento"
                                                    )
                                                    enviar_mensagem_whatsapp(sender, mensagem)
                                                    return JsonResponse({'status': 'success'})

                                        # Determina o nome do arquivo para outros documentos
                                        if "fileName" in media_info and media_info["fileName"]:
                                            file_name = media_info["fileName"]
                                        else:
                                            extension = "jpg" if has_image else "pdf"
                                            file_name = f"{doc_pendente.tipo}_{candidato.id}.{extension}"
                                        
                                        # Salva o arquivo no documento
                                        doc_pendente.arquivo.save(
                                            file_name,
                                            ContentFile(file_data),
                                            save=True
                                        )
                                    except Exception as e:
                                        print(f"Erro ao processar imagem: {str(e)}")
                                        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
                                
                                # Atualiza o status do documento
                                doc_pendente.status = 'recebido'
                                doc_pendente.data_envio = timezone.now()
                                doc_pendente.observacoes = f"{media_type.capitalize()} recebido via WhatsApp de {push_name}"
                                doc_pendente.save()

                                try:
                                    # Envia confirmação
                                    mensagem = "Documento recebido! Vamos analisar e retornaremos em breve."
                                    enviar_mensagem_whatsapp(sender, mensagem)

                                    # Verifica documentos pendentes
                                    docs_pendentes = candidato.documentos.filter(status='pendente')
                                    if docs_pendentes.exists():
                                        docs_texto = "\n".join([f"- {doc.get_tipo_display()}" 
                                                              for doc in docs_pendentes])
                                        mensagem = f"Ainda precisamos dos seguintes documentos:\n{docs_texto}"
                                        enviar_mensagem_whatsapp(sender, mensagem)
                                    else:
                                        mensagem = ("Ótimo! Todos os documentos foram recebidos. "
                                                  "Iremos analisar e entraremos em contato em breve.")
                                        enviar_mensagem_whatsapp(sender, mensagem)
                                        candidato.status = 'em_andamento'
                                        candidato.save()
                                except Exception as e:
                                    print(f"Erro ao enviar mensagem de resposta: {str(e)}")
                            else:
                                print("Nenhum documento pendente encontrado para o candidato")
                        else:
                            print("Mensagem não contém documento ou imagem")
                else:
                    print(f"Candidato não encontrado para o número: {telefone_webhook}")

            except Exception as e:
                print(f"Erro ao processar mensagem: {str(e)}")
                import traceback
                print(traceback.format_exc())
                return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

        return JsonResponse({'status': 'success'})

    except json.JSONDecodeError as e:
        print(f"Erro ao decodificar JSON: {str(e)}")
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        print(f"Erro não tratado: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

'''