


import logging
import os
import io
from PIL import Image
from django.conf import settings
from rh.models import Documento, Candidato, TipoDocumento
from rh.utils.image_recognition import recognize_face_in_image, compare_faces, validate_image_format

logger = logging.getLogger(__name__)

class ImageProcessor:
    def __init__(self):
        pass

    def validate_face_photo(self, image_data, candidato_id=None):
        """
        Valida se a imagem é uma foto de rosto adequada (detecta uma única face).
        SEMPRE tenta fazer comparação se candidato_id for fornecido.
        
        Args:
            image_data (bytes or PIL.Image.Image): Dados da imagem ou objeto Image.
            candidato_id (int, optional): ID do candidato para comparação facial.
        Returns:
            Se candidato_id for None: tuple: (is_valid: bool, message_for_html: str, comparison_info: dict)
            Se candidato_id for fornecido: tuple: (status: str, message_for_html: str, comparison_info: dict)
            
            status pode ser: 'validado', 'recebido', 'invalido'
            O dicionário comparison_info agora incluirá 'whatsapp_message_detail' com a mensagem formatada para WhatsApp.
        """
        try:
            logger.info("🔍 Iniciando validação de foto de rosto...")
            
            # Primeiro, validar o formato da imagem
            is_valid_format, format_message, image_info = validate_image_format(image_data)
            if not is_valid_format:
                comparison_info = {
                    'comparison_attempted': False,
                    'whatsapp_message_detail': f"Erro: Formato de imagem inválido: {format_message}"
                }
                logger.error(f"❌ Formato de imagem inválido: {format_message}")
                return 'invalido', format_message, comparison_info
            
            logger.info(f"✅ Formato de imagem válido: {image_info}")
            
            # Detectar faces na imagem
            success, message, faces_info = recognize_face_in_image(image_data)

            # Inicializa comparison_info com valores padrão para falha de detecção
            comparison_info = {
                'comparison_attempted': False,
                'comparison_successful': False,
                'faces_match': False,
                'comparison_message': message,
                'face_count': len(faces_info) if faces_info else 0,
                'image_info': image_info,
                'whatsapp_message_detail': f"❌ A foto enviada não atende aos requisitos:\n*{message}*" # Default WhatsApp message for general failure
            }

            if not success:
                logger.error(f"❌ Falha na detecção de faces: {message}")
                return 'invalido', message, comparison_info
            
            if len(faces_info) == 0:
                error_msg = "Nenhuma face detectada na imagem. Certifique-se de que a foto mostra claramente o rosto da pessoa."
                comparison_info['whatsapp_message_detail'] = f"❌ A foto enviada não atende aos requisitos:\n*{error_msg}*"
                logger.warning(f"❌ {error_msg}")
                return 'invalido', error_msg, comparison_info
            elif len(faces_info) > 1:
                logger.info(f"ℹ️ Múltiplas faces detectadas ({len(faces_info)}). Tentando comparação com todas as faces.")
            else:
                logger.info("✅ Foto de rosto validada - uma única face detectada.")

            # Se candidato_id não foi fornecido, retorna apenas validação básica
            if candidato_id is None:
                final_message_html = "Foto de rosto validada com sucesso."
                whatsapp_message_md = "✅ Foto de rosto validada com sucesso!"
                comparison_info['whatsapp_message_detail'] = whatsapp_message_md
                logger.info("✅ Validação concluída sem comparação (candidato_id não fornecido).")
                return 'validado', final_message_html, comparison_info

            # SEMPRE fazer comparação quando candidato_id for fornecido
            logger.info(f"🔄 Iniciando comparação facial OBRIGATÓRIA para candidato ID: {candidato_id}")
            comparison_successful, comparison_message_plain, faces_match, doc_name_clean, certainty_percent = self.compare_face_with_documents(candidato_id, image_data)
            
            # Atualiza comparison_info com os resultados da comparação
            comparison_info.update({
                'comparison_attempted': True,
                'comparison_successful': comparison_successful,
                'faces_match': faces_match,
                'comparison_message': comparison_message_plain, # Mensagem plain text da comparação
                'doc_name_clean': doc_name_clean,
                'certainty_percent': certainty_percent
            })
            
            if comparison_successful:
                if faces_match:
                    final_message_html = f"<br>✅ Foto do rosto recebida e validada com sucesso!<br>Identidade confirmada através do <b>{doc_name_clean}</b> com <b>{certainty_percent:.0f}%</b> de certeza conforme a <b>Inteligência artificial</b>."
