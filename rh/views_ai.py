
"""
Views relacionadas a funcionalidades de IA no sistema.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import json
import base64
from io import BytesIO
from PIL import Image

from .models import Candidato, Documento, TipoDocumento
from .utils.document_recognition import (
    process_document_file,
    validate_document_file,
    extract_data_from_document,
    auto_validate_document
)
from .utils.timeline import registrar_evento
from .views import atualizar_status_candidato # Import the function

@login_required
def analisar_documento(request, documento_id):
    """
    View para analisar um documento usando IA.
    """
    documento = get_object_or_404(Documento, id=documento_id)
    
    # Verificar permissões
    if not request.user.is_staff and request.user != documento.candidato.criado_por:
        messages.error(request, "Voc não tem permissão para analisar este documento.")
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)
    
    # Verificar se o documento tem arquivo
    if not documento.arquivo:
        messages.error(request, "Este documento não possui arquivo para análise.")
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)
    
    try:
        # Analisar o documento
        sucesso, mensagem, dados = process_document_file(documento.arquivo.path)
        
        if sucesso:
            # Atualizar as observações do documento com os dados extraídos
            dados_str = "\n".join([f"{k}: {v}" for k, v in dados.items() if k not in ['error']])
            documento.observacoes = f"Análise automática:\n{dados_str}"
            documento.save()
            
            messages.success(request, f"Documento analisado com sucesso: {mensagem}")
        else:
            messages.warning(request, f"Análise incompleta: {mensagem}")
        
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)
    
    except Exception as e:
        messages.error(request, f"Erro ao analisar documento: {str(e)}")
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)

@login_required
def validar_documento_ai(request, documento_id):
    """
    View para validar um documento usando IA.
    """
    documento = get_object_or_404(Documento, id=documento_id)
    
    # Verificar permissões
    if not request.user.is_staff and request.user != documento.candidato.criado_por:
        messages.error(request, "Você não tem permissão para validar este documento.")
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)
    
    # Verificar se o documento tem arquivo
    if not documento.arquivo:
        messages.error(request, "Este documento não possui arquivo para validação.")
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)
    
    try:
        # Guardar o status anterior
        status_anterior = documento.status
        
        # Validar o documento
        sucesso, mensagem = auto_validate_document(documento)
        
        if sucesso:
            # Atualizar o status do documento
            documento.status = 'validado'
            documento.save()
            
            # Registrar o evento na timeline
            registrar_evento(
                candidato=documento.candidato,
                tipo_evento='documento_validado',
                documento=documento,
                status_anterior=status_anterior,
                status_novo='validado',
                observacoes=f"Validação automática pela IA: {mensagem}"
            )
            
            messages.success(request, f"Documento validado com sucesso pela IA.")
        else:
            # Se a validação falhar, marcar como inválido
            documento.status = 'invalido'
            documento.save()
            
            # Registrar o evento na timeline
            registrar_evento(
                candidato=documento.candidato,
                tipo_evento='documento_invalidado',
                documento=documento,
                status_anterior=status_anterior,
                status_novo='invalido',
                observacoes=f"Invalidação automática pela IA: {mensagem}"
            )
            
            messages.warning(request, f"Documento invalidado pela IA: {mensagem}")
        
        # Atualizar o status do candidato após a validação/invalidação
        atualizar_status_candidato(documento.candidato)
        
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)
    
    except Exception as e:
        messages.error(request, f"Erro ao validar documento: {str(e)}")
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)

@csrf_exempt
@require_http_methods(["POST"])
def api_analisar_documento(request):
    """
    API para analisar um documento via AJAX.
    """
    try:
        # Verificar autenticação
        if not request.user.is_authenticated:
            return JsonResponse({'success': False, 'error': 'Não autenticado'}, status=401)
        
        # Obter dados do request
        data = json.loads(request.body)
        documento_id = data.get('documento_id')
        
        if not documento_id:
            return JsonResponse({'success': False, 'error': 'ID do documento não fornecido'}, status=400)
        
        # Obter o documento
        documento = get_object_or_404(Documento, id=documento_id)
        
        # Verificar permissões
        if not request.user.is_staff and request.user != documento.candidato.criado_por:
            return JsonResponse({'success': False, 'error': 'Sem permissão'}, status=403)
        
        # Verificar se o documento tem arquivo
        if not documento.arquivo:
            return JsonResponse({'success': False, 'error': 'Documento sem arquivo'}, status=400)
        
        # Analisar o documento
        sucesso, mensagem, dados = process_document_file(documento.arquivo.path)
        
        if sucesso:
            return JsonResponse({
                'success': True,
                'message': mensagem,
                'data': dados
            })
        else:
            return JsonResponse({
                'success': False,
                'error': mensagem,
                'data': dados
            })
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def validar_documentos_pendentes(request):
    """
    View para validar todos os documentos pendentes usando IA.
    """
    # Verificar permissões
    if not request.user.is_staff:
        messages.error(request, "Você não tem permissão para esta operação.")
        return redirect('dashboard')
    
    # Obter documentos pendentes
    documentos_pendentes = Documento.objects.filter(status='recebido')
    total = documentos_pendentes.count()
    
    if total == 0:
        messages.info(request, "Não há documentos pendentes para validação.")
        return redirect('dashboard')
    
    # Processar documentos
    validados = 0
    invalidados = 0
    
    # Collect unique candidate IDs to update their status once after processing all their documents
    candidates_to_update = set()

    for doc in documentos_pendentes:
        try:
            # Guardar o status anterior
            status_anterior = doc.status
            
            # Validar o documento
            sucesso, mensagem = auto_validate_document(doc)
            
            if sucesso:
                # Atualizar o status do documento
                doc.status = 'validado'
                doc.save()
                
                # Registrar o evento na timeline
                registrar_evento(
                    candidato=doc.candidato,
                    tipo_evento='documento_validado',
                    documento=doc,
                    status_anterior=status_anterior,
                    status_novo='validado',
                    observacoes=f"Validação automática em lote: {mensagem}"
                )
                
                validados += 1
            else:
                # Se a validação falhar, marcar como inválido
                doc.status = 'invalido'
                doc.save()
                
                # Registrar o evento na timeline
                registrar_evento(
                    candidato=doc.candidato,
                    tipo_evento='documento_invalidado',
                    documento=doc,
                    status_anterior=status_anterior,
                    status_novo='invalido',
                    observacoes=f"Invalidação automática em lote: {mensagem}"
                )
                
                invalidados += 1
            
            # Add candidate to the set for later update
            candidates_to_update.add(doc.candidato)

        except Exception as e:
            # Registrar erro e continuar
            doc.observacoes = f"Erro na validação automática: {str(e)}"
            doc.save()
            # Still add candidate to update set if an error occurred during processing
            candidates_to_update.add(doc.candidato)
    
    # Update status for all affected candidates
    for candidate in candidates_to_update:
        atualizar_status_candidato(candidate)

    messages.success(request, f"Processamento concluído: {validados} documentos validados, {invalidados} invalidados.")
    return redirect('dashboard')


'''

"""
Views relacionadas a funcionalidades de IA no sistema.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import json
import base64
from io import BytesIO
from PIL import Image

