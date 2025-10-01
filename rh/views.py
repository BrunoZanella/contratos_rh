from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Candidato, Documento, TipoDocumento
from .forms import CandidatoForm, DocumentoForm
from .whatsapp import enviar_mensagem_whatsapp
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from django.utils import timezone
from django.views.decorators.http import require_http_methods
import base64
from django.contrib.auth import login, authenticate, logout
from .forms import LoginForm, RegisterForm, TipoDocumentoForm

from django.contrib.auth.models import User
from django.contrib.auth.decorators import user_passes_test
from .models import Setor, PerfilUsuario, AvaliacaoPeriodoExperiencia
from .forms import SetorForm, UsuarioForm, RegisterFormExtended
from django.db.models import Q
import requests
# Importações adicionais necessárias para o webhook
import os
import tempfile
from PIL import Image
import io
from .utils.image_processor import ImageProcessor
from django.core.files.base import ContentFile
from reconhecer_imagem import analisar_arquivo # Importar a função de reconhecimento de imagem
from .utils.document_recognition import auto_validate_document # Importar a função de validação automática
from .utils.timeline import registrar_evento, formatar_duracao # Importar funções da timeline
import logging
import re
from django.core.exceptions import RequestDataTooBig
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from .ai_conversation import ConversationAI
from datetime import date

logger = logging.getLogger('rh')


def is_admin(user):
    """Verifica se o usuário é administrador"""
    return user.is_staff

def tem_acesso_completo(user):
    """Verifica se o usuário tem acesso completo baseado no setor"""
    if user.is_staff:  # Administradores sempre têm acesso
        return True
    try:
        return user.perfil.setor and user.perfil.setor.acesso_completo
    except (PerfilUsuario.DoesNotExist, AttributeError):
        return False


# python manage.py criar_tipos_documentos


@login_required
def iniciar_processo(request, candidato_id):
    """
    View para iniciar o processo de um candidato:
    - Envia mensagem WhatsApp
    - Cria documentos necessários baseado no tipo de contratação
    - Atualiza status para 'documentos_pendentes'
    """
    candidato = get_object_or_404(Candidato, id=candidato_id)
    
    # Verifica se o candidato está no status 'ativo'
    if candidato.status != 'ativo':
        messages.warning(request, 'Este candidato já teve seu processo iniciado.')
        return redirect('lista_candidatos')
    
    # Buscar tipos de documentos baseado no tipo de contratação do candidato, excluindo 'OUTROS'
    tipos_documentos = TipoDocumento.get_documentos_por_tipo(candidato.tipo_contratacao).exclude(nome='OUTROS')
    
    print(f"=== DEBUG INICIAR PROCESSO ===")
    print(f"Candidato: {candidato.nome}")
    print(f"Tipo de contratação: {candidato.tipo_contratacao}")
    print(f"Documentos encontrados: {tipos_documentos.count()}")
    for doc in tipos_documentos:
        print(f"  - {doc.nome} ({doc.get_nome_exibicao()}) - Tipo: {doc.tipo_contratacao}, Obrigatório: {doc.obrigatorio}")
    
    if not tipos_documentos.exists():
        messages.error(request, f'Nenhum tipo de documento encontrado para {candidato.get_tipo_contratacao_display()}. Verifique a configuração dos tipos de documentos.')
        return redirect('lista_candidatos')
    
    # Dicionário com instruções específicas para cada tipo de documento
    instrucoes_documentos = {
        # Documentos CLT
        'FOTO_3X4': 'foto 3x4 recente',
        'CARTEIRA_TRABALHO_DIGITAL': 'com todos os registros anteriores',
        'EXTRATO_PIS': 'extrato atualizado',
        'ASO': 'exame médico admissional',
        'CONTA_SALARIO': 'comprovante de abertura',
        'RG': 'frente e verso (imagens separadas)',
        'CPF': 'foto do documento',
        'TITULO_ELEITOR': 'frente do documento',
        'CERTIFICADO_RESERVISTA': 'documento completo',
        'COMPROVANTE_ESCOLARIDADE': 'diploma ou certificado',
        'CERTIFICADOS_CURSOS_NRS': 'todos os certificados',
        'CNH': 'frente e verso',
        'CARTAO_VACINAS': 'cartão atualizado (incluindo Covid)',
        'COMPROVANTE_RESIDENCIA': 'conta recente com CEP',
        'CERTIDAO_CASAMENTO': 'documento oficial',
        'RG_CPF_ESPOSA': 'documentos da esposa',
        'CERTIDAO_NASCIMENTO_FILHOS': 'com CPF dos filhos',
        'CARTEIRA_VACINACAO_FILHOS': 'menores de 06 anos',
        'DECLARACAO_MATRICULA_FILHOS': 'a partir de 06 anos',
        'CERTIDAO_NASCIMENTO': 'documento oficial de nascimento', # Adicionado
        
        # Documentos PJ
        'CNPJ': 'cartão CNPJ atualizado',
        'NUMERO_CONTA_PIX': 'dados bancários e PIX',
        'EMAIL_CONTRATO': 'e-mail ativo para contrato',
        'RG_CPF_CONJUGE': 'documentos do cônjuge',
        'RG_CPF_FILHOS': 'documentos dos filhos',
        
        # Documentos comuns
        'FOTO_ROSTO': 'selfie frontal bem iluminada',
    }
    
    # Separa os documentos em obrigatórios e opcionais
    documentos_obrigatorios = []
    documentos_opcionais = []
    
    for tipo_doc in tipos_documentos:
        if tipo_doc.obrigatorio:
            documentos_obrigatorios.append(tipo_doc)
        else:
            documentos_opcionais.append(tipo_doc)
            
    lista_obrigatorios = ""
    if documentos_obrigatorios:
        lista_obrigatorios += "*Documentos Obrigatórios:*\n"
        contador = 1
        for tipo_doc in documentos_obrigatorios:
            # Garante que o nome do tipo de documento está em maiúsculas para corresponder às chaves do dicionário
            codigo = tipo_doc.nome.upper() 
            instrucao = instrucoes_documentos.get(codigo, 'conforme solicitado.') # Fallback mais descritivo
#            lista_obrigatorios += f"{contador}. *{tipo_doc.get_nome_exibicao()}* - {instrucao}\n"
            lista_obrigatorios += f"{contador}. *{tipo_doc.get_nome_exibicao()}*\n"
            contador += 1
            
    lista_opcionais = ""
    if documentos_opcionais:
        lista_opcionais += "\n*Documentos Opcionais:*\n"
        contador = 1
        for tipo_doc in documentos_opcionais:
            # Garante que o nome do tipo de documento está em maiúsculas para corresponder às chaves do dicionário
            codigo = tipo_doc.nome.upper()
            instrucao = instrucoes_documentos.get(codigo, 'conforme solicitado.') # Fallback mais descritivo
#            lista_opcionais += f"{contador}. *{tipo_doc.get_nome_exibicao()}* - {instrucao}\n"
            lista_opcionais += f"{contador}. *{tipo_doc.get_nome_exibicao()}*\n"
            contador += 1
    
    # Monta a mensagem completa baseada no tipo de contratação
    tipo_contratacao_display = candidato.get_tipo_contratacao_display()
    
    mensagem = (
        f"Olá {candidato.nome}!\n\n"
        f"*Bem-vindo ao processo de contratação {tipo_contratacao_display}!*\n\n"
        f"{lista_obrigatorios}"
        f"{lista_opcionais}\n"
        "*Instruções:*\n"
        "• Envie cada documento *separadamente*\n"
        "• Use *fotos* claras e legíveis ou *PDF*\n"
        "• Aguarde confirmação após cada envio\n\n"
        "Dúvidas? Estamos à disposição para ajudar!"
    )
    
#    print(f"Mensagem gerada:\n{mensagem}")
    
    try:
        # Adiciona o prefixo 55 ao número do telefone
        telefone_completo = f"55{candidato.telefone_limpo}"
        enviar_mensagem_whatsapp(telefone_completo, mensagem)
        
        # Cria os registros de documentos necessários
        documentos_criados = 0
        for tipo_doc in tipos_documentos:
            documento, created = Documento.objects.get_or_create(
                candidato=candidato,
                tipo=tipo_doc,
                defaults={'status': 'pendente'}
            )
            if created:
                documentos_criados += 1
        
        print(f"Documentos criados: {documentos_criados}")
        
        # Atualiza o status para documentos pendentes
        candidato.status = 'documentos_pendentes'
        candidato.mensagem_enviada = True
        candidato.save()
        
        # Registra o evento na timeline
        from .utils.timeline import registrar_evento
        registrar_evento(
            candidato=candidato,
            tipo_evento='mensagem_enviada',
            status_anterior='ativo',
            status_novo='documentos_pendentes',
            observacoes=f"Processo {tipo_contratacao_display} iniciado por {request.user.username}. {documentos_criados} documentos criados."
        )
        
        messages.success(request, f'Processo {tipo_contratacao_display} iniciado para {candidato.nome}. Mensagem WhatsApp enviada com sucesso!')
    except Exception as e:
        print(f"Erro ao iniciar processo: {str(e)}")
        messages.error(request, f'Erro ao iniciar processo: {str(e)}')
    
    return redirect('lista_candidatos')


from django.db import connection, transaction
from django.http import HttpResponseBadRequest, HttpResponseNotAllowed

def _redirect_candidato(request, candidato_id):
    # 1) tenta voltar pra onde estava
    referer = request.META.get("HTTP_REFERER")
    if referer:
        return redirect(referer)

    # 2) tenta alguns nomes comuns de rota de detalhes
    for name in ("detalhes_candidato", "candidato_detalhes"):
        try:
            return redirect(reverse(name, args=[candidato_id]))
        except NoReverseMatch:
            pass

    # 3) fallback: lista de candidatos
    try:
        return redirect(reverse("lista_candidatos"))
    except NoReverseMatch:
        return redirect("/")  # fallback final

@login_required
@transaction.atomic
def rejeitar_candidato(request, candidato_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE rh_candidato SET status = 'rejeitado' WHERE id = %s",
            [candidato_id],
        )
    messages.success(request, "Candidato rejeitado com sucesso.")
    return _redirect_candidato(request, candidato_id)