#                    final_message_html = f"✅ IDENTIDADE CONFIRMADA! {comparison_message_plain}"
                    whatsapp_message_md = f"✅ Foto do rosto recebida e validada com sucesso!\n\nIdentidade confirmada através do *{doc_name_clean}* com *{certainty_percent:.0f}%* de certeza conforme a *Inteligência artificial*."
                    comparison_info['whatsapp_message_detail'] = whatsapp_message_md
                    logger.info(f"✅ SUCESSO TOTAL: {final_message_html}")
                    return 'validado', final_message_html, comparison_info
                else: # comparison_successful and not faces_match (face detected, but identity not confirmed)
                    # HTML para observações (como solicitado pelo usuário)
                    html_obs_message = comparison_message_plain.replace('Identidade NÃO confirmada!', '<b>Foto inválida!</b><br>Identidade <b>NÃO</b> confirmada!')
                    html_obs_message = html_obs_message.replace('Rosto NÃO corresponde ao', '<br><b>Rosto NÃO corresponde ao')
                    html_obs_message = html_obs_message.replace('com ', 'com ') + '</b>'
                    
                    # Markdown para WhatsApp (novo formato)
                    whatsapp_md_message = f"*Identidade NÃO confirmada!*\nRosto NÃO corresponde ao *{doc_name_clean}* com *{certainty_percent:.0f}%* de certeza conforme a *Inteligência artificial*"
                    
                    comparison_info['whatsapp_message_detail'] = whatsapp_md_message
                    
                    logger.warning(f"⚠️ PROBLEMA DE IDENTIDADE: {html_obs_message}")
                    return 'invalido', html_obs_message, comparison_info
            else: # comparison not successful (e.g., no document to compare, or internal error in comparison)
                # Alterado para retornar 'recebido' (foto em si é válida), mas com mensagem de não comparação
                final_message_html = f"ℹ️ Foto de rosto recebida. Não foi possível comparar a identidade: {comparison_message_plain}"
                whatsapp_md_message = f"ℹ️ Foto de rosto recebida. Não foi possível comparar a identidade: {comparison_message_plain}"
                comparison_info['whatsapp_message_detail'] = whatsapp_md_message
                logger.info(f"ℹ️ FOTO RECEBIDA, SEM COMPARAÇÃO POSSÍVEL: {final_message_html}")
                return 'recebido', final_message_html, comparison_info # Retorna 'recebido' para indicar que a foto é válida, mas a identidade não foi confirmada

        except Exception as e:
            logger.error(f"❌ Erro crítico ao validar foto de rosto: {e}", exc_info=True)
            error_msg = f"Erro interno ao validar foto de rosto: {str(e)}"
            comparison_info = {
                'comparison_attempted': False,
                'whatsapp_message_detail': f"❌ Erro interno ao validar foto de rosto: {str(e)}"
            }
            return 'invalido', error_msg, comparison_info

    def validate_face_photo_simple(self, image_data):
        """
        Versão simplificada que retorna apenas 2 valores para compatibilidade com código existente.
        Args:
            image_data (bytes or PIL.Image.Image): Dados da imagem ou objeto Image.
        Returns:
            tuple: (is_valid: bool, message: str)
        """
        # Chama a versão completa e converte o status para boolean
        status, message, _ = self.validate_face_photo(image_data)
        is_valid = status in ['validado', 'recebido']  # Considera tanto validado quanto recebido como "válido" para compatibilidade
        return is_valid, message

    def validate_face_photo_with_comparison(self, image_data, candidato_id):
        """
        Versão que SEMPRE faz comparação com documentos existentes.
        Args:
            image_data (bytes or PIL.Image.Image): Dados da imagem ou objeto Image.
            candidato_id (int): ID do candidato para comparação facial.
        Returns:
            tuple: (status: str, message_for_html: str, comparison_info: dict)
        """
        if candidato_id is None:
            logger.error("❌ candidato_id é obrigatório para comparação facial!")
            comparison_info = {
                'comparison_attempted': False,
                'whatsapp_message_detail': "ID do candidato é obrigatório para comparação facial."
            }
            return 'invalido', "ID do candidato é obrigatório para comparação facial.", comparison_info
        
        return self.validate_face_photo(image_data, candidato_id)

    def compare_face_with_documents(self, candidato_id, face_image_data):
        """
        Compara o rosto da 'FOTO_ROSTO' com rostos em documentos existentes do candidato.
        Prioriza documentos que normalmente contêm fotos: CNH, RG, foto_3x4.
        Args:
            candidato_id (int): ID do candidato.
            face_image_data (bytes or PIL.Image): Dados da imagem da 'FOTO_ROSTO' a ser comparada.
        Returns:
            tuple: (comparison_successful: bool, message: str, match: bool, doc_name_clean: str, certainty_percent: float)
        """
        try:
            candidato = Candidato.objects.get(id=candidato_id)
            logger.info(f"🔍 INICIANDO COMPARAÇÃO FACIAL para candidato {candidato.nome} (ID: {candidato.id}).")

            document_types_priority = [
                'cnh', 'rg', 'foto_3x4', 'cpf', 'titulo_eleitor', 
                'ctps', 'certificado_reservista'
            ]
            
            # Extrair encoding da foto de rosto enviada
            logger.info("📸 Extraindo face da foto de rosto enviada...")
            success_face, msg_face, faces_face_photo = recognize_face_in_image(face_image_data)
            if not success_face or not faces_face_photo:
                logger.error(f"❌ ERRO: Não foi possível detectar face na foto de rosto: {msg_face}")
                return False, f"Não foi possível detectar rosto na foto enviada: {msg_face}", False, "", 0.0
            
            logger.info(f"✅ {len(faces_face_photo)} face(s) extraída(s) da foto de rosto com sucesso.")

            # Contar documentos disponíveis para comparação
            total_docs_found = 0
            docs_with_faces = 0

            # Buscar documentos do candidato na ordem de prioridade
            for doc_type_name in document_types_priority:
                try:
                    logger.info(f"🔍 Procurando documento do tipo: {doc_type_name.upper()}")
                    tipo_documento = TipoDocumento.objects.get(nome__iexact=doc_type_name)
                    
                    documentos = Documento.objects.filter(
                        candidato=candidato,
                        tipo=tipo_documento,
                        status='validado'  # Apenas documentos já validados
                    )

                    if documentos.exists():
                        logger.info(f"📄 ENCONTRADOS {documentos.count()} documento(s) do tipo {doc_type_name.upper()}")
                        
                        for documento in documentos:
                            if documento.arquivo:
                                total_docs_found += 1
                                logger.info(f"📄 ANALISANDO DOCUMENTO: {doc_type_name.upper()} (ID: {documento.id})")
                                document_file_path = os.path.join(settings.MEDIA_ROOT, documento.arquivo.name)
                                
                                if not os.path.exists(document_file_path):
                                    logger.warning(f"❌ Arquivo físico não encontrado: {document_file_path}")
                                    continue

                                logger.info(f"📁 Analisando arquivo: {document_file_path}")
                                
                                # Extrair encoding do documento
                                success_doc, msg_doc, faces_doc = recognize_face_in_image(document_file_path)
                                
                                if success_doc and faces_doc:
                                    docs_with_faces += 1
                                    logger.info(f"✅ {len(faces_doc)} face(s) extraída(s) do {doc_type_name.upper()} (ID: {documento.id}) com sucesso.")
                                    
                                    for i, face_photo in enumerate(faces_face_photo):
                                        for j, face_doc in enumerate(faces_doc):
                                            logger.info(f"⚖️ COMPARANDO face {i+1} da foto vs face {j+1} do {doc_type_name.upper()} (ID: {documento.id})")
                                            match, distance = compare_faces(face_photo['encoding'], face_doc['encoding'])
                                            
                                            # Calcular porcentagem de certeza (quanto menor a distância, maior a certeza)
                                            certainty_percent = max(0, min(100, round((1 - distance) * 100, 2)))

                                            # Nome do documento limpo para uso em mensagens
                                            doc_name_clean = doc_type_name.upper()

                                            if match:
                                                logger.info(f"🎉 COMPARAÇÃO FACIAL BEM-SUCEDIDA: Face {i+1} da foto CORRESPONDE à face {j+1} do {doc_name_clean}!")
                                                logger.info(f"📊 Distância: {distance:.4f} (tolerância: 0.6) (certeza de {certainty_percent:.0f}%)")
                                                return True, f"Identidade confirmada através do {doc_name_clean} (certeza de {certainty_percent:.0f}%)", True, doc_name_clean, certainty_percent
                                            else:
                                                logger.debug(f"🔍 Face {i+1} da foto NÃO corresponde à face {j+1} do {doc_type_name.upper()} - distância: {distance:.4f}")
                                else:
                                    logger.warning(f"⚠️ Nenhuma face detectada no documento {doc_type_name.upper()} (ID: {documento.id}): {msg_doc}")
                    else:
                        logger.info(f"📄 Documento {doc_type_name.upper()} não encontrado ou não validado.")
                        
                except TipoDocumento.DoesNotExist:
                    logger.debug(f"⚠️ Tipo de documento '{doc_type_name}' não existe no banco de dados.")
                except Exception as e:
                    logger.error(f"❌ Erro ao processar documento {doc_type_name}: {e}", exc_info=True)

            # Resumo da tentativa de comparação
            logger.info(f"📊 RESUMO DA COMPARAÇÃO:")
            logger.info(f"   - Documentos encontrados: {total_docs_found}")
            logger.info(f"   - Documentos com faces detectáveis: {docs_with_faces}")
            
            if total_docs_found == 0:
                logger.warning("ℹ️ NENHUM documento adequado encontrado para comparação.")
                return False, "<br>Nenhum documento adequado (CNH/RG/Foto 3x4 validado) encontrado para comparação", False, "", 0.0
            elif docs_with_faces == 0:
                logger.warning("ℹ️ Documentos encontrados, mas NENHUM com face detectável.")
                return False, f"<br>Encontrados {total_docs_found} documento(s), mas nenhum com rosto detectável para comparação", False, "", 0.0
            else:
                logger.warning("ℹ️ Comparação realizada, mas nenhuma correspondência encontrada.")
