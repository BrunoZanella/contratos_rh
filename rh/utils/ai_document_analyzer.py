"""
Utilitário para análise de documentos usando Groq AI.
Este módulo fornece funções para analisar documentos, extrair informações
e validar documentos usando o modelo de linguagem Groq.
"""

import os
import base64
import json
from typing import Dict, List, Tuple, Optional, Any
import requests
from PIL import Image
import io
import logging
from groq import Groq
from django.conf import settings

# Configurar logging
logger = logging.getLogger(__name__)

# Obter a chave API do Groq das variáveis de ambiente
GROQ_API_KEY = settings.GROQ_API_KEY

if not GROQ_API_KEY:
    logger.warning("GROQ_API_KEY não encontrada nas variáveis de ambiente")

# Modelos disponíveis
MODELS = {
    "llama3-8b": "llama3-8b-8192",
    "llama3-70b": "llama3-70b-8192",
    "mixtral": "mixtral-8x7b-32768",
    "gemma": "gemma-7b-it",
    "llama4-scout": "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama4-maverick": "meta-llama/llama-4-maverick-17b-128e-instruct"
}

# Modelo padrão
DEFAULT_MODEL = MODELS["llama4-maverick"]

def encode_image_to_base64(image_path: str) -> str:
    """
    Converte uma imagem para base64.
    
    Args:
        image_path: Caminho para o arquivo de imagem
        
    Returns:
        String base64 da imagem
    """
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        logger.error(f"Erro ao codificar imagem: {str(e)}")
        raise

def pil_image_to_base64(image: Image.Image) -> str:
    """
    Converte uma imagem PIL para base64.
    
    Args:
        image: Objeto PIL Image
        
    Returns:
        String base64 da imagem
    """
    try:
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG")
        return base64.b64encode(buffered.getvalue()).decode('utf-8')
    except Exception as e:
        logger.error(f"Erro ao converter imagem PIL para base64: {str(e)}")
        raise

def processar_imagem(imagem: Image.Image) -> Image.Image:
    """
    Processa uma imagem para melhorar a qualidade para análise.
    
    Args:
        imagem: Objeto PIL Image
        
    Returns:
        Imagem processada
    """
    try:
        # Converter para RGB se necessário
        if imagem.mode != 'RGB':
            imagem = imagem.convert('RGB')

        # Redimensionar se for muito grande
        max_size = 1024
        if max(imagem.size) > max_size:
            ratio = max_size / max(imagem.size)
            new_size = tuple(int(dim * ratio) for dim in imagem.size)
            imagem = imagem.resize(new_size, Image.Resampling.LANCZOS)

        return imagem
    except Exception as e:
        logger.error(f"Erro ao processar imagem: {str(e)}")
        return imagem