@login_required
@transaction.atomic
def remover_rejeicao_candidato(request, candidato_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    # 1) há documentos inválidos?
    with connection.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) 
              FROM rh_documento d
             WHERE d.candidato_id = %s
               AND d.status = 'invalido'
        """, [candidato_id])
        total_invalidos = cur.fetchone()[0] or 0

    if total_invalidos > 0:
        novo_status = "documentos_invalidos"
    else:
        # 2) verificar obrigatórios do candidato
        with connection.cursor() as cur:
            cur.execute("""
                SELECT d.status
                  FROM rh_documento d
                  JOIN rh_tipodocumento t ON t.id = d.tipo_id
                 WHERE d.candidato_id = %s
                   AND t.obrigatorio = 1
            """, [candidato_id])
            obrigatorios = [row[0] for row in cur.fetchall()]

        if not obrigatorios:
            novo_status = "concluido"
        else:
            if any(st in ("pendente", "recebido") for st in obrigatorios):
                novo_status = "documentos_pendentes"
            else:
                novo_status = "concluido"

    with connection.cursor() as cur:
        cur.execute(
            "UPDATE rh_candidato SET status = %s WHERE id = %s",
            [novo_status, candidato_id],
        )

    messages.success(
        request,
        f"Rejeição removida. Status recalculado para: {novo_status.replace('_', ' ')}."
    )
    return _redirect_candidato(request, candidato_id)




@login_required
def estatisticas(request):
    """
    View para exibir estatísticas e gráficos com dados reais utilizando a timeline
    para maior precisão e insights mais detalhados
    """
    
    # Verificar se o usuário tem acesso às estatísticas
    if not tem_acesso_completo(request.user):
        return redirect('meus_candidatos')
    
    from django.db.models import Count, Avg, F, ExpressionWrapper, fields, Q, Sum, Min, Max, StdDev
    from django.db.models.functions import TruncMonth, TruncDay, TruncWeek, ExtractWeekDay
    from datetime import timedelta
    from dateutil.relativedelta import relativedelta
    import json
    from .models import Candidato, Documento, RegistroTempo
    from datetime import datetime

    # Função auxiliar para formatar tempo
    def format_time(days):
            if days is None:
                return "N/A"
            
            total_minutes = days * 24 * 60
            
            if total_minutes < 60:
                return f"{round(total_minutes)} minutos"
            elif total_minutes < 1440:  # menos de 24 horas
                horas = int(total_minutes / 60)
                minutosRestantes = int(total_minutes % 60)
                return f"{horas}h {minutosRestantes}min" if minutosRestantes > 0 else f"{horas} horas"
            elif days < 30:
                return f"{round(days * 10) / 10} dias"
            else:
                meses = round(days / 30 * 10) / 10
                return f"{meses} meses"
    
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
        'rejeitado': '#6B7280',  # cinza escuro
    }
    status_colors_array = []
    
    for item in status_counts:
            status_display = dict(Candidato.STATUS_CHOICES).get(item['status'], item['status'])
            status_labels.append(status_display)
            status_data.append(item['total'])
            status_colors_array.append(status_colors.get(item['status'], '#6B7280'))
    
    tipos_eventos = list(RegistroTempo.objects.values_list('tipo_evento', flat=True).distinct())
    
    # Obter candidatos concluídos
    candidatos_concluidos_ids = Candidato.objects.filter(status='concluido').values_list('id', flat=True)
    
    # Calcular o tempo total para cada candidato concluído
    tempo_total_por_candidato = []
    
    for candidato_id in candidatos_concluidos_ids:
        try:
            # Obter o candidato
            candidato = Candidato.objects.get(id=candidato_id)
            
            # Obter o último evento deste candidato
            ultimo_evento = RegistroTempo.objects.filter(
                candidato_id=candidato_id
            ).order_by('-data_hora').first()
            
            # Calcular a diferença entre a data de cadastro e o último evento
            if candidato and ultimo_evento and ultimo_evento.data_hora > candidato.data_cadastro:
                tempo_total = (ultimo_evento.data_hora - candidato.data_cadastro).total_seconds()
                tempo_total_por_candidato.append(tempo_total)
        except (Candidato.DoesNotExist, RegistroTempo.DoesNotExist):
            continue
    
    # Calcular estatísticas
    if tempo_total_por_candidato:
        tempo_medio_total_segundos = sum(tempo_total_por_candidato) / len(tempo_total_por_candidato)
        tempo_min_total_segundos = min(tempo_total_por_candidato)
        tempo_max_total_segundos = max(tempo_total_por_candidato)
        
        # Converter para dias
        tempo_medio_total_dias = tempo_medio_total_segundos / 86400
        tempo_min_total_dias = tempo_min_total_segundos / 86400
        tempo_max_total_dias = tempo_max_total_segundos / 86400
        
        # Formatar para exibição
        tempo_medio_total_formatado = format_time(tempo_medio_total_dias)
        tempo_min_total_formatado = format_time(tempo_min_total_dias)
        tempo_max_total_formatado = format_time(tempo_max_total_dias)
        
    else:
        # Tentar outra abordagem: usar a data de cadastro e a data do último documento validado
        candidatos_com_docs_validados = Candidato.objects.filter(
            documentos__status='validado'
        ).distinct()
        
        tempo_total_por_candidato_alt = []
        
        for candidato in candidatos_com_docs_validados:
            # Obter a data do último documento validado
            ultimo_doc_validado = RegistroTempo.objects.filter(
                candidato_id=candidato.id,
                tipo_evento='documento_validado'
            ).order_by('-data_hora').first()
            
            if ultimo_doc_validado and ultimo_doc_validado.data_hora > candidato.data_cadastro:
                tempo_total = (ultimo_doc_validado.data_hora - candidato.data_cadastro).total_seconds()
                tempo_total_por_candidato_alt.append(tempo_total)
        
        if tempo_total_por_candidato_alt:
            tempo_medio_total_segundos = sum(tempo_total_por_candidato_alt) / len(tempo_total_por_candidato_alt)
            tempo_min_total_segundos = min(tempo_total_por_candidato_alt)
            tempo_max_total_segundos = max(tempo_total_por_candidato_alt)
            
            # Converter para dias
            tempo_medio_total_dias = tempo_medio_total_segundos / 86400
            tempo_min_total_dias = tempo_min_total_segundos / 86400
            tempo_max_total_dias = tempo_max_total_segundos / 86400
            
            # Formatar para exibição
            tempo_medio_total_formatado = format_time(tempo_medio_total_dias)
            tempo_min_total_formatado = format_time(tempo_min_total_dias)
            tempo_max_total_formatado = format_time(tempo_max_total_dias)
            
        else:
            tempo_medio_total_formatado = "N/A"
            tempo_min_total_formatado = "N/A"
            tempo_max_total_formatado = "N/A"
    
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
    
    # Etapas do processo com tempos médios
    etapas_labels = ['Cadastro', 'Envio de Docs', 'Validação', 'Conclusão']
    
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
#    etapas_labels = ['Cadastro', 'Envio de Docs', 'Validação', 'Conclusão']
    etapas_labels = ['Envio de Docs', 'Validação', 'Conclusão']
    
    etapas_data = [
    #    0,  # Cadastro é instantâneo
        tempo_solicitacao_recebimento['avg_tempo'].total_seconds() / 86400 if tempo_solicitacao_recebimento['avg_tempo'] else None,
        tempo_recebimento_validacao['avg_tempo'].total_seconds() / 86400 if tempo_recebimento_validacao['avg_tempo'] else None,
        tempo_cadastro_conclusao['avg_tempo'].total_seconds() / 86400 if tempo_cadastro_conclusao['avg_tempo'] else None,
    ]
    
    # Dados para variabilidade de tempo por etapa (novo gráfico)
    etapas_std_dev = [
    #    0,  # Cadastro é instantâneo
        tempo_solicitacao_recebimento['std_tempo'].total_seconds() / 86400 if tempo_solicitacao_recebimento['std_tempo'] else None,
        tempo_recebimento_validacao['std_tempo'].total_seconds() / 86400 if tempo_recebimento_validacao['std_tempo'] else None,
        tempo_cadastro_conclusao['std_tempo'].total_seconds() / 86400 if tempo_cadastro_conclusao['std_tempo'] else None,
    ]
    
    etapas_min = [
    #    0,  # Cadastro é instantâneo
        tempo_solicitacao_recebimento['min_tempo'].total_seconds() / 86400 if tempo_solicitacao_recebimento['min_tempo'] else None,
        tempo_recebimento_validacao['min_tempo'].total_seconds() / 86400 if tempo_recebimento_validacao['min_tempo'] else None,
        tempo_cadastro_conclusao['min_tempo'].total_seconds() / 86400 if tempo_cadastro_conclusao['min_tempo'] else None,
    ]
    
    etapas_max = [
    #    0,  # Cadastro é instantâneo
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

    # Modificar para agrupar por dia em vez de mês
    tempo_medio_por_dia_raw = RegistroTempo.objects.filter(
        tipo_evento__in=['documento_validado', 'documento_recebido'],  # Usar eventos que existem no banco
        data_hora__date__gte=data_inicio,
        data_hora__date__lte=data_fim
    ).annotate(
        dia=TruncDay('data_hora')
    ).values('dia', 'candidato', 'tempo_desde_evento_anterior')

    # Processar manualmente para calcular a média por dia
    tempo_por_dia = {}
    for item in tempo_medio_por_dia_raw:
        dia_str = item['dia'].strftime('%Y-%m-%d')
        if dia_str not in tempo_por_dia:
            tempo_por_dia[dia_str] = []
        
        if item['tempo_desde_evento_anterior']:
            tempo_por_dia[dia_str].append(item['tempo_desde_evento_anterior'].total_seconds())

    # Criar uma lista de todos os dias no intervalo
    dias_completos = []
    dia_atual = data_inicio
    while dia_atual <= data_fim:
        dias_completos.append(dia_atual.strftime('%Y-%m-%d'))
        dia_atual += timedelta(days=1)
    
#    dados_tempo_medio = [None] * len(meses_completos) # para meses
    dados_tempo_medio = [None] * len(dias_completos) # para dias

    # for i, mes in enumerate(meses_completos):
    #     if mes in tempo_por_mes and tempo_por_mes[mes]:
    #         # Calcular a média manualmente
    #         media_segundos = sum(tempo_por_mes[mes]) / len(tempo_por_mes[mes])
    #         dados_tempo_medio[i] = media_segundos / 86400  # Converter para dias
    
    # Calcular a média para cada dia
    for i, dia in enumerate(dias_completos):
        if dia in tempo_por_dia and tempo_por_dia[dia]:
            # Calcular a média manualmente
            media_segundos = sum(tempo_por_dia[dia]) / len(tempo_por_dia[dia])
            dados_tempo_medio[i] = media_segundos / 86400  # Converter para dias

    # Calcular média móvel para suavizar os dados (opcional)
    dados_tempo_medio_suavizado = []
    janela = 7  # Média móvel de 7 dias

    for i in range(len(dados_tempo_medio)):
        # Pegar os valores não nulos na janela
        valores_janela = [
            dados_tempo_medio[j] 
            for j in range(max(0, i - janela + 1), i + 1) 
            if dados_tempo_medio[j] is not None
        ]
        
        if valores_janela:
            dados_tempo_medio_suavizado.append(sum(valores_janela) / len(valores_janela))
        else:
            dados_tempo_medio_suavizado.append(None)

    # Agrupar por mês para exibição no gráfico (mantendo a estrutura original)
    dados_tempo_medio_por_mes = [None] * len(meses_completos)

    for i, dia in enumerate(dias_completos):
        data = datetime.strptime(dia, '%Y-%m-%d')
        mes_str = data.strftime('%b/%Y')
        mes_idx = meses_completos.index(mes_str) if mes_str in meses_completos else -1
        
        if mes_idx >= 0 and dados_tempo_medio[i] is not None:
            if dados_tempo_medio_por_mes[mes_idx] is None:
                dados_tempo_medio_por_mes[mes_idx] = []
            
            dados_tempo_medio_por_mes[mes_idx].append(dados_tempo_medio[i])

    # Calcular a média mensal a partir das médias diárias
    for i, valores in enumerate(dados_tempo_medio_por_mes):
        if valores:
            dados_tempo_medio_por_mes[i] = sum(valores) / len(valores)
        
    # Estatísticas gerais
    total_candidatos = Candidato.objects.count()
    candidatos_concluidos = Candidato.objects.filter(status='concluido').count()
    taxa_conclusao = (candidatos_concluidos / total_candidatos * 100) if total_candidatos > 0 else 0

    taxa_conclusao_css = f"{taxa_conclusao:.1f}%"        # para width no CSS (ponto)

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
    
#    tempo_medio_total_formatado = format_time(tempo_medio_total_dias)
#    tempo_min_total_formatado = format_time(tempo_min_total_dias)
#    tempo_max_total_formatado = format_time(tempo_max_total_dias)
    
    # NOVO: Taxa de rejeição de documentos mais precisa usando a timeline
    eventos_invalidacao = RegistroTempo.objects.filter(tipo_evento='documento_invalidado').count()
    eventos_validacao = RegistroTempo.objects.filter(tipo_evento='documento_validado').count()
    
    taxa_rejeicao_docs = (eventos_invalidacao / (eventos_invalidacao + eventos_validacao) * 100) if (eventos_invalidacao + eventos_validacao) > 0 else 0
    
    # NOVO: Tempo médio até primeira submissão usando a timeline
    tempo_primeira_submissao = RegistroTempo.objects.filter(
        tipo_evento='documento_recebido'
    ).values('candidato').annotate(
        primeira_submissao=Min('data_hora'),
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
    
    docs_problematicos_labels = []
    for item in docs_problematicos:
        tipo_id = item['documento__tipo']
        if tipo_id is not None:
            try:
                tipo_doc = TipoDocumento.objects.get(id=tipo_id)
                docs_problematicos_labels.append(tipo_doc.get_nome_exibicao())
            except TipoDocumento.DoesNotExist:
                docs_problematicos_labels.append(f"Tipo ID: {tipo_id}")
        else:
            docs_problematicos_labels.append("Tipo Desconhecido")
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
    
    # print('taxa_conversao_30_dias',taxa_conversao_30_dias)
    # print('concluidos_ultimos_30_dias',concluidos_ultimos_30_dias)
    # print('candidatos_ultimos_30_dias',candidatos_ultimos_30_dias)

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
            if tipo is not None:
                try:
                    tipo_doc = TipoDocumento.objects.get(id=tipo)
                    tipo_display = tipo_doc.get_nome_exibicao()
                except TipoDocumento.DoesNotExist:
                    tipo_display = f"Tipo ID: {tipo}"
            else:
                tipo_display = "Tipo Desconhecido"
        
            tempo_medio_tipo_labels.append(tipo_display)
            tempo_medio_tipo_data.append(sum(tempos) / len(tempos) / 86400)  # Média em dias
    
    tempo_medio_tipo_data_formatada = [format_time(dias) for dias in tempo_medio_tipo_data]
    
    # NOVO: Distribuição de documentos por tipo
    documentos_por_tipo = Documento.objects.values('tipo').annotate(
        total=Count('id')
    ).order_by('-total')
    
    tipos_documentos_labels = []
    for item in documentos_por_tipo:
        tipo_id = item['tipo']
        if tipo_id is not None:
            try:
                tipo_doc = TipoDocumento.objects.get(id=tipo_id)
                tipos_documentos_labels.append(tipo_doc.get_nome_exibicao())
            except TipoDocumento.DoesNotExist:
                tipos_documentos_labels.append(f"Tipo ID: {tipo_id}")
        else:
            tipos_documentos_labels.append("Tipo Desconhecido")
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
        # 'Cadastro',
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
        # total_cadastros,
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

    media_invalidacoes_int = int(round(media_invalidacoes or 0))    
    # 2. Retrabalho
    if total_docs_retrabalho > 0:

        insights.append({
            'titulo': 'Retrabalho',
            'descricao': f'{total_docs_retrabalho} documentos precisaram ser enviados mais de uma vez (média de {media_invalidacoes_int} tentativas).',
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
        'taxa_conclusao_css': taxa_conclusao_css,
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
        form = RegisterFormExtended(request.POST)
        if form.is_valid():
            user = form.save(commit=False)  #Não salva ainda no banco
            user.is_active = False          #Define como inativo
            user.save()                     #Salva no banco agora
            # user = form.save()
            login(request, user)
            messages.success(request, "Registro realizado com sucesso!")
            return redirect('dashboard')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = RegisterFormExtended()
    return render(request, 'register.html', {'form': form})




def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def dashboard(request):
    acesso_completo = tem_acesso_completo(request.user)
    
    # Parâmetro de pesquisa
    search_query = request.GET.get('search', '').strip()

    if request.method == 'POST':
        form = CandidatoForm(request.POST)
        if form.is_valid():
            candidato = form.save(commit=False)
            candidato.status = 'ativo'  # Inicia como ativo
            candidato.criado_por = request.user  # Quem criou
            candidato.save()

            messages.success(request, 'Candidato cadastrado com sucesso!')
            return redirect('detalhe_candidato', candidato_id=candidato.id)
    else:
        form = CandidatoForm()

    # 🔥 Aqui filtra conforme o tipo de usuário
    if acesso_completo:
        queryset = Candidato.objects.all()
    else:
        queryset = Candidato.objects.filter(criado_por=request.user)

    # Aplicar pesquisa se houver
    candidatos_recentes = queryset.order_by('-data_cadastro')
    
    if search_query:
        candidatos_recentes = candidatos_recentes.filter(
            Q(nome__icontains=search_query) |
            Q(status__icontains=search_query) |
            Q(tipo_contratacao__icontains=search_query) |
            Q(data_cadastro__date__icontains=search_query)
        )[:5]
    else:
        candidatos_recentes = candidatos_recentes[:5]

    context = {
        'form': form,
        'ativos_count': queryset.filter(status='ativo').count(),
        'pendentes_count': queryset.filter(status='documentos_pendentes').count(),
        'invalidos_count': queryset.filter(status='documentos_invalidos').count(),
        'concluidos_count': queryset.filter(status='concluido').count(),
        'rejeitados_count': queryset.filter(status='rejeitado').count(),
        'candidatos_recentes': candidatos_recentes,
        'search_query': search_query,
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
    # Verificar se o usuário tem acesso à lista de candidatos
    if not tem_acesso_completo(request.user):
        return redirect('meus_candidatos')
    
    status = request.GET.get('status', 'ativo')
    search_query = request.GET.get('search', '').strip()
    
    # Buscar TODOS os candidatos para contagem (sem filtro)
    todos_candidatos = Candidato.objects.all()
    
    # Aplicar filtro de status para exibição
    if status == 'todos':
        candidatos = todos_candidatos
        status_display = 'Todos'
    else:
        candidatos = Candidato.objects.filter(status=status)
        status_display = dict(Candidato.STATUS_CHOICES).get(status, status.title())
    
    # Aplicar pesquisa se houver
    if search_query:
        candidatos = candidatos.filter(
            Q(nome__icontains=search_query) |
            Q(telefone__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(status__icontains=search_query)
        )[:5]  # Máximo 5 resultados na pesquisa
    else:
        # Paginação para lista normal (15 por página)
        from django.core.paginator import Paginator
        paginator = Paginator(candidatos, 15)
        page_number = request.GET.get('page')
        candidatos = paginator.get_page(page_number)
    
    # Preparar contadores para JavaScript
    contadores = {
        'todos': todos_candidatos.count(),
        'ativo': todos_candidatos.filter(status='ativo').count(),
        'documentos_pendentes': todos_candidatos.filter(status='documentos_pendentes').count(),
        'documentos_invalidos': todos_candidatos.filter(status='documentos_invalidos').count(),
        'concluido': todos_candidatos.filter(status='concluido').count(),
        'em_andamento': todos_candidatos.filter(status='em_andamento').count(),
        'rejeitado': todos_candidatos.filter(status='rejeitado').count(),
    }
    
    context = {
        'candidatos': candidatos,
        'todos_candidatos': todos_candidatos,  # Para JavaScript
        'contadores': contadores,
        'status_display': status_display,
        'status_atual': status,
        'search_query': search_query,
        'is_search': bool(search_query),
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
    elif candidato.documentos.filter(tipo__obrigatorio=True, status__in=['validado', 'nao_possui']).count() == \
         candidato.documentos.filter(tipo__obrigatorio=True).count() and \
         candidato.documentos.filter(tipo__obrigatorio=True).count() > 0:
        candidato.status = 'concluido'
    # Verifica se há documentos pendentes (obrigatórios ou não)
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
                # Chamar a função para atualizar o status do candidato após a exclusão
                atualizar_status_candidato(candidato)
                return redirect('detalhe_candidato', candidato_id=candidato.id)
        else:
            form = DocumentoForm(request.POST, request.FILES, instance=documento, candidato=candidato)
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
                
                # Se for um novo documento, envia mensagem WhatsApp
                if not documento:
                    try:
                        # Enviar solicitação do documento via WhatsApp
                        mensagem = f"Olá {candidato.nome}! \nPor favor, envie o documento: *{doc.tipo.get_nome_exibicao()}*. \nCertifique-se de que a imagem está clara e legível."
                        atualizar_status_candidato(candidato)
                        enviar_mensagem_whatsapp(candidato.telefone_limpo, mensagem)
                        messages.success(request, f'Documento foi adicionado com sucesso e solicitação enviada via WhatsApp para {candidato.nome}.')
                    except Exception as e:
                        messages.warning(request, f'Documento adicionado, mas não foi possível enviar a mensagem WhatsApp: {str(e)}')
                
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
                
                return redirect('detalhe_candidato', candidato_id=candidato.id)
    else:
        form = DocumentoForm(instance=documento, candidato=candidato)
    
    # REMOVIDO: A pré-formatação de registro.tempo_formatado será feita diretamente no template com o filtro.
    # if documento:
    #     from .utils.timeline import formatar_duracao
    #     registros = documento.registros_tempo.all().order_by('-data_hora')
    #     for registro in registros:
    #         registro.tempo_formatado = formatar_duracao(registro.tempo_desde_evento_anterior)
    
    context = {
        'form': form,
        'candidato': candidato,
        'documento': documento,
        'is_new': documento is None
    }
    return render(request, 'documento_form.html', context)


# @login_required
# @require_http_methods(["POST"])
# def atualizar_status_documento(request, candidato_id, documento_id):
#     """
#     View para atualizar o status de um documento via AJAX
#     """
#     # Verificar se é uma requisição AJAX
#     if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
#         return JsonResponse({'success': False, 'error': 'Requisição inválida'}, status=400)
    
