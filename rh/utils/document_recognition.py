"""
Módulo para reconhecimento e validação de documentos usando IA.
Este módulo integra com o analisador de documentos baseado em Groq
para identificar e validar documentos enviados pelos candidatos.
"""

import os
import logging
from typing import Dict, Tuple, List, Optional, Any
from PIL import Image
import io
import base64
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

# Importar o analisador de documentos
from .ai_document_analyzer import (
    identify_document_type,
    validate_document,
    extract_document_data,
    get_required_fields
)

# Configurar logging
logger = logging.getLogger(__name__)

# Mapeamento de tipos de documentos
DOCUMENT_TYPE_MAPPING = {
    "rg": "RG",
    "cpf": "CPF",
    "cnh": "CNH",
    "ctps": "CTPS",
    "comprovante_residencia": "COMPROVANTE_RESIDENCIA",
    "titulo_eleitor": "TITULO_ELEITOR",
    "dispensa_militar": "DISPENSA_MILITAR",
    "carteira_vacinacao": "CARTEIRA_VACINACAO",
    "certidao_nascimento": "CERTIDAO_NASCIMENTO",
    "certidao_casamento": "CERTIDAO_CASAMENTO",
    "passaporte": "PASSAPORTE",
    "pis": "PIS",
    "foto_rosto": "FOTO_ROSTO",
    "outros": "OUTROS"
}

def get_normalized_document_type(tipo_doc_nome: str) -> str:
    """
    Normaliza o nome do tipo de documento para o formato esperado pelo analisador.
    
    Args:
        tipo_doc_nome: Nome do tipo de documento (do modelo TipoDocumento)
        
    Returns:
        Nome normalizado do tipo de documento
    """
    tipo_doc_nome = tipo_doc_nome.lower().replace(" ", "_")
    return DOCUMENT_TYPE_MAPPING.get(tipo_doc_nome, tipo_doc_nome.upper())

def process_document_file(file_path: str) -> Tuple[bool, str, Dict]:
    """
    Processa um documento a partir do caminho do arquivo.
    
    Args:
        file_path: Caminho para o arquivo do documento
        
    Returns:
        Tupla com (sucesso, mensagem, dados)
    """
    try:
        # Verificar se o arquivo existe
        if not default_storage.exists(file_path):
            return False, f"Arquivo não encontrado: {file_path}", {}
        
        # Abrir o arquivo
        with default_storage.open(file_path, 'rb') as f:
            file_data = f.read()
        
        # Identificar o tipo de documento
        image = Image.open(io.BytesIO(file_data))
        resultado = identify_document_type(image)
        
        # Verificar se houve erro
        if resultado.startswith("erro|"):
            erro = resultado.split("|", 1)[1]
            return False, f"Erro ao identificar documento: {erro}", {"error": erro}
        
        # Extrair tipo e descrição adicional
        partes = resultado.split("|", 1)
        tipo = partes[0]
        descricao = partes[1] if len(partes) > 1 else ""
        
        # Preparar os dados de retorno
        dados = {
            "tipo_documento": tipo,
            "confianca": 90,  # Valor padrão
            "qualidade": "boa"  # Valor padrão
        }
        
        # Se for "outros" com descrição, adicionar à resposta
        if tipo == "outros" and descricao:
            dados["descricao_especial"] = descricao
            return True, f"Documento identificado como outros: {descricao}", dados
        
        return True, f"Documento identificado como {tipo}", dados
    
    except Exception as e:
        logger.error(f"Erro ao processar documento: {str(e)}")
        return False, f"Erro ao processar documento: {str(e)}", {}

def validate_document_file(file_path: str, expected_type: str) -> Tuple[bool, str, Dict]:
    """
    Valida um documento a partir do caminho do arquivo.
    
    Args:
        file_path: Caminho para o arquivo do documento
        expected_type: Tipo de documento esperado
        
    Returns:
        Tupla com (válido, mensagem, dados)
    """
    try:
        # Verificar se o arquivo existe
        if not default_storage.exists(file_path):
            return False, f"Arquivo não encontrado: {file_path}", {}
        
        # Abrir o arquivo
        with default_storage.open(file_path, 'rb') as f:
            file_data = f.read()
        
        # Normalizar o tipo esperado
        normalized_type = get_normalized_document_type(expected_type)
        
        # Obter campos obrigatórios
        required_fields = get_required_fields(normalized_type)
        
        # Validar o documento
        image = Image.open(io.BytesIO(file_data))
        result = validate_document(image, normalized_type, required_fields)
        
        if result["valido"]:
            return True, "Documento válido", result["dados"]
        else:
            return False, result["motivo"], result["dados"]
    
    except Exception as e:
        logger.error(f"Erro ao validar documento: {str(e)}")
        return False, f"Erro ao validar documento: {str(e)}", {}

