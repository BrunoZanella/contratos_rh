
'''

#!/usr/bin/env python3
"""
Script standalone para revalidar documentos marcados como inválidos.
Execução: python revalidar_documentos.py
"""

import os
import sqlite3
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import logging # Importar o módulo logging

# Configuração do logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG) # Nível mínimo para capturar todos os logs

# Formato do log
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Handler para console (stdout)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO) # Nível para o console (INFO e acima)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Handler para arquivo de log
log_file_path = Path(__file__).parent / "revalidacao.log"
file_handler = logging.FileHandler(log_file_path)
file_handler.setLevel(logging.DEBUG) # Nível para o arquivo (DEBUG e acima)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Importa a função analisar_arquivo e verifica de onde ela vem
from reconhecer_imagem import analisar_arquivo
logger.debug(f"'analisar_arquivo' importado de: {analisar_arquivo.__module__} ({analisar_arquivo.__code__.co_filename})")

import django
from django.conf import settings

# Configura o ambiente Django APENAS se ainda não estiver configurado
if not settings.configured:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'main.settings') # Substitua 'main' pelo nome do seu projeto Django
    django.setup()

class RevalidadorDocumentos:
    def __init__(self, db_path="db.sqlite3"):
        """Inicializa o revalidador com conexão direta ao banco"""
        self.db_path = db_path
        
        # Define o diretório raiz do projeto (onde revalidar_documentos.py está)
        self.project_root = Path(__file__).parent
        # Constrói o caminho para a pasta 'media'
        self.media_root = self.project_root / "media"
        
        # Rate limits do Groq para meta-llama/llama-4-maverick-17b-128e-instruct
        self.max_requests_per_minute = 25  # Margem de segurança (30 - 5)
        self.max_tokens_per_minute = 5500  # Margem de segurança (6000 - 500)
        
        # Controle de rate limiting
        self.requests_count = 0
        self.tokens_count = 0
        self.minute_start = time.time()
        
        # Estatísticas
        self.stats = {
            'total_processados': 0,
            'validados': 0,
            'ainda_invalidos': 0,
            'erros': 0,
            'inicio': datetime.now()
        }
        
        # Verifica se o banco existe
        if not os.path.exists(self.db_path):
            logger.error(f"Banco de dados não encontrado: {self.db_path}")
            raise FileNotFoundError(f"Banco de dados não encontrado: {self.db_path}")
    
    def conectar_banco(self):
        """Cria conexão com o banco de dados"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Para acessar colunas por nome
        return conn
    
    def verificar_estrutura_banco(self):
        """Verifica e mostra a estrutura das tabelas"""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        
        # Lista todas as tabelas
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tabelas = cursor.fetchall()
        
        logger.info("📋 Tabelas encontradas no banco:")
        for tabela in tabelas:
            if 'rh_' in tabela['name']:
                logger.info(f"   - {tabela['name']}")
                
                # Mostra as colunas da tabela
                cursor.execute(f"PRAGMA table_info({tabela['name']});")
                colunas = cursor.fetchall()
                for coluna in colunas:
                    logger.info(f"     └─ {coluna['name']} ({coluna['type']})")
        
        conn.close()
    
    def aguardar_rate_limit(self):
        """Aguarda se necessário para respeitar rate limits"""
        tempo_atual = time.time()
        tempo_decorrido = tempo_atual - self.minute_start
        
        # Se passou 1 minuto, reseta os contadores
        if tempo_decorrido >= 60:
            self.requests_count = 0
            self.tokens_count = 0
            self.minute_start = tempo_atual
            return
        
        # Se atingiu o limite de requests, aguarda
        if self.requests_count >= self.max_requests_per_minute:
            tempo_espera = 60 - tempo_decorrido + 1  # +1 segundo de margem
            logger.warning(f"⏳ Rate limit atingido. Aguardando {tempo_espera:.1f} segundos...")
            time.sleep(tempo_espera)
            self.requests_count = 0
            self.tokens_count = 0
            self.minute_start = time.time()
    
    def estimar_tokens(self, texto):
        """Estimativa simples de tokens (aproximadamente 4 caracteres = 1 token)"""
        return len(texto) // 4
    
    def obter_documentos_invalidos(self, limite=None, candidato_id=None):
        """
        Obtém documentos marcados como inválidos, excluindo aqueles que foram
        invalidados manualmente (via interface web).
        """
        conn = self.conectar_banco()
        cursor = conn.cursor()
        
        query = """
        SELECT 
            d.id,
            d.arquivo,
            d.status,
            d.observacoes,
            d.tipo_id,
            d.candidato_id,
            c.nome as candidato_nome,
            t.nome as tipo_documento_nome,
            t.nome_exibicao as tipo_documento_nome_exibicao
        FROM rh_documento d
        JOIN rh_candidato c ON d.candidato_id = c.id
        JOIN rh_tipodocumento t ON d.tipo_id = t.id
        WHERE d.status = 'invalido'
        AND NOT EXISTS (
            SELECT 1
            FROM rh_registrotempo rt
            WHERE rt.documento_id = d.id
            AND rt.tipo_evento = 'documento_invalidado'
            AND rt.observacoes LIKE '%Status alterado via interface web por%'
        )
        """
        
        params = []
        
        # Filtro por candidato
        if candidato_id:
            query += " AND d.candidato_id = ?"
            params.append(candidato_id)
        
        query += " ORDER BY d.id"
        
        # Limite
        if limite:
            query += " LIMIT ?"
            params.append(limite)
        
        try:
            cursor.execute(query, params)
            documentos = cursor.fetchall()
            conn.close()
            return documentos
        except sqlite3.OperationalError as e:
            logger.error(f"❌ Erro na consulta SQL: {e}")
            logger.info("🔍 Verificando estrutura do banco...")
            conn.close()
            self.verificar_estrutura_banco()
            raise

    def _get_tipo_documento_id_by_name(self, tipo_nome):
        """Obtém o ID de TipoDocumento pelo nome (código)"""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM rh_tipodocumento WHERE nome = ?", (tipo_nome,))
        result = cursor.fetchone()
        conn.close()
        return result['id'] if result else None

    def _get_pending_document(self, candidato_id, tipo_id):
        """Busca um documento pendente para o candidato e tipo especificados."""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, arquivo, status, observacoes, tipo_id, candidato_id
            FROM rh_documento
            WHERE candidato_id = ? AND tipo_id = ? AND status = 'pendente'
            LIMIT 1
        """, (candidato_id, tipo_id))
        doc = cursor.fetchone()
        conn.close()
        return doc

    def _get_validated_document(self, candidato_id, tipo_id):
        """Busca um documento validado para o candidato e tipo especificados."""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, arquivo, status, observacoes, tipo_id, candidato_id
            FROM rh_documento
            WHERE candidato_id = ? AND tipo_id = ? AND status = 'validado'
            LIMIT 1
        """, (candidato_id, tipo_id))
        doc = cursor.fetchone()
        conn.close()
        return doc

    def atualizar_documento(self, documento_id, status, observacoes, tipo_id=None, arquivo_path=None):
        """Atualiza status, observações, opcionalmente o tipo_id e o caminho do arquivo do documento"""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        
        update_fields = []
        params = []

        if status:
            update_fields.append("status = ?")
            params.append(status)
        if observacoes is not None: # Permite observacoes vazias
            update_fields.append("observacoes = ?")
            params.append(observacoes)
        if tipo_id:
            update_fields.append("tipo_id = ?")
            params.append(tipo_id)
        if arquivo_path is not None: # Permite arquivo_path vazio (para remover)
            update_fields.append("arquivo = ?")
            params.append(arquivo_path)

        if not update_fields:
            conn.close()
            return # Nada para atualizar

        query = f"UPDATE rh_documento SET {', '.join(update_fields)} WHERE id = ?"
        params.append(documento_id)
        
        cursor.execute(query, params)
        conn.commit()
        conn.close()

    def _deletar_documento(self, documento_id):
        """Deleta um documento do banco de dados."""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rh_documento WHERE id = ?", (documento_id,))
        conn.commit()
        conn.close()

    def _registrar_evento(self, candidato_id, documento_id, tipo_evento, status_anterior, status_novo, observacoes):
        """Registra um evento na tabela rh_registrotempo"""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        
        # Tenta obter o último evento para calcular tempo_desde_evento_anterior
        tempo_desde_evento_anterior_microseconds = None 
        
        # Se for um evento de documento, busca o último evento para aquele documento
        if documento_id:
            cursor.execute("""
                SELECT data_hora FROM rh_registrotempo
                WHERE candidato_id = ? AND documento_id = ?
                ORDER BY data_hora DESC LIMIT 1
            """, (candidato_id, documento_id))
        else: # Se for um evento de candidato (sem documento específico), busca o último evento geral do candidato
            cursor.execute("""
                SELECT data_hora FROM rh_registrotempo
                WHERE candidato_id = ?
                ORDER BY data_hora DESC LIMIT 1
            """, (candidato_id,))

        ultimo_evento = cursor.fetchone()
        
        if ultimo_evento:
            ultima_data_hora_str = ultimo_evento['data_hora']
            try:
                # Tenta parsear com microssegundos
                ultima_data_hora = datetime.strptime(ultima_data_hora_str, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                # Se falhar, tenta sem microssegundos
                ultima_data_hora = datetime.strptime(ultima_data_hora_str, '%Y-%m-%d %H:%M:%S')
            
            # Calcula a diferença de tempo como um objeto timedelta
            time_difference = datetime.now() - ultima_data_hora
            # Converte timedelta para microssegundos (inteiro) para armazenar no DurationField do SQLite
            tempo_desde_evento_anterior_microseconds = int(time_difference.total_seconds() * 1_000_000)
        
        cursor.execute("""
            INSERT INTO rh_registrotempo (
                candidato_id, documento_id, tipo_evento, data_hora, 
                status_anterior, status_novo, tempo_desde_evento_anterior, observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            candidato_id, documento_id, tipo_evento, datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f'),
            status_anterior, status_novo, tempo_desde_evento_anterior_microseconds, observacoes
        ))
        
        conn.commit()
        conn.close()

    def _atualizar_status_candidato(self, candidato_id):
        """
        Atualiza o status do candidato com base no status de seus documentos,
        priorizando documentos obrigatórios *que o candidato possui*.
        """
        conn = self.conectar_banco()
        cursor = conn.cursor()

        # 1. Obter o status atual do candidato
        cursor.execute("SELECT status FROM rh_candidato WHERE id = ?", (candidato_id,))
        old_candidato_status = cursor.fetchone()['status']
        logger.debug(f"   [Status Candidato] Candidato ID: {candidato_id}, Status Anterior: {old_candidato_status}")

        # 2. Obter APENAS os documentos do candidato que são marcados como obrigatórios
        # Estes são os documentos que *este candidato* precisa ter validado.
        cursor.execute("""
            SELECT
                d.id,
                d.status,
                d.tipo_id,
                t.nome as tipo_nome,
                t.obrigatorio
            FROM rh_documento d
            JOIN rh_tipodocumento t ON d.tipo_id = t.id
            WHERE d.candidato_id = ? AND t.obrigatorio = 1
        """, (candidato_id,))
        mandatory_docs_for_candidate = cursor.fetchall()
        logger.debug(f"   [Status Candidato] Documentos OBRIGATÓRIOS encontrados para o candidato: {len(mandatory_docs_for_candidate)}")
        for doc in mandatory_docs_for_candidate:
            logger.debug(f"     - Doc ID: {doc['id']}, Tipo: {doc['tipo_nome']} (Obrigatório: {bool(doc['obrigatorio'])}), Status: {doc['status']}")

        # 3. Rastrear o status dos documentos obrigatórios *que o candidato possui*
        has_invalid_mandatory = False
        has_pending_or_received_mandatory = False
        
        if not mandatory_docs_for_candidate:
            # Se o candidato não tem NENHUM documento marcado como obrigatório (ou seja, todos foram excluídos ou nunca foram adicionados como obrigatórios para ele)
            # Então ele está 'concluido' por não ter requisitos obrigatórios pendentes.
            new_candidato_status = 'concluido'
            logger.debug("   [Status Candidato] Candidato não possui documentos obrigatórios registrados. Status: concluido.")
        else:
            for doc in mandatory_docs_for_candidate:
                if doc['status'] == 'invalido':
                    has_invalid_mandatory = True
                    break # Já sabemos que há um inválido, podemos parar
                elif doc['status'] in ['pendente', 'recebido']:
                    has_pending_or_received_mandatory = True
            
            if has_invalid_mandatory:
                new_candidato_status = 'documentos_invalidos'
                logger.debug("   [Status Candidato] Pelo menos um documento obrigatório do candidato está inválido. Status: documentos_invalidos.")
            elif has_pending_or_received_mandatory:
                new_candidato_status = 'documentos_pendentes'
                logger.debug("   [Status Candidato] Pelo menos um documento obrigatório do candidato está pendente/recebido. Status: documentos_pendentes.")
            else:
                # Se não há inválidos, nem pendentes/recebidos, e há documentos obrigatórios, então todos estão validados.
                new_candidato_status = 'concluido'
                logger.debug("   [Status Candidato] Todos os documentos obrigatórios do candidato estão validados. Status: concluido.")

        # 4. Atualizar o status do candidato se houver mudança
        if new_candidato_status != old_candidato_status:
            cursor.execute("""
                UPDATE rh_candidato
                SET status = ?
                WHERE id = ?
            """, (new_candidato_status, candidato_id))
            conn.commit()
            logger.info(f"   ✨ Status do Candidato {candidato_id} atualizado: {old_candidato_status} -> {new_candidato_status}")
            
            # Registrar evento de mudança de status do candidato
            self._registrar_evento(
                candidato_id,
                None, # Nenhum documento específico
                'candidato_status_alterado',
                old_candidato_status,
                new_candidato_status,
                f"Status do candidato atualizado automaticamente para '{new_candidato_status}'"
            )
        else:
            logger.info(f"   Status do Candidato {candidato_id} permanece: {old_candidato_status}")

        conn.close()

    def _remover_documentos_pendentes_duplicados(self, candidato_id, tipo_id_validado, documento_validado_id):
        """
        Remove documentos pendentes que são duplicados de um tipo que acabou de ser validado.
        Exclui o documento que acabou de ser validado.
        """
        conn = self.conectar_banco()
        cursor = conn.cursor()
        
        # Busca por outros documentos pendentes do mesmo tipo para o mesmo candidato
        cursor.execute("""
            SELECT id, arquivo, observacoes, status
            FROM rh_documento
            WHERE candidato_id = ? AND tipo_id = ? AND status = 'pendente' AND id != ?
        """, (candidato_id, tipo_id_validado, documento_validado_id))
        
        duplicados = cursor.fetchall()
        conn.close() # Fecha a conexão antes de chamar _deletar_documento

        if duplicados:
            logger.info(f"   🗑️  Encontrados {len(duplicados)} documentos pendentes duplicados do tipo '{tipo_id_validado}' para o candidato {candidato_id}.")
            for doc_duplicado in duplicados:
                try:
                    self._deletar_documento(doc_duplicado['id'])
                    logger.info(f"      - Documento duplicado (ID: {doc_duplicado['id']}) removido.")
                    self._registrar_evento(
                        candidato_id,
                        doc_duplicado['id'],
                        'documento_removido_duplicado',
                        doc_duplicado['status'], # Status anterior (pendente)
                        None, # Não tem status novo, pois foi removido
                        f"Documento removido por ser duplicado de um já validado (ID: {documento_validado_id})"
                    )
                except Exception as e:
                    logger.error(f"      ❌ Erro ao remover documento duplicado {doc_duplicado['id']}: {str(e)}")
        else:
            logger.info(f"   ✅ Nenhum documento pendente duplicado encontrado para o tipo '{tipo_id_validado}'.")

    def _remover_duplicatas_pendentes_geral(self, candidato_id):
        """
        Remove documentos pendentes que são duplicados de documentos já validados
        para um dado candidato. Esta é uma verificação geral.
        """
        conn = self.conectar_banco()
        cursor = conn.cursor()

        # Obter todos os tipos de documentos que o candidato já tem como 'validado'
        cursor.execute("""
            SELECT DISTINCT tipo_id, id
            FROM rh_documento
            WHERE candidato_id = ? AND status = 'validado'
        """, (candidato_id,))
        validated_docs_info = cursor.fetchall()

        if not validated_docs_info:
            logger.info(f"      Nenhum documento validado encontrado para o candidato {candidato_id}. Nenhuma duplicata pendente para remover.")
            conn.close()
            return

        logger.info(f"      Tipos validados para o candidato {candidato_id}: {[row['tipo_id'] for row in validated_docs_info]}")

        for validated_doc_row in validated_docs_info:
            tipo_id = validated_doc_row['tipo_id']
            validated_doc_id = validated_doc_row['id']
            
            # Buscar documentos pendentes do mesmo tipo, excluindo o que acabou de ser validado (if applicable)
            cursor.execute("""
                SELECT id, arquivo, observacoes, status
                FROM rh_documento
                WHERE candidato_id = ? AND tipo_id = ? AND status = 'pendente' AND id != ?
            """, (candidato_id, tipo_id, validated_doc_id))
            
            duplicados_pendentes = cursor.fetchall()

            if duplicados_pendentes:
                logger.info(f"      🗑️  Encontrados {len(duplicados_pendentes)} documentos pendentes duplicados do tipo '{tipo_id}' para o candidato {candidato_id}.")
                for doc_duplicado in duplicados_pendentes:
                    try:
                        self._deletar_documento(doc_duplicado['id'])
                        logger.info(f"         - Documento duplicado (ID: {doc_duplicado['id']}) removido.")
                        self._registrar_evento(
                            candidato_id,
                            doc_duplicado['id'],
                            'documento_removido_duplicado',
                            doc_duplicado['status'], # Status anterior (pendente)
                            None, # Não tem status novo, pois foi removido
                            f"Documento pendente removido por já existir um documento validado do mesmo tipo (Tipo ID: {tipo_id})"
                        )
                    except Exception as e:
                        logger.error(f"         ❌ Erro ao remover documento duplicado {doc_duplicado['id']}: {str(e)}")
            else:
                logger.info(f"      ✅ Nenhum documento pendente duplicado encontrado para o tipo '{tipo_id}'.")
        
        conn.close()

    def revalidar_documento(self, documento):
        """Revalida um documento específico"""
        try:
            # NOVO: Pular revalidação para 'foto_rosto' se já estiver inválido
            if documento['tipo_documento_nome'] == 'foto_rosto' and documento['status'] == 'invalido':
                logger.info(f"   ⏩ Documento 'foto_rosto' (ID: {documento['id']}) está inválido e será pulado para revalidação automática.")
                self.stats['ainda_invalidos'] += 1 # Mantém a contagem de inválidos
                return False # Indica que não foi revalidado com sucesso

            arquivo_relative_path = documento['arquivo']
            
            if not arquivo_relative_path: # Lida com casos onde 'arquivo' pode ser None ou vazio
                logger.error(f"❌ Caminho do arquivo vazio para documento {documento['id']}")
                return False

            # Constrói o caminho completo para o arquivo
            arquivo_full_path = self.media_root / arquivo_relative_path

            if not arquivo_full_path.exists():
                logger.error(f"❌ Arquivo não encontrado para documento {documento['id']}")
                logger.error(f"   📁 Caminho esperado: {arquivo_full_path}")
                return False
            
            # Aguarda rate limit se necessário
            self.aguardar_rate_limit()
            
            # Nome do tipo de documento para exibição
            tipo_nome_exibicao_atual = documento['tipo_documento_nome_exibicao'] or documento['tipo_documento_nome']
            
            logger.info(f"🔄 Revalidando documento {documento['id']} - {tipo_nome_exibicao_atual}")
            logger.info(f"   👤 Candidato: {documento['candidato_nome']}")
            logger.info(f"   📁 Arquivo: {arquivo_full_path}") # Mostra o caminho completo
            
            # Analisa o documento (passando o caminho completo como string)
            inicio_request = time.time()
            resultado = analisar_arquivo(
                str(arquivo_full_path), 
                mostrar_debug=False
            )
            fim_request = time.time()
            
            # Atualiza contadores de rate limit
            self.requests_count += 1
            tokens_estimados = self.estimar_tokens(str(resultado)) + 2000  # +2000 para o prompt
            self.tokens_count += tokens_estimados
            tempo_request = fim_request - inicio_request

            logger.info(f"   ⏱️  Tempo: {tempo_request:.2f}s | Tokens estimados: {tokens_estimados}")
            
            # Processa o resultado
            timestamp = datetime.now().strftime('%d/%m/%Y %H:%M')
            
            if resultado and not resultado.startswith('Erro:'):
                if resultado.startswith('outros|'):
                    # Ainda não conseguiu identificar
                    observacoes = f"Revalidação automática ({timestamp}): {resultado}"
                    self.atualizar_documento(documento['id'], 'invalido', observacoes)
                    logger.warning(f"   ⚠️  Ainda não identificado: {resultado}")
                    self.stats['ainda_invalidos'] += 1
                    # Registrar evento de invalidação (se o status mudou para inválido)
                    if documento['status'] != 'invalido': # Se o status anterior não era inválido
                        self._registrar_evento(
                            documento['candidato_id'],
                            documento['id'],
                            'documento_invalidado',
                            documento['status'],
                            'invalido',
                            observacoes
                        )
                    return False
                else:
                    # Documento foi identificado!
                    novo_tipo_nome = resultado.strip()
                    novo_tipo_id = self._get_tipo_documento_id_by_name(novo_tipo_nome)

                    if novo_tipo_id:
                        # --- NOVA LÓGICA: Verificar se já existe um documento VALIDADO do mesmo tipo ---
                        existing_validated_doc = self._get_validated_document(documento['candidato_id'], novo_tipo_id)
                        
                        if existing_validated_doc:
                            # Já existe um documento validado desse tipo, então este é um duplicado
                            logger.warning(f"   ⚠️  Documento (ID: {documento['id']}) identificado como '{novo_tipo_nome}', mas já existe um validado (ID: {existing_validated_doc['id']}). Removendo duplicado.")
                            self._deletar_documento(documento['id'])
                            self._registrar_evento(
                                documento['candidato_id'],
                                documento['id'],
                                'documento_removido_duplicado',
                                documento['status'], # Status anterior (invalido)
                                None, # Não tem status novo, pois foi removido
                                f"Documento removido por ser duplicado de um já validado (ID: {existing_validated_doc['id']})"
                            )
                            self.stats['validados'] += 1 # Considera como "validado" no sentido de que o tipo está ok
                            return True # Processado com sucesso (removido duplicado)

                        # --- Lógica existente: Tentar preencher pendente ou atualizar o próprio documento ---
                        target_doc = self._get_pending_document(documento['candidato_id'], novo_tipo_id)

                        if target_doc:
                            # Caso 1: Encontrou um documento pendente para preencher
                            logger.info(f"   🎯 Encontrado documento pendente (ID: {target_doc['id']}) do tipo '{novo_tipo_nome}' para preencher.")
                            
                            conn = self.conectar_banco()
                            cursor = conn.cursor()
                            try:
                                # Inicia transação
                                cursor.execute("BEGIN TRANSACTION;")

                                # Atualiza o documento pendente com o arquivo e status do documento atual
                                observacoes_target = f"Documento validado automaticamente com arquivo de '{documento['tipo_documento_nome_exibicao']}' (ID {documento['id']}). Análise IA: {novo_tipo_nome}"
                                self.atualizar_documento(
                                    target_doc['id'], 
                                    'validado', 
                                    observacoes_target, 
                                    arquivo_path=documento['arquivo'] # Transfere o arquivo
                                )
                                
                                # Deleta o documento original 'invalido' (o "outros" ou o que foi revalidado)
                                self._deletar_documento(documento['id'])
                                
                                conn.commit()
                                logger.info(f"   ✅ Documento pendente (ID: {target_doc['id']}) validado e documento original (ID: {documento['id']}) removido.")
                                self.stats['validados'] += 1 # Conta como validado
                                
                                # Registrar evento para o documento que foi validado
                                self._registrar_evento(
                                    documento['candidato_id'],
                                    target_doc['id'],
                                    'documento_validado',
                                    target_doc['status'], # Status anterior do target_doc (pendente)
                                    'validado',
                                    observacoes_target
                                )
                                # Registrar evento para o documento que foi removido/substituído
                                self._registrar_evento(
                                    documento['candidato_id'],
                                    documento['id'],
                                    'documento_removido_substituido', # Novo tipo de evento
                                    documento['status'], # Status anterior do documento removido (invalido)
                                    None, # Não tem status novo, pois foi removido
                                    f"Documento removido após seu arquivo ser usado para validar documento pendente (ID: {target_doc['id']})"
                                )
                                # Remover outros documentos pendentes duplicados do mesmo tipo
                                self._remover_documentos_pendentes_duplicados(documento['candidato_id'], novo_tipo_id, target_doc['id'])

                            except Exception as e:
                                conn.rollback() # Reverte a transação em caso de erro
                                raise e # Propaga o erro para o tratamento externo
                            finally:
                                conn.close()

                        else:
                            # Caso 2: Não encontrou documento pendente, atualiza o documento atual
                            observacoes = f"Revalidação automática ({timestamp}): Identificado como {novo_tipo_nome}"
                            self.atualizar_documento(documento['id'], 'validado', observacoes, novo_tipo_id)
                            logger.info(f"   ✅ Validado como: {novo_tipo_nome.upper()}")
                            self.stats['validados'] += 1
                            
                            # Registrar evento de validação
                            self._registrar_evento(
                                documento['candidato_id'],
                                documento['id'],
                                'documento_validado',
                                documento['status'], # Status anterior (deve ser 'invalido')
                                'validado',
                                observacoes
                            )
                            # Remover outros documentos pendentes duplicados do mesmo tipo
                            self._remover_documentos_pendentes_duplicados(documento['candidato_id'], novo_tipo_id, documento['id'])

                        return True
                    else:
                        # Tipo identificado pela IA não existe na tabela TipoDocumento
                        observacoes = f"Revalidação automática ({timestamp}): IA identificou '{novo_tipo_nome}', mas tipo não existe no banco. Erro: TipoDocumento não encontrado."
                        self.atualizar_documento(documento['id'], 'invalido', observacoes)
                        logger.error(f"   ❌ Erro: Tipo '{novo_tipo_nome}' não encontrado no banco de dados.")
                        self.stats['erros'] += 1
                        return False
            else:
                # Erro na análise
                observacoes = f"Erro na revalidação ({timestamp}): {resultado}"
                self.atualizar_documento(documento['id'], 'invalido', observacoes)
                logger.error(f"   ❌ Erro: {resultado}")
                self.stats['erros'] += 1
                return False
                
        except Exception as e:
            logger.error(f"❌ Erro ao revalidar documento {documento['id']}: {str(e)}")
            timestamp = datetime.now().strftime('%d/%m/%Y %H:%M')
            observacoes = f"Erro na revalidação ({timestamp}): {str(e)}"
            self.atualizar_documento(documento['id'], 'invalido', observacoes)
            self.stats['erros'] += 1
            return False

    def executar_revalidacao(self, limite=None, candidato_id=None, dry_run=False):
        """Executa a revalidação e limpeza de documentos para todos os candidatos ou um específico."""
        logger.info("🚀 Iniciando revalidação e verificação de documentos...")
        logger.info(f"📊 Rate limits: {self.max_requests_per_minute} req/min, {self.max_tokens_per_minute} tokens/min")
        logger.info(f"💾 Banco de dados: {self.db_path}")
        logger.info(f"📁 Caminho base dos arquivos: {self.media_root}")

        conn = self.conectar_banco()
        cursor = conn.cursor()

        # Obter candidatos a serem processados
        if candidato_id:
            cursor.execute("SELECT id, nome FROM rh_candidato WHERE id = ?", (candidato_id,))
            candidates_to_process = cursor.fetchall()
            logger.info(f"🎯 Processando documentos do candidato {candidato_id}")
        else:
            cursor.execute("SELECT id, nome FROM rh_candidato ORDER BY id")
            candidates_to_process = cursor.fetchall()
            logger.info(f"📋 Total de candidatos encontrados: {len(candidates_to_process)}")
        
        conn.close() # Fecha a conexão usada para buscar candidatos

        if not candidates_to_process:
            logger.info("✅ Nenhum candidato encontrado para processar!")
            return

        if dry_run:
            logger.info("🔍 MODO DRY-RUN: Apenas simulação, nenhum dado será alterado")
            logger.info("Candidatos que seriam processados:")
            for c in candidates_to_process:
                logger.info(f"   - ID: {c['id']} | Nome: {c['nome']}")
            return

        candidatos_afetados = set()

        for i, candidato in enumerate(candidates_to_process, 1):
            current_candidato_id = candidato['id']
            current_candidato_nome = candidato['nome']
            logger.info(f"\n--- Processando Candidato: {current_candidato_nome} (ID: {current_candidato_id}) [{i}/{len(candidates_to_process)}] ---")
            
            # 1. Processar documentos inválidos para este candidato
            # Este método já filtra os que foram invalidados manualmente
            invalid_docs_for_candidate = self.obter_documentos_invalidos(candidato_id=current_candidato_id)
            
            if invalid_docs_for_candidate:
                logger.info(f"   Encontrados {len(invalid_docs_for_candidate)} documentos inválidos para revalidar.")
                for doc_invalido in invalid_docs_for_candidate:
                    self.revalidar_documento(doc_invalido)
                    self.stats['total_processados'] += 1
                    time.sleep(1) # Pequena pausa
            else:
                logger.info("   Nenhum documento inválido para revalidar neste ciclo.")

            # 2. Remover documentos pendentes duplicados (verificação geral para este candidato)
            logger.info("   Verificando e removendo documentos pendentes duplicados para este candidato...")
            self._remover_duplicatas_pendentes_geral(current_candidato_id)
            
            # Adiciona o candidato ao conjunto de afetados para atualização de status posterior
            candidatos_afetados.add(current_candidato_id)
        
        # Relatório final
        self.imprimir_relatorio()

        # Verificação final do status dos candidatos afetados
        logger.info("\n🔄 Verificando status final dos candidatos afetados...")
        for c_id in candidatos_afetados:
            self._atualizar_status_candidato(c_id)
        logger.info("✅ Verificação de status concluída.")

    def imprimir_relatorio(self):
        """Imprime relatório final da revalidação"""
        tempo_total = datetime.now() - self.stats['inicio']
        
        logger.info("\n" + "="*60)
        logger.info("📊 RELATÓRIO DE REVALIDAÇÃO")
        logger.info("="*60)
        logger.info(f"⏱️  Tempo total: {tempo_total}")
        logger.info(f"📄 Total processados: {self.stats['total_processados']}")
        logger.info(f"✅ Validados: {self.stats['validados']}")
        logger.warning(f"⚠️  Ainda inválidos: {self.stats['ainda_invalidos']}")
        logger.error(f"❌ Erros: {self.stats['erros']}")
        
        if self.stats['total_processados'] > 0:
            taxa_sucesso = (self.stats['validados'] / self.stats['total_processados']) * 100
            logger.info(f"📈 Taxa de sucesso: {taxa_sucesso:.1f}%")
        
        logger.info("="*60)
    
    def listar_documentos_invalidos(self):
        """Lista todos os documentos inválidos"""
        try:
            documentos = self.obter_documentos_invalidos()
        except Exception as e:
            logger.error(f"❌ Erro ao obter documentos: {e}")
            return
        
        if not documentos:
            logger.info("✅ Nenhum documento inválido encontrado!")
            return
        
        logger.info(f"📋 Documentos inválidos encontrados: {len(documentos)}")
        logger.info("-" * 100)
        
        for doc in documentos:
            tipo_nome = doc['tipo_documento_nome_exibicao'] or doc['tipo_documento_nome']
            full_path = self.media_root / doc['arquivo'] if doc['arquivo'] else "N/A"
            logger.info(f"ID: {doc['id']:3} | {doc['candidato_nome']:30} | {tipo_nome:25}")
            logger.info(f"     📁 {full_path} (Existe: {full_path.exists() if isinstance(full_path, Path) else 'N/A'})")
            if doc['observacoes']:
                obs_resumida = doc['observacoes'][:80] + "..." if len(doc['observacoes']) > 80 else doc['observacoes']
                logger.info(f"     💬 {obs_resumida}")
            logger.info("-" * 100)

# Nova função para a lógica principal de revalidação, que pode ser importada
def run_revalidation_logic(db_path="db.sqlite3", limite=None, candidato_id=None, dry_run=False, listar=False, verificar_db=False):
    logger.debug('Iniciando revalidação de documentos (chamada via import ou standalone).')
    try:
        revalidador = RevalidadorDocumentos(db_path=db_path)
        
        if verificar_db:
            revalidador.verificar_estrutura_banco()
        elif listar:
            revalidador.listar_documentos_invalidos()
        else:
            revalidador.executar_revalidacao(
                limite=limite,
                candidato_id=candidato_id,
                dry_run=dry_run
            )
            
    except FileNotFoundError as e:
        logger.error(f"❌ Erro: {e}")
        logger.error("💡 Certifique-se de que o caminho do banco de dados está correto")
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {e}")
        import traceback
        logger.error(traceback.format_exc()) # Loga o traceback completo
    logger.debug('Revalidação de documentos concluída.')

# A função main original, agora apenas para execução standalone com argparse
def main():
    parser = argparse.ArgumentParser(description='Revalida documentos marcados como inválidos')
    parser.add_argument('--db', default='db.sqlite3', help='Caminho para o banco de dados SQLite')
    parser.add_argument('--limite', type=int, help='Limite de documentos para processar')
    parser.add_argument('--candidato', type=int, help='ID do candidato específico')
    parser.add_argument('--dry-run', action='store_true', help='Apenas simula, não altera dados')
    parser.add_argument('--listar', action='store_true', help='Apenas lista documentos inválidos')
    parser.add_argument('--verificar-db', action='store_true', help='Verifica a estrutura do banco de dados')
    
    args = parser.parse_args()
    
    # Chama a nova função com os argumentos do argparse
    run_revalidation_logic(
        db_path=args.db,
        limite=args.limite,
        candidato_id=args.candidato,
        dry_run=args.dry_run,
        listar=args.listar,
        verificar_db=args.verificar_db
    )

if __name__ == "__main__":
    logger.info("Executando revalidar_documentos.py como script standalone...")
    main() # Chama a função main que processa os argumentos
    logger.info("Execução standalone de revalidar_documentos.py concluída.")


'''