#     try:
#         candidato = get_object_or_404(Candidato, id=candidato_id)
#         documento = get_object_or_404(Documento, id=documento_id, candidato=candidato)
        
#         novo_status = request.POST.get('status')
#         if novo_status not in dict(Documento.STATUS_CHOICES):
#             return JsonResponse({'success': False, 'error': 'Status inválido'}, status=400)
        
#         # Guardar o status anterior
#         status_anterior = documento.status
        
#         # Atualizar o status
#         documento.status = novo_status
        
#         # Se o status for alterado para validado
#         if novo_status == 'validado':
#             documento.data_validacao = timezone.now()
#         # Se o status for alterado para recebido
#         elif novo_status == 'recebido':
#             documento.data_envio = timezone.now()
        
#         documento.save()
        
#         # Registrar o evento na timeline
#         from .utils.timeline import registrar_evento
        
#         # Determina o tipo de evento com base no novo status
#         if novo_status == 'recebido':
#             tipo_evento = 'documento_recebido'
#         elif novo_status == 'validado':
#             tipo_evento = 'documento_validado'
#         elif novo_status == 'invalido':
#             tipo_evento = 'documento_invalidado'
#         else:
#             tipo_evento = 'documento_solicitado'
        
#         # Registra o evento na timeline
#         registrar_evento(
#             candidato=candidato,
#             tipo_evento=tipo_evento,
#             documento=documento,
#             status_anterior=status_anterior,
#             status_novo=novo_status,
#             observacoes=f"Status alterado via interface web por {request.user.username}"
#         )
        
#         # Atualizar o status do candidato
#         atualizar_status_candidato(candidato)
        
#         return JsonResponse({'success': True})
    
#     except Exception as e:
#         return JsonResponse({'success': False, 'error': str(e)}, status=500)

# @login_required
# def atualizar_status_documento(request, candidato_id, documento_id):
#     """View para atualizar status do documento com modal para invalidação e envio WhatsApp"""
#     if request.method == 'POST':
#         from .models import Documento, TipoDocumento
#         from .whatsapp import enviar_mensagem_whatsapp
#         from .utils.timeline import registrar_evento
#         import json
        
#         candidato = get_object_or_404(Candidato, id=candidato_id)
#         documento = get_object_or_404(Documento, id=documento_id, candidato=candidato)
        
#         try:
#             # Se for requisição AJAX para invalidação com motivo
#             if request.content_type == 'application/json':
#                 data = json.loads(request.body)
#                 novo_status = data.get('status')
#                 motivo_invalidacao = data.get('motivo', '').strip()
#                 enviar_mensagem = data.get('enviar_mensagem', True)
#             else:
#                 # Requisição normal de formulário
#                 novo_status = request.POST.get('status')
#                 motivo_invalidacao = request.POST.get('motivo', '').strip()
#                 enviar_mensagem = request.POST.get('enviar_mensagem') == 'on'
            
#             if not novo_status:
#                 return JsonResponse({'success': False, 'error': 'Status não fornecido'})
            
#             # Atualizar status do documento
#             documento.status = novo_status
#             documento.save()
            
#             atualizar_status_candidato(candidato)
            
#             if novo_status == 'invalido' and enviar_mensagem:
#                 nome_documento = documento.tipo.get_nome_exibicao()
                
#                 if motivo_invalidacao:
#                     # Mensagem com motivo personalizado
#                     mensagem = f"""🔔 *Olá {candidato.nome}!*

# 📋 *Documento Invalidado: {nome_documento}*

# ❌ *Motivo da invalidação:*
# *{motivo_invalidacao}*

# ⏰ Por favor, nos reenvie o documento corrigido o mais breve possível para darmos continuidade ao seu processo.

# Agradecemos sua compreensão!

# *Equipe RH - BRG Geradores*"""
#                 else:
#                     # Mensagem padrão sem motivo
#                     mensagem = f"""🔔 *Olá {candidato.nome}!*

# 📋 *Documento Invalidado: {nome_documento}*

# ⏰ Por favor, nos reenvie novamente o documento *{nome_documento}* o mais breve possível para darmos continuidade ao seu processo.

# Agradecemos sua compreensão!

# *Equipe RH - BRG Geradores*"""
                
#                 # Enviar mensagem via WhatsApp
#                 try:
#                     resposta_whatsapp = enviar_mensagem_whatsapp(candidato.telefone, mensagem)
                    
#                     if isinstance(resposta_whatsapp, dict):
#                         # Se retornou um dicionário, verificar o status
#                         status_whatsapp = resposta_whatsapp.get('status', '').upper()
#                         sucesso_whatsapp = status_whatsapp in ['PENDING', 'SENT', 'DELIVERED']
#                     else:
#                         # Se retornou True/False diretamente
#                         sucesso_whatsapp = bool(resposta_whatsapp)
                    
#                     # Registrar no histórico
#                     HistoricoCobranca.objects.create(
#                         candidato=candidato,
#                         mensagem_enviada=mensagem,
#                         documentos_cobrados=[nome_documento],
#                         sucesso=sucesso_whatsapp,
#                         erro=None if sucesso_whatsapp else 'Erro ao enviar mensagem via WhatsApp'
#                     )
                    
#                     if not sucesso_whatsapp:
#                         messages.warning(request, f'Documento invalidado, mas houve erro ao enviar mensagem WhatsApp para {candidato.nome}')
#                     else:
#                         messages.success(request, f'Documento invalidado e mensagem enviada via WhatsApp para {candidato.nome}')
                        
#                 except Exception as e:
#                     messages.warning(request, f'Documento invalidado, mas erro ao enviar WhatsApp: {str(e)}')
#             elif novo_status == 'invalido' and not enviar_mensagem:
#                 messages.success(request, f'Documento invalidado (mensagem WhatsApp não enviada)')
            
#             # Registrar evento na timeline
#             registrar_evento(
#                 candidato=candidato,
#                 tipo_evento='documento_invalidado' if novo_status == 'invalido' else 'documento_validado',
#                 documento=documento,
#                 status_novo=novo_status,
# #                observacoes=f'Status do documento {documento.tipo.get_nome_exibicao()} alterado para {novo_status}'
#                 observacoes=f"Status alterado via interface web por {request.user.username}"
#             )
            
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
#                 return JsonResponse({
#                     'success': True, 
#                     'message': 'Status atualizado com sucesso!',
#                     'novo_status': novo_status
#                 })
#             else:
#                 messages.success(request, 'Status do documento atualizado com sucesso!')
#                 return redirect('detalhe_candidato', candidato_id=candidato_id)
                
