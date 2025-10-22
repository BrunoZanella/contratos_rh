'''import threading
import time
from django.utils import timezone
from django.db import transaction
import os
import logging
import fcntl # Para o mecanismo de lock de arquivo
import atexit # Para garantir que o lock seja liberado ao sair
import re # Para expressões regulares
from PIL import Image # Para processamento de imagem (FOTO_ROSTO)
import io # Para lidar com dados de imagem em memória

# Importações da lógica de negócio
# Importações internas para evitar circular imports no nível superior
# e garantir que os modelos e funções estejam prontos.
# Estas importações são feitas dentro das funções que as utilizam para evitar problemas
# de importação circular e garantir que o ambiente Django esteja carregado.
# from rh.models import Candidato, Documento, TipoDocumento, RegistroTempo
# from rh.utils.timeline import registrar_evento
# from rh.views import atualizar_status_candidato

from reconhecer_imagem import analisar_arquivo
from rh.utils.image_processor import ImageProcessor
from revalidar_documentos import run_revalidation_logic # Importa a função do outro script
from rh.models import Candidato, Documento, TipoDocumento, RegistroTempo

# Configura o logger para este módulo
logger = logging.getLogger(__name__)

# Intervalo de verificação em segundos (12 horas)
REVALIDATION_INTERVAL_SECONDS = 12 * 3600

# Caminho para o arquivo de lock
LOCK_FILE = "/tmp/rh_revalidation_task.lock"
_lock_file_obj = None # Variável global para manter o objeto do arquivo de lock

# Mapeamento de tipos de documento da IA para os nomes do modelo Django
MAPPING_IA_TO_MODEL = {
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
  # 🚗 CNH
  'cnh': 'cnh',
  'carteira_motorista': 'cnh',
  'carteira nacional de habilitação': 'cnh',
  'carteira_nacional_de_habilitacao': 'cnh',
  'cnh_documento': 'cnh',
  # 🏦 Contas
  'conta_salario': 'conta_salario',
  'conta_pix': 'conta_pix',
  'pix': 'conta_pix',
  'numero_conta_pix': 'numero_conta_pix',
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
  'historico_escolar': 'historico_escolar',
  # 🎖️ Cursos e Certificados
  'certificados_cursos': 'certificados_cursos',
  'certificados': 'certificados_cursos',
  'cursos': 'certificados_cursos',
  'certificados_cursos_nrs': 'certificados_cursos',
  # 💉 Vacinas
  'cartao_vacinas': 'cartao_vacinas',
  'cartao_vacinacao': 'cartao_vacinacao',
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
  'cartao_vacinacao_filhos': 'cartao_vacinacao_filhos',
  'vacinacao_filhos': 'carteira_vacinacao_filhos',
  'declaracao_matricula_filhos': 'declaracao_matricula_filhos',
  'matricula_filhos': 'declaracao_matricula_filhos',
  # 🏢 Documentos PJ
  'cnpj': 'cnpj',
  'email_contrato': 'email_contrato',
  'email': 'email_contrato',
  # 🤳 Selfie
#  'foto_rosto': 'foto_rosto',
  'FOTO_ROSTO': 'FOTO_ROSTO',
  'selfie': 'FOTO_ROSTO'
}


def acquire_lock():
  """
  Tenta adquirir um lock exclusivo no arquivo de lock.
  Retorna True se o lock foi adquirido com sucesso, False caso contrário.
  """
  global _lock_file_obj
  try:
      _lock_file_obj = open(LOCK_FILE, 'w')
      fcntl.flock(_lock_file_obj, fcntl.LOCK_EX | fcntl.LOCK_NB)
      logger.info(f"Processo {os.getpid()} adquiriu o lock do ciclo de revalidação com sucesso.")
      return True
  except IOError:
      logger.info(f"Processo {os.getpid()} falhou ao adquirir o lock: {LOCK_FILE} já existe. Outro processo provavelmente está executando o ciclo.")
      if _lock_file_obj:
          _lock_file_obj.close()
          _lock_file_obj = None
      return False

def release_lock():
  """
  Libera o lock e fecha o arquivo de lock.
  """
  global _lock_file_obj
  if _lock_file_obj:
      fcntl.flock(_lock_file_obj, fcntl.LOCK_UN)
      _lock_file_obj.close()
      _lock_file_obj = None
      logger.info(f"Processo {os.getpid()} liberou o lock do ciclo de revalidação.")
  if os.path.exists(LOCK_FILE):
      try:
          os.remove(LOCK_FILE)
      except OSError as e:
          logger.warning(f"Erro ao remover arquivo de lock {LOCK_FILE}: {e}")
 
atexit.register(release_lock)

def _process_received_documents_task(initial_run=False):
  """
  Tarefa interna que processa APENAS os documentos com status 'recebido'.
  Não agenda a próxima execução, pois é controlada pelo ciclo principal.
  """
  logger.info(f"PASSO 1: Iniciando processamento de documentos 'recebido' (initial_run={initial_run})...")
  
  try:
      # Importações internas para evitar circular imports no nível superior
      from rh.models import Candidato, Documento, TipoDocumento, RegistroTempo
      from rh.utils.timeline import registrar_evento
      from rh.views import atualizar_status_candidato

      documents_to_revalidate = Documento.objects.filter(status='recebido').select_related('candidato', 'tipo')
      
      if not documents_to_revalidate.exists():
          logger.info("Nenhum documento 'recebido' encontrado para processamento nesta rodada.")
          return

      logger.info(f"Encontrados {documents_to_revalidate.count()} documentos 'recebido' para verificar.")
      
      candidates_to_update = set()

      for doc in documents_to_revalidate:
          logger.debug(f"Verificando documento ID: {doc.id}, Tipo: {doc.tipo.nome}, Candidato: {doc.candidato.nome}")
          try:
              received_event = RegistroTempo.objects.filter(
                  documento=doc,
                  tipo_evento='documento_recebido'
              ).order_by('-data_hora').first()

              if not received_event:
                  logger.warning(f"Documento #{doc.id} ({doc.tipo.nome}) do candidato {doc.candidato.nome} não possui evento 'documento_recebido'. Pulando.")
                  continue

              time_since_received = timezone.now() - received_event.data_hora
              
              if initial_run or time_since_received.total_seconds() >= REVALIDATION_INTERVAL_SECONDS:
                  logger.info(f"Processando documento #{doc.id} ({doc.tipo.nome}) do candidato {doc.candidato.nome} (recebido há {time_since_received}).")
                  
                  with transaction.atomic():
                      processed_doc = doc
                      status_anterior_doc = processed_doc.status

                      if not processed_doc.arquivo:
                          logger.warning(f"Documento #{processed_doc.id} não possui arquivo. Pulando reconhecimento.")
                          continue
                      
                      tipo_documento_ia = None
                      observacoes_ia_detail = ""
                      try:
                          tipo_documento_ia = analisar_arquivo(processed_doc.arquivo.path)
                          logger.debug(f"Tipo de documento identificado pela IA: {tipo_documento_ia}")
                      except Exception as e:
                          logger.error(f"Erro ao chamar analisar_arquivo para documento #{processed_doc.id}: {str(e)}", exc_info=True)
                          observacoes_ia_detail = f"Erro na IA: {str(e)}"
                          tipo_documento_ia = "ERRO_PROCESSAMENTO_IA"

                      # --- INÍCIO DA LÓGICA DE TRATAMENTO DE ERRO DE LIMITE DE TAXA E TIPOS DA IA (replicado do webhook) ---
                      # 1. Trata o erro de sobrecarga (503) primeiro
                      if "Error code: 503" in str(tipo_documento_ia) or "over capacity" in str(tipo_documento_ia):
                          processed_doc.observacoes = f"Revalidação adiada: IA sobrecarregada (503) em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}. Tentaremos novamente em 25 horas."
                          processed_doc.status = 'recebido' # Mantém como recebido para ser reprocessado
                          processed_doc.data_ultima_atualizacao = timezone.now()
                          processed_doc.save()
                          registrar_evento(
                              candidato=processed_doc.candidato,
                              tipo_evento='documento_recebido', # Tipo de evento permanece recebido
                              documento=processed_doc,
                              status_anterior=status_anterior_doc, # Usa o status antes desta tentativa
                              status_novo='recebido',
                              observacoes="Documento recebido, validação adiada por sobrecarga da IA (503)."
                          )
                          logger.info(f"Documento #{processed_doc.id} validação adiada por sobrecarga da IA (503).")
                          candidates_to_update.add(processed_doc.candidato)
                          continue # Pula para o próximo documento

                      # 2. Trata o erro de limite de taxa (se for diferente do 503)
                      elif tipo_documento_ia == "RATE_LIMIT_EXCEEDED":
                          processed_doc.observacoes = f"Revalidação adiada: Limite de taxa da IA excedido em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}. Tentaremos novamente em 25 horas."
                          processed_doc.status = 'recebido' # Mantém como recebido para ser reprocessado
                          processed_doc.data_ultima_atualizacao = timezone.now()
                          processed_doc.save()
                          registrar_evento(
                              candidato=processed_doc.candidato,
                              tipo_evento='documento_recebido',
                              documento=processed_doc,
                              status_anterior=status_anterior_doc,
                              status_novo='recebido',
                              observacoes="Documento recebido, validação adiada por limite de taxa da IA."
                          )
                          logger.info(f"Documento #{processed_doc.id} validação adiada por limite de taxa da IA.")
                          candidates_to_update.add(processed_doc.candidato)
                          continue # Pula para o próximo documento

                      # 3. Trata erros gerais de processamento da IA
                      elif tipo_documento_ia == "ERRO_PROCESSAMENTO_IA":
                          processed_doc.status = 'invalido'
                          processed_doc.observacoes = f"Revalidação falhou: Erro no processamento da IA em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}. {observacoes_ia_detail}"
                          processed_doc.data_ultima_atualizacao = timezone.now()
                          processed_doc.save()
                          registrar_evento(
                              candidato=processed_doc.candidato,
                              tipo_evento='documento_invalidado',
                              documento=processed_doc,
                              status_anterior=status_anterior_doc,
                              status_novo='invalido',
                              observacoes=f"Erro no processamento da IA: {observacoes_ia_detail}"
                          )
                          logger.warning(f"Documento #{processed_doc.id} invalidado devido a erro no processamento da IA.")
                          candidates_to_update.add(processed_doc.candidato)
                          continue # Pula para o próximo documento

                      # 4. Lógica para determinar tipo_mapeado_nome e observacoes_ia_detail com base na resposta da IA
                      tipo_mapeado_nome = 'OUTROS' # Default
                      if '|' in tipo_documento_ia:
                          parts = tipo_documento_ia.split('|', 1)
                          ia_base_type = parts[0].strip().lower()
                          ia_detailed_description = parts[1].strip()
                          observacoes_ia_detail = f"IA detalhe: {ia_detailed_description}"
                          
                          if ia_base_type == 'outros':
                              match = re.search(r'<b>(.*?)<\/b>', ia_detailed_description)
                              if match:
                                  extracted_type = match.group(1).strip().lower()
                                  tipo_mapeado_nome = MAPPING_IA_TO_MODEL.get(extracted_type, 'OUTROS')
                                  if tipo_mapeado_nome == 'OUTROS':
                                      observacoes_ia_detail = f"Tipo não reconhecido pela IA: {extracted_type}. Detalhe: {ia_detailed_description}"
                              else:
                                  observacoes_ia_detail = f"Tipo não reconhecido pela IA. Detalhe: {ia_detailed_description}"
                          else:
                              tipo_mapeado_nome = MAPPING_IA_TO_MODEL.get(ia_base_type, 'OUTROS')
                              if tipo_mapeado_nome == 'OUTROS':
                                  observacoes_ia_detail = f"Tipo não reconhecido pela IA: {ia_base_type}. Detalhe: {ia_detailed_description}"
                      else: # IA retornou um tipo direto sem '|'
                          tipo_mapeado_nome = MAPPING_IA_TO_MODEL.get(tipo_documento_ia.lower(), 'OUTROS')
                          if tipo_mapeado_nome == 'OUTROS':
                              observacoes_ia_detail = f"Tipo não reconhecido pela IA: {tipo_documento_ia}"
                      # --- FIM DA LÓGICA DE TRATAMENTO DE ERRO DE LIMITE DE TAXA E TIPOS DA IA ---

                      # Tenta obter o TipoDocumento com o nome mapeado
                      # MODIFICAÇÃO AQUI: Usar filter().first() para evitar MultipleObjectsReturned
                      new_tipo_documento = TipoDocumento.objects.filter(nome__iexact=tipo_mapeado_nome).first()
                      
                      if not new_tipo_documento:
                          logger.warning(f"Tipo de documento mapeado '{tipo_mapeado_nome}' não encontrado no sistema. Usando 'OUTROS'.")
                          try:
                              new_tipo_documento = TipoDocumento.objects.get(nome__iexact='OUTROS')
                          except TipoDocumento.DoesNotExist:
                              logger.error("Tipo de documento 'OUTROS' não encontrado no sistema. Isso é um erro de configuração crítico!")
                              # Se 'OUTROS' não existe, o sistema está em um estado inconsistente.
                              # Considere levantar uma exceção ou ter um tratamento de erro mais robusto aqui.
                          observacoes_ia_detail += f"\nTipo mapeado '{tipo_mapeado_nome}' não encontrado no sistema, usando 'OUTROS'."

                      # Lógica para atualizar o tipo do documento se for 'OUTROS' e um tipo específico foi reconhecido
                      # ou se o tipo reconhecido é diferente do tipo atual do documento.
                      if (processed_doc.tipo.nome.upper() == 'OUTROS' and new_tipo_documento != processed_doc.tipo) or \
                         (new_tipo_documento != processed_doc.tipo and processed_doc.tipo.nome.upper() != 'OUTROS'):
                          
                          if processed_doc.tipo.nome.upper() == 'OUTROS' and new_tipo_documento != processed_doc.tipo:
                              # Se o documento atual é 'OUTROS' e a IA identificou um tipo específico
                              pending_doc_of_new_type = Documento.objects.filter(
                                  candidato=processed_doc.candidato,
                                  tipo=new_tipo_documento,
                                  status='pendente'
                              ).first()

                              if pending_doc_of_new_type:
                                  logger.info(f"Documento 'Outros' #{processed_doc.id} re-categorizado como '{new_tipo_documento.nome}'. Movendo arquivo para documento pendente #{pending_doc_of_new_type.id}.")
                                  old_file_path = processed_doc.arquivo.path
                                  new_file_name = os.path.basename(old_file_path)
                                  
                                  pending_doc_of_new_type.arquivo.save(new_file_name, processed_doc.arquivo.file)
                                  
                                  pending_doc_of_new_type.status = 'recebido' # Será validado abaixo
                                  pending_doc_of_new_type.data_envio = processed_doc.data_envio
                                  pending_doc_of_new_type.save()

                                  processed_doc.delete()
                                  if os.path.exists(old_file_path):
                                      try:
                                          os.remove(old_file_path)
                                          logger.info(f"Arquivo antigo {old_file_path} removido com sucesso.")
                                      except OSError as e:
                                          logger.warning(f"Erro ao remover arquivo antigo {old_file_path}: {e}")
                                  
                                  if received_event:
                                      received_event.documento = pending_doc_of_new_type
                                      received_event.observacoes = f"Documento re-categorizado de 'Outros' para '{new_tipo_documento.nome}'. Arquivo movido para este documento. (Originalmente ID: {processed_doc.id})"
                                      received_event.save()

                                  registrar_evento(
                                      candidato=processed_doc.candidato,
                                      tipo_evento='documento_removido_substituido',
                                      observacoes=f"Documento 'Outros' (ID original: {processed_doc.id}) foi re-categorizado como '{new_tipo_documento.nome}' e substituído pelo documento pendente #{pending_doc_of_new_type.id}."
                                  )
                                  
                                  processed_doc = pending_doc_of_new_type
                              else:
                                  logger.info(f"Documento 'Outros' #{processed_doc.id} re-categorizado como '{new_tipo_documento.nome}', mas nenhum documento pendente correspondente encontrado. Atualizando tipo do documento original.")
                                  processed_doc.tipo = new_tipo_documento
                                  processed_doc.save()
                                  registrar_evento(
                                      candidato=processed_doc.candidato,
                                      tipo_evento='documento_solicitado',
                                      documento=processed_doc,
                                      status_anterior=status_anterior_doc,
                                      status_novo=processed_doc.status,
                                      observacoes=f"Tipo de documento atualizado automaticamente para '{new_tipo_documento.nome}' após re-reconhecimento."
                                  )
                          else: # Se um novo tipo é reconhecido e é diferente do tipo atual do documento (não 'OUTROS')
                              logger.info(f"Documento #{processed_doc.id} re-categorizado de '{processed_doc.tipo.nome}' para '{new_tipo_documento.nome}'.")
                              processed_doc.tipo = new_tipo_documento
                              processed_doc.save()
                              registrar_evento(
                                  candidato=processed_doc.candidato,
                                  tipo_evento='documento_solicitado',
                                  documento=processed_doc,
                                  status_anterior=status_anterior_doc,
                                  status_novo=processed_doc.status,
                                  observacoes=f"Tipo de documento atualizado automaticamente para '{new_tipo_documento.nome}' após re-reconhecimento."
                              )
                      
                      # 2. Validar e atualizar status (Lógica replicada do webhook)
                      # A observação será reescrita completamente
                      processed_doc.observacoes = f"Revalidação automática em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}: "
                      processed_doc.data_ultima_atualizacao = timezone.now()

                      # Determina se o arquivo é uma imagem para validação facial
                      is_image_file = processed_doc.arquivo.name.lower().endswith(('.png', '.jpg', '.jpeg'))

                      if processed_doc.tipo.nome.upper() == 'FOTO_ROSTO' and is_image_file:
                          try:
                              with processed_doc.arquivo.open('rb') as f:
                                  image = Image.open(io.BytesIO(f.read()))
                              processor = ImageProcessor()
                              is_valid_face, face_message, comparison_info = processor.validate_face_photo_with_comparison(image, processed_doc.candidato.id)
                              
                              whatsapp_message = ""
                              admin_obs_message = ""
                              current_evento_type = ""
                              evento_obs = "" # Initialize for scope

                              if is_valid_face: # Uma face foi detectada na foto de rosto
                                  comparison_successful = comparison_info.get('comparison_successful', False)
                                  faces_match = comparison_info.get('faces_match', False)
                                  comparison_message = comparison_info.get('comparison_message', '')
                                  
                                  # Calcula a porcentagem de certeza uma vez
                                  match_distance = re.search(r'distância: (\d+\.\d+)', comparison_message)
                                  distance = float(match_distance.group(1)) if match_distance else 0.0
                                  certainty = max(0, min(100, round((1 - (distance / 0.6)) * 100, 2)))

                                  # Determina o tipo de documento comparado para as mensagens
                                  doc_match_success = re.search(r'através do (.*?)(?: \(distância:|$)', comparison_message)
                                  doc_match_failure = re.search(r'ao (.*?)(?: \(distância:|$)', comparison_message)
                                  document_type_compared_raw = "documento desconhecido" # Raw, sem negrito
                                  if doc_match_success:
                                      document_type_compared_raw = doc_match_success.group(1).strip().replace('*', '') # Remove negrito se houver
                                  elif doc_match_failure:
                                      document_type_compared_raw = doc_match_failure.group(1).strip().replace('*', '') # Remove negrito se houver
                                  
                                  # Mapeamento para nomes amigáveis no WhatsApp (com negrito se necessário)
                                  whatsapp_document_name = document_type_compared_raw
                                  if document_type_compared_raw.lower() == 'foto_3x4':
                                      whatsapp_document_name = '*da FOTO 3X4*'
                                  elif document_type_compared_raw.lower() == 'rg':
                                      whatsapp_document_name = '*do RG*'
                                  elif document_type_compared_raw.lower() == 'cnh':
                                      whatsapp_document_name = '*da CNH*'
                                  # Adicione mais mapeamentos conforme necessário

                                  if comparison_successful and faces_match: # Identidade confirmada
                                      processed_doc.status = 'validado'
                                      processed_doc.data_validacao = timezone.now()
                                      
                                      whatsapp_message = (
                                          f"✅ Foto do rosto recebida e validada com sucesso!\n\n"
                                          f"Identidade confirmada através *{whatsapp_document_name.replace('*', '')}* com *{certainty:.2f}%* de certeza." # Remove negrito para esta mensagem
                                      )
                                      admin_obs_message = (
                                          f"<br>Foto do rosto VALIDADA AUTOMATICAMENTE pela IA. "
                                          f"Identidade CONFIRMADA atraves {document_type_compared_raw.upper()}"
                                      )
                                      current_evento_type = 'documento_validado'
                                      logger.info(f"Documento #{processed_doc.id} (FOTO_ROSTO) validado automaticamente.")

                                  elif comparison_successful and not faces_match: # Face detectada, mas NÃO corresponde ao documento de comparação
                                      processed_doc.status = 'invalido' # CORREÇÃO: Mudar para inválido
                                      
                                      # Construção da mensagem do WhatsApp conforme solicitado
                                      whatsapp_message = (
                                          f"❌ A foto enviada *não* atende aos requisitos:\n"
                                          f"*Identidade NÃO confirmada!*\n"
                                          f"Rosto NÃO corresponde ao {whatsapp_document_name} com *{certainty:.2f}%* de certeza\n"
                                          f"Por favor, envie uma nova foto seguindo as orientações:\n"
                                          f"- Rosto bem iluminado\n"
                                          f"- Olhando para frente\n"
                                          f"- Sem óculos escuros ou chapéu\n"
                                          f"- Fundo neutro\n"
                                          f"- Não envie foto de documento"
                                      )
                                      
                                      # Construção da mensagem para o Admin (com HTML)
                                      admin_obs_message = (
                                          f"<b>Foto inválida!</b> <br>"
                                          f"Identidade <b>NÃO</b> confirmada! <br>"
                                          f"<b>Rosto NÃO corresponde ao {document_type_compared_raw.upper()} com {certainty:.2f}% de confiança</b>"
                                      )
                                      
                                      current_evento_type = 'documento_invalidado' # CORREÇÃO: Mudar para documento_invalidado
                                      logger.warning(f"Documento #{processed_doc.id} (FOTO_ROSTO) invalidado automaticamente: Identidade não confirmada.")
                                      
                                      # Atualiza status do candidato se a identidade não for confirmada
                                      status_anterior_candidato = processed_doc.candidato.status
                                      processed_doc.candidato.status = 'documentos_invalidos'
                                      processed_doc.candidato.save()
                                      registrar_evento(
                                          candidato=processed_doc.candidato,
                                          tipo_evento='status_candidato_atualizado',
                                          status_anterior=status_anterior_candidato,
                                          status_novo=processed_doc.candidato.status,
                                          observacoes="Status atualizado devido a foto do rosto inválida (identidade não confirmada)"
                                      )
                                  else: # is_valid_face é True, mas a comparação não foi bem-sucedida (ex: documento de comparação não encontrado, erro interno na comparação)
                                      processed_doc.status = 'invalido' # CORREÇÃO: Mudar para inválido
                                      current_evento_type = 'documento_invalidado' # CORREÇÃO: Mudar para documento_invalidado
                                      
                                      whatsapp_message = (
                                          f"⚠ ALERTA: Foto do rosto validada, mas comparação facial não realizada ou falhou: {comparison_message}. "
                                          f"Análise manual necessária."
                                      )
                                      admin_obs_message = (
                                          f"Foto do rosto validada, mas COMPARACAO FACIAL NAO REALIZADA ou FALHOU: {comparison_message}. "
                                          f"ANALISE MANUAL NECESSARIA."
                                      )
                                      
                                      logger.warning(f"Documento #{processed_doc.id} (FOTO_ROSTO) invalidado automaticamente: Comparação facial não realizada/falhou.")
                                      
                                      # Atualiza status do candidato
                                      status_anterior_candidato = processed_doc.candidato.status
                                      processed_doc.candidato.status = 'documentos_invalidos'
                                      processed_doc.candidato.save()
                                      registrar_evento(
                                          candidato=processed_doc.candidato,
                                          tipo_evento='status_candidato_atualizado',
                                          status_anterior=status_anterior_candidato,
                                          status_novo=processed_doc.candidato.status,
                                          observacoes="Status atualizado devido a foto do rosto inválida (comparação facial não realizada)"
                                      )
                              else: # is_valid_face é False (rosto não detectado ou validação básica falhou)
                                  processed_doc.status = 'invalido'
                                  current_evento_type = 'documento_invalidado'
                                  
                                  whatsapp_message = f"⚠ ALERTA: Foto inválida: {face_message}."
                                  admin_obs_message = f"Foto INVALIDA: {face_message}."
                                  
                                  logger.warning(f"Documento #{processed_doc.id} (FOTO_ROSTO) invalidado automaticamente: {face_message}")
                                  
                                  status_anterior_candidato = processed_doc.candidato.status
                                  processed_doc.candidato.status = 'documentos_invalidos'
                                  processed_doc.candidato.save()
                                  registrar_evento(
                                      candidato=processed_doc.candidato,
                                      tipo_evento='status_candidato_atualizado',
                                      status_anterior=status_anterior_candidato,
                                      status_novo=processed_doc.candidato.status,
                                      observacoes="Status atualizado devido a foto do rosto inválida"
                                  )
                          except Exception as e:
                              logger.error(f"Erro na validação facial para documento #{processed_doc.id}: {str(e)}", exc_info=True)
                              processed_doc.status = 'invalido'
                              current_evento_type = 'documento_invalidado'
                              
                              whatsapp_message = f"⚠ ERRO: Ocorreu um erro na validação facial: {str(e)}."
                              admin_obs_message = f"ERRO na validacao facial: {str(e)}."
                              
                              logger.warning(f"Documento #{processed_doc.id} (FOTO_ROSTO) invalidado devido a erro na validação facial.")

                          # Define processed_doc.observacoes (para o Admin, sem Markdown)
                          # Reescrita completa para evitar a mistura de formatações
                          processed_doc.observacoes = (
                              f"Revalidação automática em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}: "
                              f"{admin_obs_message}"
                          )
                          if observacoes_ia_detail:
                              processed_doc.observacoes += f" Detalhes da IA: {observacoes_ia_detail}"

                          # Define evento_obs (para WhatsApp/Timeline, com Markdown)
                          evento_obs = whatsapp_message
                          evento_tipo = current_evento_type # Usa o tipo de evento determinado aqui

                      elif processed_doc.tipo.nome.upper() == 'OUTROS':
                          processed_doc.status = 'invalido'
                          processed_doc.observacoes += f"Tipo de documento não reconhecido pela IA. {observacoes_ia_detail}"
                          evento_tipo = 'documento_invalidado'
                          evento_obs = "Tipo de documento não reconhecido pela IA"
                          logger.warning(f"Documento #{processed_doc.id} invalidado automaticamente: Tipo 'OUTROS'.")
                          # Atualiza status do candidato
                          status_anterior_candidato = processed_doc.candidato.status
                          processed_doc.candidato.status = 'documentos_invalidos'
                          processed_doc.candidato.save()
                          registrar_evento(
                              candidato=processed_doc.candidato,
                              tipo_evento='status_candidato_atualizado',
                              status_anterior=status_anterior_candidato,
                              status_novo=processed_doc.candidato.status,
                              observacoes="Status atualizado devido a documento inválido (tipo 'OUTROS')"
                          )
                      else:
                          # Para todos os outros tipos de documentos identificados
                          processed_doc.status = 'validado'
                          processed_doc.data_validacao = timezone.now()
                          processed_doc.observacoes += f"Documento validado automaticamente pela IA. {observacoes_ia_detail}"
                          evento_tipo = 'documento_validado'
                          evento_obs = "Validação automática pela IA"
                          logger.info(f"Documento #{processed_doc.id} validado automaticamente.")
                      
                      processed_doc.save() # Salva status e observações
                      registrar_evento(
                          candidato=processed_doc.candidato,
                          tipo_evento=evento_tipo,
                          documento=processed_doc,
                          status_anterior=status_anterior_doc, # Usa o status original
                          status_novo=processed_doc.status,
                          observacoes=evento_obs
                      )

                      # Adiciona o candidato à lista para atualização de status
                      if processed_doc.candidato:
                          candidates_to_update.add(processed_doc.candidato)

              else:
                  logger.debug(f"Documento #{doc.id} ({doc.tipo.nome}) ainda não atingiu o tempo de revalidação. Tempo restante: {REVALIDATION_INTERVAL_SECONDS - time_since_received.total_seconds():.0f} segundos.")

          except Exception as e:
              logger.error(f"Erro inesperado ao processar documento #{doc.id}: {str(e)}", exc_info=True)
              # Garante que o status do candidato seja atualizado mesmo se um documento falhar
              if doc.candidato:
                  candidates_to_update.add(doc.candidato)

      for candidate in candidates_to_update:
          try:
              atualizar_status_candidato(candidate)
              logger.info(f"Status do candidato {candidate.nome} (ID: {candidate.id}) atualizado.")
          except Exception as e:
              logger.error(f"Erro ao atualizar status do candidato {candidate.nome} (ID: {candidate.id}): {str(e)}", exc_info=True)

  except Exception as e:
      logger.critical(f"Erro crítico no processamento de documentos 'recebido': {str(e)}", exc_info=True)


def _fix_orphaned_registrotempo_records():
  """
  Verifica e corrige registros órfãos em RegistroTempo, definindo documento_id para NULL.
  Esta função é chamada ao final do ciclo de revalidação para garantir a integridade.
  """
  logger.info("Iniciando a verificação e correção de registros órfãos em RegistroTempo...")
  
  # Obtém todos os IDs de documentos válidos
  documento_ids_validos = set(Documento.objects.values_list('id', flat=True))
  
  # Encontra registros em RegistroTempo que referenciam documentos inexistentes
  registros_para_corrigir = []
  # Use .iterator() para querysets potencialmente grandes para economizar memória
  for registro in RegistroTempo.objects.all().iterator():
      if registro.documento_id is not None and registro.documento_id not in documento_ids_validos:
          registros_para_corrigir.append(registro)
          logger.warning(f"RegistroTempo ID: {registro.id} referencia Documento ID: {registro.documento_id} que não existe. Será corrigido.")
          
  if not registros_para_corrigir:
      logger.info("Nenhum registro órfão encontrado em RegistroTempo. O banco de dados está consistente.")
      return

  logger.info(f"Encontrados {len(registros_para_corrigir)} registros órfãos. Corrigindo...")
  
  with transaction.atomic(): # Garante atomicidade para as mudanças no banco de dados
      for registro in registros_para_corrigir:
          registro.documento = None  # Define a referência como nula
          registro.save()
          logger.info(f"RegistroTempo ID: {registro.id} corrigido. documento_id definido para NULL.")
          
  logger.info("Processo de correção de registros órfãos concluído.")

def run_full_revalidation_cycle(initial_run=False):
  """
  Função mestre que executa o ciclo completo de revalidação e se auto-agenda.
  1. Processa documentos 'recebido'.
  2. Chama a lógica para processar documentos 'invalido'.
  3. Agenda a si mesma para a próxima execução.
  """
  logger.info("======================================================================")
  logger.info(f"INICIANDO CICLO COMPLETO DE REVALIDAÇÃO (initial_run={initial_run})")
  logger.info("======================================================================")
  
  try:
      # PASSO 1: Processar documentos 'recebido' (lógica que estava nesta task)
      _process_received_documents_task(initial_run=initial_run)

      # PASSO 2: Chamar a lógica de revalidação de 'revalidar_documentos.py'
      logger.info("PASSO 2: Chamando 'run_revalidation_logic' para processar outros documentos (ex: inválidos)...")
      run_revalidation_logic()

  except Exception as e:
      logger.critical(f"Erro crítico durante o ciclo de revalidação completo: {str(e)}", exc_info=True)
  finally:
      
      # PASSO 3: Executar a correção de registros órfãos
      _fix_orphaned_registrotempo_records()
        
      # PASSO 3: Agendar a próxima execução do ciclo completo
      if _lock_file_obj:
          logger.info("======================================================================")
          logger.info(f"CICLO DE REVALIDAÇÃO CONCLUÍDO.")
          logger.info(f"Próximo ciclo agendado para daqui a {REVALIDATION_INTERVAL_SECONDS / 3600:.1f} horas.")
          logger.info("======================================================================")
          
          # Agenda a própria função mestre para a próxima execução.
          # 'initial_run' será False para as execuções subsequentes.
          threading.Timer(REVALIDATION_INTERVAL_SECONDS, run_full_revalidation_cycle, kwargs={'initial_run': False}).start()
      else:
          logger.info("Este processo não detém o lock, não agendando o próximo ciclo.")


def start_document_revalidation_task():
  """
  Inicia o ciclo de revalidação de documentos em um thread separado.
  Chamado uma vez quando o aplicativo Django está pronto.
  """
  if not hasattr(start_document_revalidation_task, '_task_started'):
      if acquire_lock():
          start_document_revalidation_task._task_started = True
          logger.info("Agendando a primeira execução IMEDIATA do ciclo de revalidação completo.")
          # Agenda a execução inicial do ciclo completo com um pequeno atraso.
          threading.Timer(5, lambda: run_full_revalidation_cycle(initial_run=True)).start()
      else:
          logger.info("Outro processo já adquiriu o lock. Este processo não iniciará o ciclo de revalidação.")
  else:
      logger.info("Ciclo de revalidação de documentos já agendado, ignorando nova chamada.")
'''