def identify_document_type(
    image_data: Any,
    model: str = DEFAULT_MODEL
) -> str:
    """
    Identifica o tipo de um documento a partir de uma imagem.
    
    Args:
        image_data: Pode ser um caminho para a imagem, um objeto PIL Image, ou uma string base64
        model: Modelo Groq a ser usado
        
    Returns:
        String com o tipo de documento identificado
    """
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY não configurada")
    
    # Preparar a imagem em base64
    if isinstance(image_data, str) and os.path.isfile(image_data):
        # É um caminho de arquivo
        image_base64 = encode_image_to_base64(image_data)
        # Também carrega como PIL para processamento
        image = Image.open(image_data)
        image = processar_imagem(image)
    elif isinstance(image_data, Image.Image):
        # É um objeto PIL Image
        image = processar_imagem(image_data)
        image_base64 = pil_image_to_base64(image)
    elif isinstance(image_data, str):
        # Assume que já é uma string base64
        image_base64 = image_data
    else:
        raise ValueError("Formato de imagem não suportado")
    
    # Prompt para identificação de documentos
    prompt = """Analise esta imagem e identifique qual tipo de documento brasileiro é.
Responda APENAS com um dos seguintes códigos exatos, sem adicionar nada mais:

- rg
- cpf
- cnh
- ctps
- comprovante_residencia
- titulo_eleitor
- dispensa_militar
- carteira_vacinacao
- certidao_nascimento
- certidao_casamento
- passaporte
- carteira_trabalho_digital
- pis
- outros

Se for um documento que não está na lista acima, responda "outros" e depois descreva qual documento você acredita que seja.

Características específicas:
- RG: foto 3x4, impressão digital
- CNH: layout horizontal, categorias
- CPF: sem foto, número XXX.XXX.XXX-XX
- CTPS: azul, com foto
- Título de Eleitor: zona e seção
- Comprovante: cabeçalho de empresa, endereço, CEP
- Dispensa Militar: certificado de dispensa de incorporação (CDI) ou certificado de reservista
- Carteira de Vacinação: registro de vacinas
- Certidão de Nascimento: documento vertical com dados de nascimento
- Certidão de Casamento: similar à certidão de nascimento, mas com dados de casamento
- Passaporte: documento de viagem internacional
- PIS: número de identificação do trabalhador"""

    try:
        # Inicializar o cliente Groq
        client = Groq(api_key=GROQ_API_KEY)
        
        # Fazer a requisição
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                    ]
                }
            ],
            temperature=0.2,
            max_completion_tokens=1024,
            top_p=1,
            stream=False
        )
        
        # Extrair a resposta
        result = response.choices[0].message.content.strip()
        
        # Processar a resposta para extrair informações adicionais
        tipo_documento = result.lower()
        descricao_adicional = ""
        
        # Se a resposta contiver mais informações além do tipo
        if "outros" in tipo_documento and len(tipo_documento) > 6:
            partes = tipo_documento.split("outros", 1)
            tipo_documento = "outros"
            descricao_adicional = partes[1].strip()
            
            # Verificar se há menções a documentos específicos na descrição
            documentos_especiais = {
                "dispensa militar": "**DISPENSA MILITAR**",
                "reservista": "**RESERVISTA**",
                "certificado de dispensa": "**DISPENSA MILITAR**",
                "certificado de reservista": "**RESERVISTA**",
                "alistamento militar": "**ALISTAMENTO MILITAR**",
                "cartão cnpj": "**CARTÃO CNPJ**",
                "cartão de cnpj": "**CARTÃO CNPJ**",
                "carteira de trabalho digital": "**CTPS DIGITAL**",
                "carteira digital": "**CTPS DIGITAL**",
                "inss": "**CARTÃO INSS**",
                "cartão do inss": "**CARTÃO INSS**",
                "carteira de vacinação": "**CARTEIRA DE VACINAÇÃO**",
                "certidão de nascimento": "**CERTIDÃO DE NASCIMENTO**",
                "certidão de casamento": "**CERTIDÃO DE CASAMENTO**",
                "passaporte": "**PASSAPORTE**"
            }
            
            for termo, formatado in documentos_especiais.items():
                if termo in descricao_adicional.lower():
                    descricao_adicional = formatado
                    break
        
        # Retornar o tipo e a descrição adicional
        if descricao_adicional:
            return f"{tipo_documento}|{descricao_adicional}"
        return tipo_documento
        
    except Exception as e:
        logger.error(f"Erro na identificação do documento: {str(e)}")
        return f"erro|{str(e)}"

def analyze_document(
    image_data: Any,
    document_type: Optional[str] = None,
    model: str = DEFAULT_MODEL
) -> Dict:
    """
    Analisa um documento usando o Groq AI.
    
    Args:
        image_data: Pode ser um caminho para a imagem, um objeto PIL Image, ou uma string base64
        document_type: Tipo de documento esperado (opcional)
        model: Modelo Groq a ser usado
        
    Returns:
        Dicionário com os resultados da análise
    """
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY não configurada")
    
    # Preparar a imagem em base64
    if isinstance(image_data, str) and os.path.isfile(image_data):
        # É um caminho de arquivo
        image_base64 = encode_image_to_base64(image_data)
        # Também carrega como PIL para processamento
        image = Image.open(image_data)
        image = processar_imagem(image)
    elif isinstance(image_data, Image.Image):
        # É um objeto PIL Image
        image = processar_imagem(image_data)
        image_base64 = pil_image_to_base64(image)
    elif isinstance(image_data, str):
        # Assume que já é uma string base64
        image_base64 = image_data
    else:
        raise ValueError("Formato de imagem não suportado")
    
    # Se não tiver tipo de documento, primeiro identifica
    if not document_type:
        tipo_resultado = identify_document_type(image, model)
        
        # Verificar se houve erro na identificação
        if tipo_resultado.startswith("erro|"):
            return {"error": tipo_resultado.split("|", 1)[1]}
        
        # Extrair tipo e descrição adicional
        partes = tipo_resultado.split("|", 1)
        tipo_identificado = partes[0]
        descricao_adicional = partes[1] if len(partes) > 1 else ""
        
        # Se for "outros" com descrição, usar a descrição para melhorar a análise
        if tipo_identificado == "outros" and descricao_adicional:
            document_type = descricao_adicional.replace("**", "")
        else:
            document_type = tipo_identificado
    
    # Construir o prompt baseado no tipo de documento
    system_prompt = f"""Você é um assistente especializado em análise de documentos brasileiros.
Analise esta imagem de um {document_type} e extraia todas as informações relevantes.
Forneça os dados em formato JSON com os seguintes campos:
- tipo_documento: o tipo de documento identificado (use exatamente o que foi informado)
- dados: um objeto com as informações extraídas específicas para este tipo de documento
- qualidade: uma avaliação da qualidade e legibilidade do documento (boa, média, ruim)
- problemas: lista de problemas identificados, se houver
- confianca: nível de confiança na identificação (0-100)"""

    try:
        # Inicializar o cliente Groq
        client = Groq(api_key=GROQ_API_KEY)
        
        # Fazer a requisição
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Analise este documento e extraia as informações relevantes:"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            temperature=0.2,
            max_completion_tokens=1024,
            top_p=1,
            stream=False
        )
        
        # Extrair a resposta do modelo
        content = response.choices[0].message.content
        
        # Tentar extrair o JSON da resposta
        try:
            # Procurar por blocos de código JSON na resposta
            if "```json" in content:
                json_content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_content = content.split("```")[1].strip()
            else:
                json_content = content
                
            result = json.loads(json_content)
            
            # Se o tipo identificado for "outros" e tiver descrição adicional, adicionar ao resultado
            if document_type.lower() == "outros" and "descricao_adicional" in locals() and descricao_adicional:
                result["descricao_especial"] = descricao_adicional
            
            return result
        except json.JSONDecodeError:
            # Se não conseguir extrair JSON, retornar a resposta como texto
            return {"raw_response": content, "error": "Não foi possível extrair JSON da resposta"}
            
    except Exception as e:
        logger.error(f"Erro ao analisar documento: {str(e)}")
        return {"error": str(e)}