#         except json.JSONDecodeError:
#             return JsonResponse({'success': False, 'error': 'Dados JSON inválidos'})
#         except Exception as e:
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
#                 return JsonResponse({'success': False, 'error': str(e)})
#             else:
#                 messages.error(request, f'Erro ao atualizar status: {str(e)}')
#                 return redirect('detalhe_candidato', candidato_id=candidato_id)
    
#     return JsonResponse({'success': False, 'error': 'Método não permitido'})



@login_required
def atualizar_status_documento(request, candidato_id, documento_id):
    """View para atualizar status do documento com modal para invalidação e envio WhatsApp"""
    if request.method == 'POST':
        from .models import Documento, TipoDocumento
        from .whatsapp import enviar_mensagem_whatsapp
        from .utils.timeline import registrar_evento
        import json
        
        candidato = get_object_or_404(Candidato, id=candidato_id)
        documento = get_object_or_404(Documento, id=documento_id, candidato=candidato)
        
        try:
            # Se for requisição AJAX para invalidação com motivo
            if request.content_type == 'application/json':
                data = json.loads(request.body)
                novo_status = data.get('status')
                motivo_invalidacao = data.get('motivo', '').strip()
                enviar_mensagem = data.get('enviar_mensagem', True)
            else:
                # Requisição normal de formulário
                novo_status = request.POST.get('status')
                motivo_invalidacao = request.POST.get('motivo', '').strip()
                enviar_mensagem = request.POST.get('enviar_mensagem') == 'on'
            
            if not novo_status:
                return JsonResponse({'success': False, 'error': 'Status não fornecido'})
            
            status_candidato_anterior = candidato.status
            
            # Atualizar status do documento
            documento.status = novo_status
            documento.save()
            
            atualizar_status_candidato(candidato)
            
            candidato.refresh_from_db()
            candidato_concluido = (status_candidato_anterior != 'concluido' and candidato.status == 'concluido')
            
            if novo_status == 'validado':
                nome_documento = documento.tipo.get_nome_exibicao()
                
                if candidato_concluido:
                    # Documento validado E processo concluído
                    mensagem = f"""🎉 *Parabéns {candidato.nome}!*

✅ *Documento Validado: {nome_documento}*

🏆 *Seu processo de contratação foi CONCLUÍDO com sucesso!*

📋 Todos os seus documentos foram aprovados e seu processo foi repassado para nossa equipe de RH para os próximos passos.

Em breve entraremos em contato com você!

*Equipe RH - BRG Geradores*"""
                else:
                    # Apenas documento validado
                    mensagem = f"""✅ *Olá {candidato.nome}!*

📋 *Documento Validado: {nome_documento}*

👍 Seu documento foi aprovado com sucesso!

*Equipe RH - BRG Geradores*"""
                
                # Enviar mensagem via WhatsApp
                try:
                    resposta_whatsapp = enviar_mensagem_whatsapp(candidato.telefone, mensagem)
                    
                    if isinstance(resposta_whatsapp, dict):
                        status_whatsapp = resposta_whatsapp.get('status', '').upper()
                        sucesso_whatsapp = status_whatsapp in ['PENDING', 'SENT', 'DELIVERED']
                    else:
                        sucesso_whatsapp = bool(resposta_whatsapp)
                    
                    # Registrar no histórico
                    HistoricoCobranca.objects.create(
                        candidato=candidato,
                        mensagem_enviada=mensagem,
                        documentos_cobrados=[nome_documento],
                        sucesso=sucesso_whatsapp,
                        erro=None if sucesso_whatsapp else 'Erro ao enviar mensagem via WhatsApp'
                    )
                    
                    if not sucesso_whatsapp:
                        messages.warning(request, f'Documento validado, mas houve erro ao enviar mensagem WhatsApp para {candidato.nome}')
                    else:
                        messages.success(request, f'Documento validado e mensagem enviada via WhatsApp para {candidato.nome}')
                        
                except Exception as e:
                    messages.warning(request, f'Documento validado, mas erro ao enviar WhatsApp: {str(e)}')
            
            elif candidato_concluido and novo_status != 'validado':
                mensagem = f"""🎉 *Parabéns {candidato.nome}!*

🏆 *Seu processo de contratação foi CONCLUÍDO com sucesso!*

📋 Todos os seus documentos foram aprovados e seu processo foi repassado para nossa equipe de RH para os próximos passos.

Em breve entraremos em contato com você!

*Equipe RH - BRG Geradores*"""
                
                try:
                    resposta_whatsapp = enviar_mensagem_whatsapp(candidato.telefone, mensagem)
                    
                    if isinstance(resposta_whatsapp, dict):
                        status_whatsapp = resposta_whatsapp.get('status', '').upper()
                        sucesso_whatsapp = status_whatsapp in ['PENDING', 'SENT', 'DELIVERED']
                    else:
                        sucesso_whatsapp = bool(resposta_whatsapp)
                    
                    HistoricoCobranca.objects.create(
                        candidato=candidato,
                        mensagem_enviada=mensagem,
                        documentos_cobrados=[],
                        sucesso=sucesso_whatsapp,
                        erro=None if sucesso_whatsapp else 'Erro ao enviar mensagem via WhatsApp'
                    )
                    
                    if not sucesso_whatsapp:
                        messages.warning(request, f'Processo concluído, mas houve erro ao enviar mensagem WhatsApp para {candidato.nome}')
                    else:
                        messages.success(request, f'Processo concluído e mensagem enviada via WhatsApp para {candidato.nome}')
                        
                except Exception as e:
                    messages.warning(request, f'Processo concluído, mas erro ao enviar WhatsApp: {str(e)}')
            
            # Lógica existente para invalidação
            elif novo_status == 'invalido' and enviar_mensagem:
                nome_documento = documento.tipo.get_nome_exibicao()
                
                if motivo_invalidacao:
                    # Mensagem com motivo personalizado
                    mensagem = f"""🔔 *Olá {candidato.nome}!*

📋 *Documento Invalidado: {nome_documento}*

❌ *Motivo da invalidação:*
*{motivo_invalidacao}*

⏰ Por favor, nos reenvie o documento corrigido o mais breve possível para darmos continuidade ao seu processo.

Agradecemos sua compreensão!

*Equipe RH - BRG Geradores*"""
                else:
                    # Mensagem padrão sem motivo
                    mensagem = f"""🔔 *Olá {candidato.nome}!*

📋 *Documento Invalidado: {nome_documento}*

⏰ Por favor, nos reenvie novamente o documento *{nome_documento}* o mais breve possível para darmos continuidade ao seu processo.

Agradecemos sua compreensão!

*Equipe RH - BRG Geradores*"""
                
                # Enviar mensagem via WhatsApp
                try:
                    resposta_whatsapp = enviar_mensagem_whatsapp(candidato.telefone, mensagem)
                    
                    if isinstance(resposta_whatsapp, dict):
                        # Se retornou um dicionário, verificar o status
                        status_whatsapp = resposta_whatsapp.get('status', '').upper()
                        sucesso_whatsapp = status_whatsapp in ['PENDING', 'SENT', 'DELIVERED']
                    else:
                        # Se retornou True/False diretamente
                        sucesso_whatsapp = bool(resposta_whatsapp)
                    
                    # Registrar no histórico
                    HistoricoCobranca.objects.create(
                        candidato=candidato,
                        mensagem_enviada=mensagem,
                        documentos_cobrados=[nome_documento],
                        sucesso=sucesso_whatsapp,
                        erro=None if sucesso_whatsapp else 'Erro ao enviar mensagem via WhatsApp'
                    )
                    
                    if not sucesso_whatsapp:
                        messages.warning(request, f'Documento invalidado, mas houve erro ao enviar mensagem WhatsApp para {candidato.nome}')
                    else:
                        messages.success(request, f'Documento invalidado e mensagem enviada via WhatsApp para {candidato.nome}')
                        
                except Exception as e:
                    messages.warning(request, f'Documento invalidado, mas erro ao enviar WhatsApp: {str(e)}')
            elif novo_status == 'invalido' and not enviar_mensagem:
                messages.success(request, f'Documento invalidado (mensagem WhatsApp não enviada)')
            
            # Registrar evento na timeline
            registrar_evento(
                candidato=candidato,
                tipo_evento='documento_invalidado' if novo_status == 'invalido' else 'documento_validado',
                documento=documento,
                status_novo=novo_status,
                observacoes=f"Status alterado via interface web por {request.user.username}"
            )
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({
                    'success': True, 
                    'message': 'Status atualizado com sucesso!',
                    'novo_status': novo_status
                })
            else:
                messages.success(request, 'Status do documento atualizado com sucesso!')
                return redirect('detalhe_candidato', candidato_id=candidato_id)
                
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Dados JSON inválidos'})
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({'success': False, 'error': str(e)})
            else:
                messages.error(request, f'Erro ao atualizar status: {str(e)}')
                return redirect('detalhe_candidato', candidato_id=candidato_id)
    
    return JsonResponse({'success': False, 'error': 'Método não permitido'})


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

# @login_required
# @user_passes_test(is_admin)
# def admin_dashboard(request):
#     """Dashboard de administração para gerenciar usuários e setores"""
#     usuarios = User.objects.all().order_by('-date_joined')
#     setores = Setor.objects.all().order_by('nome')
    
#     # Calcular totais para o dashboard
#     total_setores = setores.count()
#     total_usuarios = usuarios.count()
#     total_admins = usuarios.filter(is_staff=True).count()
#     total_ativos = usuarios.filter(is_active=True).count()
#     total_pendentes = usuarios.filter(is_active=False).count()
    
#     context = {
#         'usuarios': usuarios,
#         'setores': setores,
#         'tem_acesso_completo': tem_acesso_completo(request.user),
#         'total_setores': total_setores,
#         'total_usuarios': total_usuarios,
#         'total_admins': total_admins,
#         'total_ativos': total_ativos,
#         'total_pendentes': total_pendentes
#     }
#     return render(request, 'admin_dashboard.html', context)

@login_required
@user_passes_test(is_admin)
def gerenciar_setor(request, setor_id=None):
    """Criar ou editar um setor"""
    setor = None if setor_id is None else get_object_or_404(Setor, id=setor_id)
    
    if request.method == 'POST':
        form = SetorForm(request.POST, instance=setor)
        if form.is_valid():
            form.save()
            messages.success(request, 'Setor salvo com sucesso!')
            return redirect('admin_dashboard')
    else:
        form = SetorForm(instance=setor)
    
    return render(request, 'gerenciar_setor.html', {
        'form': form,
        'setor': setor,
        'is_new': setor is None
    })

@login_required
@user_passes_test(is_admin)
def excluir_setor(request, setor_id):
    """Excluir um setor"""
    setor = get_object_or_404(Setor, id=setor_id)
    if request.method == 'POST':
        setor.delete()
        messages.success(request, 'Setor excluído com sucesso!')
        return redirect('admin_dashboard')
    return redirect('admin_dashboard')

@login_required
@user_passes_test(is_admin)
def gerenciar_usuario(request, usuario_id=None):
    """Editar um usuário existente"""
    usuario = get_object_or_404(User, id=usuario_id)
    
    if request.method == 'POST':
        form = UsuarioForm(request.POST, instance=usuario)
        if form.is_valid():
            form.save()
            messages.success(request, 'Usuário atualizado com sucesso!')
            return redirect('admin_dashboard')
    else:
        form = UsuarioForm(instance=usuario)
    
    return render(request, 'gerenciar_usuario.html', {
        'form': form,
        'usuario': usuario
    })

@login_required
@user_passes_test(is_admin)
def excluir_usuario(request, usuario_id):
    """Excluir um usuário"""
    usuario = get_object_or_404(User, id=usuario_id)
    if request.method == 'POST':
        usuario.delete()
        messages.success(request, 'Usuário excluído com sucesso!')
        return redirect('admin_dashboard')
    return redirect('admin_dashboard')

@login_required
@user_passes_test(is_admin)
def ativar_usuario(request, usuario_id):
    """Ativar um usuário pendente"""
    usuario = get_object_or_404(User, id=usuario_id)
    if request.method == 'POST':
        usuario.is_active = True
        usuario.save()
        messages.success(request, f'Usuário {usuario.username} ativado com sucesso!')
        return redirect('listar_usuarios_pendentes')
    return redirect('admin_dashboard')

def meus_candidatos(request):
    """Página para usuários sem acesso completo verem seus candidatos"""
    candidatos = Candidato.objects.filter(criado_por=request.user).order_by('-data_cadastro')
    
    context = {
        'candidatos': candidatos,
    }
    return render(request, 'meus_candidatos.html', context)