def extract_data_from_document(file_path: str, document_type: str) -> Dict:
    """
    Extrai dados de um documento a partir do caminho do arquivo.
    
    Args:
        file_path: Caminho para o arquivo do documento
        document_type: Tipo de documento
        
    Returns:
        Dicionário com os dados extraídos
    """
    try:
        # Verificar se o arquivo existe
        if not default_storage.exists(file_path):
            return {"error": f"Arquivo não encontrado: {file_path}"}
        
        # Abrir o arquivo
        with default_storage.open(file_path, 'rb') as f:
            file_data = f.read()
        
        # Normalizar o tipo
        normalized_type = get_normalized_document_type(document_type)
        
        # Extrair dados
        image = Image.open(io.BytesIO(file_data))
        return extract_document_data(image, normalized_type)
    
    except Exception as e:
        logger.error(f"Erro ao extrair dados do documento: {str(e)}")
        return {"error": str(e)}

def auto_validate_document(documento) -> Tuple[bool, str]:
    """
    Tenta validar automaticamente um documento usando IA.
    
    Args:
        documento: Objeto Documento do modelo Django
        
    Returns:
        Tupla com (sucesso, mensagem)
    """
    try:
        # Verificar se o documento tem arquivo
        if not documento.arquivo:
            return False, "Documento sem arquivo para validação"
        
        # Obter o tipo de documento normalizado
        tipo_doc_nome = documento.tipo.nome if documento.tipo else "DESCONHECIDO"
        normalized_type = get_normalized_document_type(tipo_doc_nome)
        
        # Primeiro, identificar o tipo real do documento
        with default_storage.open(documento.arquivo.path, 'rb') as f:
            file_data = f.read()
        
        image = Image.open(io.BytesIO(file_data))
        resultado_identificacao = identify_document_type(image)
        
        # Verificar se houve erro
        if resultado_identificacao.startswith("erro|"):
            erro = resultado_identificacao.split("|", 1)[1]
            documento.observacoes = f"Erro na identificação automática: {erro}"
            documento.save()
            return False, f"Erro na identificação: {erro}"
        
        # Extrair tipo e descrição adicional
        partes = resultado_identificacao.split("|", 1)
        tipo_identificado = partes[0]
        descricao_adicional = partes[1] if len(partes) > 1 else ""
        
        # Se o tipo identificado for "outros", verificar se há descrição especial
        if tipo_identificado == "outros" and descricao_adicional:
            # Adicionar a descrição especial às observações
            documento.observacoes = f"Documento identificado como: {descricao_adicional}\n\n"
            documento.observacoes += "Este documento não está na lista padrão de documentos aceitos."
            documento.save()
            
            # Se for um documento militar, podemos considerar válido
            if "militar" in descricao_adicional.lower() or "reservista" in descricao_adicional.lower():
                return True, f"Documento militar identificado: {descricao_adicional}"
            
            # Para outros tipos não reconhecidos, considerar inválido
            return False, f"Tipo de documento não reconhecido: {descricao_adicional}"
        
        # Se o tipo identificado não corresponder ao esperado
        if tipo_identificado != normalized_type.lower() and normalized_type != "OUTROS":
            documento.observacoes = f"Tipo de documento incorreto. Esperado: {normalized_type}, Identificado: {tipo_identificado}"
            documento.save()
            return False, f"Tipo de documento incorreto. Esperado: {normalized_type}, Identificado: {tipo_identificado}"
        
        # Validar o documento
        is_valid, message, data = validate_document_file(
            documento.arquivo.path, 
            normalized_type
        )
        
        # Atualizar observações do documento com os dados extraídos
        if is_valid:
            # Formatar os dados extraídos para as observações
            dados_str = "\n".join([f"{k}: {v}" for k, v in data.get("dados", {}).items()])
            documento.observacoes = f"Validado automaticamente pela IA.\nDados extraídos:\n{dados_str}"
        else:
            documento.observacoes = f"Falha na validação automática: {message}"
        
        documento.save()
        
        return is_valid, message
    
    except Exception as e:
        logger.error(f"Erro na validação automática: {str(e)}")
        return False, f"Erro na validação automática: {str(e)}"