def validate_document(
    image_data: Any, 
    expected_type: str,
    required_fields: List[str] = None
) -> Dict:
    """
    Valida se um documento é do tipo esperado e contém os campos necessários.
    
    Args:
        image_data: Pode ser um caminho para a imagem, um objeto PIL Image, ou uma string base64
        expected_type: Tipo de documento esperado
        required_fields: Lista de campos obrigatórios para validação
        
    Returns:
        Dicionário com resultado da validação
    """
    result = analyze_document(image_data, document_type=expected_type)
    
    if "error" in result:
        return {
            "valido": False,
            "motivo": f"Erro na análise: {result['error']}",
            "dados": {}
        }
    
    # Verificar se o tipo identificado corresponde ao esperado
    tipo_identificado = result.get("tipo_documento", "").lower()
    if tipo_identificado and expected_type.lower() not in tipo_identificado:
        return {
            "valido": False,
            "motivo": f"Tipo de documento incorreto. Esperado: {expected_type}, Identificado: {tipo_identificado}",
            "dados": result
        }
    
    # Verificar campos obrigatórios
    if required_fields:
        dados = result.get("dados", {})
        campos_faltantes = [campo for campo in required_fields if campo not in dados or not dados[campo]]
        
        if campos_faltantes:
            return {
                "valido": False,
                "motivo": f"Campos obrigatórios ausentes ou ilegíveis: {', '.join(campos_faltantes)}",
                "campos_faltantes": campos_faltantes,
                "dados": result
            }
    
    # Verificar qualidade
    qualidade = result.get("qualidade", "").lower()
    if qualidade == "ruim":
        return {
            "valido": False,
            "motivo": "Qualidade da imagem muito baixa para processamento adequado",
            "dados": result
        }
    
    # Se passou por todas as verificações
    return {
        "valido": True,
        "dados": result
    }

def extract_document_data(image_data: Any, document_type: str) -> Dict:
    """
    Extrai dados específicos de um tipo de documento.
    
    Args:
        image_data: Pode ser um caminho para a imagem, um objeto PIL Image, ou uma string base64
        document_type: Tipo de documento
        
    Returns:
        Dicionário com os dados extraídos
    """
    result = analyze_document(image_data, document_type=document_type)
    
    if "error" in result:
        return {"error": result["error"]}
    
    return result.get("dados", {})

# Mapeamento de campos obrigatórios por tipo de documento
REQUIRED_FIELDS = {
    "RG": ["numero", "nome", "data_nascimento"],
    "CPF": ["numero", "nome"],
    "CNH": ["numero", "nome", "categoria", "validade"],
    "CTPS": ["numero", "serie", "nome"],
    "COMPROVANTE_RESIDENCIA": ["endereco", "nome", "data"],
    "TITULO_ELEITOR": ["numero", "zona", "secao", "nome"],
    "DISPENSA_MILITAR": ["numero", "nome", "data_expedicao"],
    "CARTEIRA_VACINACAO": ["nome", "data_nascimento"],
    "CERTIDAO_NASCIMENTO": ["nome", "data_nascimento", "nome_pai", "nome_mae"],
    "CERTIDAO_CASAMENTO": ["nome_conjuge1", "nome_conjuge2", "data_casamento"],
    "PASSAPORTE": ["numero", "nome", "data_expedicao", "validade"],
    "PIS": ["numero", "nome"],
    "FOTO_ROSTO": []  # Não tem campos obrigatórios, apenas validação visual
}

def get_required_fields(document_type: str) -> List[str]:
    """
    Retorna os campos obrigatórios para um tipo de documento.
    
    Args:
        document_type: Tipo de documento
        
    Returns:
        Lista de campos obrigatórios
    """
    return REQUIRED_FIELDS.get(document_type.upper(), [])