def avaliacao_experiencia(request, token):
    """
    Exibe o formulário de avaliação do período de experiência.
    """

    avaliacao = get_object_or_404(AvaliacaoPeriodoExperiencia, token=token)

    if avaliacao.respondido:
        return render(request, 'avaliacao_respondida.html', {'avaliacao': avaliacao})

    if request.method == 'POST':
        avaliacao.apresenta_iniciativa = request.POST.get('apresenta_iniciativa')
        avaliacao.organizado_atividades = request.POST.get('organizado_atividades')
        avaliacao.adapta_novas_situacoes_clientes = request.POST.get('adapta_novas_situacoes_clientes')
        avaliacao.interage_bem_colegas = request.POST.get('interage_bem_colegas')
        avaliacao.aptidao_lideranca = request.POST.get('aptidao_lideranca')
        avaliacao.talento_para_funcao = request.POST.get('talento_para_funcao')
        avaliacao.pronto_para_colaborar = request.POST.get('pronto_para_colaborar')
        avaliacao.resultados_esperados = request.POST.get('resultados_esperados')
        avaliacao.colabora_membros_empresa = request.POST.get('colabora_membros_empresa')
        avaliacao.comportamento_etico = request.POST.get('comportamento_etico')
        avaliacao.desiste_facil = request.POST.get('desiste_facil')
        avaliacao.reduz_despesas_desperdicios = request.POST.get('reduz_despesas_desperdicios')
        avaliacao.comunica_claro_coerente = request.POST.get('comunica_claro_coerente')
        avaliacao.administra_tempo = request.POST.get('administra_tempo')
        avaliacao.autoconfiante = request.POST.get('autoconfiante')
        avaliacao.empenho_resultados_grupo = request.POST.get('empenho_resultados_grupo')
        avaliacao.aceita_opinioes_divergentes = request.POST.get('aceita_opinioes_divergentes')
        avaliacao.relutante_decisoes_grupo = request.POST.get('relutante_decisoes_grupo')
        avaliacao.expor_necessidades_perguntas = request.POST.get('expor_necessidades_perguntas')
        avaliacao.assiduo = request.POST.get('assiduo')
        avaliacao.aceita_ordens_gestor = request.POST.get('aceita_ordens_gestor')

        avaliacao.sugestao_critica_elogio = request.POST.get('sugestao_critica_elogio')
        avaliacao.aprova_demite = request.POST.get('aprova_demite')

        avaliacao.respondido = True
        avaliacao.data_avaliacao = date.today()
        avaliacao.save()

        return render(request, 'avaliacao_agradecimento.html', {'avaliacao': avaliacao})

    return render(request, 'avaliacao_form.html', {'avaliacao': avaliacao})


# sua_app/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.urls import reverse

from .models import AvaliacaoPeriodoExperiencia
from .serializers import CriarAvaliacaoSerializer

