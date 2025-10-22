

import os
import io
import base64
import tempfile
import requests
from PIL import Image
from pdf2image import convert_from_path
from groq import Groq, RateLimitError # Importa RateLimitError
import openai
from decouple import config
import time # Importar time para sleep
import random # Importar random para jitter
import logging

logger = logging.getLogger(__name__)

class AnalisadorDocumentosGroq:
  def __init__(self, provider='groq', api_key_groq=None, api_key_openai=None):
      self.api_key_groq = api_key_groq or config('API_KEY_GROQ')
      self.api_key_openai = api_key_openai or config('API_KEY_OPENAI')

      # Usando Groq como padrão, conforme o erro original
      self.client = Groq(api_key=self.api_key_groq)

  def converter_pdf_para_imagem(self, pdf_path):
      try:
          imagens = convert_from_path(pdf_path, first_page=1, last_page=1)
          if imagens:
              with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                  imagens[0].save(tmp.name, 'JPEG')
                  return tmp.name
          return None
      except Exception as e:
          print(f"Erro ao converter PDF: {str(e)}")
          return None

  def processar_imagem(self, caminho_arquivo):
      try:
          with Image.open(caminho_arquivo) as img:
              if img.mode != 'RGB':
                  img = img.convert('RGB')
              max_size = 1024
              if max(img.size) > max_size:
                  ratio = max_size / max(img.size)
                  new_size = tuple(int(dim * ratio) for dim in img.size)
                  img = img.resize(new_size, Image.Resampling.LANCZOS)
              img_byte_arr = io.BytesIO()
              img.save(img_byte_arr, format='JPEG', quality=85)
              img_byte_arr = img_byte_arr.getvalue()
              return base64.b64encode(img_byte_arr).decode('utf-8')
      except Exception as e:
          print(f"Erro ao processar imagem: {str(e)}")
          return None

  def _make_openai_request(self, messages, model="gpt-4o", temperature=0.5, max_tokens=1024):
    """Método para fazer requisições à API OpenAI como fallback"""
    try:
        logger.info("🔄 Tentando requisição à API OpenAI como fallback")
        
        try:
            # Tentar versão nova (v1.x)
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key_openai)
            
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
        except ImportError:
            # Fallback para versão antiga (v0.x)
            import openai
            openai.api_key = self.api_key_openai
            
            response = openai.ChatCompletion.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
        
        logger.info("✅ Requisição à API OpenAI bem-sucedida")
        return response
        
    except Exception as e:
        logger.error(f"❌ Erro na requisição à API OpenAI: {str(e)}")
        return None

  def _make_groq_request(self, messages, model, temperature, max_completion_tokens, top_p, stream):
    max_retries = 2  # Reduzido de 5 para 2 para evitar timeout
    base_delay = 1  # segundos
    max_wait_time = 30  # Máximo 30 segundos de espera total
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Tentativa {attempt + 1}/{max_retries} de requisição à API Groq")
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
                top_p=top_p,
                stream=stream
            )
            logger.info("✅ Requisição à API Groq bem-sucedida")
            return response
        except RateLimitError as e:
            logger.error(f"❌ Rate limit atingido na API Groq: {str(e)}")
            
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_wait_time)
                logger.warning(f"⏳ Aguardando {delay} segundos antes da próxima tentativa...")
                time.sleep(delay)
            else:
                logger.error("❌ Máximo de tentativas atingido. Rate limit excedido.")
                raise e
        except Exception as e:
            logger.error(f"❌ Erro na requisição à API Groq: {str(e)}")
            raise e

  def analisar_documento(self, caminho_arquivo, mostrar_debug=False):
      try:
          if not os.path.exists(caminho_arquivo):
              return "Erro: Arquivo não encontrado"

          extensao = os.path.splitext(caminho_arquivo)[1].lower()
          if extensao == '.pdf':
              caminho_temp = self.converter_pdf_para_imagem(caminho_arquivo)
              if not caminho_temp:
                  return "Erro: Não foi possível converter o PDF"
              imagem_base64 = self.processar_imagem(caminho_temp)
              os.unlink(caminho_temp)
          else:
              imagem_base64 = self.processar_imagem(caminho_arquivo)

          if not imagem_base64:
              return "Erro: Não foi possível processar o arquivo"




          prompt_inicial = """
            Analise a imagem e identifique qual tipo de documento brasileiro é.

            RESPOSTA: devolva APENAS UM código exato, sem nada além dele.

            CÓDIGOS PERMITIDOS

            DOCUMENTOS DE IDENTIFICAÇÃO
            - rg
            - cpf
            - cnh
            - titulo_eleitor
            - reservista

            DOCUMENTOS TRABALHISTAS
            - carteira_trabalho_digital (Carteira de Trabalho e Previdência Social – livreto físico)
            - carteira_trabalho_digital (Carteira de Trabalho Digital – app)
            - extrato_pis
            - aso

            DOCUMENTOS EMPRESARIAIS
            - cnpj

            DOCUMENTOS PESSOAIS
            - comprovante_residencia
            - certidao_casamento
            - certidao_nascimento
            - comprovante_escolaridade
            - cartao_vacinas
            - conta_salario
            - certificados_cursos
            - certidao_antecedentes_criminais
            - curriculo

            OUTROS TIPOS DE IMAGENS
            - FOTO_ROSTO
            - foto_3x4
            - outros

            CARACTERIZAÇÃO (sinais visuais e textuais)

            RG (Carteira de Identidade)
            - Frente: foto 3x4 (geralmente canto sup. direito), nome, nº RG (XX.XXX.XXX-X), CPF, nasc., filiação, naturalidade, órgão emissor (p.ex., SSP-XX), assinatura. Textos: “REPÚBLICA FEDERATIVA DO BRASIL”, “CARTEIRA DE IDENTIDADE”, brasão/estado.
            - Verso: impressão digital “Polegar Direito”, assinatura do diretor, menções legais (“LEI Nº 7.116...”), campos CTPS/NIS/CNH etc.
            - Varia: horizontal/vertical; cores variam (verde/azul/rosa). Órgãos emissores comuns: SSP, PC, IFP, DETRAN (alguns).

            CPF
            - Sem foto. Brasão/identidade da Receita Federal. Fundo azul claro/branco. Textos: “CADASTRO DE PESSOAS FÍSICAS”, “RECEITA FEDERAL”, “MINISTÉRIO DA FAZENDA”.
            - Campos: nome, CPF (XXX.XXX.XXX-XX), nasc., situação (“REGULAR”, “PENDENTE...”, “SUSPENSA”, “CANCELADA”), data inscrição. Layout horizontal simples.

            CNH
            - Foto canto sup. esquerdo; layout horizontal; código de barras; categorias A/B/C/D/E em destaque; cores azul/amarelo; validade DD/MM/AAAA.
            - Textos: “CARTEIRA NACIONAL DE HABILITAÇÃO”, “DETRAN”, UF. Campos: nome, CPF, RG, nasc., nº registro, validade, 1ª habilitação, local nasc.

            Título de Eleitor
            - Sem foto. Textos: “JUSTIÇA ELEITORAL”, “TÍTULO DE ELEITOR”, “TRIBUNAL REGIONAL ELEITORAL (TRE-XX)”. Brasão JE.
            - Campos: nome, nº título (XXXX XXXX XXXX), zona, seção, município/UF, data emissão. Layout geralmente vertical.

            Reservista (Certificado de Reservista)
            - Brasões/símbolos militares (Exército/Marinha/FAB). Textos: “CERTIFICADO DE RESERVISTA”, “EXÉRCITO BRASILEIRO” etc.
            - Campos: nome, CPF, nº certificado, categoria (1ª/2ª/3ª), datas incorporação/licenciamento, OM. Layout oficial militar.

            Carteira de Trabalho (livreto físico) — MESMO CÓDIGO: carteira_trabalho_digital
            - Capa azul/verde; páginas com contratos (empresas, cargos, salários, admissão/demissão).
            - Textos: “CARTEIRA DE TRABALHO E PREVIDÊNCIA SOCIAL”, “MINISTÉRIO DO TRABALHO”.
            - Campos: nome, CPF, PIS/PASEP, série/número, emissão, assinatura.

            Carteira de Trabalho Digital (app) — MESMO CÓDIGO: carteira_trabalho_digital
            - Interface moderna (smartphone/print), possível QR Code, logos Gov.br/Ministério do Trabalho.
            - Campos: nome, CPF, PIS, contratos digitais.

            Extrato PIS
            - Cabeçalho institucional (Caixa/BB). Textos: “EXTRATO PIS/PASEP”, “NIS/PIS/PASEP”.
            - Campos: nome, CPF, PIS, saldo, movimentações, data cadastro. Formato de extrato.

            ASO (Atestado de Saúde Ocupacional)
            - Textos: “ATESTADO DE SAÚDE OCUPACIONAL”, “ASO”. Resultado “APTO” ou “INAPTO”.
            - Campos: trabalhador (nome/CPF), empresa/cargo/função, tipo exame (admissional/periódico/demissional), médico (nome/CRM), assinatura/carimbo.

            CNPJ (Cartão CNPJ)
            - IMPORTANTE: não existe “PROCURAÇÃO ET EXTRA/AD NEGOTIA” como tipo — use CNPJ.
            - Textos: “CARTÃO CNPJ”, “RECEITA FEDERAL”, “CADASTRO NACIONAL DA PESSOA JURÍDICA”. (Podem aparecer termos como “PROCURAÇÃO”, “ET EXTRA”, “AD NEGOTIA” no conteúdo, mas o tipo é CNPJ.)
            - Campos: razão social, nome fantasia, CNPJ (XX.XXX.XXX/XXXX-XX), situação (ATIVA/SUSPENSA/INAPTA/BAIXADA), abertura, CNAE principal, endereço.

            Comprovante de Residência
            - Endereço completo com CEP e titular; empresa prestadora (contas de luz/água/telefone/gás/internet, IPTU, contrato de aluguel).
            - Campos: titular, endereço, CEP, vencimento, valores/consumos. Observação: mesmo com CPF, se for fatura de serviço com endereço, classifique aqui.

            Certidão de Casamento
            - Papel timbrado oficial, brasão/cartório. Textos: “CERTIDÃO DE CASAMENTO”, nome do cartório/UF/municipio, “OFICIAL DE REGISTRO CIVIL”.
            - Campos: cônjuges, data/local, livro/folha/termo, testemunhas.

            Certidão de Nascimento
            - Papel timbrado oficial, brasão/cartório. Textos: “CERTIDÃO DE NASCIMENTO”.
            - Campos: nome do registrado, nasc., local, filiação (pais), avós, cartório, livro/folha/termo.

            Comprovante de Escolaridade (Diploma/Histórico/Certificado)
            - Timbre da instituição, assinaturas. Textos: “DIPLOMA”, “CERTIFICADO”, “HISTÓRICO ESCOLAR”.
            - Campos: nome, curso, instituição, conclusão/carga horária/notas, dirigentes. Layout solene.

            Cartão de Vacinas
            - Tabelas de vacinas, datas, carimbos SUS/unidades. Textos: “CARTÃO/CADERNETA DE VACINAÇÃO”.
            - Campos: nome, nasc., vacinas, datas, lotes, unidade.

            Conta Salário
            - DADOS BANCÁRIOS COMPLETOS obrigatórios: banco + agência + conta.
            - Textos: nome do banco, “CONTA SALÁRIO” (ou corrente, desde que contenha dados completos).
            - Bancos: BB, Bradesco, Itaú, Santander, Caixa etc. Pode ser print de app.
            - NUNCA usar “comprovante de dados bancários/bancário/conta bancária”: o tipo correto é conta_salario.

            Carteira Identidade Profissional (Conselhos)
            - Foto 3x4, nome, nº registro profissional, CPF, conselho (CRC/CREA/CRM/OAB etc.), assinaturas/carimbos, possível QR Code.
            - Não possui dados veiculares (CNH), eleitorais, bancários ou estrutura de CTPS.

            Certificados de Cursos e NRs
            - Timbre/logo institucional, assinatura responsável, carga horária, nome do curso, QR Code opcional.
            - Textos: “CERTIFICADO”, “DECLARAÇÃO”, “carga horária”, “concluiu/participou”.
            - Inclui NRs (NR-10, NR-35, NR-33), primeiros socorros, brigada, cursos técnicos/livres.

            Currículo (CV)
            - Seções típicas: “Experiência”, “Formação”, “Cursos”, “Habilidades”, “Idiomas”, “Objetivo/Resumo”. Pode ter LinkedIn/portfolio. Foto opcional.
            - Formatos: cronológico/funcional/combinado; acadêmico/Lattes (CNPq).
            - Sinais negativos para “curriculo”: foco em carga horária/certificação/timbre oficial → avaliar “certificados_cursos” ou “comprovante_escolaridade”.

            Foto 3x4
            - Apenas rosto em fundo neutro, formato retrato 3x4, expressão neutra, sem logos/brasões/textos. Sem qualquer documento visível. Usada em documentos.

            FOTO_ROSTO (selfie/foto casual)
            - Rosto em primeiro plano; fundo/ambiente variado; sem documentos/brasões/texto institucional. Pode haver braço segurando celular.

            Certidão de Antecedentes Criminais
            - Órgão oficial (PF/SSP), brasão da República; número da certidão; nome completo; filiação; nasc.; RG/CPF; data/hora emissão; validade; verificação/QR Code.
            - Textos comuns: “CERTIDÃO DE ANTECEDENTES CRIMINAIS”, “NÃO CONSTA”, “certifica”, “validar”.

            INSTRUÇÕES CRÍTICAS / REGRAS ESPECIAIS
            1) Analise brasões/logos/layouts/cores/foto.
            2) Busque textos identificadores da lista.
            3) Atenção a formatos numéricos (CPF XXX.XXX.XXX-XX; CNPJ XX.XXX.XXX/XXXX-XX).
            4) Identifique órgãos emissores (SSP, Receita, DETRAN, TRE etc.).
            5) Presença/ausência de foto (RG/CNH têm; CPF/Título não).
            6) Orientação do documento (CNH horizontal; RG pode variar).
            7) Comprovante de residência: foque em endereço + prestadora.
            8) Conta salário: exige banco+agência+conta (nunca use rótulos genéricos).
            9) Se houver qualquer sinal dos tipos listados, NÃO use “outros”.
            10) Documentos oficiais sempre têm elementos únicos listados.
            11) Se o documento (RG/CNH etc.) contém foto 3x4, classifique pelo TIPO DO DOCUMENTO, nunca como FOTO_ROSTO/foto_3x4.
            12) Não existe tipo “PROCURAÇÃO ET EXTRA/AD NEGOTIA”: classifique como cnpj.
            13) Não existe “comprovante de dados bancários/bancário/conta bancária”: classifique como conta_salario.
            14) Se dados essenciais estiverem ilegíveis (nº, nome, nasc., endereço etc.), classifique “outros” imediatamente, mesmo reconhecendo o tipo.
            15) “Certidão de Escritura Pública de Declaração de União Estável” → use certidao_casamento.
            16) “Certificado da Condição de Microempreendedor Individual (MEI)” → use cnpj.
            17) Nunca classifique fatura de cartão de crédito como outra coisa: é comprovante_residencia.

            CHECKLIST FINAL (antes de decidir)
            1) Imagem nítida e completa? Se NÃO → “outros”.
            2) Textos/brasões/campos-chave presentes? Se NÃO → “outros”.
            3) Estrutura/layout típico reconhecível? Se NÃO → “outros”.
            4) Dados essenciais legíveis? Se NÃO → “outros”.
            5) É possível extrair com confiança ao menos um dado importante (nº/CPF/RG/nome/nasc./endereço etc.)? Se NÃO → “outros”.

            SAÍDA (obrigatório): um único código exato dentre
            "rg", "cpf", "cnh", "titulo_eleitor", "reservista",
            "carteira_trabalho_digital", "extrato_pis", "aso", "cnpj",
            "comprovante_residencia", "certidao_casamento", "certidao_nascimento",
            "comprovante_escolaridade", "cartao_vacinas", "conta_salario",
            "certificados_cursos", "curriculo", "FOTO_ROSTO", "foto_3x4",
            "certidao_antecedentes_criminais", "outros".
            """


          def fazer_requisicao_com_fallback(messages, prompt_type="inicial"):
              response = None
              
              # Tentar Groq primeiro
              try:
                  logger.info(f"🔄 Tentando requisição {prompt_type} com Groq...")
                  response = self._make_groq_request(
                      messages=messages,
                      model="meta-llama/llama-4-maverick-17b-128e-instruct",
                      temperature=0.5,
                      max_completion_tokens=1024,
                      top_p=1,
                      stream=False
                  )
                  logger.info(f"✅ Requisição {prompt_type} com Groq bem-sucedida")
                  return response
                  
              except RateLimitError:
                  logger.warning(f"🔄 Groq rate limit na requisição {prompt_type}, tentando com OpenAI...")
                  
                  # Tentar OpenAI como fallback
                  try:
                      response = self._make_openai_request(messages=messages)
                      if response:
                          logger.info(f"✅ Requisição {prompt_type} com OpenAI bem-sucedida")
                          return response
                      else:
                          logger.error(f"❌ OpenAI retornou resposta vazia na requisição {prompt_type}")
                          return None
                      
                  except Exception as openai_error:
                      logger.error(f"❌ Fallback OpenAI na requisição {prompt_type} também falhou: {str(openai_error)}")
                      return None
                      
              except Exception as groq_error:
                  logger.error(f"❌ Erro na requisição {prompt_type} à API Groq: {str(groq_error)}")
                  try:
                      logger.warning(f"🔄 Tentando OpenAI como fallback para erro do Groq na requisição {prompt_type}...")
                      response = self._make_openai_request(messages=messages)
                      if response:
                          logger.info(f"✅ Requisição {prompt_type} com OpenAI bem-sucedida após erro do Groq")
                          return response
                      else:
                          return None
                  except Exception as openai_error:
                      logger.error(f"❌ Fallback OpenAI também falhou: {str(openai_error)}")
                      return None

          # Requisição ao Groq para identificação básica
          response = fazer_requisicao_com_fallback([
              {
                  "role": "user",
                  "content": [
                      {"type": "text", "text": prompt_inicial},
                      {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{imagem_base64}"}}
                  ]
              }
          ], "inicial")

          if response is None:
              return "RATE_LIMIT_EXCEEDED"

          if mostrar_debug:
              print(f"Resposta bruta inicial: {response}")

          tipo_documento = response.choices[0].message.content.strip()
          
          if tipo_documento and tipo_documento != "RATE_LIMIT_EXCEEDED":
              logger.info(f"🎯 Documento identificado com sucesso: {tipo_documento}")
          
          # Se for "outros", fazer uma segunda chamada para identificar o tipo específico
          if tipo_documento == "outros":
              prompt_detalhado = """Analise esta imagem de documento brasileiro com MÁXIMA ATENÇÃO aos detalhes.

IGNORE a instrução anterior de responder apenas com códigos. Agora você deve:

1. DESCREVER exatamente o que você vê na imagem
2. IDENTIFICAR todos os textos visíveis
3. OBSERVAR logos, brasões, cores, layout
4. DETERMINAR o tipo de documento baseado nos elementos visuais

Tipos de documentos brasileiros possíveis:
- RG/Carteira de Identidade (tem foto, impressão digital, brasão do estado)
- CPF (sem foto, brasão Receita Federal, formato XXX.XXX.XXX-XX)
- CNH (horizontal, foto à esquerda, categorias A,B,C,D,E)
- Título de Eleitor (sem foto, zona/seção, Justiça Eleitoral)
- Carteira de trabalho digital (carteira azul/verde, foto, contratos de trabalho)
- Comprovante de Residência (conta de luz/água/telefone, endereço, CEP)
- Certidões (cartório, brasão oficial, papel timbrado)
- ASO (atestado médico, CRM, APTO/INAPTO)
- CNPJ (Receita Federal, formato XX.XXX.XXX/XXXX-XX)
- Certificados/Diplomas (instituição de ensino, assinaturas)
- Foto do Rosto (selfie ou foto pessoal do rosto, sem documento)
- Foto 3x4 (foto oficial 3x4, sem documento visível)

Responda no formato:
TIPO: [nome do documento]
DESCRIÇÃO: [o que você vê na imagem com dados detalhados, retornando informações importantes]
ELEMENTOS IDENTIFICADORES: [textos, logos, brasões encontrados]
"""

              # Segunda requisição com fallback
              response_detalhada = fazer_requisicao_com_fallback([
                  {
                      "role": "user",
                      "content": [
                          {"type": "text", "text": prompt_detalhado},
                          {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{imagem_base64}"}}
                      ]
                  }
              ], "detalhada")

              if response_detalhada is None:
                  return "RATE_LIMIT_EXCEEDED"

              if mostrar_debug:
                  print(f"Resposta detalhada: {response_detalhada}")

              tipo_especifico = response_detalhada.choices[0].message.content.strip()
              
              if tipo_especifico:
                  logger.info(f"🔍 Análise detalhada concluída: {tipo_especifico}")
              
              # Formatar a resposta para incluir o tipo específico
              return f"outros|Tipo não reconhecido, a inteligência artificial acha que é <b>{tipo_especifico.upper()}</b>"
              
          return tipo_documento

      except Exception as e:
          logger.error(f"❌ Erro geral na análise do documento: {str(e)}")
          return f"Erro: {str(e)}"

def analisar_arquivo(caminho_arquivo, mostrar_debug=False):
  analisador = AnalisadorDocumentosGroq()
  return analisador.analisar_documento(caminho_arquivo, mostrar_debug)

if __name__ == "__main__":
  caminho = input("Digite o caminho do arquivo (imagem ou PDF): ").strip()
  resultado = analisar_arquivo(caminho, mostrar_debug=True)
  print(f"\nTipo de Documento: {resultado}")


'''
          # Primeiro prompt para identificar o tipo básico de documento
          prompt_inicial = """

Analise esta imagem e identifique qual tipo de documento brasileiro é.

Responda APENAS com um dos seguintes códigos exatos, sem adicionar nada mais:

DOCUMENTOS DE IDENTIFICAÇÃO:
- rg (Registro Geral/Carteira de Identidade)
- cpf (Cadastro de Pessoa Física)
- cnh (Carteira Nacional de Habilitação)
- titulo_eleitor (Título de Eleitor)
- reservista (Certificado de Reservista)

DOCUMENTOS TRABALHISTAS:
- carteira_trabalho_digital (Carteira de Trabalho e Previdência Social)
- carteira_trabalho_digital (Carteira de Trabalho Digital)
- extrato_pis (Extrato PIS)
- aso (Atestado de Saúde Ocupacional)

DOCUMENTOS EMPRESARIAIS:
- cnpj (Cartão CNPJ)

DOCUMENTOS PESSOAIS:
- comprovante_residencia (Comprovante de Residência - contas de luz, água, etc.)
- certidao_casamento (Certidão de Casamento)
- certidao_nascimento (Certidão de Nascimento)
- comprovante_escolaridade (Diploma, Certificado de Escolaridade)
- cartao_vacinas (Cartão de Vacinação)
- conta_salario (Conta Salário)
- certificados_cursos (Certificados de Cursos e NRs)
- certidao_antecedentes_criminais (Certidão de Antecedentes Criminais)

OUTROS TIPOS DE IMAGENS:
- FOTO_ROSTO (Selfie, foto pessoal do rosto ou para reconhecimento facial, SEM documento visível)
- foto_3x4 (Foto oficial 3x4 para documentos, com fundo neutro, SEM documento visível)
- outros (se não conseguir identificar ou for outro tipo não listado)

CARACTERÍSTICAS ESPECÍFICAS E DETALHADAS PARA IDENTIFICAÇÃO:

RG (Registro Geral / Carteira de Identidade):
ELEMENTOS OBRIGATÓRIOS: Frente: Foto 3x4 (normalmente no canto superior direito), nome completo, número do RG (formato XX.XXX.XXX-X ou similar), CPF, data de nascimento, filiação (pai e mãe), naturalidade, órgão emissor (SSP-XX, IFP-XX, etc.), assinatura do titular. Verso: Impressão digital do polegar direito, assinatura do diretor do órgão emissor, campos administrativos como CTPS, NIS/PIS/PASEP, CNH, CNS, Cert. Militar, etc.
TEXTOS IDENTIFICADORES: Frente: "REPÚBLICA FEDERATIVA DO BRASIL", "CARTEIRA DE IDENTIDADE", nome do estado emissor, brasão estadual. Verso: "LEI Nº 7.116, DE 29 DE AGOSTO DE 1983", "VALIDA EM TODO TERRITÓRIO NACIONAL", “Polegar Direito”.
VARIAÇÕES DE MODELO: Alguns modelos são horizontais (mais antigos) e não possuem foto visível no verso. A cor pode variar (verde, azul, rosa) dependendo do estado e da época da emissão.
ÓRGÃOS EMISSORES: SSP-SP, SSP-RJ, SSP-GO, PC-GO, IFP-PR, DETRAN (alguns estados), entre outros.

CPF (Cadastro de Pessoa Física):
- ELEMENTOS OBRIGATÓRIOS: SEM FOTO, brasão da Receita Federal do Brasil, fundo azul claro ou branco
- TEXTOS IDENTIFICADORES: "CADASTRO DE PESSOAS FÍSICAS", "RECEITA FEDERAL", "MINISTÉRIO DA FAZENDA"
- CAMPOS PRINCIPAIS: Nome completo, número CPF (formato XXX.XXX.XXX-XX), data nascimento, situação cadastral, data inscrição
- LAYOUT: Formato horizontal simples, CPF em destaque no centro
- SITUAÇÃO CADASTRAL: "REGULAR", "PENDENTE DE REGULARIZAÇÃO", "SUSPENSA", "CANCELADA"
- AUSÊNCIA DE: Foto, impressão digital, endereço

CNH (Carteira Nacional de Habilitação):
- ELEMENTOS OBRIGATÓRIOS: Foto no canto superior esquerdo, layout horizontal, código de barras, categorias de habilitação
- TEXTOS IDENTIFICADORES: "CARTEIRA NACIONAL DE HABILITAÇÃO", "DETRAN", nome do estado
- CAMPOS PRINCIPAIS: Nome, CPF, RG, data nascimento, número registro CNH, categorias (A,B,C,D,E), validade, primeira habilitação, local nascimento
- LAYOUT: Formato horizontal (paisagem), foto à esquerda, dados à direita
- CATEGORIAS: A (motocicleta), B (automóvel), C (caminhão), D (ônibus), E (carreta) - destacadas em caixas
- CORES: Predominantemente azul e amarelo, com elementos de segurança
- VALIDADE: Sempre presente no formato DD/MM/AAAA

TITULO_ELEITOR (Título de Eleitor):
- ELEMENTOS OBRIGATÓRIOS: SEM FOTO, brasão da Justiça Eleitoral, "JUSTIÇA ELEITORAL", "JUSTIÇA ELEITORAL", "TRIBUNAL SUPERIOR ELEITORAL"
- TEXTOS IDENTIFICADORES: "TÍTULO DE ELEITOR", "TRIBUNAL REGIONAL ELEITORAL", nome do estado (TRE-XX), Eleitor(a)
- CAMPOS PRINCIPAIS: Nome completo, número título (formato XXXX XXXX XXXX), zona eleitoral, seção eleitoral, município, estado, data emissão
- LAYOUT: Formato vertical, número do título em destaque
- ZONA/SEÇÃO: Números de 3-4 dígitos cada
- AUSÊNCIA DE: Foto, CPF (geralmente), impressão digital

RESERVISTA (Certificado de Reservista):
- ELEMENTOS OBRIGATÓRIOS: Brasão das Forças Armadas (Exército, Marinha ou Aeronáutica), cores militares
- TEXTOS IDENTIFICADORES: "CERTIFICADO DE RESERVISTA", "EXÉRCITO BRASILEIRO", "MARINHA DO BRASIL", "FORÇA AÉREA BRASILEIRA", "ATESTADO DE DESOBRIGAÇÃO MILITAR", "DOCUMENTO COMPROBATÓRIO DE SITUAÇÃO MILITAR"
- CAMPOS PRINCIPAIS: Nome, CPF, número certificado, categoria (1ª, 2ª, 3ª), data incorporação, data licenciamento, unidade militar
- LAYOUT: Formato oficial militar com brasões e símbolos das forças armadas
- CATEGORIAS: 1ª categoria (alistado e serviu), 2ª categoria (dispensado), 3ª categoria (excesso de contingente)

carteira_trabalho_digital (Carteira de Trabalho e Previdência Social):
- ELEMENTOS OBRIGATÓRIOS: Foto 3x4, capa azul ou verde (versões antigas), páginas internas com contratos
- TEXTOS IDENTIFICADORES: "CARTEIRA DE TRABALHO E PREVIDÊNCIA SOCIAL", "MINISTÉRIO DO TRABALHO"
- CAMPOS PRINCIPAIS: Nome, CPF, PIS/PASEP, série, número, data emissão, assinatura do portador
- CONTRATOS: Páginas com dados de empresas, cargos, salários, datas admissão/demissão
- LAYOUT: Formato de carteira (livreto), múltiplas páginas
- HISTÓRICO: Registros de trabalho com carimbos e assinaturas das empresas

carteira_trabalho_digital (Carteira de Trabalho Digital):
- ELEMENTOS OBRIGATÓRIOS: Interface de aplicativo, layout moderno, pode ter QR Code
- TEXTOS IDENTIFICADORES: "CARTEIRA DE TRABALHO DIGITAL", logos do Ministério do Trabalho, "Gov.br"
- CAMPOS PRINCIPAIS: Nome, CPF, PIS, contratos digitais atualizados, dados em formato digital
- LAYOUT: Interface de smartphone ou impressão de tela do aplicativo
- CARACTERÍSTICAS: Design moderno, cores do governo federal, informações organizadas digitalmente

EXTRATO_PIS (Extrato PIS):
- ELEMENTOS OBRIGATÓRIOS: Logo da Caixa Econômica Federal ou Banco do Brasil
- TEXTOS IDENTIFICADORES: "EXTRATO PIS/PASEP", "CAIXA ECONÔMICA FEDERAL", "BANCO DO BRASIL", "NIS/PIS/PASEP"
- CAMPOS PRINCIPAIS: Nome, CPF, número PIS/PASEP, saldo, movimentações, data cadastramento
- LAYOUT: Formato de extrato bancário com cabeçalho institucional
- MOVIMENTAÇÕES: Histórico de depósitos e saques do PIS/PASEP

ASO (Atestado de Saúde Ocupacional):
- ELEMENTOS OBRIGATÓRIOS: Carimbo médico com CRM, assinatura do médico responsável
- TEXTOS IDENTIFICADORES: "ATESTADO DE SAÚDE OCUPACIONAL", "ASO", resultado "APTO" ou "INAPTO"
- CAMPOS PRINCIPAIS: Nome trabalhador, CPF, empresa, cargo, função, tipo exame (admissional, periódico, demissional), resultado, médico responsável, CRM
- LAYOUT: Formato de atestado médico com campos específicos ocupacionais
- RESULTADO: Sempre presente - "APTO" ou "INAPTO" para o trabalho
- MÉDICO: Nome, CRM, assinatura e carimbo obrigatórios

NAO EXISTE PROCURAÇÃO "ET EXTRA" E "AD NEGOTIA", use sempre CNPJ.

CNPJ (Cartão CNPJ):
- ELEMENTOS OBRIGATÓRIOS: Brasão da Receita Federal, "CARTÃO CNPJ", PROCURAÇÃO ET EXTRA E AD NEGOTIA"
- TEXTOS IDENTIFICADORES: "CARTÃO CNPJ", "RECEITA FEDERAL", "CADASTRO NACIONAL DA PESSOA JURÍDICA", "PROCURAÇÃO" ,"ET EXTRA", "AD NEGOTIA"
- CAMPOS PRINCIPAIS: Razão social, nome fantasia, CNPJ (formato XX.XXX.XXX/XXXX-XX), situação cadastral, data abertura, atividade principal, endereço
- LAYOUT: Formato de cartão empresarial oficial
- SITUAÇÃO: "ATIVA", "SUSPENSA", "INAPTA", "BAIXADA"

COMPROVANTE_RESIDENCIA (Comprovante de Residência):
- ELEMENTOS OBRIGATÓRIOS: Endereço completo com CEP, nome do titular, empresa prestadora de serviço
- TIPOS: Conta de luz (Enel, Equatorial, CPFL, Cemig), água (Sabesp, Saneago, Cedae), telefone (Vivo, TIM, Claro, Oi), gás (Comgás, Naturgy), internet, IPTU, contrato aluguel
- CAMPOS PRINCIPAIS: Nome titular, endereço completo, CEP, data vencimento, valor, consumo (kWh, m³, etc.)
- EMPRESAS COMUNS: Enel, Equatorial, CPFL, Cemig, Sabesp, Saneago, Cedae, Vivo, TIM, Claro, Oi, Comgás, Naturgy
- LAYOUT: Formato de fatura com cabeçalho da empresa, dados de consumo, endereço destacado
- OBSERVAÇÃO: Mesmo com CPF presente, se tiver endereço e for fatura de serviço, é comprovante_residencia

CERTIDAO_CASAMENTO (Certidão de Casamento):
- ELEMENTOS OBRIGATÓRIOS: Brasão oficial do cartório, papel timbrado oficial
- TEXTOS IDENTIFICADORES: "CERTIDÃO DE CASAMENTO", nome do cartório, "OFICIAL DE REGISTRO CIVIL"
- CAMPOS PRINCIPAIS: Nomes dos cônjuges, data casamento, local cerimônia, cartório, livro, folha, termo, testemunhas
- LAYOUT: Formato oficial de certidão com texto corrido e dados organizados
- CARTÓRIO: Nome completo do cartório emissor, cidade, estado

CERTIDAO_NASCIMENTO (Certidão de Nascimento):
- ELEMENTOS OBRIGATÓRIOS: Brasão oficial do cartório, papel timbrado oficial
- TEXTOS IDENTIFICADORES: "CERTIDÃO DE NASCIMENTO", nome do cartório, "OFICIAL DE REGISTRO CIVIL"
- CAMPOS PRINCIPAIS: Nome registrado, data nascimento, local nascimento, filiação (pai/mãe), avós, cartório, livro, folha, termo
- LAYOUT: Formato oficial de certidão com texto detalhado
- FILIAÇÃO: Nomes completos dos pais obrigatórios

COMPROVANTE_ESCOLARIDADE (Diploma, Certificado de Escolaridade):
- ELEMENTOS OBRIGATÓRIOS: Timbre da instituição de ensino, assinaturas oficiais
- TEXTOS IDENTIFICADORES: Nome da instituição, "DIPLOMA", "CERTIFICADO", "HISTÓRICO ESCOLAR"
- CAMPOS PRINCIPAIS: Nome formando, curso, instituição, data conclusão, carga horária, notas/conceitos, diretor/coordenador
- TIPOS: Diploma superior, certificado técnico, histórico escolar, declaração matrícula
- LAYOUT: Formato solene com bordas decorativas, assinaturas e carimbos

CARTAO_VACINAS (Cartão de Vacinação):
- ELEMENTOS OBRIGATÓRIOS: Tabela de vacinas, datas de aplicação, carimbos de unidades de saúde
- TEXTOS IDENTIFICADORES: "CARTÃO DE VACINAÇÃO", "CADERNETA DE VACINAÇÃO", logos do SUS
- CAMPOS PRINCIPAIS: Nome, data nascimento, vacinas aplicadas, datas aplicação, lotes, unidade saúde aplicadora
- LAYOUT: Formato de cartão ou caderneta com tabelas organizadas por idade/vacina
- VACINAS: BCG, Hepatite B, Pentavalente, Pneumocócica, Rotavírus, Meningocócica, Febre Amarela, Tríplice Viral, etc.

CONTA_SALARIO (Conta Salário):
- ELEMENTOS OBRIGATÓRIOS: Logo do banco, dados completos da conta (banco, agência, conta)
- TEXTOS IDENTIFICADORES: Nome do banco, "CONTA SALÁRIO", "CONTA CORRENTE"
- CAMPOS PRINCIPAIS: Nome titular, CPF, banco, agência, número conta, tipo conta, gerente
- BANCOS: Banco do Brasil, Bradesco, Itaú, Santander, Caixa, bancos digitais
- LAYOUT: Formato de documento bancário oficial ou print de aplicativo
- OBSERVAÇÃO: Deve conter dados bancários completos (banco + agência + conta), NUNCA FALE COMPROVANTE DE DADOS BANCÁRIOS, COMPROVANTE BANCÁRIO OU COMPROVANTE DE CONTA BANCÁRIA USE SOMENTE CONTA_SALARIO

CARTEIRA_IDENTIDADE_PROFISSIONAL (Documento de Identificação Profissional emitido por Conselhos de Classe):
- ELEMENTOS OBRIGATÓRIOS: Foto 3x4, nome completo, número de registro profissional, CPF, órgão emissor (ex: CRC, CREA, CRM, OAB), assinatura do profissional, assinatura ou carimbo do conselho, brasão da república ou logotipo do conselho.
- CARACTERÍSTICAS: Formato pode ser horizontal ou vertical, estrutura semelhante a uma identidade oficial. Cores e layout variam conforme o conselho (azul, branco, verde, etc.). Pode conter QR Code ou selo de autenticação. Documento impresso em papel especial ou cartão rígido, com dados organizados.
- AUSÊNCIA DE: Dados de veículos (como na CNH), informações eleitorais, registros militares, comprovantes de endereço ou dados bancários. Não possui estrutura de contratos como a carteira_trabalho_digital.
- USO COMUM: Utilizado para comprovação legal da habilitação do profissional em sua área regulamentada (advocacia, medicina, contabilidade, engenharia, etc.) e apresentação em instituições públicas e privadas.

CERTIFICADOS_CURSOS (Certificados de Cursos e NRs):
- ELEMENTOS OBRIGATÓRIOS: Timbre da instituição de ensino ou empresa, assinatura do responsável pelo curso, carimbos institucionais (quando houver), carga horária, nome do curso.
- TEXTOS IDENTIFICADORES: "CERTIFICADO", "DECLARAÇÃO", "CERTIFICAMOS", nome da instituição/empresa, tipo do curso, "carga horária", "concluiu", "participou", "com êxito", "aproveitamento", "ministrado por".
- TIPOS: Certificados de NRs (NR-10, NR-35, NR-33), primeiros socorros, brigada de incêndio, cursos técnicos, capacitações profissionais, treinamentos internos, cursos livres.
- CAMPOS PRINCIPAIS: Nome do participante, nome do curso, carga horária (em horas), data de conclusão, nota/conceito, nome e cargo do instrutor/responsável, CNPJ ou dados da instituição.
- LAYOUT: Formato horizontal ou vertical, aparência formal, margens decorativas ou bordas, geralmente com logos da instituição no cabeçalho. Pode conter QR Code para validação.
- CORES: Variedade de cores, normalmente azul, verde ou cinza; uso frequente de brasões ou logos institucionais em destaque.
- OBSERVAÇÃO: Mesmo que haja termos como "digital" ou "validação eletrônica", se o texto central estiver relacionado à conclusão ou participação em cursos, deve ser classificado como certificados_cursos.

curriculo (Currículo/CV):
- ELEMENTOS OBRIGATÓRIOS: Nome completo do candidato; informações de contato (e-mail e/ou telefone); pelo menos uma seção estruturada sobre trajetória (ex.: “Experiência”, “Formação”). Pode conter link para LinkedIn/portfólio. Foto é opcional.
- TEXTOS IDENTIFICADORES: Títulos/seções como “Currículo”, “Curriculum Vitae”, “Resumo Profissional”, “Objetivo”, “Experiência Profissional”, “Atividades”, “Projetos”, “Educação”/“Formação Acadêmica”, “Cursos Complementares”, “Certificações”, “Idiomas”, “Habilidades”/“Competências”, “Publicações”. No padrão acadêmico/Lattes: “Dados Gerais”, “Formação Acadêmica/Titulação”, “Atuação Profissional”, “Projetos de Pesquisa”, “Produções”.
- TIPOS:Cronológico/cronológico-invertido (experiências listadas por data). Funcional (ênfase em habilidades/resultados, pouca ênfase em datas). Combinado (híbrido de cronológico + funcional). Acadêmico/Lattes (foco em publicações, orientações, projetos, eventos).
- CAMPOS PRINCIPAIS: Nome; contato (e-mail/telefone, cidade/UF); objetivo ou resumo; experiências (empresa, cargo, período DD/MM/AAAA ou MM/AAAA, atividades/resultados); formação (curso, instituição, nível, período); cursos/treinamentos; certificações; idiomas (nível); habilidades técnicas e comportamentais; links (LinkedIn, GitHub, site).
- LAYOUT: Geralmente 1–2 colunas; listas com marcadores; datas alinhadas à direita ou em linha; cabeçalhos/rodapés simples; separadores horizontais entre seções. Em versões Lattes/PDF oficial, cabeçalhos padronizados e logotipo do CNPq podem aparecer.
- CORES: Predominantemente preto/cinza; pode haver cor de destaque (ex.: azul/verde) em títulos/ícones. Papel de fundo branco; sem brasões/carimbos oficiais.
- OBSERVAÇÃO:Classifique como curriculo quando o documento sintetiza trajetória profissional/ acadêmica do candidato em seções típicas, mesmo que traga logos de empresas/instituições, QR code para perfil, ou foto. Não classifique como curriculo se o foco for: certificado/declaração (“CERTIFICAMOS”, “DECLARAÇÃO”, “carga horária”), histórico escolar/boletim (notas/disciplinas), carta de apresentação (texto corrido direcionado a empresa), comprovante de inscrição/participação, contrato/CTPS, portfólio visual predominante ou print isolado de rede social. “Currículo Lattes” (HTML/PDF do CNPq) também é curriculo: presença de seções padronizadas e listagens extensas de produções acadêmicas é indicativa. Sinais positivos: títulos de seção claros, listas de cargos com datas e responsabilidades, formação com instituição/curso, blocos de “Habilidades/Idiomas/Certificações”. Sinais negativos: timbre oficial, carimbos/assinaturas de validação, linguagem certificadora (“concluiu com êxito”), ênfase em carga horária/nota — nesses casos, avaliar “certificados_cursos” ou “comprovante_escolaridade”.

FOTO_3X4 (Foto oficial 3x4):
- ELEMENTOS OBRIGATÓRIOS: Apenas o rosto da pessoa, fundo neutro, liso e claro (branco, cinza claro ou azul claro), sem outros elementos na imagem.
- CARACTERÍSTICAS:
- Formato retrato, proporcional a 3x4 cm.
- A pessoa deve estar olhando diretamente para a câmera, com expressão neutra.
- Roupas formais ou neutras.
- Sem acessórios que cubram o rosto (óculos escuros, bonés, chapéus, máscaras).
- Iluminação uniforme e boa nitidez.
- Ombros visíveis e centralizados no enquadramento.
- AUSÊNCIA DE: Qualquer tipo de documento visível, bordas, brasões, carimbos, marcas d'água ou textos. Logotipos ou nomes de instituições.
- USO COMUM: Para documentos oficiais (RG, passaporte, CNH), crachás, carteiras de estudante ou currículos.
- IMPORTANTE: Só classifique como foto_3x4 se não houver nenhum elemento de documento ou layout institucional. Se a imagem estiver dentro de um documento (como RG ou CNH), não classifique como foto_3x4.

FOTO_ROSTO (Selfie ou foto casual do rosto):
- ELEMENTOS OBRIGATÓRIOS: Rosto da pessoa visível em primeiro plano, sem elementos de documentos ou textos ao redor.
- CARACTERÍSTICAS: Pode ser uma selfie ou uma foto espontânea.Fundo variado ou ambiente real (não precisa ser neutro). A pessoa pode estar sorrindo ou com expressão natural. Pode haver braço visível segurando o celular (em caso de selfie). Pode estar em ambientes internos ou externos.
- AUSÊNCIA DE: Documentos, bordas de papel, brasões oficiais ou qualquer marca institucional. Padrões de foto oficial como fundo branco e expressão neutra.
- USO COMUM: Validação facial, fotos de perfil, identificação visual fora de contextos formais ou documentos.
- IMPORTANTE: Só use FOTO_ROSTO se a imagem for somente da pessoa, sem nenhum documento por perto. Se houver um documento visível ao lado ou no fundo, classifique como o tipo de documento correspondente, nunca como FOTO_ROSTO.

certidao_antecedentes_criminais (Certidão de Antecedentes Criminais):
- ELEMENTOS OBRIGATÓRIOS: Emissão por órgão oficial (geralmente Polícia Federal ou Secretaria de Segurança Pública), brasão da República Federativa do Brasil ou símbolo institucional, número da certidão, nome completo do indivíduo, filiação (nome dos pais), data de nascimento, documento de identificação (RG/CI, CPF), data e hora de emissão. Pode conter prazo de validade (ex.: 90 dias).
- TEXTOS IDENTIFICADORES: “Certidão de Antecedentes Criminais”, “Polícia Federal”, “Sistema Nacional de Informações Criminais (SINIC)”, “CERTIFICA”, “NÃO CONSTA condenação”, “com trânsito em julgado”, “expedida em [data]”, “autenticidade desta certidão”, “validar” (muitas vezes acompanhado de link ou QR Code).
- TIPOS: Certidão negativa de antecedentes criminais; certidão positiva (quando há registros); certidão expedida pela Polícia Federal; certidão expedida por Secretarias de Segurança estaduais.
- CAMPOS PRINCIPAIS: Nome completo; filiação; nacionalidade; data de nascimento; número de RG/CI; número de CPF; número de certidão; data e hora de emissão; validade; órgão emissor; código de verificação ou QR Code.
- LAYOUT: Formato A4 vertical, com brasão oficial no topo; texto corrido e formal; geralmente estruturado em parágrafos, podendo conter cabeçalhos com nome do órgão e subsistema (ePol/SINIC, Polícia Federal). Assinatura digital ou QR Code substituem, em muitos casos, a assinatura manual.
- CORES: Predominantemente preto/branco, podendo incluir brasão colorido (verde, azul, amarelo) e QR Code em preto. Estilo sóbrio, sem elementos decorativos.
- OBSERVAÇÃO: Sempre documento oficial, não confundir com currículos, certificados de cursos ou declarações genéricas. A presença de termos como “CERTIFICA”, “NÃO CONSTA condenação” e validação por QR Code/link institucional é fortemente indicativa de certidao_antecedentes_criminais.

INSTRUÇÕES CRÍTICAS PARA EVITAR CLASSIFICAÇÃO COMO "OUTROS":
1. Analise TODOS os elementos visuais: brasões, logos, layouts, cores, presença de fotos
2. Procure por textos identificadores específicos mencionados acima
3. Observe formatos de números (CPF: XXX.XXX.XXX-XX, CNPJ: XX.XXX.XXX/XXXX-XX)
4. Identifique órgãos emissores (SSP, Receita Federal, DETRAN, TRE, etc.)
5. Verifique presença/ausência de foto (RG e CNH têm, CPF e Título não têm)
6. Observe orientação do documento (CNH horizontal, RG vertical)
7. Para comprovantes de residência: foque no endereço e empresa prestadora, não apenas no CPF
8. Para conta salário: certifique-se de que há dados bancários completos
9. Se identificar qualquer elemento das características acima, NÃO classifique como "outros"
10. Seja criterioso: documentos brasileiros oficiais sempre têm elementos identificadores únicos listados acima
11. **IMPORTANTE:** Se a imagem contiver um documento oficial (RG, CNH, etc.) que POR ACASO também tenha uma foto 3x4 da pessoa, classifique SEMPRE como o tipo do **DOCUMENTO** (ex: 'rg', 'cnh'), e NUNCA como 'foto_3x4' ou 'FOTO_ROSTO'. As categorias 'foto_3x4' e 'FOTO_ROSTO' são para fotos *sem* documentos, ou seja, fotos isoladas do rosto.
12. NAO EXISTE TIPO: PROCURAÇÃO "ET EXTRA" E "AD NEGOTIA", use sempre CNPJ, Se colocar o TIPO como PROCURAÇÃO "ET EXTRA" E "AD NEGOTIA" mude para CNPJ.
13. NAO EXISTE TIPO: COMPROVANTE DE DADOS BANCÁRIOS ou COMPROVANTE BANCÁRIO, use sempre CONTA_SALÁRIO. Se colocar o TIPO como COMPROVANTE DE DADOS BANCÁRIOS ou COMPROVANTE BANCÁRIO mude para CONTA_SALÁRIO.
14. SE NAO CONSEGUIR EXTRAIR UM DADO IMPORTANTE DO DOCUMENTO (EX: NUMERO DO RG, CPF, NOME, DATA DE NASCIMENTO, ENDEREÇO, ETC) PORQUE O DOCUMENTO ESTÁ MUITO RUIM/ILEGÍVEL, CLASSIFIQUE COMO "outros" IMEDIATAMENTE, MESMO QUE VOCÊ CONSIGA IDENTIFICAR O TIPO DO DOCUMENTO. NÃO TENTE CHUTAR OU ADIVINHAR O DADO.
15. SE FOR CERTIDÃO DE ESCRITURA PÚBLICA DE DECLARAÇÃO DE UNIÃO ESTÁVEL COLOQUE como certidao_casamento.
16. SE FOR CERTIFICADO DA CONDIÇÃO DE MICROEMPREENDEDOR INDIVIDUAL (MEI) COLOQUE como CNPJ.
17. NUNCA COLOQUE COMPROVANTE DE RESIDÊNCIA (FATURA DE CARTÃO DE CRÉDITO) COLOQUE COMO comprovante_residencia.

PRIORIZE a identificação correta baseada nas características específicas listadas. Use "outros" APENAS quando realmente não conseguir identificar.

CHECKLIST FINAL ANTES DE DECIDIR:
1) A imagem é nítida e completa (sem cortes)? Se NÃO → outros.
2) Vejo textos identificadores/brasões/campos-chave? Se NÃO → outros.
3) Consigo distinguir claramente a estrutura/lay­out típico do documento? Se NÃO → outros.
4) Há dados essenciais legíveis para sustentar a classificação? Se NÃO → outros.
5) DEVE SER POSSIVEL EXTRAIR UM DADO IMPORTANTE DO DOCUMENTO (EX: NUMERO DO RG, CPF, NOME, DATA DE NASCIMENTO, ENDEREÇO, ETC) COM CONFIANÇA.
6) RESPONDA APENAS COM O CÓDIGO EXATO, SEM NADA MAIS (ex: "rg", "cpf", "cnh", "titulo_eleitor", "reservista", "carteira_trabalho_digital", "extrato_pis", "aso", "cnpj", "comprovante_residencia", "certidao_casamento", "certidao_nascimento", "comprovante_escolaridade", "cartao_vacinas", "conta_salario", "certificados_cursos", "curriculo", "FOTO_ROSTO", "foto_3x4", "certidao_antecedentes_criminais" ou "outros").

Se qualquer resposta acima for NÃO, responda “outros”.

"""
'''








# funciona perfeitamente (backup)

'''



import os
import io
import base64
import tempfile
import requests
from PIL import Image
from pdf2image import convert_from_path
from groq import Groq, RateLimitError # Importa RateLimitError
import openai
from decouple import config
import time # Importar time para sleep
import random # Importar random para jitter
import logging

logger = logging.getLogger(__name__)

class AnalisadorDocumentosGroq:
  def __init__(self, provider='groq', api_key_groq=None, api_key_openai=None):
      self.api_key_groq = api_key_groq or config('API_KEY_GROQ')
      self.api_key_openai = api_key_openai or config('API_KEY_OPENAI')

      # Usando Groq como padrão, conforme o erro original
      self.client = Groq(api_key=self.api_key_groq)

  def converter_pdf_para_imagem(self, pdf_path):
      try:
          imagens = convert_from_path(pdf_path, first_page=1, last_page=1)
          if imagens:
              with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                  imagens[0].save(tmp.name, 'JPEG')
                  return tmp.name
          return None
      except Exception as e:
          print(f"Erro ao converter PDF: {str(e)}")
          return None

  def processar_imagem(self, caminho_arquivo):
      try:
          with Image.open(caminho_arquivo) as img:
              if img.mode != 'RGB':
                  img = img.convert('RGB')
              max_size = 1024
              if max(img.size) > max_size:
                  ratio = max_size / max(img.size)
                  new_size = tuple(int(dim * ratio) for dim in img.size)
                  img = img.resize(new_size, Image.Resampling.LANCZOS)
              img_byte_arr = io.BytesIO()
              img.save(img_byte_arr, format='JPEG', quality=85)
              img_byte_arr = img_byte_arr.getvalue()
              return base64.b64encode(img_byte_arr).decode('utf-8')
      except Exception as e:
          print(f"Erro ao processar imagem: {str(e)}")
          return None

  def _make_groq_request(self, messages, model, temperature, max_completion_tokens, top_p, stream):
    max_retries = 2  # Reduzido de 5 para 2 para evitar timeout
    base_delay = 1  # segundos
    max_wait_time = 30  # Máximo 30 segundos de espera total
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Tentativa {attempt + 1}/{max_retries} de requisição à API Groq")
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
                top_p=top_p,
                stream=stream
            )
            logger.info("✅ Requisição à API Groq bem-sucedida")
            return response
        except RateLimitError as e:
            logger.error(f"❌ Rate limit atingido na API Groq: {str(e)}")
            
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_wait_time)
                logger.warning(f"⏳ Aguardando {delay} segundos antes da próxima tentativa...")
                time.sleep(delay)
            else:
                logger.error("❌ Máximo de tentativas atingido. Rate limit excedido.")
                raise e
        except Exception as e:
            logger.error(f"❌ Erro na requisição à API Groq: {str(e)}")
            raise e

  def analisar_documento(self, caminho_arquivo, mostrar_debug=False):
      try:
          if not os.path.exists(caminho_arquivo):
              return "Erro: Arquivo não encontrado"

          extensao = os.path.splitext(caminho_arquivo)[1].lower()
          if extensao == '.pdf':
              caminho_temp = self.converter_pdf_para_imagem(caminho_arquivo)
              if not caminho_temp:
                  return "Erro: Não foi possível converter o PDF"
              imagem_base64 = self.processar_imagem(caminho_temp)
              os.unlink(caminho_temp)
          else:
              imagem_base64 = self.processar_imagem(caminho_arquivo)

          if not imagem_base64:
              return "Erro: Não foi possível processar o arquivo"

          # Primeiro prompt para identificar o tipo básico de documento
          prompt_inicial = """Analise esta imagem e identifique qual tipo de documento brasileiro é.

Responda APENAS com um dos seguintes códigos exatos, sem adicionar nada mais:

DOCUMENTOS DE IDENTIFICAÇÃO:
- rg (Registro Geral/Carteira de Identidade)
- cpf (Cadastro de Pessoa Física)
- cnh (Carteira Nacional de Habilitação)
- titulo_eleitor (Título de Eleitor)
- reservista (Certificado de Reservista)

DOCUMENTOS TRABALHISTAS:
- ctps (Carteira de Trabalho e Previdência Social)
- carteira_trabalho_digital (Carteira de Trabalho Digital)
- extrato_pis (Extrato PIS)
- aso (Atestado de Saúde Ocupacional)

DOCUMENTOS EMPRESARIAIS:
- cnpj (Cartão CNPJ)

DOCUMENTOS PESSOAIS:
- comprovante_residencia (Comprovante de Residência - contas de luz, água, etc.)
- certidao_casamento (Certidão de Casamento)
- certidao_nascimento (Certidão de Nascimento)
- comprovante_escolaridade (Diploma, Certificado de Escolaridade)
- cartao_vacinas (Cartão de Vacinação)
- conta_salario (Conta Salário)
- certificados_cursos (Certificados de Cursos e NRs)

OUTROS TIPOS DE IMAGENS:
- FOTO_ROSTO (Selfie, foto pessoal do rosto ou para reconhecimento facial, SEM documento visível)
- foto_3x4 (Foto oficial 3x4 para documentos, com fundo neutro, SEM documento visível)
- outros (se não conseguir identificar ou for outro tipo não listado)

CARACTERÍSTICAS ESPECÍFICAS E DETALHADAS PARA IDENTIFICAÇÃO:

RG (Registro Geral / Carteira de Identidade):
ELEMENTOS OBRIGATÓRIOS: Frente: Foto 3x4 (normalmente no canto superior direito), nome completo, número do RG (formato XX.XXX.XXX-X ou similar), CPF, data de nascimento, filiação (pai e mãe), naturalidade, órgão emissor (SSP-XX, IFP-XX, etc.), assinatura do titular. Verso: Impressão digital do polegar direito, assinatura do diretor do órgão emissor, campos administrativos como CTPS, NIS/PIS/PASEP, CNH, CNS, Cert. Militar, etc.
TEXTOS IDENTIFICADORES: Frente: "REPÚBLICA FEDERATIVA DO BRASIL", "CARTEIRA DE IDENTIDADE", nome do estado emissor, brasão estadual. Verso: "LEI Nº 7.116, DE 29 DE AGOSTO DE 1983", "VALIDA EM TODO TERRITÓRIO NACIONAL", “Polegar Direito”.
VARIAÇÕES DE MODELO: Alguns modelos são horizontais (mais antigos) e não possuem foto visível no verso. A cor pode variar (verde, azul, rosa) dependendo do estado e da época da emissão.
ÓRGÃOS EMISSORES: SSP-SP, SSP-RJ, SSP-GO, PC-GO, IFP-PR, DETRAN (alguns estados), entre outros.

CPF (Cadastro de Pessoa Física):
- ELEMENTOS OBRIGATÓRIOS: SEM FOTO, brasão da Receita Federal do Brasil, fundo azul claro ou branco
- TEXTOS IDENTIFICADORES: "CADASTRO DE PESSOAS FÍSICAS", "RECEITA FEDERAL", "MINISTÉRIO DA FAZENDA"
- CAMPOS PRINCIPAIS: Nome completo, número CPF (formato XXX.XXX.XXX-XX), data nascimento, situação cadastral, data inscrição
- LAYOUT: Formato horizontal simples, CPF em destaque no centro
- SITUAÇÃO CADASTRAL: "REGULAR", "PENDENTE DE REGULARIZAÇÃO", "SUSPENSA", "CANCELADA"
- AUSÊNCIA DE: Foto, impressão digital, endereço

CNH (Carteira Nacional de Habilitação):
- ELEMENTOS OBRIGATÓRIOS: Foto no canto superior esquerdo, layout horizontal, código de barras, categorias de habilitação
- TEXTOS IDENTIFICADORES: "CARTEIRA NACIONAL DE HABILITAÇÃO", "DETRAN", nome do estado
- CAMPOS PRINCIPAIS: Nome, CPF, RG, data nascimento, número registro CNH, categorias (A,B,C,D,E), validade, primeira habilitação, local nascimento
- LAYOUT: Formato horizontal (paisagem), foto à esquerda, dados à direita
- CATEGORIAS: A (motocicleta), B (automóvel), C (caminhão), D (ônibus), E (carreta) - destacadas em caixas
- CORES: Predominantemente azul e amarelo, com elementos de segurança
- VALIDADE: Sempre presente no formato DD/MM/AAAA

TITULO_ELEITOR (Título de Eleitor):
- ELEMENTOS OBRIGATÓRIOS: SEM FOTO, brasão da Justiça Eleitoral, "JUSTIÇA ELEITORAL"
- TEXTOS IDENTIFICADORES: "TÍTULO DE ELEITOR", "TRIBUNAL REGIONAL ELEITORAL", nome do estado (TRE-XX)
- CAMPOS PRINCIPAIS: Nome completo, número título (formato XXXX XXXX XXXX), zona eleitoral, seção eleitoral, município, estado, data emissão
- LAYOUT: Formato vertical, número do título em destaque
- ZONA/SEÇÃO: Números de 3-4 dígitos cada
- AUSÊNCIA DE: Foto, CPF (geralmente), impressão digital

RESERVISTA (Certificado de Reservista):
- ELEMENTOS OBRIGATÓRIOS: Brasão das Forças Armadas (Exército, Marinha ou Aeronáutica), cores militares
- TEXTOS IDENTIFICADORES: "CERTIFICADO DE RESERVISTA", "EXÉRCITO BRASILEIRO", "MARINHA DO BRASIL", "FORÇA AÉREA BRASILEIRA"
- CAMPOS PRINCIPAIS: Nome, CPF, número certificado, categoria (1ª, 2ª, 3ª), data incorporação, data licenciamento, unidade militar
- LAYOUT: Formato oficial militar com brasões e símbolos das forças armadas
- CATEGORIAS: 1ª categoria (alistado e serviu), 2ª categoria (dispensado), 3ª categoria (excesso de contingente)

CTPS (Carteira de Trabalho e Previdência Social):
- ELEMENTOS OBRIGATÓRIOS: Foto 3x4, capa azul ou verde (versões antigas), páginas internas com contratos
- TEXTOS IDENTIFICADORES: "CARTEIRA DE TRABALHO E PREVIDÊNCIA SOCIAL", "MINISTÉRIO DO TRABALHO"
- CAMPOS PRINCIPAIS: Nome, CPF, PIS/PASEP, série, número, data emissão, assinatura do portador
- CONTRATOS: Páginas com dados de empresas, cargos, salários, datas admissão/demissão
- LAYOUT: Formato de carteira (livreto), múltiplas páginas
- HISTÓRICO: Registros de trabalho com carimbos e assinaturas das empresas

CARTEIRA_TRABALHO_DIGITAL (Carteira de Trabalho Digital):
- ELEMENTOS OBRIGATÓRIOS: Interface de aplicativo, layout moderno, pode ter QR Code
- TEXTOS IDENTIFICADORES: "CARTEIRA DE TRABALHO DIGITAL", logos do Ministério do Trabalho, "Gov.br"
- CAMPOS PRINCIPAIS: Nome, CPF, PIS, contratos digitais atualizados, dados em formato digital
- LAYOUT: Interface de smartphone ou impressão de tela do aplicativo
- CARACTERÍSTICAS: Design moderno, cores do governo federal, informações organizadas digitalmente

EXTRATO_PIS (Extrato PIS):
- ELEMENTOS OBRIGATÓRIOS: Logo da Caixa Econômica Federal ou Banco do Brasil
- TEXTOS IDENTIFICADORES: "EXTRATO PIS/PASEP", "CAIXA ECONÔMICA FEDERAL", "BANCO DO BRASIL"
- CAMPOS PRINCIPAIS: Nome, CPF, número PIS/PASEP, saldo, movimentações, data cadastramento
- LAYOUT: Formato de extrato bancário com cabeçalho institucional
- MOVIMENTAÇÕES: Histórico de depósitos e saques do PIS/PASEP

ASO (Atestado de Saúde Ocupacional):
- ELEMENTOS OBRIGATÓRIOS: Carimbo médico com CRM, assinatura do médico responsável
- TEXTOS IDENTIFICADORES: "ATESTADO DE SAÚDE OCUPACIONAL", "ASO", resultado "APTO" ou "INAPTO"
- CAMPOS PRINCIPAIS: Nome trabalhador, CPF, empresa, cargo, função, tipo exame (admissional, periódico, demissional), resultado, médico responsável, CRM
- LAYOUT: Formato de atestado médico com campos específicos ocupacionais
- RESULTADO: Sempre presente - "APTO" ou "INAPTO" para o trabalho
- MÉDICO: Nome, CRM, assinatura e carimbo obrigatórios

CNPJ (Cartão CNPJ):
- ELEMENTOS OBRIGATÓRIOS: Brasão da Receita Federal, "CARTÃO CNPJ"
- TEXTOS IDENTIFICADORES: "CARTÃO CNPJ", "RECEITA FEDERAL", "CADASTRO NACIONAL DA PESSOA JURÍDICA"
- CAMPOS PRINCIPAIS: Razão social, nome fantasia, CNPJ (formato XX.XXX.XXX/XXXX-XX), situação cadastral, data abertura, atividade principal, endereço
- LAYOUT: Formato de cartão empresarial oficial
- SITUAÇÃO: "ATIVA", "SUSPENSA", "INAPTA", "BAIXADA"

COMPROVANTE_RESIDENCIA (Comprovante de Residência):
- ELEMENTOS OBRIGATÓRIOS: Endereço completo com CEP, nome do titular, empresa prestadora de serviço
- TIPOS: Conta de luz (Enel, Equatorial, CPFL, Cemig), água (Sabesp, Saneago, Cedae), telefone (Vivo, TIM, Claro, Oi), gás (Comgás, Naturgy), internet, IPTU, contrato aluguel
- CAMPOS PRINCIPAIS: Nome titular, endereço completo, CEP, data vencimento, valor, consumo (kWh, m³, etc.)
- EMPRESAS COMUNS: Enel, Equatorial, CPFL, Cemig, Sabesp, Saneago, Cedae, Vivo, TIM, Claro, Oi, Comgás, Naturgy
- LAYOUT: Formato de fatura com cabeçalho da empresa, dados de consumo, endereço destacado
- OBSERVAÇÃO: Mesmo com CPF presente, se tiver endereço e for fatura de serviço, é comprovante_residencia

CERTIDAO_CASAMENTO (Certidão de Casamento):
- ELEMENTOS OBRIGATÓRIOS: Brasão oficial do cartório, papel timbrado oficial
- TEXTOS IDENTIFICADORES: "CERTIDÃO DE CASAMENTO", nome do cartório, "OFICIAL DE REGISTRO CIVIL"
- CAMPOS PRINCIPAIS: Nomes dos cônjuges, data casamento, local cerimônia, cartório, livro, folha, termo, testemunhas
- LAYOUT: Formato oficial de certidão com texto corrido e dados organizados
- CARTÓRIO: Nome completo do cartório emissor, cidade, estado

CERTIDAO_NASCIMENTO (Certidão de Nascimento):
- ELEMENTOS OBRIGATÓRIOS: Brasão oficial do cartório, papel timbrado oficial
- TEXTOS IDENTIFICADORES: "CERTIDÃO DE NASCIMENTO", nome do cartório, "OFICIAL DE REGISTRO CIVIL"
- CAMPOS PRINCIPAIS: Nome registrado, data nascimento, local nascimento, filiação (pai/mãe), avós, cartório, livro, folha, termo
- LAYOUT: Formato oficial de certidão com texto detalhado
- FILIAÇÃO: Nomes completos dos pais obrigatórios

COMPROVANTE_ESCOLARIDADE (Diploma, Certificado de Escolaridade):
- ELEMENTOS OBRIGATÓRIOS: Timbre da instituição de ensino, assinaturas oficiais
- TEXTOS IDENTIFICADORES: Nome da instituição, "DIPLOMA", "CERTIFICADO", "HISTÓRICO ESCOLAR"
- CAMPOS PRINCIPAIS: Nome formando, curso, instituição, data conclusão, carga horária, notas/conceitos, diretor/coordenador
- TIPOS: Diploma superior, certificado técnico, histórico escolar, declaração matrícula
- LAYOUT: Formato solene com bordas decorativas, assinaturas e carimbos

CARTAO_VACINAS (Cartão de Vacinação):
- ELEMENTOS OBRIGATÓRIOS: Tabela de vacinas, datas de aplicação, carimbos de unidades de saúde
- TEXTOS IDENTIFICADORES: "CARTÃO DE VACINAÇÃO", "CADERNETA DE VACINAÇÃO", logos do SUS
- CAMPOS PRINCIPAIS: Nome, data nascimento, vacinas aplicadas, datas aplicação, lotes, unidade saúde aplicadora
- LAYOUT: Formato de cartão ou caderneta com tabelas organizadas por idade/vacina
- VACINAS: BCG, Hepatite B, Pentavalente, Pneumocócica, Rotavírus, Meningocócica, Febre Amarela, Tríplice Viral, etc.

CONTA_SALARIO (Conta Salário):
- ELEMENTOS OBRIGATÓRIOS: Logo do banco, dados completos da conta (banco, agência, conta)
- TEXTOS IDENTIFICADORES: Nome do banco, "CONTA SALÁRIO", "CONTA CORRENTE"
- CAMPOS PRINCIPAIS: Nome titular, CPF, banco, agência, número conta, tipo conta, gerente
- BANCOS: Banco do Brasil, Bradesco, Itaú, Santander, Caixa, bancos digitais
- LAYOUT: Formato de documento bancário oficial ou print de aplicativo
- OBSERVAÇÃO: Deve conter dados bancários completos (banco + agência + conta)

CARTEIRA_IDENTIDADE_PROFISSIONAL (Documento de Identificação Profissional emitido por Conselhos de Classe):
- ELEMENTOS OBRIGATÓRIOS: Foto 3x4, nome completo, número de registro profissional, CPF, órgão emissor (ex: CRC, CREA, CRM, OAB), assinatura do profissional, assinatura ou carimbo do conselho, brasão da república ou logotipo do conselho.
- CARACTERÍSTICAS: Formato pode ser horizontal ou vertical, estrutura semelhante a uma identidade oficial. Cores e layout variam conforme o conselho (azul, branco, verde, etc.). Pode conter QR Code ou selo de autenticação. Documento impresso em papel especial ou cartão rígido, com dados organizados.
- AUSÊNCIA DE: Dados de veículos (como na CNH), informações eleitorais, registros militares, comprovantes de endereço ou dados bancários. Não possui estrutura de contratos como a CTPS.
- USO COMUM: Utilizado para comprovação legal da habilitação do profissional em sua área regulamentada (advocacia, medicina, contabilidade, engenharia, etc.) e apresentação em instituições públicas e privadas.

CERTIFICADOS_CURSOS (Certificados de Cursos e NRs):
- ELEMENTOS OBRIGATÓRIOS: Timbre da instituição de ensino ou empresa, assinatura do responsável pelo curso, carimbos institucionais (quando houver), carga horária, nome do curso.
- TEXTOS IDENTIFICADORES: "CERTIFICADO", "DECLARAÇÃO", "CERTIFICAMOS", nome da instituição/empresa, tipo do curso, "carga horária", "concluiu", "participou", "com êxito", "aproveitamento", "ministrado por".
- TIPOS: Certificados de NRs (NR-10, NR-35, NR-33), primeiros socorros, brigada de incêndio, cursos técnicos, capacitações profissionais, treinamentos internos, cursos livres.
- CAMPOS PRINCIPAIS: Nome do participante, nome do curso, carga horária (em horas), data de conclusão, nota/conceito, nome e cargo do instrutor/responsável, CNPJ ou dados da instituição.
- LAYOUT: Formato horizontal ou vertical, aparência formal, margens decorativas ou bordas, geralmente com logos da instituição no cabeçalho. Pode conter QR Code para validação.
- CORES: Variedade de cores, normalmente azul, verde ou cinza; uso frequente de brasões ou logos institucionais em destaque.
- OBSERVAÇÃO: Mesmo que haja termos como "digital" ou "validação eletrônica", se o texto central estiver relacionado à conclusão ou participação em cursos, deve ser classificado como certificados_cursos.

FOTO_3X4 (Foto oficial 3x4):
- ELEMENTOS OBRIGATÓRIOS: Apenas o rosto da pessoa, fundo neutro, liso e claro (branco, cinza claro ou azul claro), sem outros elementos na imagem.
- CARACTERÍSTICAS:
- Formato retrato, proporcional a 3x4 cm.
- A pessoa deve estar olhando diretamente para a câmera, com expressão neutra.
- Roupas formais ou neutras.
- Sem acessórios que cubram o rosto (óculos escuros, bonés, chapéus, máscaras).
- Iluminação uniforme e boa nitidez.
- Ombros visíveis e centralizados no enquadramento.
- AUSÊNCIA DE: Qualquer tipo de documento visível, bordas, brasões, carimbos, marcas d'água ou textos. Logotipos ou nomes de instituições.
- USO COMUM: Para documentos oficiais (RG, passaporte, CNH), crachás, carteiras de estudante ou currículos.
- IMPORTANTE: Só classifique como foto_3x4 se não houver nenhum elemento de documento ou layout institucional. Se a imagem estiver dentro de um documento (como RG ou CNH), não classifique como foto_3x4.

FOTO_ROSTO (Selfie ou foto casual do rosto):
- ELEMENTOS OBRIGATÓRIOS: Rosto da pessoa visível em primeiro plano, sem elementos de documentos ou textos ao redor.
- CARACTERÍSTICAS: Pode ser uma selfie ou uma foto espontânea.Fundo variado ou ambiente real (não precisa ser neutro). A pessoa pode estar sorrindo ou com expressão natural. Pode haver braço visível segurando o celular (em caso de selfie). Pode estar em ambientes internos ou externos.
- AUSÊNCIA DE: Documentos, bordas de papel, brasões oficiais ou qualquer marca institucional. Padrões de foto oficial como fundo branco e expressão neutra.
- USO COMUM: Validação facial, fotos de perfil, identificação visual fora de contextos formais ou documentos.
- IMPORTANTE: Só use FOTO_ROSTO se a imagem for somente da pessoa, sem nenhum documento por perto. Se houver um documento visível ao lado ou no fundo, classifique como o tipo de documento correspondente, nunca como FOTO_ROSTO.

INSTRUÇÕES CRÍTICAS PARA EVITAR CLASSIFICAÇÃO COMO "OUTROS":
1. Analise TODOS os elementos visuais: brasões, logos, layouts, cores, presença de fotos
2. Procure por textos identificadores específicos mencionados acima
3. Observe formatos de números (CPF: XXX.XXX.XXX-XX, CNPJ: XX.XXX.XXX/XXXX-XX)
4. Identifique órgãos emissores (SSP, Receita Federal, DETRAN, TRE, etc.)
5. Verifique presença/ausência de foto (RG e CNH têm, CPF e Título não têm)
6. Observe orientação do documento (CNH horizontal, RG vertical)
7. Para comprovantes de residência: foque no endereço e empresa prestadora, não apenas no CPF
8. Para conta salário: certifique-se de que há dados bancários completos
9. Se identificar qualquer elemento das características acima, NÃO classifique como "outros"
10. Seja criterioso: documentos brasileiros oficiais sempre têm elementos identificadores únicos listados acima
11. **IMPORTANTE:** Se a imagem contiver um documento oficial (RG, CNH, etc.) que POR ACASO também tenha uma foto 3x4 da pessoa, classifique SEMPRE como o tipo do **DOCUMENTO** (ex: 'rg', 'cnh'), e NUNCA como 'foto_3x4' ou 'FOTO_ROSTO'. As categorias 'foto_3x4' e 'FOTO_ROSTO' são para fotos *sem* documentos, ou seja, fotos isoladas do rosto.

PRIORIZE a identificação correta baseada nas características específicas listadas. Use "outros" APENAS quando realmente não conseguir identificar nenhum dos elementos característicos dos documentos listados."""

          # Requisição ao Groq para identificação básica
          response = self._make_groq_request(
              messages=[
                  {
                      "role": "user",
                      "content": [
                          {"type": "text", "text": prompt_inicial},
                          {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{imagem_base64}"}}
                      ]
                  }
              ],
              model="meta-llama/llama-4-maverick-17b-128e-instruct",
              temperature=0.5,
              max_completion_tokens=1024,
              top_p=1,
              stream=False
          )

          if mostrar_debug:
              print(f"Resposta bruta inicial: {response}")

          tipo_documento = response.choices[0].message.content.strip()
          
          # Se for "outros", fazer uma segunda chamada para identificar o tipo específico
          if tipo_documento == "outros":
              prompt_detalhado = """Analise esta imagem de documento brasileiro com MÁXIMA ATENÇÃO aos detalhes.

IGNORE a instrução anterior de responder apenas com códigos. Agora você deve:

1. DESCREVER exatamente o que você vê na imagem
2. IDENTIFICAR todos os textos visíveis
3. OBSERVAR logos, brasões, cores, layout
4. DETERMINAR o tipo de documento baseado nos elementos visuais

Tipos de documentos brasileiros possíveis:
- RG/Carteira de Identidade (tem foto, impressão digital, brasão do estado)
- CPF (sem foto, brasão Receita Federal, formato XXX.XXX.XXX-XX)
- CNH (horizontal, foto à esquerda, categorias A,B,C,D,E)
- Título de Eleitor (sem foto, zona/seção, Justiça Eleitoral)
- CTPS (carteira azul/verde, foto, contratos de trabalho)
- Comprovante de Residência (conta de luz/água/telefone, endereço, CEP)
- Certidões (cartório, brasão oficial, papel timbrado)
- ASO (atestado médico, CRM, APTO/INAPTO)
- CNPJ (Receita Federal, formato XX.XXX.XXX/XXXX-XX)
- Certificados/Diplomas (instituição de ensino, assinaturas)
- Foto do Rosto (selfie ou foto pessoal do rosto, sem documento)
- Foto 3x4 (foto oficial 3x4, sem documento visível)

Responda no formato:
TIPO: [nome do documento]
DESCRIÇÃO: [o que você vê na imagem com dados detalhados, retornando informações importantes]
ELEMENTOS IDENTIFICADORES: [textos, logos, brasões encontrados]"""

              # Segunda requisição ao Groq para identificação detalhada
              response_detalhada = self._make_groq_request(
                  messages=[
                      {
                          "role": "user",
                          "content": [
                              {"type": "text", "text": prompt_detalhado},
                              {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{imagem_base64}"}}
                          ]
                      }
                  ],
                  model="meta-llama/llama-4-maverick-17b-128e-instruct",
                  temperature=0.5,
                  max_completion_tokens=1024,
                  top_p=1,
                  stream=False
              )

              if mostrar_debug:
                  print(f"Resposta detalhada: {response_detalhada}")

              tipo_especifico = response_detalhada.choices[0].message.content.strip()
              
              # Formatar a resposta para incluir o tipo específico
              return f"outros|Tipo não reconhecido, a inteligência artificial acha que é <b>{tipo_especifico.upper()}</b>"
              
          return tipo_documento

      except RateLimitError as e: # Captura o erro específico de limite de taxa
          print(f"Erro de limite de taxa da Groq: {str(e)}")
          return "RATE_LIMIT_EXCEEDED" # Retorna uma string específica para o webhook
      except Exception as e:
          return f"Erro: {str(e)}"

def analisar_arquivo(caminho_arquivo, mostrar_debug=False):
  analisador = AnalisadorDocumentosGroq()
  return analisador.analisar_documento(caminho_arquivo, mostrar_debug)

if __name__ == "__main__":
  caminho = input("Digite o caminho do arquivo (imagem ou PDF): ").strip()
  resultado = analisar_arquivo(caminho, mostrar_debug=True)
  print(f"\nTipo de Documento: {resultado}")

'''