from .models import Candidato, Documento, TipoDocumento
from .utils.document_recognition import (
    process_document_file,
    validate_document_file,
    extract_data_from_document,
    auto_validate_document
)
from .utils.timeline import registrar_evento

@login_required
def analisar_documento(request, documento_id):
    """
    View para analisar um documento usando IA.
    """
    documento = get_object_or_404(Documento, id=documento_id)
    
    # Verificar permissões
    if not request.user.is_staff and request.user != documento.candidato.criado_por:
        messages.error(request, "Voc�� não tem permissão para analisar este documento.")
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)
    
    # Verificar se o documento tem arquivo
    if not documento.arquivo:
        messages.error(request, "Este documento não possui arquivo para análise.")
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)
    
    try:
        # Analisar o documento
        sucesso, mensagem, dados = process_document_file(documento.arquivo.path)
        
        if sucesso:
            # Atualizar as observações do documento com os dados extraídos
            dados_str = "\n".join([f"{k}: {v}" for k, v in dados.items() if k not in ['error']])
            documento.observacoes = f"Análise automática:\n{dados_str}"
            documento.save()
            
            messages.success(request, f"Documento analisado com sucesso: {mensagem}")
        else:
            messages.warning(request, f"Análise incompleta: {mensagem}")
        
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)
    
    except Exception as e:
        messages.error(request, f"Erro ao analisar documento: {str(e)}")
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)