class CriarAvaliacaoAPIView(APIView):
    """
    Endpoint para criar uma nova Avaliação de Experiência e retornar
    o link único para o formulário.
    """
    # Se precisar de autenticação, adicione aqui.
    # Ex: permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # Passa os dados recebidos na requisição (request.data) para o serializer
        serializer = CriarAvaliacaoSerializer(data=request.data)
        
        # Valida os dados. Se não forem válidos, retorna um erro 400.
        if serializer.is_valid():
            # .save() cria a nova instância do modelo no banco de dados
            nova_avaliacao = serializer.save()
            
            # Pega o token que foi gerado automaticamente pelo seu método save() no model
            token_gerado = nova_avaliacao.token
            
            # Gera a URL relativa para o formulário, passando o token como argumento
            # 'responder_avaliacao' deve ser o 'name' da sua URL do formulário
            try:
                url_relativa = reverse('avaliacao_experiencia', kwargs={'token': token_gerado})
                url_absoluta = request.build_absolute_uri(url_relativa)
                
                # Prepara a resposta de sucesso
                data = {
                    'message': 'Avaliação criada com sucesso.',
                    'evaluation_token': token_gerado,
                    'evaluation_form_url': url_absoluta
                }
                return Response(data, status=status.HTTP_201_CREATED)

            except Exception as e:
                 return Response(
                    {'error': 'Avaliação criada, mas falhou ao gerar a URL.', 'details': str(e)},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        # Se os dados não forem válidos, retorna os erros de validação
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)





 


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
              candidato = None
              for c in Candidato.objects.all():
                  numero_candidato = ''.join(filter(str.isdigit, c.telefone))
                  if numero_candidato[-8:] == telefone_webhook[-8:]:
                      candidato = c
                      break

              if candidato:

                #   if candidato.status in ['concluido', 'rejeitado']:
                #       logger.info(f"Pulando processamento do webhook para candidato {candidato.nome} - status: {candidato.status}")
                #       return JsonResponse({'status': 'success', 'message': 'Candidato já finalizado'})
                  if candidato.status in ['concluido', 'rejeitado']:
                      # Verifica se tem documentos marcados como "nao_possui"
                      documentos_nao_possui = candidato.documentos.filter(status='nao_possui')
                      
                      if not documentos_nao_possui.exists():
                          # Se não tem documentos "nao_possui", pula o processamento
                          logger.info(f"Pulando processamento do webhook para candidato {candidato.nome} - status: {candidato.status} (sem documentos nao_possui)")
                          return JsonResponse({'status': 'success', 'message': 'Candidato já finalizado sem documentos pendentes'})
                      
                      # Se tem documentos "nao_possui", continua o processamento para verificar se o documento enviado corresponde
                      logger.info(f"Processando documento de candidato {candidato.status} {candidato.nome} - verificando se corresponde a documento nao_possui")

                  if "message" in data:
                      message_data = data["message"]
                      has_document = "documentMessage" in message_data
                      has_image = "imageMessage" in message_data
                      has_text = "conversation" in message_data

                      if has_document or has_image:
                          media_info = message_data["documentMessage"] if has_document else message_data["imageMessage"]
                          media_type = "documento" if has_document else "imagem"

                          base64_data = (
                              body.get("base64") or
                              data.get("base64") or
                              message_data.get("base64") or
                              media_info.get("base64")
                          )

                            # 2) Se não veio base64, tenta baixar pela URL (ou outro campo equivalente)
                          if not base64_data:
                                print("Dados base64 não encontrados na mensagem. Tentando baixar a mídia pela URL...")
                                media_url = media_info.get("url")
                                if media_url:
                                    try:
                                        resp = requests.get(media_url, timeout=15)
                                        resp.raise_for_status()
                                        base64_data = base64.b64encode(resp.content).decode("utf-8")
                                    except Exception as e:
                                        print(f"Erro ao baixar mídia: {e}")
                                        return JsonResponse({'status': 'error', 'message': 'Could not fetch media'}, status=400)
                                else:
                                    print("URL de mídia não encontrada no payload.")
                                    return JsonResponse({'status': 'error', 'message': 'Media URL not found'}, status=400)

                            # 3) Se após tentativa ainda não houver base64, falha
                          if not base64_data:
                                print("Ainda sem base64 após tentativa de download.")
                                return JsonResponse({'status': 'error', 'message': 'Base64 data not found'}, status=400)

                            # 4) A partir daqui SEMPRE temos base64_data → decodifica e segue o fluxo normal
                        #   try:
                        #         file_data = base64.b64decode(base64_data)
                        #   except Exception as e:
                        #         print(f"Falha ao decodificar base64: {e}")
                        #         return JsonResponse({'status': 'error', 'message': 'Invalid base64'}, status=400)

                          if base64_data:
                              try:
                                  file_data = base64.b64decode(base64_data)

                                  # --- INÍCIO DA CORREÇÃO: Determinação da extensão do arquivo temporário ---
                                  temp_extension = "tmp" # Default fallback
                                  
                                  # Prioriza mimetype se disponível
                                  if "mimetype" in media_info:
                                      mime = media_info["mimetype"]
                                      if "image/" in mime:
                                          temp_extension = mime.split('/')[-1] # Ex: 'jpeg', 'png'
                                          if temp_extension == 'jpeg': temp_extension = 'jpg' # Padroniza para jpg
                                      elif "application/pdf" in mime:
                                          temp_extension = "pdf"
                                      elif "application/msword" in mime or "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in mime:
                                          logger.warning(f"⚠️ Documento Word (.doc/.docx) recebido. Conversão para PDF não é suportada neste ambiente.")
                                          enviar_mensagem_whatsapp(sender, "Recebemos seu documento Word (.doc/.docx). No momento, não conseguimos processar este formato. Por favor, envie o documento em formato PDF ou imagem (JPG/PNG).")
                                          return JsonResponse({'status': 'error', 'message': 'Word document conversion not supported'}, status=400)
                                    
                                  # Se mimetype não ajudou ou não existe, tenta pelo fileName
                                  if temp_extension == "tmp" and "fileName" in media_info and media_info["fileName"]:
                                      file_name_from_info = media_info["fileName"]
                                      _, ext = os.path.splitext(file_name_from_info)
                                      if ext:
                                          temp_extension = ext.lower().lstrip('.')
                                          if temp_extension == 'jpeg': temp_extension = 'jpg' # Padroniza para jpg
                                          if temp_extension in ['doc', 'docx']:
                                                logger.warning(f"⚠️ Documento Word (.doc/.docx) recebido. Conversão para PDF não é suportada neste ambiente.")
                                                enviar_mensagem_whatsapp(sender, "Recebemos seu documento Word (.doc/.docx). No momento, não conseguimos processar este formato. Por favor, envie o documento em formato PDF ou imagem (JPG/PNG).")
                                                return JsonResponse({'status': 'error', 'message': 'Word document conversion not supported'}, status=400)
                                            
                                  # Fallback final se nada foi determinado
                                  if temp_extension == "tmp":
                                      temp_extension = "jpg" if has_image else "pdf" # Usa a lógica anterior como último recurso

                                  # Garante que a extensão é uma das esperadas para o analisador
                                  if temp_extension not in ['jpg', 'jpeg', 'png', 'pdf']:
                                      temp_extension = 'jpg' if has_image else 'pdf' # Força para um tipo conhecido

                                  # --- FIM DA CORREÇÃO ---

                                  temp_file_path = None
                                  with tempfile.NamedTemporaryFile(suffix=f'.{temp_extension}', delete=False) as tmp_file:
                                      tmp_file.write(file_data)
                                      temp_file_path = tmp_file.name

                                  from reconhecer_imagem import analisar_arquivo
                                  tipo_documento_ia = analisar_arquivo(temp_file_path)
                                  os.unlink(temp_file_path) # Limpar o arquivo temporário

                                  print(f"Tipo de documento identificado pela IA: {tipo_documento_ia}")

                                  # 2. Mapear o tipo de documento da IA para o modelo Django
                                  # Mapeamento direto dos códigos da IA para os nomes do seu modelo Django (em maiúsculas)
                                  mapeamento_ia_para_modelo = {
                                        # 📸 Foto
                                        'foto_3x4': 'foto_3x4',
                                        'foto': 'foto_3x4',
                                        'foto_documento': 'foto_3x4',
                                        'comprovante_residencia': 'comprovante_residencia',
                                        'certidao_nascimento': 'certidao_nascimento',

                                        # 📄 Documentos Pessoais
                                        'rg': 'rg',
                                        'cpf': 'cpf',
                                        'titulo_eleitor': 'titulo_eleitor',
                                        'certificado_reservista': 'reservista',
                                        'reservista': 'reservista',
                                        'certidao_antecedentes_criminais': 'certidao_antecedentes_criminais',

                                        # 🚗 CNH
                                        'cnh': 'cnh',
                                        'carteira_motorista': 'cnh',

                                        # 🏦 Contas
                                        'conta_salario': 'conta_salario',
                                        'conta_pix': 'conta_pix',
                                        'pix': 'conta_pix',
                                        'numero_conta_pix': 'conta_pix',

                                        # 📕 Carteira de Trabalho
                                        'carteira_trabalho_digital': 'carteira_trabalho_digital',
                                        'carteira_trabalho': 'carteira_trabalho_digital',
                                        'ctps': 'carteira_trabalho_digital',

                                        # 💰 PIS
                                        'extrato_pis': 'extrato_pis',
                                        'pis': 'extrato_pis',

                                        # 🩺 Saúde
                                        'aso': 'aso',
                                        'atestado_saude_ocupacional': 'aso',

                                        # 🎓 Escolaridade
                                        'comprovante_escolaridade': 'comprovante_escolaridade',
                                        'diploma': 'comprovante_escolaridade',
                                        'historico_escolar': 'comprovante_escolaridade',
                                        'curriculo': 'curriculo',

                                        # 🎖️ Cursos e Certificados
                                        'certificados_cursos': 'certificados_cursos',
                                        'certificados': 'certificados_cursos',
                                        'cursos': 'certificados_cursos',
                                        'certificados_cursos_nrs': 'certificados_cursos',

                                        # 💉 Vacinas
                                        'cartao_vacinas': 'cartao_vacinas',
                                        'cartao_vacinacao': 'cartao_vacinas',
                                        'vacinas': 'cartao_vacinas',

                                        # 💍 Casamento
                                        'certidao_casamento': 'certidao_casamento',
                                        'casamento': 'certidao_casamento',

                                        # 👫 Cônjuge
                                        'rg_cpf_esposa': 'rg_cpf_esposa',
                                        'rg_cpf_conjuge': 'rg_cpf_conjuge',

                                        # 👶 Filhos
                                        'certidao_nascimento_filhos': 'certidao_nascimento_filhos',
                                        'nascimento_filhos': 'certidao_nascimento_filhos',
                                        'rg_cpf_filhos': 'rg_cpf_filhos',
                                        'carteira_vacinacao_filhos': 'carteira_vacinacao_filhos',
                                        'cartao_vacinacao_filhos': 'carteira_vacinacao_filhos',
                                        'vacinacao_filhos': 'carteira_vacinacao_filhos',
                                        'declaracao_matricula_filhos': 'declaracao_matricula_filhos',
                                        'matricula_filhos': 'declaracao_matricula_filhos',

                                        # 🏢 Documentos PJ
                                        'cnpj': 'cnpj',
                                        'email_contrato': 'email_contrato',
                                        'email': 'email_contrato',

                                        # 🤳 Selfie
                                        'foto_rosto': 'FOTO_ROSTO',
                                        'FOTO_ROSTO': 'FOTO_ROSTO',
                                        'selfie': 'FOTO_ROSTO'
                                  }
                                  tipo_mapeado_nome = 'OUTROS' # Default
                                  observacoes_ia = ""

                                  # --- INÍCIO DA LÓGICA DE TRATAMENTO DE ERRO DE LIMITE DE TAXA ---
                                  if tipo_documento_ia == "RATE_LIMIT_EXCEEDED":
                                      # Se a IA retornou limite de taxa, marca como 'recebido' e agenda revalidação
                                      tipo_mapeado, _ = TipoDocumento.objects.get_or_create(
                                          nome='OUTROS', # Pode ser qualquer tipo, pois será revalidado
                                          defaults={'ativo': True}
                                      )
                                      doc_to_update = candidato.documentos.filter(tipo=tipo_mapeado, status='pendente').first()
                                      if not doc_to_update:
                                          doc_to_update = Documento.objects.create(
                                              candidato=candidato,
                                              tipo=tipo_mapeado,
                                              status='pendente',
                                              observacoes="Documento recebido. Tipo não identificado automaticamente."
                                          )
                                          registrar_evento(
                                              candidato=candidato,
                                              tipo_evento='documento_solicitado',
                                              documento=doc_to_update,
                                              status_novo='pendente',
                                              observacoes="Documento criado automaticamente após recebimento."
                                          )

                                      file_name = media_info.get("fileName")
                                      if not file_name:
                                          file_name = f"{tipo_mapeado.nome.lower()}_{candidato.id}.{temp_extension}"
                                      
                                      doc_to_update.arquivo.save(
                                          file_name,
                                          ContentFile(file_data),
                                          save=False
                                      )

                                      status_anterior = doc_to_update.status
                                      doc_to_update.status = 'recebido' # Marca como recebido
                                      doc_to_update.data_envio = timezone.now()
                                      doc_to_update.observacoes = "Validação adiada devido a alta demanda da IA. Tentaremos novamente em 25 horas."
                                      doc_to_update.data_ultima_atualizacao = timezone.now() # Atualiza para o cron job
                                      doc_to_update.save()

                                      registrar_evento(
                                          candidato=candidato,
                                          tipo_evento='documento_recebido',
                                          documento=doc_to_update,
                                          status_anterior=status_anterior,
                                          status_novo='recebido',
                                          observacoes="Documento recebido, validação adiada por limite de taxa da IA."
                                      )
                                      enviar_mensagem_whatsapp(sender, "Recebemos seu documento! Devido a um alto volume de solicitações, a análise automática será feita em breve. Agradecemos a sua paciência.")
                                      return JsonResponse({'status': 'success'})
                                  # --- FIM DA LÓGICA DE TRATAMENTO DE ERRO DE LIMITE DE TAXA ---


                                  if '|' in tipo_documento_ia:
                                      # Se a IA retornou "outros|Tipo não reconhecido, a inteligência artificial acha que é <b>[TIPO]</b>"
                                      parts = tipo_documento_ia.split('|', 1)
                                      ia_base_type = parts[0].strip().lower()
                                      ia_detailed_description = parts[1].strip()
                                      observacoes_ia = f"IA detalhe: {ia_detailed_description}"

                                      # Tentar extrair o tipo específico da descrição detalhada se for 'outros'
                                      if ia_base_type == 'outros':
                                          match = re.search(r'<b>(.*?)<\/b>', ia_detailed_description)
                                          if match:
                                              extracted_type = match.group(1).strip().lower()
                                              tipo_mapeado_nome = mapeamento_ia_para_modelo.get(extracted_type, 'OUTROS')
                                              if tipo_mapeado_nome == 'OUTROS': # Se o tipo extraído não mapeou
                                                  observacoes_ia = f"Tipo não reconhecido pela IA: {extracted_type}. Detalhe: {ia_detailed_description}"
                                          else:
                                              observacoes_ia = f"Tipo não reconhecido pela IA. Detalhe: {ia_detailed_description}"
                                      else: # Se a IA retornou um tipo direto (não 'outros|...')
                                          tipo_mapeado_nome = mapeamento_ia_para_modelo.get(ia_base_type, 'OUTROS')
                                          if tipo_mapeado_nome == 'OUTROS': # Se o tipo direto não mapeou
                                              observacoes_ia = f"Tipo não reconhecido pela IA: {ia_base_type}. Detalhe: {ia_detailed_description}"
                                  else: # IA retornou um tipo direto sem '|'
                                      tipo_mapeado_nome = mapeamento_ia_para_modelo.get(tipo_documento_ia.lower(), 'OUTROS')
                                      if tipo_mapeado_nome == 'OUTROS':
                                          observacoes_ia = f"Tipo não reconhecido pela IA: {tipo_documento_ia}"


                                  tipo_mapeado, _ = TipoDocumento.objects.get_or_create(
                                      nome=tipo_mapeado_nome,
                                      defaults={'ativo': True}
                                  )

                                  # 3. Encontrar ou criar o documento no banco de dados
                                  # Tenta encontrar um documento pendente do tipo identificado
                                #   doc_to_update = candidato.documentos.filter(tipo=tipo_mapeado, status='pendente').first()

                                #   if not doc_to_update:
                                #       # Se não encontrou um pendente, cria um novo documento
                                #       doc_to_update = Documento.objects.create(
                                #           candidato=candidato,
                                #           tipo=tipo_mapeado,
                                #           status='pendente', # Começa como pendente, será validado/invalidado abaixo
                                #           observacoes=f"Documento {tipo_mapeado.nome} criado automaticamente após identificação da IA."
                                #       )
                                #       registrar_evento(
                                #           candidato=candidato,
                                #           tipo_evento='documento_solicitado', # Ou 'documento_criado_ia'
                                #           documento=doc_to_update,
                                #           status_novo='pendente',
                                #           observacoes=f"Documento {doc_to_update.tipo.nome} criado automaticamente pela IA."
                                #       )
                                #   else:
                                #       # Se encontrou um pendente, atualiza as observações
                                #       doc_to_update.observacoes = f"Documento {tipo_mapeado.nome} recebido para o tipo pendente existente."

                                  doc_to_update = candidato.documentos.filter(tipo=tipo_mapeado, status='nao_possui').first()
                                
                                  if doc_to_update:
                                      # Se encontrou um documento 'nao_possui', mantém o status original e adiciona observação
                                      # O status será atualizado diretamente pela IA para 'validado' ou outro status final
                                      doc_to_update.observacoes += f"\nCandidato enviou o documento que anteriormente informou não possuir via WhatsApp."
                                      logger.info(f"[DOCUMENTO] Documento '{tipo_mapeado.nome}' encontrado como 'nao_possui', será atualizado diretamente pela IA para {candidato.nome}")
                                    
                                      # Não registra evento aqui - será registrado quando a IA processar o documento
                                      # com o status final correto
                                  else:
                                      # Se não encontrou 'nao_possui', tenta encontrar um documento pendente do tipo identificado
                                      doc_to_update = candidato.documentos.filter(tipo=tipo_mapeado, status='pendente').first()

                                      if not doc_to_update:
                                          # Se não encontrou um pendente, cria um novo documento
                                          doc_to_update = Documento.objects.create(
                                              candidato=candidato,
                                              tipo=tipo_mapeado,
                                              status='pendente', # Começa como pendente, será validado/invalidado abaixo
                                              observacoes=f"Documento {tipo_mapeado.nome} criado automaticamente após identificação da IA."
                                          )
                                          registrar_evento(
                                              candidato=candidato,
                                              tipo_evento='documento_solicitado', # Ou 'documento_criado_ia'
                                              documento=doc_to_update,
                                              status_novo='pendente',
                                              observacoes=f"Documento {doc_to_update.tipo.nome} criado automaticamente pela IA."
                                          )
                                      else:
                                          # Se encontrou um pendente, atualiza as observações
                                          doc_to_update.observacoes = f"Documento {tipo_mapeado.nome} recebido para o tipo pendente existente."

                                  # 4. Salvar o arquivo
                                  file_name = media_info.get("fileName")
                                  if not file_name:
                                      # Usa a extensão determinada para o arquivo temporário
                                      file_name = f"{tipo_mapeado.nome.lower()}_{candidato.id}.{temp_extension}"

                                  doc_to_update.arquivo.save(
                                      file_name,
                                      ContentFile(file_data),
                                      save=False # Não salvar ainda, vamos atualizar o status
                                  )

                                  # 5. Validar e atualizar status
                                  status_anterior = doc_to_update.status
                                  doc_to_update.data_envio = timezone.now()
                                  doc_to_update.data_ultima_atualizacao = timezone.now() # Adiciona esta linha
                                  if tipo_mapeado.nome.upper() == 'FOTO_ROSTO' and has_image:
                                      # Se a IA identificou como FOTO_ROSTO, faz a validação facial
                                      image = Image.open(io.BytesIO(file_data))
                                      processor = ImageProcessor()
                                      # AQUI: Captura o status retornado pela ImageProcessor
                                      status_from_processor, admin_obs_message_from_processor, comparison_info = processor.validate_face_photo_with_comparison(image, candidato.id)
                                      whatsapp_message_from_processor = comparison_info.get('whatsapp_message_detail', "Erro ao processar foto.")

                                      if status_from_processor == 'validado':
                                          doc_to_update.status = 'validado'
                                          doc_to_update.data_validacao = timezone.now()

                                          mensagem_resposta = whatsapp_message_from_processor
                                          evento_tipo = 'documento_validado'
                                          evento_obs = admin_obs_message_from_processor # Use admin message for timeline obs
                                          
                                          doc_to_update.observacoes += f"\n{admin_obs_message_from_processor}" # Use admin message for doc obs

                                      elif status_from_processor == 'recebido': # Novo status para foto recebida mas não comparada
                                          doc_to_update.status = 'recebido'
                                          doc_to_update.observacoes += f"\n{admin_obs_message_from_processor}"
                                          mensagem_resposta = whatsapp_message_from_processor
                                          evento_tipo = 'documento_recebido'
                                          evento_obs = admin_obs_message_from_processor
                                          # Não altera status do candidato aqui, pois a foto é 'recebida' mas não 'validada'
                                          # A revalidação posterior ou ação manual será necessária.

                                      else: # status_from_processor == 'invalido'
                                          doc_to_update.status = 'invalido'
                                          
                                          # Use the messages directly from the processor
                                          doc_to_update.observacoes += f"\nFoto inválida: {admin_obs_message_from_processor}"
                                          
                                          # Construct the WhatsApp message as requested:
                                          # "❌ A foto enviada não atende aos requisitos:\n*Identidade NÃO confirmada!*Rosto NÃO corresponde ao FOTO_3X4 com X % de certeza"
                                          mensagem_resposta = f"❌ A foto enviada não atende aos requisitos:\n{whatsapp_message_from_processor}"
                                          
                                          evento_tipo = 'documento_invalidado'
                                          evento_obs = f"Foto inválida: {admin_obs_message_from_processor}" # Use admin message for timeline obs
                                          
                                          # Atualiza o status do candidato se a foto do rosto for inválida
                                          status_anterior_candidato = candidato.status
                                          candidato.status = 'documentos_invalidos'
                                          candidato.save()
                                          registrar_evento(
                                              candidato=candidato,
                                              tipo_evento='status_candidato_atualizado',
                                              status_anterior=status_anterior_candidato,
                                              status_novo=candidato.status,
                                              observacoes="Status atualizado devido a foto do rosto inválida"
                                          )
                                  elif tipo_mapeado.nome.upper() == 'OUTROS':
                                      doc_to_update.status = 'invalido'
                                      doc_to_update.observacoes += f"\nTipo de documento não reconhecido pela IA. {observacoes_ia}"
                                      mensagem_resposta = f"Documento recebido, mas não conseguimos identificar o tipo. Por favor, envie um documento claro e legível. Detalhes da IA: {observacoes_ia}"
                                      evento_tipo = 'documento_invalidado'
                                      evento_obs = "Tipo de documento não reconhecido pela IA"
                                      # Atualiza status do candidato
                                      status_anterior_candidato = candidato.status
                                      candidato.status = 'documentos_invalidos'
                                      candidato.save()
                                      registrar_evento(
                                          candidato=candidato,
                                          tipo_evento='status_candidato_atualizado',
                                          status_anterior=status_anterior_candidato,
                                          status_novo=candidato.status,
                                          observacoes="Status atualizado devido a documento inválido (tipo 'OUTROS')"
                                      )
                                  else:
                                      # Para todos os outros tipos de documentos identificados
                                      doc_to_update.status = 'validado'
                                      doc_to_update.data_validacao = timezone.now()
                                      doc_to_update.observacoes += f"\n{media_type.capitalize()} validado(a) através de inteligência artificial. {observacoes_ia}"
                                      mensagem_resposta = f"Documento recebido! Identificamos como: *{doc_to_update.tipo.get_nome_exibicao()}*. \nVamos analisar e retornaremos em breve."
                                      evento_tipo = 'documento_validado'
                                      evento_obs = "Validação automática pela IA"

                                  doc_to_update.save()
                                  registrar_evento(
                                      candidato=candidato,
                                      tipo_evento=evento_tipo,
                                      documento=doc_to_update,
                                      status_anterior=status_anterior,
                                      status_novo=doc_to_update.status,
                                      observacoes=evento_obs
                                  )

                                  # 6. Enviar mensagem de resposta e verificar documentos pendentes
                                  enviar_mensagem_whatsapp(sender, mensagem_resposta)

                                  # Lógica para verificar se todos os documentos OBRIGATÓRIOS foram validados
                                  required_docs = candidato.documentos.filter(tipo__obrigatorio=True)
                                #  validated_required_docs = required_docs.filter(status='validado')
                                  validated_required_docs = required_docs.filter(status__in=['validado', 'nao_possui'])

                                  if required_docs.count() > 0 and required_docs.count() == validated_required_docs.count():
                                      # Todos os documentos obrigatórios foram validados
                                      mensagem_final = ("Ótimo! Todos os documentos obrigatórios foram recebidos e validados. "
                                                        "Seu processo está concluído e entraremos em contato em breve.")
                                      enviar_mensagem_whatsapp(sender, mensagem_final)
                                      status_anterior_candidato = candidato.status
                                      candidato.status = 'concluido' # Define como concluído
                                      candidato.save()
                                      registrar_evento(
                                          candidato=candidato,
                                          tipo_evento='processo_concluido',
                                          status_anterior=status_anterior_candidato,
                                          status_novo=candidato.status,
                                          observacoes="Todos os documentos obrigatórios recebidos e validados"
                                      )
                                  else:

                                      # Documentos obrigatórios que ainda estão pendentes ou foram invalidados
                                      docs_restantes_obrigatorios = required_docs.filter(
                                          Q(status='pendente') | Q(status='invalido')
                                      )

                                      if docs_restantes_obrigatorios.exists():
                                          # Separar em inválidos e pendentes para mensagens mais claras
                                          invalid_docs = docs_restantes_obrigatorios.filter(status='invalido')
                                          pending_docs = docs_restantes_obrigatorios.filter(status='pendente')

                                          follow_up_messages = []

                                        #   if invalid_docs.exists():
                                        #       invalid_docs_text = "\n".join([f"- {doc.tipo.get_nome_exibicao()}" for doc in invalid_docs])
                                        #       follow_up_messages.append(f"❌ Atenção! Os seguintes documentos precisam ser reenviados pois estão inválidos:\n{invalid_docs_text}")

                                          if pending_docs.exists():
                                              pending_docs_text = "\n".join([f"- {doc.tipo.get_nome_exibicao()}" for doc in pending_docs])
                                              follow_up_messages.append(f"⏳ Ainda precisamos dos seguintes documentos obrigatórios:\n{pending_docs_text}")
                                          
                                          # Combine and send
                                          if follow_up_messages:
                                              enviar_mensagem_whatsapp(sender, "\n\n".join(follow_up_messages))
                                      # else: No explicit message needed here based on user's request.

                                  return JsonResponse({'status': 'success'})
                              
                              except Exception as e:
                                  print(f"Erro ao processar documento: {str(e)}")
                                  import traceback
                                  print(traceback.format_exc())
                                  return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
                          else:
                              print("Dados base64 não encontrados na mensagem.")
                              return JsonResponse({'status': 'error', 'message': 'Base64 data not found'}, status=400)

                      elif has_text:
                            message_text = message_data["conversation"]
                            
                            logger.info(f"[CONVERSA] Mensagem recebida de {candidato.nome} ({candidato.telefone}): {message_text}")
                            
                            # Buscar documentos pendentes obrigatórios do candidato
                            pending_documents = candidato.documentos.filter(
                                tipo__obrigatorio=True,
                                status__in=['pendente', 'recebido']
                            )
                            
                            if pending_documents.exists():
                                # Usar IA para analisar a mensagem
                                conversation_ai = ConversationAI()
                                result = conversation_ai.analyze_message(
                                    message_text, 
                                    candidato.nome, 
                                    pending_documents
                                )
                                
                                logger.info(f"[CONVERSA] Análise IA para {candidato.nome}: {result}")
                                
                                documentos_validados = []
                                
                                if result.get("tem_documento_faltante") and result.get("documentos_faltantes"):
                                    documentos_faltantes = result["documentos_faltantes"]
                                    
                                    for documento_nome in documentos_faltantes:
                                        # Procurar o documento pendente correspondente
                                        documento_encontrado = None
                                        for doc in pending_documents:
                                            nome_exibicao = doc.tipo.get_nome_exibicao()
                                            nome_tecnico = doc.tipo.nome
                                            
                                            # Verificar correspondência com nome de exibição ou técnico
                                            if (documento_nome.lower() in nome_exibicao.lower() or 
                                                nome_exibicao.lower() in documento_nome.lower() or
                                                documento_nome.lower() in nome_tecnico.lower() or
                                                nome_tecnico.lower() in documento_nome.lower()):
                                                documento_encontrado = doc
                                                break
                                        
                                        if documento_encontrado:
                                            logger.info(f"[CONVERSA] Documento '{documento_encontrado.tipo.get_nome_exibicao()}' marcado como não possui automaticamente para {candidato.nome}")
                                            
                                            status_anterior = documento_encontrado.status
                                            documento_encontrado.status = 'nao_possui'
                                            documento_encontrado.data_validacao = timezone.now()
                                            documento_encontrado.observacoes += f"\nCandidato informou que não possui este documento via WhatsApp: \n'{message_text}'"
                                            documento_encontrado.save()
                                            
                                            documentos_validados.append(documento_encontrado.tipo.get_nome_exibicao())
                                            
                                            # Registrar evento na timeline
                                            registrar_evento(
                                                candidato=candidato,
                                                tipo_evento='documento_nao_possui',
                                                documento=documento_encontrado,
                                                status_anterior=status_anterior,
                                                status_novo='nao_possui',
                                                observacoes=f"Candidato informou via WhatsApp que não possui o documento: {documento_encontrado.tipo.get_nome_exibicao()}"
                                            )

                                if documentos_validados:
                                    atualizar_status_candidato(candidato)
                                    
                                    if len(documentos_validados) == 1:
                                        resposta = f"Registrei que você não possui: {documentos_validados[0]}. Seu processo foi atualizado."
                                    else:
                                        docs_lista = ", ".join(documentos_validados)
                                        resposta = f"Registrei que você não possui: {docs_lista}. Seu processo foi atualizado."
                                    
                                    logger.info(f"[CONVERSA] Resposta enviada para {candidato.nome}: {resposta}")
                                    enviar_mensagem_whatsapp(sender, resposta)
                                else:
                                    logger.info(f"[CONVERSA] Mensagem de {candidato.nome} não resultou em validação automática de documento - não enviando resposta")
                            else:
                                logger.info(f"[CONVERSA] {candidato.nome} não possui documentos pendentes - não enviando resposta")
                      else:
                          pass
                        #   print("Mensagem não contém documento ou imagem")
                        #   return JsonResponse({'status': 'error', 'message': 'No document or image found in message'}, status=400)
              else:
                  pass
                #   print(f"Candidato não encontrado para o número: {telefone_webhook}")
                #   return JsonResponse({'status': 'error', 'message': 'Candidato not found'}, status=404)
          except Exception as e:
              logger.error(f"Erro ao processar mensagem no webhook: {str(e)}", exc_info=True)
              return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
      return JsonResponse({'status': 'success'}) # Deve ser alcançado se is_from_me for True
  except json.JSONDecodeError as e:
      logger.debug(f"Erro ao decodificar JSON no webhook: {str(e)}. Body: {request.body.decode()}")
      return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
  except Exception as e:
      logger.critical(f"Erro não tratado no webhook: {str(e)}", exc_info=True)
      return JsonResponse({'status': 'error', 'message': str(e)}, status=500)