#!/usr/bin/env python3
"""
Script standalone para revalidar documentos marcados como inválidos.
Execução: python revalidar_documentos.py
"""

import os
import sqlite3
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import logging # Importar o módulo logging

# Configuração do logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG) # Nível mínimo para capturar todos os logs

# Formato do log
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Handler para console (stdout)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO) # Nível para o console (INFO e acima)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Handler para arquivo de log
log_file_path = Path(__file__).parent / "revalidacao.log"
file_handler = logging.FileHandler(log_file_path)
file_handler.setLevel(logging.DEBUG) # Nível para o arquivo (DEBUG e acima)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Importa a função analisar_arquivo e verifica de onde ela vem
from reconhecer_imagem import analisar_arquivo
logger.debug(f"'analisar_arquivo' importado de: {analisar_arquivo.__module__} ({analisar_arquivo.__code__.co_filename})")

import django
from django.conf import settings

# Configura o ambiente Django APENAS se ainda não estiver configurado
if not settings.configured:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'main.settings') # Substitua 'main' pelo nome do seu projeto Django
    django.setup()

class RevalidadorDocumentos:
    def __init__(self, db_path="db.sqlite3"):
        """Inicializa o revalidador com conexão direta ao banco"""
        self.db_path = db_path

        # Define o diretório raiz do projeto (onde revalidar_documentos.py está)
        self.project_root = Path(__file__).parent
        # Constrói o caminho para a pasta 'media'
        self.media_root = self.project_root / "media"

        # Rate limits do Groq para meta-llama/llama-4-maverick-17b-128e-instruct
        self.max_requests_per_minute = 25  # Margem de segurança (30 - 5)
        self.max_tokens_per_minute = 5500  # Margem de segurança (6000 - 500)

        # Controle de rate limiting
        self.requests_count = 0
        self.tokens_count = 0
        self.minute_start = time.time()

        # Estatísticas
        self.stats = {
            'total_processados': 0,
            'validados': 0,
            'ainda_invalidos': 0,
            'erros': 0,
            'inicio': datetime.now()
        }
        
        # Verifica se o banco existe
        if not os.path.exists(self.db_path):
            logger.error(f"Banco de dados não encontrado: {self.db_path}")
            raise FileNotFoundError(f"Banco de dados não encontrado: {self.db_path}")
    
    def conectar_banco(self):
        """Cria conexão com o banco de dados"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Para acessar colunas por nome
        return conn
    
    def verificar_estrutura_banco(self):
        """Verifica e mostra a estrutura das tabelas"""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        
        # Lista todas as tabelas
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tabelas = cursor.fetchall()
        
        logger.info("📋 Tabelas encontradas no banco:")
        for tabela in tabelas:
            if 'rh_' in tabela['name']:
                logger.info(f"   - {tabela['name']}")
                
                # Mostra as colunas da tabela
                cursor.execute(f"PRAGMA table_info({tabela['name']});")
                colunas = cursor.fetchall()
                for coluna in colunas:
                    logger.info(f"     └─ {coluna['name']} ({coluna['type']})")
        
        conn.close()
    
    def aguardar_rate_limit(self):
        """Aguarda se necessário para respeitar rate limits"""
        tempo_atual = time.time()
        tempo_decorrido = tempo_atual - self.minute_start
        
        # Se passou 1 minuto, reseta os contadores
        if tempo_decorrido >= 60:
            self.requests_count = 0
            self.tokens_count = 0
            self.minute_start = tempo_atual
            return
        
        # Se atingiu o limite de requests, aguarda
        if self.requests_count >= self.max_requests_per_minute:
            tempo_espera = 60 - tempo_decorrido + 1  # +1 segundo de margem
            logger.warning(f"⏳ Rate limit atingido. Aguardando {tempo_espera:.1f} segundos...")
            time.sleep(tempo_espera)
            self.requests_count = 0
            self.tokens_count = 0
            self.minute_start = time.time()
    
    def estimar_tokens(self, texto):
        """Estimativa simples de tokens (aproximadamente 4 caracteres = 1 token)"""
        return len(texto) // 4
    
    def obter_documentos_invalidos(self, limite=None, candidato_id=None):
        """
        Obtém documentos marcados como inválidos, excluindo aqueles que foram
        invalidados manualmente (via interface web) e que já atingiram o limite de tentativas.
        """
        conn = self.conectar_banco()
        cursor = conn.cursor()
        
        # query = """
        # SELECT 
        #     d.id,
        #     d.arquivo,
        #     d.status,
        #     d.observacoes,
        #     d.tipo_id,
        #     d.candidato_id,
        #     d.tentativas_revalidacao,
        #     c.nome as candidato_nome,
        #     t.nome as tipo_documento_nome,
        #     t.nome_exibicao as tipo_documento_nome_exibicao
        # FROM rh_documento d
        # JOIN rh_candidato c ON d.candidato_id = c.id
        # JOIN rh_tipodocumento t ON d.tipo_id = t.id
        # WHERE d.status = 'invalido'
        # AND d.tentativas_revalidacao < 5
        # AND NOT EXISTS (
        #     SELECT 1
        #     FROM rh_registrotempo rt
        #     WHERE rt.documento_id = d.id
        #     AND rt.tipo_evento = 'documento_invalidado'
        #     AND rt.observacoes LIKE '%Status alterado via interface web por%'
        # )
        # """

        query = """
        SELECT 
            d.id,
            d.arquivo,
            d.status,
            d.observacoes,
            d.tipo_id,
            d.candidato_id,
            d.tentativas_revalidacao,
            c.nome as candidato_nome,
            t.nome as tipo_documento_nome,
            t.nome_exibicao as tipo_documento_nome_exibicao
        FROM rh_documento d
        JOIN rh_candidato c ON d.candidato_id = c.id
        JOIN rh_tipodocumento t ON d.tipo_id = t.id
        WHERE d.status IN ('invalido', 'recebido')
        AND d.tentativas_revalidacao < 5
        AND NOT EXISTS (
            SELECT 1
            FROM rh_registrotempo rt
            WHERE rt.documento_id = d.id
            AND rt.tipo_evento = 'documento_invalidado'
            AND rt.observacoes LIKE '%Status alterado via interface web por%'
        )
        """
        
        params = []
        
        # Filtro por candidato
        if candidato_id:
            query += " AND d.candidato_id = ?"
            params.append(candidato_id)
        
        query += " ORDER BY d.id"
        
        # Limite
        if limite:
            query += " LIMIT ?"
            params.append(limite)
        
        try:
            cursor.execute(query, params)
            documentos = cursor.fetchall()
            conn.close()
            return documentos
        except sqlite3.OperationalError as e:
            logger.error(f"❌ Erro na consulta SQL: {e}")
            logger.info("🔍 Verificando estrutura do banco...")
            conn.close()
            self.verificar_estrutura_banco()
            raise

    def _get_tipo_documento_id_by_name(self, tipo_nome):
        """Obtém o ID de TipoDocumento pelo nome (código)"""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM rh_tipodocumento WHERE nome = ?", (tipo_nome,))
        result = cursor.fetchone()
        conn.close()
        return result['id'] if result else None

    def _get_pending_document(self, candidato_id, tipo_id):
        """Busca um documento pendente para o candidato e tipo especificados."""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, arquivo, status, observacoes, tipo_id, candidato_id
            FROM rh_documento
            WHERE candidato_id = ? AND tipo_id = ? AND status = 'pendente'
            LIMIT 1
        """, (candidato_id, tipo_id))
        doc = cursor.fetchone()
        conn.close()
        return doc

    def _get_validated_document(self, candidato_id, tipo_id):
        """Busca um documento validado para o candidato e tipo especificados."""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, arquivo, status, observacoes, tipo_id, candidato_id
            FROM rh_documento
            WHERE candidato_id = ? AND tipo_id = ? AND status = 'validado'
            LIMIT 1
        """, (candidato_id, tipo_id))
        doc = cursor.fetchone()
        conn.close()
        return doc

    def atualizar_documento(self, documento_id, status, observacoes, tipo_id=None, arquivo_path=None):
        """Atualiza status, observações, opcionalmente o tipo_id e o caminho do arquivo do documento"""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        
        update_fields = []
        params = []

        if status:
            update_fields.append("status = ?")
            params.append(status)
        if observacoes is not None: # Permite observacoes vazias
            update_fields.append("observacoes = ?")
            params.append(observacoes)
        if tipo_id:
            update_fields.append("tipo_id = ?")
            params.append(tipo_id)
        if arquivo_path is not None: # Permite arquivo_path vazio (para remover)
            update_fields.append("arquivo = ?")
            params.append(arquivo_path)

        if not update_fields:
            conn.close()
            return # Nada para atualizar

        query = f"UPDATE rh_documento SET {', '.join(update_fields)} WHERE id = ?"
        params.append(documento_id)
        
        cursor.execute(query, params)
        conn.commit()
        conn.close()

    def _deletar_documento(self, documento_id):
        """Deleta um documento do banco de dados."""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rh_documento WHERE id = ?", (documento_id,))
        conn.commit()
        conn.close()

    def _registrar_evento(self, candidato_id, documento_id, tipo_evento, status_anterior, status_novo, observacoes):
        """Registra um evento na tabela rh_registrotempo"""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        
        # Tenta obter o último evento para calcular tempo_desde_evento_anterior
        tempo_desde_evento_anterior_microseconds = None 
        
        # Se for um evento de documento, busca o último evento para aquele documento
        if documento_id:
            cursor.execute("""
                SELECT data_hora FROM rh_registrotempo
                WHERE candidato_id = ? AND documento_id = ?
                ORDER BY data_hora DESC LIMIT 1
            """, (candidato_id, documento_id))
        else: # Se for um evento de candidato (sem documento específico), busca o último evento geral do candidato
            cursor.execute("""
                SELECT data_hora FROM rh_registrotempo
                WHERE candidato_id = ?
                ORDER BY data_hora DESC LIMIT 1
            """, (candidato_id,))

        ultimo_evento = cursor.fetchone()
        
        if ultimo_evento:
            ultima_data_hora_str = ultimo_evento['data_hora']
            try:
                # Tenta parsear com microssegundos
                ultima_data_hora = datetime.strptime(ultima_data_hora_str, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                # Se falhar, tenta sem microssegundos
                ultima_data_hora = datetime.strptime(ultima_data_hora_str, '%Y-%m-%d %H:%M:%S')
            
            # Calcula a diferença de tempo como um objeto timedelta
            time_difference = datetime.now() - ultima_data_hora
            # Converte timedelta para microssegundos (inteiro) para armazenar no DurationField do SQLite
            tempo_desde_evento_anterior_microseconds = int(time_difference.total_seconds() * 1_000_000)
        
        cursor.execute("""
            INSERT INTO rh_registrotempo (
                candidato_id, documento_id, tipo_evento, data_hora, 
                status_anterior, status_novo, tempo_desde_evento_anterior, observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            candidato_id, documento_id, tipo_evento, datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f'),
            status_anterior, status_novo, tempo_desde_evento_anterior_microseconds, observacoes
        ))
        
        conn.commit()
        conn.close()

    def _atualizar_status_candidato(self, candidato_id):
        """
        Atualiza o status do candidato com base no status de seus documentos,
        priorizando documentos obrigatórios *que o candidato possui*.
        """
        conn = self.conectar_banco()
        cursor = conn.cursor()

        # 1. Obter o status atual do candidato
        cursor.execute("SELECT status FROM rh_candidato WHERE id = ?", (candidato_id,))
        old_candidato_status = cursor.fetchone()['status']
        logger.debug(f"\n")        
        logger.debug(f"   [Status Candidato] Candidato ID: {candidato_id}, Status Anterior: {old_candidato_status}")

        cursor.execute("""
            SELECT COUNT(*) as total_invalidos
            FROM rh_documento d
            WHERE d.candidato_id = ? AND d.status = 'invalido'
        """, (candidato_id,))
        total_invalidos = cursor.fetchone()['total_invalidos']
        logger.debug(f"   [Status Candidato] Total de documentos inválidos (todos): {total_invalidos}")

        # >>> BLOQUEIO PARA NÃO MEXER EM REJEITADO <<<
        if old_candidato_status == 'rejeitado':
            logger.debug("   [Status Candidato] Candidato está rejeitado. Nenhuma atualização será feita.")
            return  # Sai direto sem mudar nada
        
        # Se tem QUALQUER documento inválido, o candidato fica como documentos_invalidos
        if total_invalidos > 0:
            new_candidato_status = 'documentos_invalidos'
            logger.debug(f"   [Status Candidato] Candidato tem {total_invalidos} documento(s) inválido(s). Status: documentos_invalidos.")
        else:
            # 2. Se não tem inválidos, verificar documentos obrigatórios pendentes
            cursor.execute("""
                SELECT
                    d.id,
                    d.status,
                    d.tipo_id,
                    t.nome as tipo_nome,
                    t.obrigatorio
                FROM rh_documento d
                JOIN rh_tipodocumento t ON d.tipo_id = t.id
                WHERE d.candidato_id = ? AND t.obrigatorio = 1
            """, (candidato_id,))
            mandatory_docs_for_candidate = cursor.fetchall()
            logger.debug(f"   [Status Candidato] Documentos OBRIGATÓRIOS encontrados para o candidato: {len(mandatory_docs_for_candidate)}")
            for doc in mandatory_docs_for_candidate:
#                logger.debug(f"     - Doc ID: {doc['id']}, Tipo: {doc['tipo_nome']} (Obrigatório: {bool(doc['obrigatorio'])}), Status: {doc['status']}")
                pass

            # 3. Verificar status dos documentos obrigatórios
            has_pending_or_received_mandatory = False
            
            if not mandatory_docs_for_candidate:
                # Se o candidato não tem NENHUM documento marcado como obrigatório
                new_candidato_status = 'concluido'
                logger.debug("   [Status Candidato] Candidato não possui documentos obrigatórios registrados. Status: concluido.")
            else:
                for doc in mandatory_docs_for_candidate:
                    if doc['status'] in ['pendente', 'recebido']:
                        has_pending_or_received_mandatory = True
                        break
                
                if has_pending_or_received_mandatory:
                    new_candidato_status = 'documentos_pendentes'
                    logger.debug("   [Status Candidato] Pelo menos um documento obrigatório do candidato está pendente/recebido. Status: documentos_pendentes.")
                else:
                    # Se não há inválidos, nem pendentes/recebidos, e há documentos obrigatórios, então todos estão validados.
                    new_candidato_status = 'concluido'
                    logger.debug("   [Status Candidato] Todos os documentos obrigatórios do candidato estão validados. Status: concluido.")

        # 4. Atualizar o status do candidato se houver mudança
        if new_candidato_status != old_candidato_status:
            cursor.execute("""
                UPDATE rh_candidato
                SET status = ?
                WHERE id = ?
            """, (new_candidato_status, candidato_id))
            conn.commit()
            logger.info(f"   ✨ Status do Candidato {candidato_id} atualizado: {old_candidato_status} -> {new_candidato_status}")
            
            # Registrar evento de mudança de status do candidato
            self._registrar_evento(
                candidato_id,
                None, # Nenhum documento específico
                'candidato_status_alterado',
                old_candidato_status,
                new_candidato_status,
                f"Status do candidato atualizado automaticamente para '{new_candidato_status}'"
            )
        else:
            logger.info(f"   Status do Candidato {candidato_id} permanece: {old_candidato_status}")

        conn.close()

    def revalidar_documento(self, documento):
        """Revalida um documento específico"""
        try:
            tentativas_atuais = documento['tentativas_revalidacao'] or 0
            
            # Se já atingiu 5 tentativas, pula o documento
            if tentativas_atuais >= 5:
                logger.info(f"   ⏩ Documento (ID: {documento['id']}) já atingiu o limite de 5 tentativas de revalidação. Pulando.")
                self.stats['ainda_invalidos'] += 1
                return False
            
            # Incrementa o contador de tentativas no banco
            conn = self.conectar_banco()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE rh_documento 
                SET tentativas_revalidacao = tentativas_revalidacao + 1 
                WHERE id = ?
            """, (documento['id'],))
            conn.commit()
            conn.close()
            
            nova_tentativa = tentativas_atuais + 1
            logger.info(f"   🔄 Tentativa {nova_tentativa}/5 de revalidação para documento {documento['id']}")

            # NOVO: Pular revalidação para 'foto_rosto' se já estiver inválido
            if documento['tipo_documento_nome'] == 'FOTO_ROSTO' and documento['status'] == 'invalido':
                logger.info(f"   ⏩ Documento 'FOTO_ROSTO' (ID: {documento['id']}) está inválido e será pulado para revalidação automática.")
                self.stats['ainda_invalidos'] += 1 # Mantém a contagem de inválidos
                return False # Indica que não foi revalidado com sucesso

            arquivo_relative_path = documento['arquivo']
            
            if not arquivo_relative_path: # Lida com casos onde 'arquivo' pode ser None ou vazio
                logger.error(f"❌ Caminho do arquivo vazio para documento {documento['id']}")
                return False

            # Constrói o caminho completo para o arquivo
            arquivo_full_path = self.media_root / arquivo_relative_path

            if not arquivo_full_path.exists():
                logger.error(f"❌ Arquivo não encontrado para documento {documento['id']}")
                logger.error(f"   📁 Caminho esperado: {arquivo_full_path}")
                return False
            
            # Aguarda rate limit se necessário
            self.aguardar_rate_limit()
            
            # Nome do tipo de documento para exibição
            tipo_nome_exibicao_atual = documento['tipo_documento_nome_exibicao'] or documento['tipo_documento_nome']
            
            logger.info(f"🔄 Revalidando documento {documento['id']} - {tipo_nome_exibicao_atual}")
            logger.info(f"   👤 Candidato: {documento['candidato_nome']}")
            logger.info(f"   📁 Arquivo: {arquivo_full_path}") # Mostra o caminho completo
            
            # Analisa o documento (passando o caminho completo como string)
            inicio_request = time.time()
            resultado = analisar_arquivo(
                str(arquivo_full_path), 
                mostrar_debug=False
            )
            fim_request = time.time()
            
            # Atualiza contadores de rate limit
            self.requests_count += 1
            tokens_estimados = self.estimar_tokens(str(resultado)) + 2000  # +2000 para o prompt
            self.tokens_count += tokens_estimados
            tempo_request = fim_request - inicio_request

            logger.info(f"   ⏱️  Tempo: {tempo_request:.2f}s | Tokens estimados: {tokens_estimados}")
            
            # Processa o resultado
            timestamp = datetime.now().strftime('%d/%m/%Y %H:%M')
            
            if resultado and not resultado.startswith('Erro:'):
                if resultado.startswith('outros|'):
                    # Ainda não conseguiu identificar
                    observacoes = f"Revalidação automática ({timestamp}) - Tentativa {nova_tentativa}/5: {resultado}"
                    self.atualizar_documento(documento['id'], 'invalido', observacoes)
                    logger.warning(f"   ⚠️  Ainda não identificado: {resultado}")
                    self.stats['ainda_invalidos'] += 1
                    # Registrar evento de invalidação (se o status mudou para inválido)
                    if documento['status'] != 'invalido': # Se o status anterior não era inválido
                        self._registrar_evento(
                            documento['candidato_id'],
                            documento['id'],
                            'documento_invalidado',
                            documento['status'],
                            'invalido',
                            observacoes
                        )
                    return False
                else:
                    conn = self.conectar_banco()
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE rh_documento 
                        SET tentativas_revalidacao = 0 
                        WHERE id = ?
                    """, (documento['id'],))
                    conn.commit()
                    conn.close()
                    
                    # Documento foi identificado!
                    novo_tipo_nome = resultado.strip()
                    novo_tipo_id = self._get_tipo_documento_id_by_name(novo_tipo_nome)

                    if novo_tipo_id:
                        # --- NOVA LÓGICA: Verificar se já existe um documento VALIDADO do mesmo tipo ---
                        existing_validated_doc = self._get_validated_document(documento['candidato_id'], novo_tipo_id)
                        
                        if existing_validated_doc:
                            # Já existe um documento validado desse tipo, então este é um duplicado
                            logger.warning(f"   ⚠️  Documento (ID: {documento['id']}) identificado como '{novo_tipo_nome}', mas já existe um validado (ID: {existing_validated_doc['id']}). Removendo duplicado.")
                            self._deletar_documento(documento['id'])
                            self._registrar_evento(
                                documento['candidato_id'],
                                documento['id'],
                                'documento_removido_duplicado',
                                documento['status'], # Status anterior (invalido)
                                None, # Não tem status novo, pois foi removido
                                f"Documento removido por ser duplicado de um já validado (ID: {existing_validated_doc['id']})"
                            )
                            self.stats['validados'] += 1 # Considera como "validado" no sentido de que o tipo está ok
                            return True # Processado com sucesso (removido duplicado)

                        # --- Lógica existente: Tentar preencher pendente ou atualizar o próprio documento ---
                        target_doc = self._get_pending_document(documento['candidato_id'], novo_tipo_id)

                        if target_doc:
                            # Caso 1: Encontrou um documento pendente para preencher
                            logger.info(f"   🎯 Encontrado documento pendente (ID: {target_doc['id']}) do tipo '{novo_tipo_nome}' para preencher.")
                            
                            conn = self.conectar_banco()
                            cursor = conn.cursor()
                            try:
                                # Inicia transação
                                cursor.execute("BEGIN TRANSACTION;")

                                # Atualiza o documento pendente com o arquivo e status do documento atual
                                observacoes_target = f"Documento validado automaticamente com arquivo de '{documento['tipo_documento_nome_exibicao']}' (ID {documento['id']}). Análise IA: {novo_tipo_nome}"
                                self.atualizar_documento(
                                    target_doc['id'], 
                                    'validado', 
                                    observacoes_target, 
                                    arquivo_path=documento['arquivo'] # Transfere o arquivo
                                )
                                
                                # Deleta o documento original 'invalido' (o "outros" ou o que foi revalidado)
                                self._deletar_documento(documento['id'])
                                
                                conn.commit()
                                logger.info(f"   ✅ Documento pendente (ID: {target_doc['id']}) validado e documento original (ID: {documento['id']}) removido.")
                                self.stats['validados'] += 1 # Conta como validado
                                
                                # Registrar evento para o documento que foi validado
                                self._registrar_evento(
                                    documento['candidato_id'],
                                    target_doc['id'],
                                    'documento_validado',
                                    target_doc['status'], # Status anterior do target_doc (pendente)
                                    'validado',
                                    observacoes_target
                                )
                                # Registrar evento para o documento que foi removido/substituído
                                self._registrar_evento(
                                    documento['candidato_id'],
                                    documento['id'],
                                    'documento_removido_substituido', # Novo tipo de evento
                                    documento['status'], # Status anterior do documento removido (invalido)
                                    None, # Não tem status novo, pois foi removido
                                    f"Documento removido após seu arquivo ser usado para validar documento pendente (ID: {target_doc['id']})"
                                )
                                # Remover outros documentos pendentes duplicados do mesmo tipo
                                self._remover_documentos_pendentes_duplicados(documento['candidato_id'], novo_tipo_id, target_doc['id'])

                            except Exception as e:
                                conn.rollback() # Reverte a transação em caso de erro
                                raise e # Propaga o erro para o tratamento externo
                            finally:
                                conn.close()

                        else:
                            # Caso 2: Não encontrou documento pendente, atualiza o documento atual
                            observacoes = f"Revalidação automática ({timestamp}): Identificado como {novo_tipo_nome}"
                            self.atualizar_documento(documento['id'], 'validado', observacoes, novo_tipo_id)
                            logger.info(f"   ✅ Validado como: {novo_tipo_nome.upper()}")
                            self.stats['validados'] += 1
                            
                            # Registrar evento de validação
                            self._registrar_evento(
                                documento['candidato_id'],
                                documento['id'],
                                'documento_validado',
                                documento['status'], # Status anterior (deve ser 'invalido')
                                'validado',
                                observacoes
                            )
                            # Remover outros documentos pendentes duplicados do mesmo tipo
                            self._remover_documentos_pendentes_duplicados(documento['candidato_id'], novo_tipo_id, documento['id'])

                        return True
                    else:
                        # Tipo identificado pela IA não existe na tabela TipoDocumento
                        observacoes = f"Revalidação automática ({timestamp}) - Tentativa {nova_tentativa}/5: IA identificou '{novo_tipo_nome}', mas tipo não existe no banco. Erro: TipoDocumento não encontrado."
                        self.atualizar_documento(documento['id'], 'invalido', observacoes)
                        logger.error(f"   ❌ Erro: Tipo '{novo_tipo_nome}' não encontrado no banco de dados.")
                        self.stats['erros'] += 1
                        return False
            else:
                # Erro na análise
                observacoes = f"Erro na revalidação ({timestamp}) - Tentativa {nova_tentativa}/5: {resultado}"
                self.atualizar_documento(documento['id'], 'invalido', observacoes)
                logger.error(f"   ❌ Erro: {resultado}")
                self.stats['erros'] += 1
                return False
                
        except Exception as e:
            logger.error(f"❌ Erro ao revalidar documento {documento['id']}: {str(e)}")
            timestamp = datetime.now().strftime('%d/%m/%Y %H:%M')
            tentativas_atuais = documento['tentativas_revalidacao'] or 0
            nova_tentativa = tentativas_atuais + 1
            observacoes = f"Erro na revalidação ({timestamp}) - Tentativa {nova_tentativa}/5: {str(e)}"
            self.atualizar_documento(documento['id'], 'invalido', observacoes)
            self.stats['erros'] += 1
            return False

    def executar_revalidacao(self, limite=None, candidato_id=None, dry_run=False):
        """Executa a revalidação e limpeza de documentos para todos os candidatos ou um específico."""
        logger.info("🚀 Iniciando revalidação e verificação de documentos...")
        logger.info(f"📊 Rate limits: {self.max_requests_per_minute} req/min, {self.max_tokens_per_minute} tokens/min")
        logger.info(f"💾 Banco de dados: {self.db_path}")
        logger.info(f"📁 Caminho base dos arquivos: {self.media_root}")

        conn = self.conectar_banco()
        cursor = conn.cursor()

        # Obter candidatos a serem processados
        if candidato_id:
            cursor.execute("SELECT id, nome FROM rh_candidato WHERE id = ?", (candidato_id,))
            candidates_to_process = cursor.fetchall()
            logger.info(f"🎯 Processando documentos do candidato {candidato_id}")
        else:
            cursor.execute("SELECT id, nome FROM rh_candidato ORDER BY id")
            candidates_to_process = cursor.fetchall()
            logger.info(f"📋 Total de candidatos encontrados: {len(candidates_to_process)}")
        
        conn.close() # Fecha a conexão usada para buscar candidatos

        if not candidates_to_process:
            logger.info("✅ Nenhum candidato encontrado para processar!")
            return

        if dry_run:
            logger.info("🔍 MODO DRY-RUN: Apenas simulação, nenhum dado será alterado")
            logger.info("Candidatos que seriam processados:")
            for c in candidates_to_process:
                logger.info(f"   - ID: {c['id']} | Nome: {c['nome']}")
            return

        candidatos_afetados = set()

        for i, candidato in enumerate(candidates_to_process, 1):
            current_candidato_id = candidato['id']
            current_candidato_nome = candidato['nome']
            logger.info(f"\n--- Processando Candidato: {current_candidato_nome} (ID: {current_candidato_id}) [{i}/{len(candidates_to_process)}] ---")
            
            # 1. Processar documentos inválidos e nao validados ainda para este candidato
            # Este método já filtra os que foram invalidados manualmente
            invalid_docs_for_candidate = self.obter_documentos_invalidos(candidato_id=current_candidato_id)
            
            if invalid_docs_for_candidate:
                logger.info(f"   Encontrados {len(invalid_docs_for_candidate)} documentos inválidos para revalidar.")
                for doc_invalido in invalid_docs_for_candidate:
                    self.revalidar_documento(doc_invalido)
                    self.stats['total_processados'] += 1
                    time.sleep(1) # Pequena pausa
            else:
                logger.info("   Nenhum documento inválido para revalidar neste ciclo.")

            # Adiciona o candidato ao conjunto de afetados para atualização de status posterior
            candidatos_afetados.add(current_candidato_id)
        
        # Relatório final
        self.imprimir_relatorio()

        # Verificação final do status dos candidatos afetados
        logger.info("\n🔄 Verificando status final dos candidatos afetados...")
        for c_id in candidatos_afetados:
            self._atualizar_status_candidato(c_id)
        logger.info("✅ Verificação de status concluída.")

    def imprimir_relatorio(self):
        """Imprime relatório final da revalidação"""
        tempo_total = datetime.now() - self.stats['inicio']
        
        logger.info("\n" + "="*60)
        logger.info("📊 RELATÓRIO DE REVALIDAÇÃO")
        logger.info("="*60)
        logger.info(f"⏱️  Tempo total: {tempo_total}")
        logger.info(f"📄 Total processados: {self.stats['total_processados']}")
        logger.info(f"✅ Validados: {self.stats['validados']}")
        logger.warning(f"⚠️  Ainda inválidos: {self.stats['ainda_invalidos']}")
        logger.error(f"❌ Erros: {self.stats['erros']}")
        
        if self.stats['total_processados'] > 0:
            taxa_sucesso = (self.stats['validados'] / self.stats['total_processados']) * 100
            logger.info(f"📈 Taxa de sucesso: {taxa_sucesso:.1f}%")
        
        logger.info("="*60)
    
    def listar_documentos_invalidos(self):
        """Lista todos os documentos inválidos"""
        try:
            documentos = self.obter_documentos_invalidos()
        except Exception as e:
            logger.error(f"❌ Erro ao obter documentos: {e}")
            return
        
        if not documentos:
            logger.info("✅ Nenhum documento inválido encontrado!")
            return
        
        logger.info(f"📋 Documentos inválidos encontrados: {len(documentos)}")
        logger.info("-" * 100)
        
        for doc in documentos:
            tipo_nome = doc['tipo_documento_nome_exibicao'] or doc['tipo_documento_nome']
            full_path = self.media_root / doc['arquivo'] if doc['arquivo'] else "N/A"
            logger.info(f"ID: {doc['id']:3} | {doc['candidato_nome']:30} | {tipo_nome:25}")
            logger.info(f"     📁 {full_path} (Existe: {full_path.exists() if isinstance(full_path, Path) else 'N/A'})")
            if doc['observacoes']:
                obs_resumida = doc['observacoes'][:80] + "..." if len(doc['observacoes']) > 80 else doc['observacoes']
                logger.info(f"     💬 {obs_resumida}")
            logger.info("-" * 100)

    def _remover_documentos_pendentes_duplicados(self, candidato_id, tipo_id, documento_id):
        """Remove documentos pendentes duplicados do mesmo tipo para um candidato específico."""
        conn = self.conectar_banco()
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM rh_documento
            WHERE candidato_id = ? AND tipo_id = ? AND status = 'pendente' AND id != ?
        """, (candidato_id, tipo_id, documento_id))
        conn.commit()
        conn.close()
        logger.info(f"   🗑️  Removidos documentos pendentes duplicados do tipo '{tipo_id}' para o candidato {candidato_id}.")