import threading
import time
from django.utils import timezone
from django.db import transaction
import os
import logging
import fcntl # Para o mecanismo de lock de arquivo
import atexit # Para garantir que o lock seja liberado ao sair
import re # Para expressões regulares
from PIL import Image # Para processamento de imagem (FOTO_ROSTO)
import io # Para lidar com dados de imagem em memória

# Importações da lógica de negócio
# Importações internas para evitar circular imports no nível superior
# e garantir que os modelos e funções estejam prontos.
# Estas importações são feitas dentro das funções que as utilizam para evitar problemas
# de importação circular e garantir que o ambiente Django esteja carregado.
# from rh.models import Candidato, Documento, TipoDocumento, RegistroTempo
# from rh.utils.timeline import registrar_evento
# from rh.views import atualizar_status_candidato

from reconhecer_imagem import analisar_arquivo
from rh.utils.image_processor import ImageProcessor
from revalidar_documentos import run_revalidation_logic # Importa a função do outro script
from rh.models import Candidato, Documento, TipoDocumento, RegistroTempo

# Configura o logger para este módulo
logger = logging.getLogger(__name__)

# Intervalo de verificação em segundos (12 horas)
REVALIDATION_INTERVAL_SECONDS = 6 * 3600

# Caminho para o arquivo de lock
LOCK_FILE = "/tmp/rh_revalidation_task.lock"
_lock_file_obj = None # Variável global para manter o objeto do arquivo de lock