#                return False, f"Comparação realizada com {docs_with_faces} documento(s), mas nenhuma correspondência de identidade encontrada", False, "", 0.0
                return False, (f"<br>Incompatibilidade facial: <b>{certainty_percent:.0f}%</b> (mín. 60%). {docs_with_faces} doc(s) comparado(s). <b>Revisão manual necessária.</b>"), False, "", 0.0

        except Candidato.DoesNotExist:
            logger.error(f"❌ ERRO CRÍTICO: Candidato com ID {candidato_id} não encontrado!")
            return False, "Candidato não encontrado no sistema.", False, "", 0.0
        except Exception as e:
            logger.critical(f"❌ ERRO CRÍTICO na comparação facial: {e}", exc_info=True)
            return False, f"Erro interno crítico ao comparar rostos: {str(e)}", False, "", 0.0

    def get_candidate_documents_summary(self, candidato_id):
        """
        Retorna um resumo dos documentos do candidato para debug.
        """
        try:
            candidato = Candidato.objects.get(id=candidato_id)
            documentos = Documento.objects.filter(candidato=candidato)
            
            summary = {
                'candidato_nome': candidato.nome,
                'total_documentos': documentos.count(),
                'documentos_validados': documentos.filter(status='validado').count(),
                'tipos_disponiveis': []
            }
            
            for doc in documentos.filter(status='validado'):
                summary['tipos_disponiveis'].append({
                    'tipo': doc.tipo.nome,
                    'arquivo': doc.arquivo.name if doc.arquivo else None,
                    'data_validacao': doc.data_validacao
                })
            
            logger.info(f"📋 Resumo de documentos para candidato {candidato_id}: {summary}")
            return summary
            
        except Exception as e:
            logger.error(f"Erro ao obter resumo de documentos: {e}")
            return {}










