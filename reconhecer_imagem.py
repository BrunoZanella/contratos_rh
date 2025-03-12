
import requests
import base64
import os
from pdf2image import convert_from_path
from PIL import Image
import io
import tempfile


chaves = {
    "chave_1": "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",
    "chave_2": "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",
    "chave_3": "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",
    "chave_4": "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"
}

class AnalisadorDocumentos:
    def __init__(self, api_key=None, chaves_dict=None):
        self.chaves_dict = chaves_dict or {}
        self.api_key = api_key or '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'
        self.api_url = 'https://openrouter.ai/api/v1/chat/completions'
        self.headers = self._criar_headers(self.api_key)
    
    def _criar_headers(self, api_key):
        """Cria os headers com a chave de API fornecida"""
        return {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://localhost:3000',
            'X-Title': 'Document Analysis'
        }

    def converter_pdf_para_imagem(self, pdf_path):
        """Converte a primeira página de um PDF para imagem."""
        try:
            # Converter primeira página do PDF para imagem
            imagens = convert_from_path(pdf_path, first_page=1, last_page=1)
            if imagens:
                # Salvar temporariamente a imagem
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                    imagens[0].save(tmp.name, 'JPEG')
                    return tmp.name
            return None
        except Exception as e:
            print(f"Erro ao converter PDF: {str(e)}")
            return None

    def processar_imagem(self, caminho_arquivo):
        """Processa imagem para garantir formato adequado e tamanho."""
        try:
            # Abrir imagem com PIL
            with Image.open(caminho_arquivo) as img:
                # Converter para RGB se necessário
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Redimensionar se muito grande
                max_size = 1024
                if max(img.size) > max_size:
                    ratio = max_size / max(img.size)
                    new_size = tuple(int(dim * ratio) for dim in img.size)
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                
                # Converter para bytes
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG', quality=85)
                img_byte_arr = img_byte_arr.getvalue()
                
                return base64.b64encode(img_byte_arr).decode('utf-8')
        except Exception as e:
            print(f"Erro ao processar imagem: {str(e)}")
            return None

    def fazer_requisicao_com_rotacao_chaves(self, data, mostrar_debug=False):
        """Faz requisição à API com rotação de chaves em caso de erro 401"""
        # Primeira tentativa com a chave padrão
        response = requests.post(self.api_url, json=data, headers=self.headers)
        
        if response.status_code != 401 or not self.chaves_dict:
            # Se não for erro 401 ou não tiver chaves alternativas, retorna a resposta atual
            return response
        
        if mostrar_debug:
            print(f"Erro 401 com chave padrão. Tentando chaves alternativas...")
        
        # Tenta com cada chave do dicionário
        for nome_chave, valor_chave in self.chaves_dict.items():
            if mostrar_debug:
                print(f"Tentando com {nome_chave}...")
            
            # Atualiza headers com a nova chave
            headers_temp = self._criar_headers(valor_chave)
            
            # Faz nova requisição
            response = requests.post(self.api_url, json=data, headers=headers_temp)
            
            if response.status_code != 401:
                # Se não for erro 401, encontramos uma chave válida
                if mostrar_debug:
                    print(f"Sucesso com {nome_chave}!")
                
                # Atualiza a chave padrão para uso futuro
                self.api_key = valor_chave
                self.headers = headers_temp
                
                return response
        
        # Se chegou aqui, nenhuma chave funcionou
        if mostrar_debug:
            print("Todas as chaves falharam com erro 401.")
        
        return response  # Retorna a última resposta com erro 401

    def analisar_documento(self, caminho_arquivo, mostrar_debug=False):
        """Analisa um documento (imagem ou PDF) e retorna sua descrição."""
        
        try:
            # Verificar se arquivo existe
            if not os.path.exists(caminho_arquivo):
                return "Erro: Arquivo não encontrado"

            # Determinar tipo de arquivo
            extensao = os.path.splitext(caminho_arquivo)[1].lower()
            
            # Processar arquivo baseado na extensão
            if extensao == '.pdf':
                caminho_temp = self.converter_pdf_para_imagem(caminho_arquivo)
                if not caminho_temp:
                    return "Erro: Não foi possível converter o PDF"
                imagem_base64 = self.processar_imagem(caminho_temp)
                os.unlink(caminho_temp)  # Remover arquivo temporário
            else:  # Assumir que é imagem
                imagem_base64 = self.processar_imagem(caminho_arquivo)

            if not imagem_base64:
                return "Erro: Não foi possível processar o arquivo"

            # Prompt modificado para análise do documento
            prompt = """Analise esta imagem e identifique qual tipo de documento brasileiro é.
            Responda APENAS com um dos seguintes códigos exatos, sem adicionar nada mais:
            
            - rg (para RG/Carteira de Identidade)
            - cpf (para CPF)
            - cnh (para Carteira Nacional de Habilitação)
            - ctps (para Carteira de Trabalho)
            - comprovante_residencia (para Comprovante de Residência como contas de luz, água, etc.)
            - titulo_eleitor (para Título de Eleitor)
            - outros (se não conseguir identificar ou for outro tipo de documento)
            
            Características específicas:
            - RG: Possui foto 3x4, impressão digital, número de registro
            - CNH: Layout horizontal, foto à esquerda, categorias de habilitação
            - CPF: Sem foto, número formatado XXX.XXX.XXX-XX
            - CTPS: Carteira de trabalho, geralmente azul, com foto
            - Título de Eleitor: Sem foto, com zona e seção eleitoral
            - Comprovante de Residência: Cabeçalho de empresa (ex: 'COMPANHIA DE SANEAMENTO', 'ENERGISA'), campos como endereço, CEP, mês de referência
            
            Responda APENAS com um dos códigos listados acima, sem explicações ou texto adicional."""

            # Dados para a requisição
            data = {
                "model": "anthropic/claude-3-haiku",
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

            # Fazer requisição com rotação de chaves
            response = self.fazer_requisicao_com_rotacao_chaves(data, mostrar_debug)
            
            if mostrar_debug:
                print(f"Status Code final: {response.status_code}")
                print(f"Resposta completa: {response.text}")

            # Processar resposta
            if response.status_code == 200:
                resultado = response.json()
                if 'choices' in resultado and len(resultado['choices']) > 0:
                    return resultado['choices'][0]['message']['content'].strip()
                else:
                    return "Erro: Resposta da API não contém descrição"
            else:
                return f"Erro na API: {response.status_code}"

        except Exception as e:
            return f"Erro: {str(e)}"

def analisar_arquivo(caminho_arquivo, mostrar_debug=False):
    """Função auxiliar para facilitar o uso."""
    analisador = AnalisadorDocumentos(chaves_dict=chaves)
    return analisador.analisar_documento(caminho_arquivo, mostrar_debug)

if __name__ == "__main__":
    # Teste direto do script
    caminho = input("Digite o caminho do arquivo (imagem ou PDF): ").strip()
    resultado = analisar_arquivo(caminho, mostrar_debug=True)
    print(f"\nTipo de Documento: {resultado}")





'''
import base64
import cv2
import numpy as np
from PIL import Image
from io import BytesIO
from groq import Groq
import os
import json
import sys

def preprocessar_imagem(caminho_imagem):
    """Aplica pré-processamento para melhorar o reconhecimento de documentos."""
    try:
        # Ler imagem
        imagem = cv2.imread(caminho_imagem)
        if imagem is None:
            print(f"Erro: Não foi possível ler a imagem em {caminho_imagem}")
            return None
            
        # Converter para escala de cinza
        cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
        
        # Aplicar limiarização adaptativa
        limiar = cv2.adaptiveThreshold(cinza, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                      cv2.THRESH_BINARY, 11, 2)
        
        # Reduzir ruído
        sem_ruido = cv2.fastNlMeansDenoising(limiar, None, 10, 7, 21)
        
        # Melhorar contraste
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        melhorado = clahe.apply(cinza)
        
        # Converter para PIL Image e depois para base64
        imagem_pil = Image.fromarray(melhorado)
        buffer = BytesIO()
        imagem_pil.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"Erro durante o pré-processamento da imagem: {str(e)}")
        return None

def criar_prompt_exemplos(tipos_documentos):
    """Cria um prompt com exemplos para melhor reconhecimento."""
    exemplos = [
        {
            "descricao": "Documento tem 'REPÚBLICA FEDERATIVA DO BRASIL' no topo, contém uma foto, impressão digital e texto 'REGISTRO GERAL'. Possui emblema estadual.",
            "tipo": "RG"
        },
        {
            "descricao": "Documento tem cabeçalho 'MINISTÉRIO DA FAZENDA', contém um número de 11 dígitos formatado como 000.000.000-00 e 'CADASTRO DE PESSOAS FÍSICAS'.",
            "tipo": "CPF"
        },
        {
            "descricao": "Documento tem título 'CARTEIRA NACIONAL DE HABILITAÇÃO', contém foto do motorista, assinatura e categorias de habilitação (A, B, etc.).",
            "tipo": "CNH"
        },
        {
            "descricao": "Documento tem título 'CARTEIRA DE TRABALHO E PREVIDÊNCIA SOCIAL', contém histórico de emprego, foto do trabalhador e número da CTPS.",
            "tipo": "Carteira de Trabalho"
        },
        {
            "descricao": "Conta de serviço público com nome do cliente, endereço, detalhes de consumo e informações de pagamento. Contém logotipo do provedor de serviços (como empresa de eletricidade, água ou internet).",
            "tipo": "Comprovante de Residência"
        },
        {
            "descricao": "Documento tem texto 'JUSTIÇA ELEITORAL' e 'TÍTULO ELEITORAL', contém informações do eleitor, zona eleitoral e seção.",
            "tipo": "Título de Eleitor"
        },
        {
            "descricao": "Apenas uma fotografia do rosto de uma pessoa sem qualquer formato de documento ou texto oficial.",
            "tipo": "Foto do Rosto"
        }
    ]
    
    # Criar o prompt com exemplos
    texto_exemplos = "Aqui estão exemplos de descrições de documentos brasileiros e seus tipos:\n\n"
    
    for exemplo in exemplos:
        texto_exemplos += f"Descrição: {exemplo['descricao']}\n"
        texto_exemplos += f"Tipo de Documento: {exemplo['tipo']}\n\n"
    
    texto_exemplos += "Agora, analise a imagem fornecida e siga o mesmo padrão:\n"
    texto_exemplos += "1. Descreva o que você vê no documento (campos de texto, layout, cores, logotipos, fotos)\n"
    texto_exemplos += "2. Liste qualquer texto importante que você possa ler no documento\n"
    texto_exemplos += "3. Determine o tipo de documento entre estas opções: " + ", ".join(tipos_documentos) + "\n"
    texto_exemplos += "4. Forneça sua resposta final apenas com o tipo de documento"
    
    return texto_exemplos

def reconhecer_documento(caminho_imagem, chave_api, usar_preprocessamento=True):
    """Função aprimorada de reconhecimento de documentos."""
    try:
        # Pré-processar imagem se solicitado
        if usar_preprocessamento:
            imagem_codificada = preprocessar_imagem(caminho_imagem)
            if imagem_codificada is None:
                print("Falha no pré-processamento da imagem. Tentando método padrão...")
                with open(caminho_imagem, "rb") as arquivo_imagem:
                    imagem_codificada = base64.b64encode(arquivo_imagem.read()).decode("utf-8")
        else:
            with open(caminho_imagem, "rb") as arquivo_imagem:
                imagem_codificada = base64.b64encode(arquivo_imagem.read()).decode("utf-8")
        
        # Criar cliente
        cliente = Groq(api_key=chave_api)
        
        # Tipos de documentos
        TIPOS_DOCUMENTOS = [
            "RG", "CPF", "CNH", "Carteira de Trabalho",
            "Comprovante de Residência", "Título de Eleitor",
            "Foto do Rosto", "Outros"
        ]
        
        # Criar prompt aprimorado com exemplos
        prompt = criar_prompt_exemplos(TIPOS_DOCUMENTOS)
        
        # Fazer requisição com temperatura mais baixa para resultados mais consistentes
        try:
            completacao = cliente.chat.completions.create(
                model="llama-3.2-90b-vision-preview",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{imagem_codificada}"}}
                        ]
                    }
                ],
                temperature=0.2,  # Temperatura mais baixa para resultados mais consistentes
                max_completion_tokens=1024,
                top_p=1,
                stream=False,
                stop=None,
            )
            
            return completacao.choices[0].message
        except Exception as e:
            if "invalid_api_key" in str(e):
                print("\nERRO: Chave de API inválida. Por favor, verifique sua chave API da Groq.")
                print("Você pode obter uma chave API em: https://console.groq.com/keys")
                print("Substitua a chave API no código ou defina a variável de ambiente GROQ_API_KEY.")
                sys.exit(1)
            else:
                print(f"\nErro na chamada da API: {str(e)}")
                sys.exit(1)
    except Exception as e:
        print(f"Erro durante o reconhecimento do documento: {str(e)}")
        return None

def validar_precisao_modelo(pasta_teste, chave_api, arquivo_verdade=None):
    """
    Valida a precisão do modelo usando uma pasta de teste com tipos de documentos conhecidos.
    
    Args:
        pasta_teste: Pasta contendo imagens de teste
        chave_api: Chave API para Groq
        arquivo_verdade: Arquivo JSON com rótulos verdadeiros (opcional)
    
    Returns:
        Dicionário com métricas de precisão
    """
    # Carregar verdade se fornecida
    verdade = {}
    if arquivo_verdade and os.path.exists(arquivo_verdade):
        with open(arquivo_verdade, 'r') as f:
            verdade = json.load(f)
    
    resultados = {
        "total": 0,
        "corretos": 0,
        "incorretos": 0,
        "por_tipo": {},
        "matriz_confusao": {}
    }
    
    # Processar cada imagem na pasta de teste
    for nome_arquivo in os.listdir(pasta_teste):
        if nome_arquivo.lower().endswith(('.png', '.jpg', '.jpeg')):
            caminho_arquivo = os.path.join(pasta_teste, nome_arquivo)
            
            # Obter rótulo verdadeiro se disponível
            rotulo_verdadeiro = None
            if nome_arquivo in verdade:
                rotulo_verdadeiro = verdade[nome_arquivo]
            elif "_" in nome_arquivo:
                # Assumir formato de nome de arquivo como "RG_001.jpg"
                rotulo_verdadeiro = nome_arquivo.split("_")[0]
            
            if not rotulo_verdadeiro:
                print(f"Pulando {nome_arquivo} - sem rótulo verdadeiro")
                continue
            
            # Inicializar estatísticas de tipo se não existir
            if rotulo_verdadeiro not in resultados["por_tipo"]:
                resultados["por_tipo"][rotulo_verdadeiro] = {"total": 0, "corretos": 0}
            
            # Processar imagem
            print(f"Processando {nome_arquivo}...")
            resposta = reconhecer_documento(caminho_arquivo, chave_api)
            
            if resposta is None:
                print(f"  Falha ao processar {nome_arquivo}, pulando...")
                continue
                
            # Extrair rótulo previsto (assumindo que a última linha contém apenas o tipo de documento)
            linhas_conteudo = resposta.content.strip().split('\n')
            rotulo_previsto = linhas_conteudo[-1].strip()
            
            # Limpar rótulo previsto (caso tenha texto extra)
            for tipo_doc in ["RG", "CPF", "CNH", "Carteira de Trabalho", 
                            "Comprovante de Residência", "Título de Eleitor", 
                            "Foto do Rosto", "Outros"]:
                if tipo_doc in rotulo_previsto:
                    rotulo_previsto = tipo_doc
                    break
            
            # Atualizar estatísticas
            resultados["total"] += 1
            resultados["por_tipo"][rotulo_verdadeiro]["total"] += 1
            
            if rotulo_previsto == rotulo_verdadeiro:
                resultados["corretos"] += 1
                resultados["por_tipo"][rotulo_verdadeiro]["corretos"] += 1
            else:
                resultados["incorretos"] += 1
                
                # Atualizar matriz de confusão
                if rotulo_verdadeiro not in resultados["matriz_confusao"]:
                    resultados["matriz_confusao"][rotulo_verdadeiro] = {}
                
                if rotulo_previsto not in resultados["matriz_confusao"][rotulo_verdadeiro]:
                    resultados["matriz_confusao"][rotulo_verdadeiro][rotulo_previsto] = 0
                
                resultados["matriz_confusao"][rotulo_verdadeiro][rotulo_previsto] += 1
            
            print(f"  Verdadeiro: {rotulo_verdadeiro}, Previsto: {rotulo_previsto}")
    
    # Calcular precisão
    if resultados["total"] > 0:
        resultados["precisao"] = resultados["corretos"] / resultados["total"]
        
        # Calcular precisão por tipo
        for tipo_doc in resultados["por_tipo"]:
            estatisticas_tipo = resultados["por_tipo"][tipo_doc]
            if estatisticas_tipo["total"] > 0:
                estatisticas_tipo["precisao"] = estatisticas_tipo["corretos"] / estatisticas_tipo["total"]
    
    return resultados

def obter_chave_api():
    """Obtém a chave API da Groq do ambiente ou solicita ao usuário."""
    # Tentar obter do ambiente
    chave_api = os.environ.get("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")
    
    # Se não estiver no ambiente, solicitar ao usuário
    if not chave_api:
        print("\nChave API da Groq não encontrada no ambiente.")
        print("Você pode definir a variável de ambiente GROQ_API_KEY ou inserir sua chave abaixo.")
        chave_api = input("Digite sua chave API da Groq: ").strip()
        
        if not chave_api:
            print("Nenhuma chave API fornecida. Saindo.")
            sys.exit(1)
    
    return chave_api

# Função principal
def main():
    print("=== Reconhecimento de Documentos Brasileiros ===")
    print("Este script identifica o tipo de documento brasileiro a partir de uma imagem.")
    
    # Obter chave API
    chave_api = obter_chave_api()
    
    # Menu de opções
    print("\nEscolha uma opção:")
    print("1. Reconhecer um documento")
    print("2. Validar precisão do modelo em um conjunto de documentos")
    print("3. Sair")
    
    opcao = input("Opção: ").strip()
    
    if opcao == "1":
        # Reconhecer um documento
        caminho_imagem = input("\nDigite o caminho para a imagem do documento: ").strip()
        
        if not os.path.exists(caminho_imagem):
            print(f"Erro: O arquivo {caminho_imagem} não existe.")
            return
        
        print("\nProcessando documento...")
        print("Testando com pré-processamento:")
        resultado_com_preprocessamento = reconhecer_documento(caminho_imagem, chave_api, usar_preprocessamento=True)
        
        if resultado_com_preprocessamento:
            print("\nResultado com pré-processamento:")
            print(resultado_com_preprocessamento.content)
            
            # Extrair tipo de documento da resposta
            linhas = resultado_com_preprocessamento.content.strip().split('\n')
            tipo_documento = linhas[-1].strip()
            
            print(f"\nTipo de documento identificado: {tipo_documento}")
        
    elif opcao == "2":
        # Validar precisão do modelo
        pasta_teste = input("\nDigite o caminho para a pasta com imagens de teste: ").strip()
        
        if not os.path.exists(pasta_teste):
            print(f"Erro: A pasta {pasta_teste} não existe.")
            criar_pasta = input("Deseja criar esta pasta? (s/n): ").strip().lower()
            
            if criar_pasta == 's':
                os.makedirs(pasta_teste)
                print(f"Pasta criada: {pasta_teste}")
                print("Adicione imagens de teste a esta pasta com nomes como 'RG_001.jpg'")
            return
        
        # Verificar se há imagens na pasta
        imagens = [f for f in os.listdir(pasta_teste) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        
        if not imagens:
            print(f"Erro: Não há imagens na pasta {pasta_teste}.")
            print("Adicione imagens de teste com nomes como 'RG_001.jpg'")
            return
        
        print(f"\nEncontradas {len(imagens)} imagens para validação.")
        print("Iniciando validação...")
        
        # Executar validação
        resultados = validar_precisao_modelo(pasta_teste, chave_api)
        
        # Imprimir resultados
        print("\nResultados da Validação:")
        print(f"Total de imagens: {resultados['total']}")
        
        if 'precisao' in resultados:
            print(f"Precisão geral: {resultados['precisao']:.2%}")
            
            print("\nPrecisão por tipo de documento:")
            for tipo_doc, estatisticas in resultados["por_tipo"].items():
                if 'precisao' in estatisticas:
                    print(f"  {tipo_doc}: {estatisticas['precisao']:.2%} ({estatisticas['corretos']}/{estatisticas['total']})")
            
            # Salvar resultados em arquivo
            with open("resultados_validacao.json", "w") as f:
                json.dump(resultados, f, indent=2)
            
            print("\nResultados salvos em resultados_validacao.json")
        else:
            print("Nenhum documento foi processado com sucesso.")
    
    elif opcao == "3":
        print("Saindo...")
        return
    
    else:
        print("Opção inválida.")

# Executar o programa se for o script principal
if __name__ == "__main__":
    main()

'''







'''
import os
import base64
from groq import Groq

# Diretório com os documentos-padrão
pasta_padrao = "media/documentos_padrao"
documentos_padrao = {}

# Lê os documentos-padrão e associa nomes aos tipos de documentos
for arquivo in os.listdir(pasta_padrao):
    caminho_arquivo = os.path.join(pasta_padrao, arquivo)
    
    if os.path.isfile(caminho_arquivo):
        with open(caminho_arquivo, "rb") as img_file:
            documentos_padrao[arquivo] = base64.b64encode(img_file.read()).decode("utf-8")

# Caminho do documento a ser analisado
image_path = "media/documentos/LcSD6WJ1_o.png"

# Lendo a imagem do documento a ser analisado
with open(image_path, "rb") as image_file:
    encoded_image = base64.b64encode(image_file.read()).decode("utf-8")

# Criando cliente da API
client = Groq(api_key="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")

# Criando o prompt informativo
prompt = (
    "Aqui estão exemplos de documentos brasileiros comuns e suas imagens de referência:\n\n"
)

for nome_arquivo in documentos_padrao.keys():
    nome_formatado = os.path.splitext(nome_arquivo)[0]  # Remove extensão
    prompt += f"- Documento: {nome_formatado}\n"

prompt += (
    "\nAgora, analise o documento enviado e me diga qual ele é, comparando visualmente "
    "com os exemplos fornecidos. Use padrões de texto e formatação do documento para ajudar "
    "na identificação.\n"
    "Responda em JSON com os seguintes campos: 'tipo' (tipo do documento identificado) e "
    "'dados_extraidos' (informações textuais extraídas do documento)."
)

# Fazendo a requisição para análise
completion = client.chat.completions.create(
    model="llama-3.2-90b-vision-preview",
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded_image}"}}
            ]
        }
    ],
    temperature=0.7,  # Um pouco mais conservador para evitar erros
    max_completion_tokens=1024,
    top_p=1,
    stream=False,
    stop=None,
    response_format={"type": "json_object"},
)

# Exibir resultado
print(completion.choices[0].message)

'''