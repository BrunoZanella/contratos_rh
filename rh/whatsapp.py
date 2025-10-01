import requests
import json
from django.conf import settings
import time

def enviar_mensagem_whatsapp(telefone, mensagem):
    """
    Envia uma mensagem via WhatsApp usando a Evolution API.
    
    Args:
        telefone (str): Número de telefone do destinatário (com ou sem o prefixo 55)
        mensagem (str): Texto da mensagem a ser enviada
    
    Returns:
        dict: Resposta da API em formato JSON
    
    Raises:
        Exception: Se ocorrer um erro na requisição
    """
    # Garante que o telefone tenha o formato correto
    telefone = ''.join(filter(str.isdigit, telefone))
    if not telefone.startswith('55'):
        telefone = f"55{telefone}"
    
    print(f"Enviando mensagem para {telefone}")
    
    url = f"{settings.EVOLUTION_API_URL}/message/sendText/{settings.EVOLUTION_API_INSTANCE}"
    headers = {
        "Content-Type": "application/json",
        "apikey": settings.EVOLUTION_API_KEY
    }
    payload = {
        "number": telefone,
        "text": mensagem
    }
    
    # print(f"URL: {url}")
    # print(f"Headers: {json.dumps(headers)}")
    # print(f"Payload: {json.dumps(payload)}")
    
    try:
        # Adiciona um pequeno atraso para evitar sobrecarga da API
        time.sleep(1)
        
        # Faz a requisição com timeout de 30 segundos
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        # Verifica se a requisição foi bem-sucedida
        response.raise_for_status()
        
        # Tenta converter a resposta para JSON
        response_json = response.json()
    #    print(f"Resposta da API: {json.dumps(response_json)}")
        
        return response_json
    except requests.exceptions.RequestException as e:
        print(f"Erro na requisição HTTP: {str(e)}")
        raise Exception(f"Erro ao enviar mensagem WhatsApp: {str(e)}")
    except json.JSONDecodeError as e:
        print(f"Erro ao decodificar resposta JSON: {str(e)}")
    #    print(f"Resposta recebida: {response.text}")
        raise Exception(f"Resposta inválida da API: {str(e)}")
    except Exception as e:
        print(f"Erro não tratado: {str(e)}")
        raise