# Mapeamento de tipos de documento da IA para os nomes do modelo Django
MAPPING_IA_TO_MODEL = {
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
  'carteira nacional de habilitação': 'cnh',
  'carteira_nacional_de_habilitacao': 'cnh',
  'cnh_documento': 'cnh',
  # 🏦 Contas
  'conta_salario': 'conta_salario',
  'conta_pix': 'conta_pix',
  'pix': 'conta_pix',
  'numero_conta_pix': 'numero_conta_pix',
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
  'historico_escolar': 'historico_escolar',
  'curriculo': 'curriculo',
  # 🎖️ Cursos e Certificados
  'certificados_cursos': 'certificados_cursos',
  'certificados': 'certificados_cursos',
  'cursos': 'certificados_cursos',
  'certificados_cursos_nrs': 'certificados_cursos',
  # 💉 Vacinas
  'cartao_vacinas': 'cartao_vacinas',
  'cartao_vacinacao': 'cartao_vacinacao',
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
  'cartao_vacinacao_filhos': 'cartao_vacinacao_filhos',
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


def acquire_lock():
  """
  Tenta adquirir um lock exclusivo no arquivo de lock.
  Retorna True se o lock foi adquirido com sucesso, False caso contrário.
  """
  global _lock_file_obj
  try:
      _lock_file_obj = open(LOCK_FILE, 'w')
      fcntl.flock(_lock_file_obj, fcntl.LOCK_EX | fcntl.LOCK_NB)
      logger.info(f"Processo {os.getpid()} adquiriu o lock do ciclo de revalidação com sucesso.")
      return True
  except IOError:
      logger.info(f"Processo {os.getpid()} falhou ao adquirir o lock: {LOCK_FILE} já existe. Outro processo provavelmente está executando o ciclo.")
      if _lock_file_obj:
          _lock_file_obj.close()
          _lock_file_obj = None
      return False

def release_lock():
  """
  Libera o lock e fecha o arquivo de lock.
  """
  global _lock_file_obj
  if _lock_file_obj:
      fcntl.flock(_lock_file_obj, fcntl.LOCK_UN)
      _lock_file_obj.close()
      _lock_file_obj = None
      logger.info(f"Processo {os.getpid()} liberou o lock do ciclo de revalidação.")
  if os.path.exists(LOCK_FILE):
      try:
          os.remove(LOCK_FILE)
      except OSError as e:
          logger.warning(f"Erro ao remover arquivo de lock {LOCK_FILE}: {e}")
 
atexit.register(release_lock)

def _process_received_documents_task(initial_run=False):
  """
  Tarefa interna que processa APENAS os documentos com status 'recebido'.
  Não agenda a próxima execução, pois é controlada pelo ciclo principal.
  """
  logger.info(f"PASSO 1: Iniciando processamento de documentos 'recebido' (initial_run={initial_run})...")
  
  try:
      # Importações internas para evitar circular imports no nível superior
      from rh.models import Candidato, Documento, TipoDocumento, RegistroTempo
      from rh.utils.timeline import registrar_evento
      from rh.views import atualizar_status_candidato

      documents_to_revalidate = Documento.objects.filter(status='recebido').select_related('candidato', 'tipo')
      
      if not documents_to_revalidate.exists():
          logger.info("Nenhum documento 'recebido' encontrado para processamento nesta rodada.")
          return

      logger.info(f"Encontrados {documents_to_revalidate.count()} documentos 'recebido' para verificar.")
      
      candidates_to_update = set()

      for doc in documents_to_revalidate:
          logger.debug(f"Verificando documento ID: {doc.id}, Tipo: {doc.tipo.nome}, Candidato: {doc.candidato.nome}")
          try:
              received_event = RegistroTempo.objects.filter(
                  documento=doc,
                  tipo_evento='documento_recebido'
              ).order_by('-data_hora').first()

              if not received_event:
                  logger.warning(f"Documento #{doc.id} ({doc.tipo.nome}) do candidato {doc.candidato.nome} não possui evento 'documento_recebido'. Pulando.")
                  continue

              time_since_received = timezone.now() - received_event.data_hora
              
#              if initial_run or time_since_received.total_seconds() >= REVALIDATION_INTERVAL_SECONDS:
              if initial_run:
                  logger.info(f"Processando documento #{doc.id} ({doc.tipo.nome}) do candidato {doc.candidato.nome} (recebido há {time_since_received}).")
                  
                  with transaction.atomic():
                      processed_doc = doc
                      status_anterior_doc = processed_doc.status

                      if not processed_doc.arquivo:
                          logger.warning(f"Documento #{processed_doc.id} não possui arquivo. Pulando reconhecimento.")
                          continue
                      
                      tipo_documento_ia = None
                      observacoes_ia_detail = ""
                      try:
                          tipo_documento_ia = analisar_arquivo(processed_doc.arquivo.path)
                          logger.debug(f"Tipo de documento identificado pela IA: {tipo_documento_ia}")
                      except Exception as e:
                          logger.error(f"Erro ao chamar analisar_arquivo para documento #{processed_doc.id}: {str(e)}", exc_info=True)
                          observacoes_ia_detail = f"Erro na IA: {str(e)}"
                          tipo_documento_ia = "ERRO_PROCESSAMENTO_IA"

                      # --- INÍCIO DA LÓGICA DE TRATAMENTO DE ERRO DE LIMITE DE TAXA E TIPOS DA IA (replicado do webhook) ---
                      # 1. Trata o erro de sobrecarga (503) primeiro
                      if "Error code: 503" in str(tipo_documento_ia) or "over capacity" in str(tipo_documento_ia):
                          processed_doc.observacoes = f"Revalidação adiada: IA sobrecarregada (503) em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}. Tentaremos novamente em 25 horas."
                          processed_doc.status = 'recebido' # Mantém como recebido para ser reprocessado
                          processed_doc.data_ultima_atualizacao = timezone.now()
                          processed_doc.save()
                          registrar_evento(
                              candidato=processed_doc.candidato,
                              tipo_evento='documento_recebido', # Tipo de evento permanece recebido
                              documento=processed_doc,
                              status_anterior=status_anterior_doc, # Usa o status antes desta tentativa
                              status_novo='recebido',
                              observacoes="Documento recebido, validação adiada por sobrecarga da IA (503)."
                          )
                          logger.info(f"Documento #{processed_doc.id} validação adiada por sobrecarga da IA (503).")
                          candidates_to_update.add(processed_doc.candidato)
                          continue # Pula para o próximo documento

                      # 2. Trata o erro de limite de taxa (se for diferente do 503)
                      elif tipo_documento_ia == "RATE_LIMIT_EXCEEDED":
                          processed_doc.observacoes = f"Revalidação adiada: Limite de taxa da IA excedido em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}. Tentaremos novamente em 25 horas."
                          processed_doc.status = 'recebido' # Mantém como recebido para ser reprocessado
                          processed_doc.data_ultima_atualizacao = timezone.now()
                          processed_doc.save()
                          registrar_evento(
                              candidato=processed_doc.candidato,
                              tipo_evento='documento_recebido',
                              documento=processed_doc,
                              status_anterior=status_anterior_doc,
                              status_novo='recebido',
                              observacoes="Documento recebido, validação adiada por limite de taxa da IA."
                          )
                          logger.info(f"Documento #{processed_doc.id} validação adiada por limite de taxa da IA.")
                          candidates_to_update.add(processed_doc.candidato)
                          continue # Pula para o próximo documento

                      # 3. Trata erros gerais de processamento da IA
                      elif tipo_documento_ia == "ERRO_PROCESSAMENTO_IA":
                          processed_doc.status = 'invalido'
                          processed_doc.observacoes = f"Revalidação falhou: Erro no processamento da IA em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}. {observacoes_ia_detail}"
                          processed_doc.data_ultima_atualizacao = timezone.now()
                          processed_doc.save()
                          registrar_evento(
                              candidato=processed_doc.candidato,
                              tipo_evento='documento_invalidado',
                              documento=processed_doc,
                              status_anterior=status_anterior_doc,
                              status_novo='invalido',
                              observacoes=f"Erro no processamento da IA: {observacoes_ia_detail}"
                          )
                          logger.warning(f"Documento #{processed_doc.id} invalidado devido a erro no processamento da IA.")
                          candidates_to_update.add(processed_doc.candidato)
                          continue # Pula para o próximo documento

                      # 4. Lógica para determinar tipo_mapeado_nome e observacoes_ia_detail com base na resposta da IA
                      tipo_mapeado_nome = 'OUTROS' # Default
                      if '|' in tipo_documento_ia:
                          parts = tipo_documento_ia.split('|', 1)
                          ia_base_type = parts[0].strip().lower()
                          ia_detailed_description = parts[1].strip()
                          observacoes_ia_detail = f"IA detalhe: {ia_detailed_description}"
                          
                          if ia_base_type == 'outros':
                              match = re.search(r'<b>(.*?)<\/b>', ia_detailed_description)
                              if match:
                                  extracted_type = match.group(1).strip().lower()
                                  tipo_mapeado_nome = MAPPING_IA_TO_MODEL.get(extracted_type, 'OUTROS')
                                  if tipo_mapeado_nome == 'OUTROS':
                                      observacoes_ia_detail = f"Tipo não reconhecido pela IA: {extracted_type}. Detalhe: {ia_detailed_description}"
                              else:
                                  observacoes_ia_detail = f"Tipo não reconhecido pela IA. Detalhe: {ia_detailed_description}"
                          else:
                              tipo_mapeado_nome = MAPPING_IA_TO_MODEL.get(ia_base_type, 'OUTROS')
                              if tipo_mapeado_nome == 'OUTROS':
                                  observacoes_ia_detail = f"Tipo não reconhecido pela IA: {ia_base_type}. Detalhe: {ia_detailed_description}"
                      else: # IA retornou um tipo direto sem '|'
                          tipo_mapeado_nome = MAPPING_IA_TO_MODEL.get(tipo_documento_ia.lower(), 'OUTROS')
                          if tipo_mapeado_nome == 'OUTROS':
                              observacoes_ia_detail = f"Tipo não reconhecido pela IA: {tipo_documento_ia}"
                      # --- FIM DA LÓGICA DE TRATAMENTO DE ERRO DE LIMITE DE TAXA E TIPOS DA IA ---

                      # Tenta obter o TipoDocumento com o nome mapeado
                      # MODIFICAÇÃO AQUI: Usar filter().first() para evitar MultipleObjectsReturned
                      new_tipo_documento = TipoDocumento.objects.filter(nome__iexact=tipo_mapeado_nome).first()
                      
                      if not new_tipo_documento:
                          logger.warning(f"Tipo de documento mapeado '{tipo_mapeado_nome}' não encontrado no sistema. Usando 'OUTROS'.")
                          try:
                              new_tipo_documento = TipoDocumento.objects.get(nome__iexact='OUTROS')
                          except TipoDocumento.DoesNotExist:
                              logger.error("Tipo de documento 'OUTROS' não encontrado no sistema. Isso é um erro de configuração crítico!")
                              # Se 'OUTROS' não existe, o sistema está em um estado inconsistente.
                              # Considere levantar uma exceção ou ter um tratamento de erro mais robusto aqui.
                          observacoes_ia_detail += f"\nTipo mapeado '{tipo_mapeado_nome}' não encontrado no sistema, usando 'OUTROS'."

                      # Lógica para atualizar o tipo do documento se for 'OUTROS' e um tipo específico foi reconhecido
                      # ou se o tipo reconhecido é diferente do tipo atual do documento.
                      if (processed_doc.tipo.nome.upper() == 'OUTROS' and new_tipo_documento != processed_doc.tipo) or \
                         (new_tipo_documento != processed_doc.tipo and processed_doc.tipo.nome.upper() != 'OUTROS'):
                          
                          if processed_doc.tipo.nome.upper() == 'OUTROS' and new_tipo_documento != processed_doc.tipo:
                              # Se o documento atual é 'OUTROS' e a IA identificou um tipo específico
                              pending_doc_of_new_type = Documento.objects.filter(
                                  candidato=processed_doc.candidato,
                                  tipo=new_tipo_documento,
                                  status='pendente'
                              ).first()

                              if pending_doc_of_new_type:
                                  logger.info(f"Documento 'Outros' #{processed_doc.id} re-categorizado como '{new_tipo_documento.nome}'. Movendo arquivo para documento pendente #{pending_doc_of_new_type.id}.")
                                  old_file_path = processed_doc.arquivo.path
                                  new_file_name = os.path.basename(old_file_path)
                                  
                                  pending_doc_of_new_type.arquivo.save(new_file_name, processed_doc.arquivo.file)
                                  
                                  pending_doc_of_new_type.status = 'recebido' # Será validado abaixo
                                  pending_doc_of_new_type.data_envio = processed_doc.data_envio
                                  pending_doc_of_new_type.save()

                                  processed_doc.delete()
                                  if os.path.exists(old_file_path):
                                      try:
                                          os.remove(old_file_path)
                                          logger.info(f"Arquivo antigo {old_file_path} removido com sucesso.")
                                      except OSError as e:
                                          logger.warning(f"Erro ao remover arquivo antigo {old_file_path}: {e}")
                                  
                                  if received_event:
                                      received_event.documento = pending_doc_of_new_type
                                      received_event.observacoes = f"Documento re-categorizado de 'Outros' para '{new_tipo_documento.nome}'. Arquivo movido para este documento. (Originalmente ID: {processed_doc.id})"
                                      received_event.save()

                                  registrar_evento(
                                      candidato=processed_doc.candidato,
                                      tipo_evento='documento_removido_substituido',
                                      observacoes=f"Documento 'Outros' (ID original: {processed_doc.id}) foi re-categorizado como '{new_tipo_documento.nome}' e substituído pelo documento pendente #{pending_doc_of_new_type.id}."
                                  )
                                  
                                  processed_doc = pending_doc_of_new_type
                              else:
                                  logger.info(f"Documento 'Outros' #{processed_doc.id} re-categorizado como '{new_tipo_documento.nome}', mas nenhum documento pendente correspondente encontrado. Atualizando tipo do documento original.")
                                  processed_doc.tipo = new_tipo_documento
                                  processed_doc.save()
                                  registrar_evento(
                                      candidato=processed_doc.candidato,
                                      tipo_evento='documento_solicitado',
                                      documento=processed_doc,
                                      status_anterior=status_anterior_doc,
                                      status_novo=processed_doc.status,
                                      observacoes=f"Tipo de documento atualizado automaticamente para '{new_tipo_documento.nome}' após re-reconhecimento."
                                  )
                          else: # Se um novo tipo é reconhecido e é diferente do tipo atual do documento (não 'OUTROS')
                              logger.info(f"Documento #{processed_doc.id} re-categorizado de '{processed_doc.tipo.nome}' para '{new_tipo_documento.nome}'.")
                              processed_doc.tipo = new_tipo_documento
                              processed_doc.save()
                              registrar_evento(
                                  candidato=processed_doc.candidato,
                                  tipo_evento='documento_solicitado',
                                  documento=processed_doc,
                                  status_anterior=status_anterior_doc,
                                  status_novo=processed_doc.status,
                                  observacoes=f"Tipo de documento atualizado automaticamente para '{new_tipo_documento.nome}' após re-reconhecimento."
                              )
                      
                      # 2. Validar e atualizar status (Lógica replicada do webhook)
                      # A observação será reescrita completamente
                      processed_doc.observacoes = f"Revalidação automática em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}: "
                      processed_doc.data_ultima_atualizacao = timezone.now()

                      # Determina se o arquivo é uma imagem para validação facial
                      is_image_file = processed_doc.arquivo.name.lower().endswith(('.png', '.jpg', '.jpeg'))

                      if processed_doc.tipo.nome.upper() == 'FOTO_ROSTO' and is_image_file:
                          try:
                              with processed_doc.arquivo.open('rb') as f:
                                  image = Image.open(io.BytesIO(f.read()))
                              processor = ImageProcessor()
                              is_valid_face, face_message, comparison_info = processor.validate_face_photo_with_comparison(image, processed_doc.candidato.id)
                              
                              whatsapp_message = ""
                              admin_obs_message = ""
                              current_evento_type = ""
                              evento_obs = "" # Initialize for scope

                              if is_valid_face: # Uma face foi detectada na foto de rosto
                                  comparison_successful = comparison_info.get('comparison_successful', False)
                                  faces_match = comparison_info.get('faces_match', False)
                                  comparison_message = comparison_info.get('comparison_message', '')
                                  
                                  # Calcula a porcentagem de certeza uma vez
                                  match_distance = re.search(r'distância: (\d+\.\d+)', comparison_message)
                                  distance = float(match_distance.group(1)) if match_distance else 0.0
                                  certainty = max(0, min(100, round((1 - (distance / 0.6)) * 100, 2)))

                                  # Determina o tipo de documento comparado para as mensagens
                                  doc_match_success = re.search(r'através do (.*?)(?: \(distância:|$)', comparison_message)
                                  doc_match_failure = re.search(r'ao (.*?)(?: \(distância:|$)', comparison_message)
                                  document_type_compared_raw = "documento desconhecido" # Raw, sem negrito
                                  if doc_match_success:
                                      document_type_compared_raw = doc_match_success.group(1).strip().replace('*', '') # Remove negrito se houver
                                  elif doc_match_failure:
                                      document_type_compared_raw = doc_match_failure.group(1).strip().replace('*', '') # Remove negrito se houver
                                  
                                  # Mapeamento para nomes amigáveis no WhatsApp (com negrito se necessário)
                                  whatsapp_document_name = document_type_compared_raw
                                  if document_type_compared_raw.lower() == 'foto_3x4':
                                      whatsapp_document_name = '*da FOTO 3X4*'
                                  elif document_type_compared_raw.lower() == 'rg':
                                      whatsapp_document_name = '*do RG*'
                                  elif document_type_compared_raw.lower() == 'cnh':
                                      whatsapp_document_name = '*da CNH*'
                                  # Adicione mais mapeamentos conforme necessário

                                  if comparison_successful and faces_match: # Identidade confirmada
                                      processed_doc.status = 'validado'
                                      processed_doc.data_validacao = timezone.now()
                                      
                                      whatsapp_message = (
                                          f"✅ Foto do rosto recebida e validada com sucesso!\n\n"
                                          f"Identidade confirmada através *{whatsapp_document_name.replace('*', '')}* com *{certainty:.2f}%* de certeza." # Remove negrito para esta mensagem
                                      )
                                      admin_obs_message = (
                                          f"<br>Foto do rosto VALIDADA AUTOMATICAMENTE pela IA. "
                                          f"Identidade CONFIRMADA atraves {document_type_compared_raw.upper()}"
                                      )
                                      current_evento_type = 'documento_validado'
                                      logger.info(f"Documento #{processed_doc.id} (FOTO_ROSTO) validado automaticamente.")

                                  elif comparison_successful and not faces_match: # Face detectada, mas NÃO corresponde ao documento de comparação
                                      processed_doc.status = 'invalido' # CORREÇÃO: Mudar para inválido
                                      
                                      # Construção da mensagem do WhatsApp conforme solicitado
                                      whatsapp_message = (
                                          f"❌ A foto enviada *não* atende aos requisitos:\n"
                                          f"*Identidade NÃO confirmada!*\n"
                                          f"Rosto NÃO corresponde ao {whatsapp_document_name} com *{certainty:.2f}%* de certeza\n"
                                          f"Por favor, envie uma nova foto seguindo as orientações:\n"
                                          f"- Rosto bem iluminado\n"
                                          f"- Olhando para frente\n"
                                          f"- Sem óculos escuros ou chapéu\n"
                                          f"- Fundo neutro\n"
                                          f"- Não envie foto de documento"
                                      )
                                      
                                      # Construção da mensagem para o Admin (com HTML)
                                      admin_obs_message = (
                                          f"<b>Foto inválida!</b> <br>"
                                          f"Identidade <b>NÃO</b> confirmada! <br>"
                                          f"<b>Rosto NÃO corresponde ao {document_type_compared_raw.upper()} com {certainty:.2f}% de confiança</b>"
                                      )
                                      
                                      current_evento_type = 'documento_invalidado' # CORREÇÃO: Mudar para documento_invalidado
                                      logger.warning(f"Documento #{processed_doc.id} (FOTO_ROSTO) invalidado automaticamente: Identidade não confirmada.")
                                      
                                      # Atualiza status do candidato se a identidade não for confirmada
                                      status_anterior_candidato = processed_doc.candidato.status
                                      processed_doc.candidato.status = 'documentos_invalidos'
                                      processed_doc.candidato.save()
                                      registrar_evento(
                                          candidato=processed_doc.candidato,
                                          tipo_evento='status_candidato_atualizado',
                                          status_anterior=status_anterior_candidato,
                                          status_novo=processed_doc.candidato.status,
                                          observacoes="Status atualizado devido a foto do rosto inválida (identidade não confirmada)"
                                      )
                                  else: # is_valid_face é True, mas a comparação não foi bem-sucedida (ex: documento de comparação não encontrado, erro interno na comparação)
                                      processed_doc.status = 'invalido' # CORREÇÃO: Mudar para inválido
                                      current_evento_type = 'documento_invalidado' # CORREÇÃO: Mudar para documento_invalidado
                                      
                                      whatsapp_message = (
                                          f"⚠ ALERTA: Foto do rosto validada, mas comparação facial não realizada ou falhou: {comparison_message}. "
                                          f"Análise manual necessária."
                                      )
                                    #   admin_obs_message = (
                                    #       f"Foto do rosto validada, mas COMPARACAO FACIAL NAO REALIZADA ou FALHOU: {comparison_message}. "
                                    #       f"ANALISE MANUAL NECESSARIA."
                                    #   )
                                      admin_obs_message = (
                                          f"{comparison_message}"
                                      )
                                      
                                      logger.warning(f"Documento #{processed_doc.id} (FOTO_ROSTO) invalidado automaticamente: Comparação facial não realizada/falhou.")
                                      
                                      # Atualiza status do candidato
                                      status_anterior_candidato = processed_doc.candidato.status
                                      processed_doc.candidato.status = 'documentos_invalidos'
                                      processed_doc.candidato.save()
                                      registrar_evento(
                                          candidato=processed_doc.candidato,
                                          tipo_evento='status_candidato_atualizado',
                                          status_anterior=status_anterior_candidato,
                                          status_novo=processed_doc.candidato.status,
                                          observacoes="Status atualizado devido a foto do rosto inválida (comparação facial não realizada)"
                                      )
                              else: # is_valid_face é False (rosto não detectado ou validação básica falhou)
                                  processed_doc.status = 'invalido'
                                  current_evento_type = 'documento_invalidado'
                                  
                                  whatsapp_message = f"⚠ ALERTA: Foto inválida: {face_message}."
                                  admin_obs_message = f"Foto INVALIDA: {face_message}."
                                  
                                  logger.warning(f"Documento #{processed_doc.id} (FOTO_ROSTO) invalidado automaticamente: {face_message}")
                                  
                                  status_anterior_candidato = processed_doc.candidato.status
                                  processed_doc.candidato.status = 'documentos_invalidos'
                                  processed_doc.candidato.save()
                                  registrar_evento(
                                      candidato=processed_doc.candidato,
                                      tipo_evento='status_candidato_atualizado',
                                      status_anterior=status_anterior_candidato,
                                      status_novo=processed_doc.candidato.status,
                                      observacoes="Status atualizado devido a foto do rosto inválida"
                                  )
                          except Exception as e:
                              logger.error(f"Erro na validação facial para documento #{processed_doc.id}: {str(e)}", exc_info=True)
                              processed_doc.status = 'invalido'
                              current_evento_type = 'documento_invalidado'
                              
                              whatsapp_message = f"⚠ ERRO: Ocorreu um erro na validação facial: {str(e)}."
                              admin_obs_message = f"ERRO na validacao facial: {str(e)}."
                              
                              logger.warning(f"Documento #{processed_doc.id} (FOTO_ROSTO) invalidado devido a erro na validação facial.")

                          # Define processed_doc.observacoes (para o Admin, sem Markdown)
                          # Reescrita completa para evitar a mistura de formatações
                          processed_doc.observacoes = (
                              f"Revalidação automática em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}: "
                              f"{admin_obs_message}"
                          )
                          if observacoes_ia_detail:
                              processed_doc.observacoes += f" Detalhes da IA: {observacoes_ia_detail}"

                          # Define evento_obs (para WhatsApp/Timeline, com Markdown)
                          evento_obs = whatsapp_message
                          evento_tipo = current_evento_type # Usa o tipo de evento determinado aqui

                      elif processed_doc.tipo.nome.upper() == 'OUTROS':
                          processed_doc.status = 'invalido'
                          processed_doc.observacoes += f"Tipo de documento não reconhecido pela IA. {observacoes_ia_detail}"
                          evento_tipo = 'documento_invalidado'
                          evento_obs = "Tipo de documento não reconhecido pela IA"
                          logger.warning(f"Documento #{processed_doc.id} invalidado automaticamente: Tipo 'OUTROS'.")
                          # Atualiza status do candidato
                          status_anterior_candidato = processed_doc.candidato.status
                          processed_doc.candidato.status = 'documentos_invalidos'
                          processed_doc.candidato.save()
                          registrar_evento(
                              candidato=processed_doc.candidato,
                              tipo_evento='status_candidato_atualizado',
                              status_anterior=status_anterior_candidato,
                              status_novo=processed_doc.candidato.status,
                              observacoes="Status atualizado devido a documento inválido (tipo 'OUTROS')"
                          )
                      else:
                          # Para todos os outros tipos de documentos identificados
                          processed_doc.status = 'validado'
                          processed_doc.data_validacao = timezone.now()
                          processed_doc.observacoes += f"Documento validado automaticamente pela IA. {observacoes_ia_detail}"
                          evento_tipo = 'documento_validado'
                          evento_obs = "Validação automática pela IA"
                          logger.info(f"Documento #{processed_doc.id} validado automaticamente.")
                      
                      processed_doc.save() # Salva status e observações
                      registrar_evento(
                          candidato=processed_doc.candidato,
                          tipo_evento=evento_tipo,
                          documento=processed_doc,
                          status_anterior=status_anterior_doc, # Usa o status original
                          status_novo=processed_doc.status,
                          observacoes=evento_obs
                      )

                      # Adiciona o candidato à lista para atualização de status
                      if processed_doc.candidato:
                          candidates_to_update.add(processed_doc.candidato)

              else:
                  logger.debug(f"Documento #{doc.id} ({doc.tipo.nome}) ainda não atingiu o tempo de revalidação. Tempo restante: {REVALIDATION_INTERVAL_SECONDS - time_since_received.total_seconds():.0f} segundos.")

          except Exception as e:
              logger.error(f"Erro inesperado ao processar documento #{doc.id}: {str(e)}", exc_info=True)
              # Garante que o status do candidato seja atualizado mesmo se um documento falhar
              if doc.candidato:
                  candidates_to_update.add(doc.candidato)

      for candidate in candidates_to_update:
          try:
              atualizar_status_candidato(candidate)
              logger.info(f"Status do candidato {candidate.nome} (ID: {candidate.id}) atualizado.")
          except Exception as e:
              logger.error(f"Erro ao atualizar status do candidato {candidate.nome} (ID: {candidate.id}): {str(e)}", exc_info=True)

  except Exception as e:
      logger.critical(f"Erro crítico no processamento de documentos 'recebido': {str(e)}", exc_info=True)



def _fix_orphaned_registrotempo_records():
  """
  Verifica e corrige registros órfãos em RegistroTempo, definindo documento_id para NULL.
  Esta função é chamada ao final do ciclo de revalidação para garantir a integridade.
  """
  logger.info("Iniciando a verificação e correção de registros órfãos em RegistroTempo...")
  
  # Obtém todos os IDs de documentos válidos
  documento_ids_validos = set(Documento.objects.values_list('id', flat=True))
  
  # Encontra registros em RegistroTempo que referenciam documentos inexistentes
  registros_para_corrigir = []
  # Use .iterator() para querysets potencialmente grandes para economizar memória
  for registro in RegistroTempo.objects.all().iterator():
      if registro.documento_id is not None and registro.documento_id not in documento_ids_validos:
          registros_para_corrigir.append(registro)
          logger.warning(f"RegistroTempo ID: {registro.id} referencia Documento ID: {registro.documento_id} que não existe. Será corrigido.")
          
  if not registros_para_corrigir:
      logger.info("Nenhum registro órfão encontrado em RegistroTempo. O banco de dados está consistente.")
      return

  logger.info(f"Encontrados {len(registros_para_corrigir)} registros órfãos. Corrigindo...")
  
  with transaction.atomic(): # Garante atomicidade para as mudanças no banco de dados
      for registro in registros_para_corrigir:
          registro.documento = None  # Define a referência como nula
          registro.save()
          logger.info(f"RegistroTempo ID: {registro.id} corrigido. documento_id definido para NULL.")
          
  logger.info("Processo de correção de registros órfãos concluído.")



def _process_invalid_documents_task():
    """
    Tarefa que processa documentos com status 'invalido' que não foram alterados via interface web
    e ainda têm tentativas de revalidação disponíveis.
    """
    logger.info("PASSO 1.5: Iniciando processamento de documentos 'invalido' para revalidação...")
    
    try:
        # Importações internas para evitar circular imports no nível superior
        from rh.models import Candidato, Documento, TipoDocumento, RegistroTempo
        from rh.utils.timeline import registrar_evento
        from rh.views import atualizar_status_candidato

        # Busca documentos inválidos que:
        # 1. Não foram invalidados via interface web (não contém "Status alterado via interface web por" nas observações)
        # 2. Ainda têm tentativas de revalidação disponíveis (tentativas_revalidacao < 5)
        invalid_documents = Documento.objects.filter(
            status='invalido',
            tentativas_revalidacao__lt=5
        ).exclude(
            observacoes__icontains='Status alterado via interface web por'
        ).exclude(
            candidato__status__in=['concluido', 'rejeitado']
        ).select_related('candidato', 'tipo')
        
        if not invalid_documents.exists():
            logger.info("Nenhum documento 'invalido' encontrado para revalidação nesta rodada.")
            return

        logger.info(f"Encontrados {invalid_documents.count()} documentos 'invalido' para tentar revalidar (excluindo candidatos concluídos/rejeitados).")
        
        candidates_to_update = set()

        for doc in invalid_documents:
            if doc.candidato.status in ['concluido', 'rejeitado']:
                logger.info(f"Pulando documento inválido #{doc.id} - candidato {doc.candidato.nome} está {doc.candidato.status}")
                continue
                
            logger.debug(f"Tentando revalidar documento ID: {doc.id}, Tipo: {doc.tipo.nome}, Candidato: {doc.candidato.nome}, Tentativas: {doc.tentativas_revalidacao}/5")
            
            try:
                with transaction.atomic():
                    # Incrementa o contador de tentativas
                    doc.tentativas_revalidacao += 1
                    doc.save(update_fields=['tentativas_revalidacao'])
                    
                    logger.info(f"Revalidando documento #{doc.id} ({doc.tipo.nome}) - Tentativa {doc.tentativas_revalidacao}/5")
                    
                    status_anterior_doc = doc.status

                    if not doc.arquivo:
                        logger.warning(f"Documento #{doc.id} não possui arquivo. Pulando revalidação.")
                        continue
                    
                    # Pula revalidação para FOTO_ROSTO se já estiver inválido
                    if doc.tipo.nome.upper() == 'FOTO_ROSTO':
                        logger.info(f"Documento 'FOTO_ROSTO' (ID: {doc.id}) está inválido e será pulado para revalidação automática.")
                        continue
                    
                    tipo_documento_ia = None
                    observacoes_ia_detail = ""
                    try:
                        tipo_documento_ia = analisar_arquivo(doc.arquivo.path)
                        logger.debug(f"Tipo de documento identificado pela IA: {tipo_documento_ia}")
                    except Exception as e:
                        logger.error(f"Erro ao chamar analisar_arquivo para documento #{doc.id}: {str(e)}", exc_info=True)
                        observacoes_ia_detail = f"Erro na IA: {str(e)}"
                        tipo_documento_ia = "ERRO_PROCESSAMENTO_IA"

                    # Trata erros da IA
                    if "Error code: 503" in str(tipo_documento_ia) or "over capacity" in str(tipo_documento_ia):
                        doc.observacoes = f"Revalidação adiada: IA sobrecarregada (503) em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}. Tentativa {doc.tentativas_revalidacao}/5."
                        doc.data_ultima_atualizacao = timezone.now()
                        doc.save()
                        logger.info(f"Documento #{doc.id} revalidação adiada por sobrecarga da IA (503).")
                        candidates_to_update.add(doc.candidato)
                        continue

                    elif tipo_documento_ia == "RATE_LIMIT_EXCEEDED":
                        doc.observacoes = f"Revalidação adiada: Limite de taxa da IA excedido em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}. Tentativa {doc.tentativas_revalidacao}/5."
                        doc.data_ultima_atualizacao = timezone.now()
                        doc.save()
                        logger.info(f"Documento #{doc.id} revalidação adiada por limite de taxa da IA.")
                        candidates_to_update.add(doc.candidato)
                        continue

                    elif tipo_documento_ia == "ERRO_PROCESSAMENTO_IA":
                        doc.observacoes = f"Revalidação falhou: Erro no processamento da IA em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}. Tentativa {doc.tentativas_revalidacao}/5. {observacoes_ia_detail}"
                        doc.data_ultima_atualizacao = timezone.now()
                        doc.save()
                        logger.warning(f"Documento #{doc.id} revalidação falhou devido a erro no processamento da IA.")
                        candidates_to_update.add(doc.candidato)
                        continue

                    # Processa o resultado da IA
                    if tipo_documento_ia and not tipo_documento_ia.startswith('outros|'):
                        # Documento foi identificado com sucesso!
                        tipo_mapeado_nome = MAPPING_IA_TO_MODEL.get(tipo_documento_ia.lower(), 'OUTROS')
                        
                        if tipo_mapeado_nome != 'OUTROS':
                            # Reseta o contador de tentativas pois foi validado com sucesso
                            doc.tentativas_revalidacao = 0
                            doc.status = 'validado'
                            doc.data_validacao = timezone.now()
                            doc.observacoes = f"Revalidação automática bem-sucedida em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}: Identificado como {tipo_documento_ia}"
                            doc.data_ultima_atualizacao = timezone.now()
                            
                            # Verifica se precisa atualizar o tipo do documento
                            new_tipo_documento = TipoDocumento.objects.filter(nome__iexact=tipo_mapeado_nome).first()
                            if new_tipo_documento and new_tipo_documento != doc.tipo:
                                doc.tipo = new_tipo_documento
                                logger.info(f"Documento #{doc.id} tipo atualizado para '{new_tipo_documento.nome}'")
                            
                            doc.save()
                            
                            registrar_evento(
                                candidato=doc.candidato,
                                tipo_evento='documento_validado',
                                documento=doc,
                                status_anterior=status_anterior_doc,
                                status_novo='validado',
                                observacoes=f"Documento revalidado automaticamente como {tipo_documento_ia}"
                            )
                            
                            logger.info(f"✅ Documento #{doc.id} revalidado com sucesso como: {tipo_documento_ia}")
                            candidates_to_update.add(doc.candidato)
                        else:
                            # Tipo ainda não reconhecido
                            doc.observacoes = f"Revalidação em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')} - Tentativa {doc.tentativas_revalidacao}/5: Tipo '{tipo_documento_ia}' não reconhecido no sistema."
                            doc.data_ultima_atualizacao = timezone.now()
                            doc.save()
                            logger.warning(f"Documento #{doc.id} ainda não foi identificado corretamente: {tipo_documento_ia}")
                            candidates_to_update.add(doc.candidato)
                    else:
                        # Ainda não conseguiu identificar (outros|...)
                        doc.observacoes = f"Revalidação em {timezone.now().strftime('%Y-%m-%d %H:%M:%S')} - Tentativa {doc.tentativas_revalidacao}/5: {tipo_documento_ia}"
                        doc.data_ultima_atualizacao = timezone.now()
                        doc.save()
                        logger.warning(f"Documento #{doc.id} ainda não identificado: {tipo_documento_ia}")
                        candidates_to_update.add(doc.candidato)

            except Exception as e:
                logger.error(f"Erro inesperado ao revalidar documento #{doc.id}: {str(e)}", exc_info=True)
                if doc.candidato:
                    candidates_to_update.add(doc.candidato)

        # Atualiza status dos candidatos afetados
        for candidate in candidates_to_update:
            try:
                atualizar_status_candidato(candidate)
                logger.info(f"Status do candidato {candidate.nome} (ID: {candidate.id}) atualizado após revalidação.")
            except Exception as e:
                logger.error(f"Erro ao atualizar status do candidato {candidate.nome} (ID: {candidate.id}): {str(e)}", exc_info=True)

    except Exception as e:
        logger.critical(f"Erro crítico no processamento de documentos 'invalido' para revalidação: {str(e)}", exc_info=True)



def run_full_revalidation_cycle(initial_run=False):
  """
  Função mestre que executa o ciclo completo de revalidação e se auto-agenda.
  1. Processa documentos 'recebido'.
  2. Chama a lógica para processar documentos 'invalido'.
  3. Agenda a si mesma para a próxima execução.
  """
  logger.info("======================================================================")
  logger.info(f"INICIANDO CICLO COMPLETO DE REVALIDAÇÃO (initial_run={initial_run})")
  logger.info("======================================================================")
  
  try:
      # PASSO 1: Processar documentos 'recebido' (lógica que estava nesta task)
      _process_received_documents_task(initial_run=initial_run)
      _process_invalid_documents_task()

      # PASSO 2: Chamar a lógica de revalidação de 'revalidar_documentos.py'
      logger.info("PASSO 2: Chamando 'run_revalidation_logic' para processar outros documentos (ex: inválidos)...")
      run_revalidation_logic()

  except Exception as e:
      logger.critical(f"Erro crítico durante o ciclo de revalidação completo: {str(e)}", exc_info=True)
  finally:
        # PASSO 3: Executar a correção de registros órfãos
        _fix_orphaned_registrotempo_records()

        # PASSO 4: Agendar a próxima execução do ciclo completo
        if _lock_file_obj:
            logger.info("======================================================================")
            logger.info(f"CICLO DE REVALIDAÇÃO CONCLUÍDO.")
            logger.info(f"Próximo ciclo agendado para daqui a {REVALIDATION_INTERVAL_SECONDS / 3600:.1f} horas.")
            logger.info("======================================================================")
            
            # Agenda a própria função mestre para a próxima execução.
            # 'initial_run' será False para as execuções subsequentes.
            threading.Timer(REVALIDATION_INTERVAL_SECONDS, run_full_revalidation_cycle, kwargs={'initial_run': False}).start()
        else:
            logger.info("Este processo não detém o lock, não agendando o próximo ciclo.")



def start_document_revalidation_task():
  """
  Inicia o ciclo de revalidação de documentos em um thread separado.
  Chamado uma vez quando o aplicativo Django está pronto.
  """
  if not hasattr(start_document_revalidation_task, '_task_started'):
      if acquire_lock():
          start_document_revalidation_task._task_started = True
          logger.info("Agendando a primeira execução IMEDIATA do ciclo de revalidação completo.")
          # Agenda a execução inicial do ciclo completo com um pequeno atraso.
          threading.Timer(5, lambda: run_full_revalidation_cycle(initial_run=True)).start()
      else:
          logger.info("Outro processo já adquiriu o lock. Este processo não iniciará o ciclo de revalidação.")
  else:
      logger.info("Ciclo de revalidação de documentos já agendado, ignorando nova chamada.")
