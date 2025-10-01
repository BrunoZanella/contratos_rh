import os
import json
import logging
from decouple import config
from groq import Groq, RateLimitError
import openai

logger = logging.getLogger(__name__)

class ConversationAI:
    def __init__(self):
        self.groq_client = Groq(api_key=config('API_KEY_GROQ'))
        self.api_key_openai = config('API_KEY_OPENAI', default='')
        self.processed_messages = set()
     
    def _make_openai_request(self, messages, model="gpt-4o", temperature=0.1, max_tokens=500):
        """Método para fazer requisições à API OpenAI como fallback"""
        try:
            logger.info("🔄 Tentando requisição à API OpenAI como fallback para conversa")
            
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
            
            logger.info("✅ Requisição à API OpenAI bem-sucedida para conversa")
            return response
            
        except Exception as e:
            logger.error(f"❌ Erro na requisição à API OpenAI para conversa: {str(e)}")
            return None

    def _make_groq_request(self, messages, model="openai/gpt-oss-120b", temperature=0.1, max_tokens=500):
        """Método para fazer requisições à API Groq"""
        try:
            logger.info("🔄 Tentando requisição à API Groq para conversa")
            response = self.groq_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            logger.info("✅ Requisição à API Groq bem-sucedida para conversa")
            return response
        except Exception as e:
            logger.error(f"❌ Erro na requisição à API Groq para conversa: {str(e)}")
            raise e

    def analyze_message(self, message_text, candidate_name, pending_documents, message_id=None):
        """
        Analisa mensagem do candidato para detectar se está dizendo que não possui algum documento
        """
        if message_id and message_id in self.processed_messages:
            logger.warning(f"[CONVERSA] Mensagem {message_id} já processada, ignorando duplicata")
            return None
        
        if message_id:
            self.processed_messages.add(message_id)
        
        logger.info(f"[CONVERSA] === ANÁLISE DE MENSAGEM ===")
        logger.info(f"[CONVERSA] Candidato: {candidate_name}")
        logger.info(f"[CONVERSA] Mensagem original: '{message_text}'")
        logger.info(f"[CONVERSA] Documentos pendentes: {[doc.tipo.get_nome_exibicao() for doc in pending_documents]}")
        
        pending_docs_info = []
        for doc in pending_documents:
            nome_exibicao = doc.tipo.get_nome_exibicao()
            nome_tecnico = doc.tipo.nome
            pending_docs_info.append(f"{nome_exibicao} (também conhecido como: {nome_tecnico})")
        
        pending_docs_list = "\n- ".join(pending_docs_info)
        
        prompt = f"""
Você é um assistente de RH que analisa mensagens de candidatos sobre documentos.

CANDIDATO: {candidate_name}
DOCUMENTOS PENDENTES:
- {pending_docs_list}

MENSAGEM DO CANDIDATO: "{message_text}"

TAREFA CRÍTICA
Identifique TODOS os documentos que o candidato está dizendo que NÃO POSSUI dentre os pendentes.
ATENÇÃO: O candidato pode mencionar MÚLTIPLOS documentos em uma única mensagem!

EXEMPLOS DE MÚLTIPLOS DOCUMENTOS:
- "não tenho CNH e certidão de casamento" → identificar AMBOS
- "não possuo RG nem CPF" → identificar AMBOS  
- "perdi minha carteira de trabalho e título de eleitor" → identificar AMBOS

ROBUSTEZ LINGUÍSTICA
- Considere variações de escrita, erros de digitação e sinônimos:
  • "currículo" ≈ curriculo, kuriculo, curriculius, curriculum
  • "CNH" ≈ cnh, carteira de motorista, habilitação, carteira de habilitação
  • "RG" ≈ rg, identidade, carteira de identidade
  • "CPF" ≈ cpf, cadastro de pessoa física
  • "certidão de nascimento" ≈ certidao nascimento, certidao de nascimento
  • "certidão de casamento" ≈ certidao casamento, certidao de casamento
  • "título de eleitor" ≈ titulo eleitor, titulo de eleitor
  • "carteira de trabalho" ≈ ctps, carteira trabalho
  • e outros equivalentes plausíveis.

CONECTORES PARA MÚLTIPLOS DOCUMENTOS:
- "e", "nem", "também não", "e também", "além disso", vírgulas, etc.

FORMATO DE SAÍDA (APENAS JSON VÁLIDO, sem texto extra):
{{
  "tem_documento_faltante": true/false,
  "documentos_faltantes": ["nome1", "nome2", "nome3"] ou [],
  "resposta_candidato": "mensagem_breve_e_profissional"
}}

REGRAS LÓGICAS
1) Se o candidato disser que não tem, não possui, perdeu, foi furtado/roubado, ou não encontra UM OU MAIS documentos, use "tem_documento_faltante": true.
2) "documentos_faltantes" deve conter TODOS os nomes de exibição listados em DOCUMENTOS PENDENTES que foram mencionados como faltantes.
3) NUNCA ignore documentos mencionados - se há múltiplos, liste TODOS.
4) Se não for possível identificar quais documentos são, use "tem_documento_faltante": false e "documentos_faltantes": [].

RESPOSTA PROFISSIONAL
- Tom cordial e conciso, confirmando TODOS os documentos identificados como faltantes.
- Se múltiplos documentos: "Registrei que você não possui: [lista completa]. Seu processo será atualizado."
- Se um documento: "Registrei que você não possui [documento]. Seu processo será atualizado."
"""

        messages = [{"role": "user", "content": prompt}]
        response = None
        
        try:
            # Tentar Groq primeiro
            response = self._make_groq_request(messages)
            
        except RateLimitError:
            logger.warning("🔄 Groq rate limit na conversa, tentando com OpenAI...")
            try:
                response = self._make_openai_request(messages)
                if response:
                    logger.info("✅ Fallback OpenAI bem-sucedido na conversa")
                else:
                    logger.error("❌ OpenAI retornou resposta vazia na conversa")
            except Exception as openai_error:
                logger.error(f"❌ Fallback OpenAI na conversa também falhou: {str(openai_error)}")
                
        except Exception as groq_error:
            logger.error(f"Erro com Groq: {groq_error}")
            try:
                logger.warning("🔄 Tentando OpenAI como fallback para erro do Groq na conversa...")
                response = self._make_openai_request(messages)
                if response:
                    logger.info("✅ Fallback OpenAI bem-sucedido após erro do Groq na conversa")
            except Exception as openai_error:
                logger.error(f"❌ Fallback OpenAI também falhou: {str(openai_error)}")
        
        if not response:
            default_response = {
                "tem_documento_faltante": False,
                "documentos_faltantes": [],
                "resposta_candidato": "Obrigado pela sua mensagem! Nossa equipe analisará e retornará em breve."
            }
            logger.info(f"[CONVERSA] Resposta padrão para '{message_text}' de {candidate_name}: {default_response}")
            return default_response
        
        try:
            if not hasattr(response, 'choices') or not response.choices:
                logger.error(f"[CONVERSA] Resposta da IA sem choices para '{message_text}'")
                raise ValueError("Resposta da IA sem choices")
            
            if not response.choices[0].message or not hasattr(response.choices[0].message, 'content'):
                logger.error(f"[CONVERSA] Resposta da IA sem content para '{message_text}'")
                raise ValueError("Resposta da IA sem content")
            
            result = response.choices[0].message.content
            
            if not result or result.strip() == "":
                logger.error(f"[CONVERSA] Resposta da IA vazia para '{message_text}' de {candidate_name}")
                logger.error(f"[CONVERSA] Response object: {response}")
                logger.error(f"[CONVERSA] Choices: {response.choices if hasattr(response, 'choices') else 'N/A'}")
                raise ValueError("Resposta da IA está vazia")
            
            result = result.strip()
            
            logger.info(f"[DEBUG] Mensagem original: '{message_text}'")
            logger.info(f"[DEBUG] Resposta bruta da IA: '{result}'")
            
            original_result = result
            
            # Tenta extrair JSON da resposta
            if "\`\`\`json" in result:
                result = result.split("\`\`\`json")[1].split("\`\`\`")[0].strip()
            elif "\`\`\`" in result:
                result = result.split("\`\`\`")[1].split("\`\`\`")[0].strip()
            elif result.startswith("\`\`\`") and result.endswith("\`\`\`"):
                result = result[3:-3].strip()
            
            # Remove possíveis caracteres extras no início/fim
            result = result.strip()
            if result.startswith("json"):
                result = result[4:].strip()
            
            if not result or result.strip() == "":
                logger.error(f"[CONVERSA] JSON extraído está vazio após limpeza para '{message_text}'")
                logger.error(f"[CONVERSA] Resposta original: '{original_result}'")
                raise ValueError("JSON extraído está vazio")
            
            logger.info(f"[DEBUG] JSON extraído: '{result}'")
            
            parsed_result = json.loads(result)
            
            if not isinstance(parsed_result, dict):
                logger.error(f"[CONVERSA] Resposta da IA não é um dict para '{message_text}': {type(parsed_result)}")
                raise ValueError("Resposta da IA não é um dicionário válido")
            
            # Garantir que tem as chaves necessárias
            if "tem_documento_faltante" not in parsed_result:
                logger.warning(f"[CONVERSA] Resposta da IA sem 'tem_documento_faltante', assumindo False")
                parsed_result["tem_documento_faltante"] = False
            
            if "resposta_candidato" not in parsed_result:
                logger.warning(f"[CONVERSA] Resposta da IA sem 'resposta_candidato', usando padrão")
                parsed_result["resposta_candidato"] = "Obrigado pela sua mensagem! Nossa equipe analisará e retornará em breve."
            
            if "documento_faltante" in parsed_result and "documentos_faltantes" not in parsed_result:
                if parsed_result["documento_faltante"]:
                    parsed_result["documentos_faltantes"] = [parsed_result["documento_faltante"]]
                else:
                    parsed_result["documentos_faltantes"] = []
                del parsed_result["documento_faltante"]
            
            if "documentos_faltantes" not in parsed_result:
                parsed_result["documentos_faltantes"] = []
            
            logger.info(f"[CONVERSA] Análise final para '{message_text}' de {candidate_name}: {parsed_result}")
            return parsed_result
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Erro ao processar resposta da IA para mensagem '{message_text}': {e}")
            logger.error(f"Conteúdo que causou erro: '{result if 'result' in locals() else 'N/A'}'")
            
            if not hasattr(self, '_tried_openai_fallback'):
                logger.warning("🔄 Tentando OpenAI como fallback após erro de processamento...")
                try:
                    self._tried_openai_fallback = True
                    fallback_response = self._make_openai_request(messages)
                    if fallback_response and hasattr(fallback_response, 'choices') and fallback_response.choices:
                        fallback_content = fallback_response.choices[0].message.content
                        if fallback_content and fallback_content.strip():
                            logger.info("✅ Fallback OpenAI retornou conteúdo válido")
                            # Recursivamente processar a resposta do OpenAI
                            delattr(self, '_tried_openai_fallback')
                            return self.analyze_message(message_text, candidate_name, pending_documents, message_id)
                except Exception as fallback_error:
                    logger.error(f"❌ Fallback OpenAI também falhou: {str(fallback_error)}")
                finally:
                    if hasattr(self, '_tried_openai_fallback'):
                        delattr(self, '_tried_openai_fallback')
            
            default_response = {
                "tem_documento_faltante": False,
                "documentos_faltantes": [],
                "resposta_candidato": "Obrigado pela sua mensagem! Nossa equipe analisará e retornará em breve."
            }
            logger.info(f"[CONVERSA] Resposta padrão após erro de processamento para '{message_text}' de {candidate_name}: {default_response}")
            return default_response