# Nova função para a lógica principal de revalidação, que pode ser importada
def run_revalidation_logic(db_path="db.sqlite3", limite=None, candidato_id=None, dry_run=False, listar=False, verificar_db=False):
    logger.debug('Iniciando revalidação de documentos (chamada via import ou standalone).')
    try:
        revalidador = RevalidadorDocumentos(db_path=db_path)
        
        if verificar_db:
            revalidador.verificar_estrutura_banco()
        elif listar:
            revalidador.listar_documentos_invalidos()
        else:
            revalidador.executar_revalidacao(
                limite=limite,
                candidato_id=candidato_id,
                dry_run=dry_run
            )
            
    except FileNotFoundError as e:
        logger.error(f"❌ Erro: {e}")
        logger.error("💡 Certifique-se de que o caminho do banco de dados está correto")
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {e}")
        import traceback
        logger.error(traceback.format_exc()) # Loga o traceback completo
    logger.debug('Revalidação de documentos concluída.')

# A função main original, agora apenas para execução standalone com argparse
def main():
    parser = argparse.ArgumentParser(description='Revalida documentos marcados como inválidos')
    parser.add_argument('--db', default='db.sqlite3', help='Caminho para o banco de dados SQLite')
    parser.add_argument('--limite', type=int, help='Limite de documentos para processar')
    parser.add_argument('--candidato', type=int, help='ID do candidato específico')
    parser.add_argument('--dry-run', action='store_true', help='Apenas simula, não altera dados')
    parser.add_argument('--listar', action='store_true', help='Apenas lista documentos inválidos')
    parser.add_argument('--verificar-db', action='store_true', help='Verifica a estrutura do banco de dados')
    
    args = parser.parse_args()
    
    # Chama a nova função com os argumentos do argparse
    run_revalidation_logic(
        db_path=args.db,
        limite=args.limite,
        candidato_id=args.candidato,
        dry_run=args.dry_run,
        listar=args.listar,
        verificar_db=args.verificar_db
    )

if __name__ == "__main__":
    logger.info("Executando revalidar_documentos.py como script standalone...")
    main() # Chama a função main que processa os argumentos
    logger.info("Execução standalone de revalidar_documentos.py concluída.")
