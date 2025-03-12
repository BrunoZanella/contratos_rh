# api_deepseek = sk-23494376e33249bd81c2ba68e6ae8e34
# api https://openrouter.ai/settings/keys = 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



import requests
import base64
import os

def encode_image_to_base64(image_path):
    """Converte uma imagem para base64"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def analisar_imagem(caminho_imagem):
    """Analisa uma imagem usando a API OpenRouter"""
    
    # Verificar se o arquivo existe
    if not os.path.exists(caminho_imagem):
        return "Erro: Arquivo não encontrado"

    # Converter imagem para base64
    try:
        imagem_base64 = encode_image_to_base64(caminho_imagem)
    except Exception as e:
        return f"Erro ao processar imagem: {str(e)}"

    # Configuração da API
    API_KEY = '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'
    API_URL = 'https://openrouter.ai/api/v1/chat/completions'

    # Cabeçalhos da requisição
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://localhost:3000',
        'X-Title': 'Image Analysis'
    }

    # Prompt específico para análise de documentos
    prompt = """Analise esta imagem e identifique qual tipo de documento brasileiro é.
    Responda APENAS com o tipo do documento em maiúsculas (exemplo: "CNH", "RG", "CPF", etc.).
    
    Características específicas:
    - RG: Possui foto 3x4, impressão digital, número de registro
    - CNH: Layout horizontal, foto à esquerda, categorias de habilitação
    - CPF: Sem foto, número formatado XXX.XXX.XXX-XX
    - CTPS: Carteira de trabalho, geralmente azul, com foto
    - Título de Eleitor: Sem foto, com zona e seção eleitoral
    
    Responda APENAS com o tipo do documento, sem explicações."""

    # Dados da requisição
    data = {
        "model": "anthropic/claude-3-haiku",  # Modelo com suporte a visão
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{imagem_base64}"
                        }
                    }
                ]
            }
        ]
    }

    try:
        # Enviar requisição
        response = requests.post(API_URL, json=data, headers=headers)
        
        # Verificar resposta
        if response.status_code == 200:
            resultado = response.json()
            if 'choices' in resultado and len(resultado['choices']) > 0:
                return resultado['choices'][0]['message']['content'].strip()
            else:
                # Mostrar a resposta completa para debug
                print("Resposta completa da API:", resultado)
                return "Erro: Resposta da API não contém descrição"
        else:
            return f"Erro na API: {response.status_code} - {response.text}"

    except Exception as e:
        return f"Erro na requisição: {str(e)}"

def main():
    # Solicitar caminho da imagem
    caminho_imagem = input("Digite o caminho da imagem: ").strip()
    
    # Analisar imagem
    print("\nAnalisando imagem...")
    resultado = analisar_imagem(caminho_imagem)
    
    # Mostrar resultado
    print("\nTipo de Documento:")
    print(resultado)

if __name__ == "__main__":
    main()