'''
import logging
import os
import io
from PIL import Image
from django.conf import settings
from rh.models import Documento, Candidato, TipoDocumento
from rh.utils.image_recognition import recognize_face_in_image, compare_faces, validate_image_format

logger = logging.getLogger(__name__)

class ImageProcessor:
    def __init__(self):
        pass

    def validate_face_photo(self, image_data, candidato_id=None):
        """
        Valida se a imagem é uma foto de rosto adequada (detecta uma única face).
        SEMPRE tenta fazer comparação se candidato_id for fornecido.
        
        Args:
            image_data (bytes or PIL.Image.Image): Dados da imagem ou objeto Image.
            candidato_id (int, optional): ID do candidato para comparação facial.
        Returns:
            Se candidato_id for None: tuple: (is_valid: bool, message_for_html: str, comparison_info: dict)
            Se candidato_id for fornecido: tuple: (status: str, message_for_html: str, comparison_info: dict)
            
            status pode ser: 'validado', 'recebido', 'invalido'
            O dicionário comparison_info agora incluirá 'whatsapp_message_detail' com a mensagem formatada para WhatsApp.
        """
        try:
            logger.info("🔍 Iniciando validação de foto de rosto...")
            
            # Primeiro, validar o formato da imagem
            is_valid_format, format_message, image_info = validate_image_format(image_data)
            if not is_valid_format:
                comparison_info = {
                    'comparison_attempted': False,
                    'whatsapp_message_detail': f"Erro: Formato de imagem inválido: {format_message}"
                }
                logger.error(f"❌ Formato de imagem inválido: {format_message}")
                return 'invalido', format_message, comparison_info
            
            logger.info(f"✅ Formato de imagem válido: {image_info}")
            
            # Detectar faces na imagem
            success, message, faces_info = recognize_face_in_image(image_data)

            # Inicializa comparison_info com valores padrão para falha de detecção
            comparison_info = {
                'comparison_attempted': False,
                'comparison_successful': False,
                'faces_match': False,
                'comparison_message': message,
                'face_count': len(faces_info) if faces_info else 0,
                'image_info': image_info,
                'whatsapp_message_detail': f"❌ A foto enviada não atende aos requisitos:\n*{message}*" # Default WhatsApp message for general failure
            }

            if not success:
                logger.error(f"❌ Falha na detecção de faces: {message}")
                return 'invalido', message, comparison_info
            
            if len(faces_info) == 0:
                error_msg = "Nenhuma face detectada na imagem. Certifique-se de que a foto mostra claramente o rosto da pessoa."
                comparison_info['whatsapp_message_detail'] = f"❌ A foto enviada não atende aos requisitos:\n*{error_msg}*"
                logger.warning(f"❌ {error_msg}")
                return 'invalido', error_msg, comparison_info
            elif len(faces_info) > 1:
                error_msg = f"Múltiplas faces detectadas ({len(faces_info)}). Por favor, envie uma foto com apenas uma pessoa."
                comparison_info['whatsapp_message_detail'] = f"❌ A foto enviada não atende aos requisitos:\n*{error_msg}*"
                logger.warning(f"❌ {error_msg}")
                return 'invalido', error_msg, comparison_info
            
            logger.info("✅ Foto de rosto validada - uma única face detectada.")

            # Se candidato_id não foi fornecido, retorna apenas validação básica
            if candidato_id is None:
                final_message_html = "Foto de rosto validada com sucesso."
                whatsapp_message_md = "✅ Foto de rosto validada com sucesso!"
                comparison_info['whatsapp_message_detail'] = whatsapp_message_md
                logger.info("✅ Validação concluída sem comparação (candidato_id não fornecido).")
                return 'validado', final_message_html, comparison_info

            # SEMPRE fazer comparação quando candidato_id for fornecido
            logger.info(f"🔄 Iniciando comparação facial OBRIGATÓRIA para candidato ID: {candidato_id}")
            comparison_successful, comparison_message_plain, faces_match, doc_name_clean, certainty_percent = self.compare_face_with_documents(candidato_id, image_data)
            
            # Atualiza comparison_info com os resultados da comparação
            comparison_info.update({
                'comparison_attempted': True,
                'comparison_successful': comparison_successful,
                'faces_match': faces_match,
                'comparison_message': comparison_message_plain, # Mensagem plain text da comparação
                'doc_name_clean': doc_name_clean,
                'certainty_percent': certainty_percent
            })
            
            if comparison_successful:
                if faces_match:
                    final_message_html = f"<br>✅ Foto do rosto recebida e validada com sucesso!<br>Identidade confirmada através do <b>{doc_name_clean}</b> com <b>{certainty_percent:.0f}%</b> de certeza conforme a <b>Inteligência artificial</b>."
#                    final_message_html = f"✅ IDENTIDADE CONFIRMADA! {comparison_message_plain}"
                    whatsapp_message_md = f"✅ Foto do rosto recebida e validada com sucesso!\n\nIdentidade confirmada através do *{doc_name_clean}* com *{certainty_percent:.0f}%* de certeza conforme a *Inteligência artificial*."
                    comparison_info['whatsapp_message_detail'] = whatsapp_message_md
                    logger.info(f"✅ SUCESSO TOTAL: {final_message_html}")
                    return 'validado', final_message_html, comparison_info
                else: # comparison_successful and not faces_match (face detected, but identity not confirmed)
                    # HTML para observações (como solicitado pelo usuário)
                    html_obs_message = comparison_message_plain.replace('Identidade NÃO confirmada!', '<b>Foto inválida!</b><br>Identidade <b>NÃO</b> confirmada!')
                    html_obs_message = html_obs_message.replace('Rosto NÃO corresponde ao', '<br><b>Rosto NÃO corresponde ao')
                    html_obs_message = html_obs_message.replace('com ', 'com ') + '</b>'
                    
                    # Markdown para WhatsApp (novo formato)
                    whatsapp_md_message = f"*Identidade NÃO confirmada!*\nRosto NÃO corresponde ao *{doc_name_clean}* com *{certainty_percent:.0f}%* de certeza conforme a *Inteligência artificial*"
                    
                    comparison_info['whatsapp_message_detail'] = whatsapp_md_message
                    
                    logger.warning(f"⚠️ PROBLEMA DE IDENTIDADE: {html_obs_message}")
                    return 'invalido', html_obs_message, comparison_info
            else: # comparison not successful (e.g., no document to compare, or internal error in comparison)
                # Alterado para retornar 'recebido' (foto em si é válida), mas com mensagem de não comparação
                final_message_html = f"ℹ️ Foto de rosto recebida. Não foi possível comparar a identidade: {comparison_message_plain}"
                whatsapp_md_message = f"ℹ️ Foto de rosto recebida. Não foi possível comparar a identidade: {comparison_message_plain}"
                comparison_info['whatsapp_message_detail'] = whatsapp_md_message
                logger.info(f"ℹ️ FOTO RECEBIDA, SEM COMPARAÇÃO POSSÍVEL: {final_message_html}")
                return 'recebido', final_message_html, comparison_info # Retorna 'recebido' para indicar que a foto é válida, mas a identidade não foi confirmada

        except Exception as e:
            logger.error(f"❌ Erro crítico ao validar foto de rosto: {e}", exc_info=True)
            error_msg = f"Erro interno ao validar foto de rosto: {str(e)}"
            comparison_info = {
                'comparison_attempted': False,
                'whatsapp_message_detail': f"❌ Erro interno ao validar foto de rosto: {str(e)}"
            }
            return 'invalido', error_msg, comparison_info

    def validate_face_photo_simple(self, image_data):
        """
        Versão simplificada que retorna apenas 2 valores para compatibilidade com código existente.
        Args:
            image_data (bytes or PIL.Image.Image): Dados da imagem ou objeto Image.
        Returns:
            tuple: (is_valid: bool, message: str)
        """
        # Chama a versão completa e converte o status para boolean
        status, message, _ = self.validate_face_photo(image_data)
        is_valid = status in ['validado', 'recebido']  # Considera tanto validado quanto recebido como "válido" para compatibilidade
        return is_valid, message

    def validate_face_photo_with_comparison(self, image_data, candidato_id):
        """
        Versão que SEMPRE faz comparação com documentos existentes.
        Args:
            image_data (bytes or PIL.Image.Image): Dados da imagem ou objeto Image.
            candidato_id (int): ID do candidato para comparação facial.
        Returns:
            tuple: (status: str, message_for_html: str, comparison_info: dict)
        """
        if candidato_id is None:
            logger.error("❌ candidato_id é obrigatório para comparação facial!")
            comparison_info = {
                'comparison_attempted': False,
                'whatsapp_message_detail': "ID do candidato é obrigatório para comparação facial."
            }
            return 'invalido', "ID do candidato é obrigatório para comparação facial.", comparison_info
        
        return self.validate_face_photo(image_data, candidato_id)

    def compare_face_with_documents(self, candidato_id, face_image_data):
        """
        Compara o rosto da 'FOTO_ROSTO' com rostos em documentos existentes do candidato.
        Prioriza documentos que normalmente contêm fotos: CNH, RG, foto_3x4.
        Args:
            candidato_id (int): ID do candidato.
            face_image_data (bytes or PIL.Image): Dados da imagem da 'FOTO_ROSTO' a ser comparada.
        Returns:
            tuple: (comparison_successful: bool, message: str, match: bool, doc_name_clean: str, certainty_percent: float)
        """
        try:
            candidato = Candidato.objects.get(id=candidato_id)
            logger.info(f"🔍 INICIANDO COMPARAÇÃO FACIAL para candidato {candidato.nome} (ID: {candidato.id}).")

            # Prioridade de documentos para comparação (documentos que normalmente contêm fotos)
        #    document_types_priority = ['cnh', 'rg', 'foto_3x4']
            document_types_priority = [
                'cnh', 'rg', 'foto_3x4', 'cpf', 'comprovante_residencia',
                'titulo_eleitor', 'ctps', 'certificado_reservista',
                'certidao_nascimento_casamento'
            ]
            # Extrair encoding da foto de rosto enviada
            logger.info("📸 Extraindo face da foto de rosto enviada...")
            success_face, msg_face, faces_face_photo = recognize_face_in_image(face_image_data)
            if not success_face or not faces_face_photo:
                logger.error(f"❌ ERRO: Não foi possível detectar face na foto de rosto: {msg_face}")
                return False, f"Não foi possível detectar rosto na foto enviada: {msg_face}", False, "", 0.0
            
            face_encoding_photo = faces_face_photo[0]['encoding']
            logger.info("✅ Face extraída da foto de rosto com sucesso.")

            # Contar documentos disponíveis para comparação
            total_docs_found = 0
            docs_with_faces = 0

            # Buscar documentos do candidato na ordem de prioridade
            for doc_type_name in document_types_priority:
                try:
                    logger.info(f"🔍 Procurando documento do tipo: {doc_type_name.upper()}")
                    tipo_documento = TipoDocumento.objects.get(nome__iexact=doc_type_name)
                    documento = Documento.objects.filter(
                        candidato=candidato,
                        tipo=tipo_documento,
                        status='validado'  # Apenas documentos já validados
                    ).first()

                    if documento and documento.arquivo:
                        total_docs_found += 1
                        logger.info(f"📄 DOCUMENTO ENCONTRADO: {doc_type_name.upper()} (ID: {documento.id})")
                        document_file_path = os.path.join(settings.MEDIA_ROOT, documento.arquivo.name)
                        
                        if not os.path.exists(document_file_path):
                            logger.warning(f"❌ Arquivo físico não encontrado: {document_file_path}")
                            continue

                        logger.info(f"📁 Analisando arquivo: {document_file_path}")
                        
                        # A verificação de PDF foi movida para image_recognition.py
                        # if document_file_path.lower().endswith('.pdf'):
                        #     logger.warning(f"⚠️ Arquivo PDF ignorado para reconhecimento facial: {document_file_path}")
                        #     continue
                        
                        # Extrair encoding do documento
                        success_doc, msg_doc, faces_doc = recognize_face_in_image(document_file_path)
                        
                        if success_doc and faces_doc:
                            docs_with_faces += 1
                            face_encoding_doc = faces_doc[0]['encoding']
                            logger.info(f"✅ Face extraída do {doc_type_name.upper()} com sucesso.")
                            
                            # Fazer a comparação
                            logger.info(f"⚖️ COMPARANDO rostos: FOTO_ROSTO vs {doc_type_name.upper()}")
                            match, distance = compare_faces(face_encoding_photo, face_encoding_doc)
                            
                            # Calcular porcentagem de certeza (quanto menor a distância, maior a certeza)
                            # A porcentagem agora reflete a similaridade (1 - distância), não a certeza dentro da tolerância.
                            certainty_percent = max(0, min(100, round((1 - distance) * 100, 2)))

                            # Nome do documento limpo para uso em mensagens
                            doc_name_clean = doc_type_name.upper()

                            if match:
                                logger.info(f"🎉 COMPARAÇÃO FACIAL BEM-SUCEDIDA: Rosto da foto CORRESPONDE ao rosto no {doc_name_clean}!")
                                logger.info(f"📊 Distância: {distance:.4f} (tolerância: 0.6) (certeza de {certainty_percent:.0f})")
#                                return True, f"Identidade confirmada através do {doc_name_clean} (distância: {distance:.4f})", True, doc_name_clean, certainty_percent
                                return True, f"Identidade confirmada através do {doc_name_clean} (certeza de {certainty_percent:.0f})", True, doc_name_clean, certainty_percent
                            else:
                                logger.warning(f"🚨 COMPARAÇÃO FACIAL FALHOU: Rosto da foto NÃO corresponde ao rosto no {doc_name_clean}!")
                                logger.warning(f"📊 Distância: {distance:.4f} (tolerância: 0.6) (certeza de {certainty_percent:.0f})")
                                return True, f"Identidade NÃO confirmada! Rosto NÃO corresponde ao {doc_name_clean} com {certainty_percent:.0f}% de compatibilidade", False, doc_name_clean, certainty_percent
                        else:
                            logger.warning(f"⚠️ Nenhuma face detectada no documento {doc_type_name.upper()}: {msg_doc}")
                    else:
                        logger.info(f"📄 Documento {doc_type_name.upper()} não encontrado ou não validado.")
                        
                except TipoDocumento.DoesNotExist:
                    logger.debug(f"⚠️ Tipo de documento '{doc_type_name}' não existe no banco de dados.")
                except Exception as e:
                    logger.error(f"❌ Erro ao processar documento {doc_type_name}: {e}", exc_info=True)

            # Resumo da tentativa de comparação
            logger.info(f"📊 RESUMO DA COMPARAÇÃO:")
            logger.info(f"   - Documentos encontrados: {total_docs_found}")
            logger.info(f"   - Documentos com faces detectáveis: {docs_with_faces}")
            
            if total_docs_found == 0:
                logger.warning("ℹ️ NENHUM documento adequado encontrado para comparação.")
                return False, "Nenhum documento adequado (CNH/RG/Foto 3x4 validado) encontrado para comparação", False, "", 0.0
            elif docs_with_faces == 0:
                logger.warning("ℹ️ Documentos encontrados, mas NENHUM com face detectável.")
                return False, f"Encontrados {total_docs_found} documento(s), mas nenhum com rosto detectável para comparação", False, "", 0.0
            else:
                logger.warning("ℹ️ Comparação realizada, mas nenhuma correspondência encontrada.")
                return False, f"Comparação realizada com {docs_with_faces} documento(s), mas nenhuma correspondência de identidade encontrada", False, "", 0.0

        except Candidato.DoesNotExist:
            logger.error(f"❌ ERRO CRÍTICO: Candidato com ID {candidato_id} não encontrado!")
            return False, "Candidato não encontrado no sistema.", False, "", 0.0
        except Exception as e:
            logger.critical(f"❌ ERRO CRÍTICO na comparação facial: {e}", exc_info=True)
            return False, f"Erro interno crítico ao comparar rostos: {str(e)}", False, "", 0.0

    def get_candidate_documents_summary(self, candidato_id):
        """
        Retorna um resumo dos documentos do candidato para debug.
        """
        try:
            candidato = Candidato.objects.get(id=candidato_id)
            documentos = Documento.objects.filter(candidato=candidato)
            
            summary = {
                'candidato_nome': candidato.nome,
                'total_documentos': documentos.count(),
                'documentos_validados': documentos.filter(status='validado').count(),
                'tipos_disponiveis': []
            }
            
            for doc in documentos.filter(status='validado'):
                summary['tipos_disponiveis'].append({
                    'tipo': doc.tipo.nome,
                    'arquivo': doc.arquivo.name if doc.arquivo else None,
                    'data_validacao': doc.data_validacao
                })
            
            logger.info(f"📋 Resumo de documentos para candidato {candidato_id}: {summary}")
            return summary
            
        except Exception as e:
            logger.error(f"Erro ao obter resumo de documentos: {e}")
            return {}



'''