@login_required
def novo_documento(request, candidato_id):
    candidato = get_object_or_404(Candidato, id=candidato_id)
    if request.method == 'POST':
        form = DocumentoForm(request.POST, candidato=candidato)
        if form.is_valid():
            documento = form.save(commit=False)
            documento.candidato = candidato
            documento.save()
            
            # Enviar solicitação do documento via WhatsApp
            tipo_documento = documento.tipo.get_nome_exibicao()
            mensagem = f"Olá {candidato.nome}, por favor, envie o documento: {tipo_documento}. Certifique-se de que a imagem está clara e legível."
            atualizar_status_candidato(candidato)
            enviar_mensagem_whatsapp(candidato.telefone, mensagem)
            messages.success(request, 'Documento adicionado com sucesso e solicitação enviada via WhatsApp.')
            return redirect('detalhes_candidato', candidato_id=candidato.id)
    else:
        form = DocumentoForm(candidato=candidato)
    
    return render(request, 'novo_documento.html', {'form': form, 'candidato': candidato})

@login_required
@user_passes_test(is_admin)
def novo_usuario(request):
    """Criar um novo usuário"""
    if request.method == 'POST':
        form = RegisterFormExtended(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, 'Usuário criado com sucesso!')
            return redirect('admin_dashboard')
    else:
        form = RegisterFormExtended()
    
    return render(request, 'novo_usuario.html', {
        'form': form,
        'is_new': True
    })

@login_required
@user_passes_test(is_admin)
def listar_setores(request):
    """Listar todos os setores"""
    setores = Setor.objects.all().order_by('nome')
    return render(request, 'listar_setores.html', {
        'setores': setores,
        'total_setores': setores.count()
    })

@login_required
@user_passes_test(is_admin)
def listar_usuarios(request):
    """Listar todos os usuários"""
    usuarios = User.objects.all().order_by('-date_joined')
    return render(request, 'listar_usuarios.html', {
        'usuarios': usuarios,
        'total_usuarios': usuarios.count()
    })

@login_required
@user_passes_test(is_admin)
def listar_administradores(request):
    """Listar todos os administradores"""
    administradores = User.objects.filter(is_staff=True).order_by('-date_joined')
    return render(request, 'listar_administradores.html', {
        'administradores': administradores,
        'total_administradores': administradores.count()
    })

@login_required
@user_passes_test(is_admin)
def listar_usuarios_ativos(request):
    """Listar todos os usuários ativos"""
    usuarios_ativos = User.objects.filter(is_active=True).order_by('-date_joined')
    return render(request, 'listar_usuarios_ativos.html', {
        'usuarios_ativos': usuarios_ativos,
        'total_usuarios_ativos': usuarios_ativos.count()
    })

@login_required
@user_passes_test(is_admin)
def listar_usuarios_pendentes(request):
    """Listar todos os usuários pendentes de ativação"""
    # Modificando a consulta para garantir que estamos obtendo os usuários pendentes corretamente
    usuarios_pendentes = User.objects.filter(is_active=False).order_by('-date_joined')
    
    # Adicionando log para debug
    print(f"Usuários pendentes encontrados: {usuarios_pendentes.count()}")
    for user in usuarios_pendentes:
        print(f"Usuário pendente: {user.username}, is_active={user.is_active}")
    
    return render(request, 'listar_usuarios_pendentes.html', {
        'usuarios': usuarios_pendentes,  # Garantindo que a variável no template seja 'usuarios'
        'total_usuarios_pendentes': usuarios_pendentes.count()
    })

@login_required
@user_passes_test(is_admin)
def listar_tipos_documentos(request):
    """Listar todos os tipos de documentos"""
    tipos = TipoDocumento.objects.all().order_by('nome')
    return render(request, 'listar_tipos_documentos.html', {
        'tipos': tipos,
        'total_tipos': tipos.count()
    })

@login_required
@user_passes_test(is_admin)
def gerenciar_tipo_documento(request, tipo_id=None):
    """Criar ou editar um tipo de documento"""
    tipo = None if tipo_id is None else get_object_or_404(TipoDocumento, id=tipo_id)
    
    if request.method == 'POST':
        form = TipoDocumentoForm(request.POST, instance=tipo)
        if form.is_valid():
            form.save()
            messages.success(request, 'Tipo de documento salvo com sucesso!')
            return redirect('listar_tipos_documentos')
    else:
        form = TipoDocumentoForm(instance=tipo)
    
    return render(request, 'gerenciar_tipo_documento.html', {
        'form': form,
        'tipo': tipo,
        'is_new': tipo is None
    })

@login_required
@user_passes_test(is_admin)
def excluir_tipo_documento(request, tipo_id):
    """Excluir um tipo de documento"""
    tipo = get_object_or_404(TipoDocumento, id=tipo_id)
    
    # Verificar se o tipo está sendo usado
    if tipo.documentos.exists():
        messages.error(request, 'Não é possível excluir este tipo de documento pois está sendo usado por documentos existentes.')
        return redirect('listar_tipos_documentos')
    
    if request.method == 'POST':
        tipo.delete()
        messages.success(request, 'Tipo de documento excluído com sucesso!')
        return redirect('listar_tipos_documentos')
    
    return redirect('listar_tipos_documentos')