@login_required
def validar_documento_ai(request, documento_id):
    """
    View para validar um documento usando IA.
    """
    documento = get_object_or_404(Documento, id=documento_id)
    
    # Verificar permissões
    if not request.user.is_staff and request.user != documento.candidato.criado_por:
        messages.error(request, "Você não tem permissão para validar este documento.")
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)
    
    # Verificar se o documento tem arquivo
    if not documento.arquivo:
        messages.error(request, "Este documento não possui arquivo para validação.")
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)
    
    try:
        # Guardar o status anterior
        status_anterior = documento.status
        
        # Validar o documento
        sucesso, mensagem = auto_validate_document(documento)
        
        if sucesso:
            # Atualizar o status do documento
            documento.status = 'validado'
            documento.save()
            
            # Registrar o evento na timeline
            registrar_evento(
                candidato=documento.candidato,
                tipo_evento='documento_validado',
                documento=documento,
                status_anterior=status_anterior,
                status_novo='validado',
                observacoes=f"Validação automática pela IA: {mensagem}"
            )
            
            messages.success(request, f"Documento validado com sucesso pela IA.")
        else:
            # Se a validação falhar, marcar como inválido
            documento.status = 'invalido'
            documento.save()
            
            # Registrar o evento na timeline
            registrar_evento(
                candidato=documento.candidato,
                tipo_evento='documento_invalidado',
                documento=documento,
                status_anterior=status_anterior,
                status_novo='invalido',
                observacoes=f"Invalidação automática pela IA: {mensagem}"
            )
            
            messages.warning(request, f"Documento invalidado pela IA: {mensagem}")
        
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)
    
    except Exception as e:
        messages.error(request, f"Erro ao validar documento: {str(e)}")
        return redirect('detalhe_candidato', candidato_id=documento.candidato.id)

@csrf_exempt
@require_http_methods(["POST"])
def api_analisar_documento(request):
    """
    API para analisar um documento via AJAX.
    """
    try:
        # Verificar autenticação
        if not request.user.is_authenticated:
            return JsonResponse({'success': False, 'error': 'Não autenticado'}, status=401)
        
        # Obter dados do request
        data = json.loads(request.body)
        documento_id = data.get('documento_id')
        
        if not documento_id:
            return JsonResponse({'success': False, 'error': 'ID do documento não fornecido'}, status=400)
        
        # Obter o documento
        documento = get_object_or_404(Documento, id=documento_id)
        
        # Verificar permissões
        if not request.user.is_staff and request.user != documento.candidato.criado_por:
            return JsonResponse({'success': False, 'error': 'Sem permissão'}, status=403)
        
        # Verificar se o documento tem arquivo
        if not documento.arquivo:
            return JsonResponse({'success': False, 'error': 'Documento sem arquivo'}, status=400)
        
        # Analisar o documento
        sucesso, mensagem, dados = process_document_file(documento.arquivo.path)
        
        if sucesso:
            return JsonResponse({
                'success': True,
                'message': mensagem,
                'data': dados
            })
        else:
            return JsonResponse({
                'success': False,
                'error': mensagem,
                'data': dados
            })
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def validar_documentos_pendentes(request):
    """
    View para validar todos os documentos pendentes usando IA.
    """
    # Verificar permissões
    if not request.user.is_staff:
        messages.error(request, "Você não tem permissão para esta operação.")
        return redirect('dashboard')
    
    # Obter documentos pendentes
    documentos_pendentes = Documento.objects.filter(status='recebido')
    total = documentos_pendentes.count()
    
    if total == 0:
        messages.info(request, "Não há documentos pendentes para validação.")
        return redirect('dashboard')
    
    # Processar documentos
    validados = 0
    invalidados = 0
    
    for doc in documentos_pendentes:
        try:
            # Guardar o status anterior
            status_anterior = doc.status
            
            # Validar o documento
            sucesso, mensagem = auto_validate_document(doc)
            
            if sucesso:
                # Atualizar o status do documento
                doc.status = 'validado'
                doc.save()
                
                # Registrar o evento na timeline
                registrar_evento(
                    candidato=doc.candidato,
                    tipo_evento='documento_validado',
                    documento=doc,
                    status_anterior=status_anterior,
                    status_novo='validado',
                    observacoes=f"Validação automática em lote: {mensagem}"
                )
                
                validados += 1
            else:
                # Se a validação falhar, marcar como inválido
                doc.status = 'invalido'
                doc.save()
                
                # Registrar o evento na timeline
                registrar_evento(
                    candidato=doc.candidato,
                    tipo_evento='documento_invalidado',
                    documento=doc,
                    status_anterior=status_anterior,
                    status_novo='invalido',
                    observacoes=f"Invalidação automática em lote: {mensagem}"
                )
                
                invalidados += 1
        
        except Exception as e:
            # Registrar erro e continuar
            doc.observacoes = f"Erro na validação automática: {str(e)}"
            doc.save()
    
    messages.success(request, f"Processamento concluído: {validados} documentos validados, {invalidados} invalidados.")
    return redirect('dashboard')
'''