@login_required
@user_passes_test(is_admin)
def alternar_status_tipo_documento(request, tipo_id):
    """Ativar ou desativar um tipo de documento"""
    tipo = get_object_or_404(TipoDocumento, id=tipo_id)
    
    if request.method == 'POST':
        tipo.ativo = not tipo.ativo
        tipo.save()
        status = "ativado" if tipo.ativo else "desativado"
        messages.success(request, f'Tipo de documento {status} com sucesso!')
    
    return redirect('listar_tipos_documentos')

@login_required
@require_http_methods(["POST"])
def ajax_criar_tipo_documento(request):
    """
    View para criar um novo tipo de documento via AJAX
    """
    # Verificar se é uma requisição AJAX
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Requisição inválida'}, status=400)
    
    try:
        nome = request.POST.get('nome', '').strip().upper()
        nome_exibicao = request.POST.get('nome_exibicao', '').strip()
        ativo = request.POST.get('ativo') == '1'
        obrigatorio = request.POST.get('obrigatorio') == '1' # Captura o valor do checkbox
        
        if not nome:
            return JsonResponse({'success': False, 'error': 'Nome é obrigatório'}, status=400)
        
        if not nome_exibicao:
            nome_exibicao = nome.replace('_', ' ').title()
        
        # Verificar se já existe um tipo com este nome
        if TipoDocumento.objects.filter(nome=nome).exists():
            return JsonResponse({'success': False, 'error': 'Já existe um tipo de documento com este nome'}, status=400)
        
        # Criar o novo tipo
        tipo = TipoDocumento.objects.create(
            nome=nome,
            nome_exibicao=nome_exibicao,
            ativo=ativo,
            obrigatorio=obrigatorio # Salva o valor do checkbox
        )
        
        return JsonResponse({
            'success': True,
            'id': tipo.id,
            'nome': tipo.nome,
            'nome_exibicao': tipo.get_nome_exibicao(),
            'ativo': tipo.ativo,
            'obrigatorio': tipo.obrigatorio # Retorna o valor do checkbox
        })
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)




from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from .models import ConfiguracaoCobranca, ControleCobrancaCandidato, HistoricoCobranca, Candidato, Documento, TipoDocumento
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.shortcuts import render
from django.contrib.auth.models import User
from .models import Setor
from .forms import ConfiguracaoCobrancaForm
from django.contrib.auth.decorators import user_passes_test
from .views_mp import tem_acesso_completo
from django.utils import timezone

def is_admin(user):
    """Verifica se o usuário é administrador"""
    return user.is_staff or user.is_superuser

@login_required
def configuracao_cobranca(request):
    """View para configurar a cobrança automática"""
    config, created = ConfiguracaoCobranca.objects.get_or_create(pk=1)
    
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT DISTINCT c.id, c.nome, 
                   COUNT(d.id) as documentos_pendentes
            FROM rh_candidato c
            INNER JOIN rh_documento d ON c.id = d.candidato_id
            INNER JOIN rh_tipodocumento td ON d.tipo_id = td.id
            WHERE d.status IN ('pendente', 'recebido') 
            AND td.obrigatorio = 1
            GROUP BY c.id, c.nome
            HAVING COUNT(d.id) > 0
            ORDER BY c.nome
        """)
        candidatos_teste = [
            {'id': row[0], 'nome': row[1], 'documentos_pendentes': row[2]}
            for row in cursor.fetchall()
        ]
    
    if request.method == 'POST':
        print(f"[v0] POST data recebido: {request.POST}")
        form = ConfiguracaoCobrancaForm(request.POST, instance=config)
        print(f"[v0] Form is_valid: {form.is_valid()}")
        if form.is_valid():
            print(f"[v0] Dados limpos do form: {form.cleaned_data}")
            try:
                saved_config = form.save()
                print(f"[v0] Configuração salva com sucesso: {saved_config}")
                
                from .automacao_cobranca import automacao_cobranca
                automacao_cobranca.reload_config()
                
                messages.success(request, 'Configuração de cobrança salva com sucesso!')
                return redirect('configuracao_cobranca')
            except Exception as e:
                print(f"[v0] Erro ao salvar: {str(e)}")
                messages.error(request, f'Erro ao salvar configuração: {str(e)}')
        else:
            print(f"[v0] Erros do formulário: {form.errors}")
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'Erro no campo {field}: {error}')
    else:
        form = ConfiguracaoCobrancaForm(instance=config)
    
    return render(request, 'rh/configuracao_cobranca.html', {
        'form': form, 
        'config': config,
        'candidatos_teste': candidatos_teste
    })

@login_required
def pausar_cobranca_candidato(request, candidato_id):
    """View para pausar/despausar cobrança de um candidato específico"""
    candidato = get_object_or_404(Candidato, id=candidato_id)
    
    if request.method == 'POST':
        controle, created = ControleCobrancaCandidato.objects.get_or_create(candidato=candidato)
        
        if not controle.cobranca_pausada:
            # Pausando a cobrança
            motivo = request.POST.get('motivo_pausa', '')
            controle.cobranca_pausada = True
            controle.data_pausa = timezone.now()
            controle.pausado_por = request.user
            controle.motivo_pausa = motivo
            controle.save()
            
            messages.success(request, f'Cobrança pausada para {candidato.nome}!')
            status = "pausada"
        else:
            # Reativando a cobrança
            controle.cobranca_pausada = False
            controle.data_pausa = None
            controle.pausado_por = None
            controle.motivo_pausa = None
            controle.save()
            
            messages.success(request, f'Cobrança reativada para {candidato.nome}!')
            status = "reativada"
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'pausado': controle.cobranca_pausada})
    
    return redirect('detalhe_candidato', candidato_id=candidato_id)

@login_required
def reativar_cobranca_candidato(request, candidato_id):
    """View para reativar cobrança de um candidato específico"""
    candidato = get_object_or_404(Candidato, id=candidato_id)
    
    if request.method == 'POST':
        controle, created = ControleCobrancaCandidato.objects.get_or_create(candidato=candidato)
        controle.cobranca_pausada = False
        controle.data_pausa = None
        controle.pausado_por = None
        controle.motivo_pausa = None
        controle.save()
        
        messages.success(request, f'Cobrança reativada para {candidato.nome}!')
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'pausado': False})
    
    return redirect('detalhe_candidato', candidato_id=candidato_id)

@login_required
def historico_cobranca(request):
    """View para visualizar histórico de cobranças"""
    historicos = HistoricoCobranca.objects.all().order_by('-data_envio')
    
    # Filtros
    candidato_nome = request.GET.get('candidato')
    data_inicio = request.GET.get('data_inicio')
    data_fim = request.GET.get('data_fim')
    
    if candidato_nome:
        historicos = historicos.filter(candidato__nome__icontains=candidato_nome)
    
    if data_inicio:
        historicos = historicos.filter(data_envio__gte=data_inicio)
    
    if data_fim:
        historicos = historicos.filter(data_envio__lte=data_fim)
    
    # Paginação
    from django.core.paginator import Paginator
    paginator = Paginator(historicos, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'rh/historico_cobranca.html', {'page_obj': page_obj})

@login_required
def executar_cobranca_manual(request):
    """View para executar cobrança manual"""
    if request.method == 'POST':
        from .tasks import executar_cobranca_automatica
        try:
            resultado = executar_cobranca_automatica()
            messages.success(request, f'Cobrança executada! {resultado["enviados"]} mensagens enviadas.')
        except Exception as e:
            messages.error(request, f'Erro ao executar cobrança: {str(e)}')
    
    return redirect('configuracao_cobranca')

@login_required
@user_passes_test(is_admin)
def admin_dashboard(request):
    """View para o dashboard administrativo com configurações de cobrança"""
    config, created = ConfiguracaoCobranca.objects.get_or_create(pk=1)
    
    if request.method == 'POST' and 'salvar_cobranca' in request.POST:
        form_cobranca = ConfiguracaoCobrancaForm(request.POST, instance=config)
        if form_cobranca.is_valid():
            try:
                form_cobranca.save()
                
                from .automacao_cobranca import automacao_cobranca
                automacao_cobranca.reload_config()
                
                messages.success(request, 'Configuração de cobrança automática salva com sucesso!')
                return redirect('admin_dashboard')
            except Exception as e:
                messages.error(request, f'Erro ao salvar configuração: {str(e)}')
        else:
            for field, errors in form_cobranca.errors.items():
                for error in errors:
                    messages.error(request, f'Erro no campo {field}: {error}')
    else:
        form_cobranca = ConfiguracaoCobrancaForm(instance=config)
        
    usuarios = User.objects.all().order_by('-date_joined')
    setores = Setor.objects.all().order_by('nome')
    
    # Calcular totais para o dashboard
    total_setores = setores.count()
    total_usuarios = usuarios.count()
    total_admins = usuarios.filter(is_staff=True).count()
    total_ativos = usuarios.filter(is_active=True).count()
    total_pendentes = usuarios.filter(is_active=False).count()
    
    context = {
        'usuarios': usuarios,
        'setores': setores,
        'tem_acesso_completo': tem_acesso_completo(request.user),
        'total_setores': total_setores,
        'total_usuarios': total_usuarios,
        'total_admins': total_admins,
        'total_ativos': total_ativos,
        'total_pendentes': total_pendentes,
        'form_cobranca': form_cobranca,
        'config_cobranca': config,        
    }
    
    return render(request, 'admin_dashboard.html', context)

@login_required
def testar_envio_cobranca(request):
    """View para testar envio de mensagem de cobrança para um candidato específico"""
    if request.method == 'POST':
        import json
        try:
            data = json.loads(request.body)
            candidato_id = data.get('candidato_id')
            
            if not candidato_id:
                return JsonResponse({'success': False, 'message': 'ID do candidato não fornecido'})
            
            candidato = get_object_or_404(Candidato, id=candidato_id)
            
            config = ConfiguracaoCobranca.objects.first()
            if not config:
                return JsonResponse({'success': False, 'message': 'Configuração de cobrança não encontrada'})
            
            # Buscar documentos obrigatórios pendentes
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT td.nome, td.nome_exibicao
                    FROM rh_documento d
                    INNER JOIN rh_tipodocumento td ON d.tipo_id = td.id
                    WHERE d.candidato_id = %s 
                    AND d.status IN ('pendente', 'recebido')
                    AND td.obrigatorio = 1
                    ORDER BY td.nome
                """, [candidato_id])
                documentos_data = cursor.fetchall()
            
            if not documentos_data:
                return JsonResponse({'success': False, 'message': 'Candidato não possui documentos obrigatórios pendentes'})
            
            template = config.mensagem_template or """🔔 *Olá {nome}!*

Esperamos que esteja bem! Notamos que ainda há alguns documentos pendentes em seu processo de contratação.

📋 *Documentos obrigatórios pendentes:*

{documentos}

⏰ *Por favor, envie estes documentos o mais breve possível para darmos continuidade ao seu processo.*

📱 Você pode enviar através do nosso sistema online ou entrar em contato conosco.

Agradecemos sua atenção!

*Equipe RH - BRG Geradores*"""
            
            documentos_tecnicos = [row[0] for row in documentos_data]
            documentos_formatados = '\n'.join([f'• *{row[0]}*' for row in documentos_data])
            
            # Criar lista com nomes de exibição
            documentos_exibicao = []
            for row in documentos_data:
                nome_tecnico, nome_exibicao = row
                if nome_exibicao:
                    documentos_exibicao.append(nome_exibicao)
                else:
                    # Se não tiver nome_exibicao, formata o nome técnico
                    documentos_exibicao.append(nome_tecnico.replace('_', ' ').title())
            
            documentos_exibicao_formatados = '\n'.join([f'• *{doc}*' for doc in documentos_exibicao])
            
            # Substituir variáveis no template
            mensagem = template.replace('{nome}', candidato.nome)
            mensagem = mensagem.replace('{documentos}', documentos_formatados)
            mensagem = mensagem.replace('{documentos_exibicao}', documentos_exibicao_formatados)
            
            # Enviar mensagem via WhatsApp
            from .whatsapp import enviar_mensagem_whatsapp
            sucesso = enviar_mensagem_whatsapp(candidato.telefone, mensagem)
            
            if sucesso:
                HistoricoCobranca.objects.create(
                    candidato=candidato,
                    mensagem_enviada=mensagem,
                    documentos_cobrados=documentos_tecnicos,  # Lista de documentos técnicos
                    sucesso=True
                )
                
                return JsonResponse({
                    'success': True, 
                    'message': f'Mensagem de teste enviada com sucesso para {candidato.nome}!'
                })
            else:
                HistoricoCobranca.objects.create(
                    candidato=candidato,
                    mensagem_enviada=mensagem,
                    documentos_cobrados=documentos_tecnicos,
                    sucesso=False,
                    erro='Erro ao enviar mensagem via WhatsApp'
                )
                
                return JsonResponse({
                    'success': False, 
                    'message': 'Erro ao enviar mensagem via WhatsApp'
                })
                
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'message': 'Dados JSON inválidos'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Erro interno: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Método não permitido'})
