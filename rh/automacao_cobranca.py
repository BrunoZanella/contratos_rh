import threading
import time
import schedule
import fcntl
import os
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from .models import ConfiguracaoCobranca, ControleCobrancaCandidato, Candidato, Documento, HistoricoCobranca
from .whatsapp import enviar_mensagem_whatsapp
import logging
from django.db.models import Count as models_Count

logger = logging.getLogger(__name__)

class AutomacaoCobranca:
    def __init__(self):
        self.running = False
        self.thread = None
        self.lock_file = None
        self.lock_path = '/tmp/rh_automacao_cobranca.lock'
        self.last_config_check = None
        self.current_config_hash = None
        
    def start(self):
        """Inicia o sistema de automação de cobrança"""
        if self.running:
            return
            
        try:
            self.lock_file = open(self.lock_path, 'w')
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            logger.info("Lock da automação de cobrança adquirido com sucesso")
        except (IOError, OSError) as e:
            logger.info(f"Outro processo já está executando a automação de cobrança. Lock não adquirido: {e}")
            if self.lock_file:
                self.lock_file.close()
                self.lock_file = None
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info("Sistema de automação de cobrança iniciado")
        
    def stop(self):
        """Para o sistema de automação de cobrança"""
        self.running = False
        if self.thread:
            self.thread.join()
            
        if self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self.lock_file.close()
                os.unlink(self.lock_path)
                logger.info("Lock da automação de cobrança liberado")
            except Exception as e:
                logger.error(f"Erro ao liberar lock: {e}")
            finally:
                self.lock_file = None
                
        logger.info("Sistema de automação de cobrança parado")
        
    def _run_scheduler(self):
        """Executa o agendador em loop"""
        # Configura os horários baseado na configuração do banco
        self._setup_schedule()
        
        while self.running:
            if self._should_reload_config():
                logger.info("Configurações alteradas, recarregando agendamento...")
                self._setup_schedule()
                
            schedule.run_pending()
            time.sleep(60)  # Verifica a cada minuto
            
    def _should_reload_config(self):
        """Verifica se as configurações mudaram e precisam ser recarregadas"""
        try:
            now = timezone.now()
            
            # Verifica a cada 5 minutos
            if self.last_config_check and (now - self.last_config_check).seconds < 300:
                return False
                
            self.last_config_check = now
            
            # Busca configuração atual
            config = ConfiguracaoCobranca.objects.first()
            if not config:
                return False
                
            # Cria hash das configurações importantes
            config_data = f"{config.ativo}_{config.dias_semana}_{config.horarios}_{config.mensagem_template}"
            config_hash = hash(config_data)
            
            # Verifica se mudou
            if self.current_config_hash != config_hash:
                self.current_config_hash = config_hash
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Erro ao verificar mudanças na configuração: {e}")
            return False
            
    def _setup_schedule(self):
        """Configura os horários de execução baseado na configuração do banco"""
        try:
            config = ConfiguracaoCobranca.objects.first()
            if not config or not config.ativo:
                logger.info("Automação de cobrança desativada ou não configurada")
                schedule.clear()
                return
                
            # Limpa agendamentos anteriores
            schedule.clear()
            
            # Configura para cada dia da semana e horário
            dias_semana = {
                0: 'monday', 1: 'tuesday', 2: 'wednesday', 3: 'thursday',
                4: 'friday', 5: 'saturday', 6: 'sunday'
            }
            
            for dia_num in config.dias_semana:
                if dia_num in dias_semana:
                    dia_nome = dias_semana[dia_num]
                    for horario in config.horarios:
                        getattr(schedule.every(), dia_nome).at(horario).do(self._executar_cobranca)
                        logger.info(f"Agendado para {dia_nome} às {horario}")
                        
        except Exception as e:
            logger.error(f"Erro ao configurar agendamento: {e}")
            
    def _executar_cobranca(self):
        """Executa a cobrança automática"""
        logger.info("Iniciando execução da cobrança automática")
        
        try:
            # Verifica se a configuração ainda está ativa
            config = ConfiguracaoCobranca.objects.first()
            if not config or not config.ativo:
                logger.info("Automação desativada, pulando execução")
                return
                
            # Busca candidatos com cobrança ativa e documentos pendentes
            candidatos_para_cobrar = self._buscar_candidatos_para_cobranca()
            
            for candidato in candidatos_para_cobrar:
                try:
                    self._enviar_cobranca_candidato(candidato, config)
                except Exception as e:
                    logger.error(f"Erro ao enviar cobrança para candidato {candidato.id}: {e}")
                    
            logger.info(f"Cobrança automática executada para {len(candidatos_para_cobrar)} candidatos")
            
        except Exception as e:
            logger.error(f"Erro na execução da cobrança automática: {e}")
            
    def _buscar_candidatos_para_cobranca(self):
        """Busca candidatos que devem receber cobrança"""
        candidatos = []
        
        logger.info("[DEBUG] Iniciando busca de candidatos para cobrança")
        
        # Busca candidatos com cobrança ativa
        controles_ativos = ControleCobrancaCandidato.objects.filter(
            cobranca_pausada=False
        ).select_related('candidato')
        
        logger.info(f"[DEBUG] Total de ControleCobrancaCandidato com cobranca_pausada=False: {controles_ativos.count()}")
        
        # Se não há controles ativos, verifica se existem candidatos sem controle
        if not controles_ativos.exists():
            logger.info("[DEBUG] Nenhum ControleCobrancaCandidato ativo encontrado")
            
            # Verifica quantos candidatos existem no total
            total_candidatos = Candidato.objects.count()
            logger.info(f"[DEBUG] Total de candidatos no sistema: {total_candidatos}")
            
            # Verifica quantos ControleCobrancaCandidato existem no total
            total_controles = ControleCobrancaCandidato.objects.count()
            logger.info(f"[DEBUG] Total de ControleCobrancaCandidato no sistema: {total_controles}")
            
            # Verifica quantos estão pausados
            controles_pausados = ControleCobrancaCandidato.objects.filter(cobranca_pausada=True).count()
            logger.info(f"[DEBUG] ControleCobrancaCandidato pausados: {controles_pausados}")
        
        for controle in controles_ativos:
            candidato = controle.candidato
            logger.info(f"[DEBUG] Verificando candidato: {candidato.nome} (ID: {candidato.id})")
            
            # Verifica se tem documentos obrigatórios pendentes
            docs_pendentes = Documento.objects.filter(
                candidato=candidato,
                tipo__obrigatorio=True,
                status__in=['pendente', 'recebido']
            )
            
            docs_count = docs_pendentes.count()
            logger.info(f"[DEBUG] Candidato {candidato.nome}: {docs_count} documentos obrigatórios pendentes")
            
            if docs_count > 0:
                # Lista os documentos pendentes para debug
                for doc in docs_pendentes:
                    logger.info(f"[DEBUG] - Documento pendente: {doc.tipo.nome} (status: {doc.status})")
                candidatos.append(candidato)
            else:
                # Verifica quantos documentos obrigatórios existem no total para este candidato
                total_docs_obrigatorios = Documento.objects.filter(
                    candidato=candidato,
                    tipo__obrigatorio=True
                ).count()
                logger.info(f"[DEBUG] Candidato {candidato.nome}: {total_docs_obrigatorios} documentos obrigatórios no total")
                
                # Verifica status dos documentos obrigatórios
                docs_por_status = Documento.objects.filter(
                    candidato=candidato,
                    tipo__obrigatorio=True
                ).values('status').annotate(count=models_Count('status'))
                
                for item in docs_por_status:
                    logger.info(f"[DEBUG] - Status '{item['status']}': {item['count']} documentos")
        
        logger.info(f"[DEBUG] Total de candidatos encontrados para cobrança: {len(candidatos)}")
        return candidatos
        
    def _enviar_cobranca_candidato(self, candidato, config):
        """Envia cobrança para um candidato específico"""
        docs_pendentes = Documento.objects.filter(
            candidato=candidato,
            tipo__obrigatorio=True,
            status__in=['pendente', 'recebido']
        ).select_related('tipo')
        
        if not docs_pendentes:
            return
            
        # Criar listas de documentos: técnica e de exibição
        lista_docs_tecnicos = []
        lista_docs_exibicao = []
        
        for doc in docs_pendentes:
            lista_docs_tecnicos.append(doc.tipo.nome)
            lista_docs_exibicao.append(doc.tipo.get_nome_exibicao())
        
        # Formatar listas para exibição
        lista_docs_formatada = '\n'.join([f"• {doc}" for doc in lista_docs_tecnicos])
        lista_docs_exibicao_formatada = '\n'.join([f"• *{doc}*" for doc in lista_docs_exibicao])
        
        # Monta a mensagem
        if config.mensagem_template:
            mensagem = config.mensagem_template.replace('{nome}', candidato.nome)
            mensagem = mensagem.replace('{documentos}', lista_docs_formatada)
            mensagem = mensagem.replace('{documentos_exibicao}', lista_docs_exibicao_formatada)
        else:
            mensagem = f"""Olá {candidato.nome}, você ainda possui documentos pendentes:

{lista_docs_formatada}

Por favor, envie-os o mais breve possível."""
        
        # Envia a mensagem via WhatsApp
        resposta_whatsapp = enviar_mensagem_whatsapp(candidato.telefone, mensagem)
        
        sucesso = False
        erro_msg = None
        
        try:
            if isinstance(resposta_whatsapp, dict) and 'status' in resposta_whatsapp:
                # Status PENDING significa que foi aceito pelo WhatsApp
                sucesso = resposta_whatsapp.get('status') in ['PENDING', 'SENT', 'DELIVERED']
                if not sucesso:
                    erro_msg = f"Status: {resposta_whatsapp.get('status', 'UNKNOWN')}"
            elif isinstance(resposta_whatsapp, bool):
                sucesso = resposta_whatsapp
            else:
                sucesso = bool(resposta_whatsapp)
        except Exception as e:
            sucesso = False
            erro_msg = str(e)
        
        # Registra no histórico
        with transaction.atomic():
            HistoricoCobranca.objects.create(
                candidato=candidato,
                data_envio=timezone.now(),
                documentos_cobrados=lista_docs_tecnicos,  # Usar nomes técnicos para histórico
                sucesso=sucesso,
                mensagem_enviada=mensagem,
                erro=erro_msg if not sucesso else None
            )
            
            # Atualiza a data da última cobrança
            controle = ControleCobrancaCandidato.objects.get(candidato=candidato)
            controle.data_ultima_cobranca = timezone.now()
            controle.save()
            
        logger.info(f"Cobrança enviada para {candidato.nome}: {'Sucesso' if sucesso else 'Falha'}")

    def reload_config(self):
        """Força a recarga das configurações"""
        logger.info("Forçando recarga das configurações de automação...")
        self.current_config_hash = None
        self._setup_schedule()

# Instância global do sistema de automação
automacao_cobranca = AutomacaoCobranca()




'''
import threading
import time
import schedule
import fcntl
import os
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from .models import ConfiguracaoCobranca, ControleCobrancaCandidato, Candidato, Documento, HistoricoCobranca
from .whatsapp import enviar_mensagem_whatsapp
import logging

logger = logging.getLogger(__name__)

class AutomacaoCobranca:
    def __init__(self):
        self.running = False
        self.thread = None
        self.lock_file = None
        self.lock_path = '/tmp/rh_automacao_cobranca.lock'
        
    def start(self):
        """Inicia o sistema de automação de cobrança"""
        if self.running:
            return
            
        try:
            self.lock_file = open(self.lock_path, 'w')
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            logger.info("Lock da automação de cobrança adquirido com sucesso")
        except (IOError, OSError) as e:
            logger.info(f"Outro processo já está executando a automação de cobrança. Lock não adquirido: {e}")
            if self.lock_file:
                self.lock_file.close()
                self.lock_file = None
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info("Sistema de automação de cobrança iniciado")
        
    def stop(self):
        """Para o sistema de automação de cobrança"""
        self.running = False
        if self.thread:
            self.thread.join()
            
        if self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self.lock_file.close()
                os.unlink(self.lock_path)
                logger.info("Lock da automação de cobrança liberado")
            except Exception as e:
                logger.error(f"Erro ao liberar lock: {e}")
            finally:
                self.lock_file = None
                
        logger.info("Sistema de automação de cobrança parado")
        
    def _run_scheduler(self):
        """Executa o agendador em loop"""
        # Configura os horários baseado na configuração do banco
        self._setup_schedule()
        
        while self.running:
            schedule.run_pending()
            time.sleep(60)  # Verifica a cada minuto
            
    def _setup_schedule(self):
        """Configura os horários de execução baseado na configuração do banco"""
        try:
            config = ConfiguracaoCobranca.objects.first()
            if not config or not config.ativo:
                logger.info("Automação de cobrança desativada ou não configurada")
                return
                
            # Limpa agendamentos anteriores
            schedule.clear()
            
            # Configura para cada dia da semana e horário
            dias_semana = {
                0: 'monday', 1: 'tuesday', 2: 'wednesday', 3: 'thursday',
                4: 'friday', 5: 'saturday', 6: 'sunday'
            }
            
            for dia_num in config.dias_semana:
                if dia_num in dias_semana:
                    dia_nome = dias_semana[dia_num]
                    for horario in config.horarios:
                        getattr(schedule.every(), dia_nome).at(horario).do(self._executar_cobranca)
                        logger.info(f"Agendado para {dia_nome} às {horario}")
                        
        except Exception as e:
            logger.error(f"Erro ao configurar agendamento: {e}")
            
    def _executar_cobranca(self):
        """Executa a cobrança automática"""
        logger.info("Iniciando execução da cobrança automática")
        
        try:
            # Verifica se a configuração ainda está ativa
            config = ConfiguracaoCobranca.objects.first()
            if not config or not config.ativo:
                logger.info("Automação desativada, pulando execução")
                return
                
            # Busca candidatos com cobrança ativa e documentos pendentes
            candidatos_para_cobrar = self._buscar_candidatos_para_cobranca()
            
            for candidato in candidatos_para_cobrar:
                try:
                    self._enviar_cobranca_candidato(candidato, config)
                except Exception as e:
                    logger.error(f"Erro ao enviar cobrança para candidato {candidato.id}: {e}")
                    
            logger.info(f"Cobrança automática executada para {len(candidatos_para_cobrar)} candidatos")
            
        except Exception as e:
            logger.error(f"Erro na execução da cobrança automática: {e}")
            
    def _buscar_candidatos_para_cobranca(self):
        """Busca candidatos que devem receber cobrança"""
        candidatos = []
        
        # Busca candidatos com cobrança ativa
        controles_ativos = ControleCobrancaCandidato.objects.filter(
            cobranca_pausada=False
        ).select_related('candidato')
        
        for controle in controles_ativos:
            candidato = controle.candidato
            
            # Verifica se tem documentos obrigatórios pendentes
            docs_pendentes = Documento.objects.filter(
                candidato=candidato,
                tipo__obrigatorio=True,
                status__in=['pendente', 'recebido']
            )
            
            if docs_pendentes.exists():
                candidatos.append(candidato)
                
        return candidatos
        
    def _enviar_cobranca_candidato(self, candidato, config):
        """Envia cobrança para um candidato específico"""
        # Busca documentos obrigatórios pendentes
        docs_pendentes = Documento.objects.filter(
            candidato=candidato,
            tipo__obrigatorio=True,
            status__in=['pendente', 'recebido']
        ).values_list('tipo__nome', flat=True)
        
        if not docs_pendentes:
            return
            
        # Monta a mensagem
        lista_docs = '\n'.join([f"• {doc}" for doc in docs_pendentes])
        
        if config.mensagem_template:
            mensagem = config.mensagem_template.replace('{nome}', candidato.nome)
            mensagem = mensagem.replace('{documentos}', lista_docs)
        else:
            mensagem = f"""Olá {candidato.nome}, você ainda possui documentos pendentes:

{lista_docs}

Por favor, envie-os o mais breve possível."""
        
        # Envia a mensagem via WhatsApp
        resposta_whatsapp = enviar_mensagem_whatsapp(candidato.telefone, mensagem)
        
        sucesso = False
        erro_msg = None

        try:
            if isinstance(resposta_whatsapp, dict) and 'status' in resposta_whatsapp:
                # Status PENDING significa que foi aceito pelo WhatsApp
                sucesso = resposta_whatsapp.get('status') in ['PENDING', 'SENT', 'DELIVERED']
                if not sucesso:
                    erro_msg = f"Status: {resposta_whatsapp.get('status', 'UNKNOWN')}"
            elif isinstance(resposta_whatsapp, bool):
                sucesso = resposta_whatsapp
            else:
                sucesso = bool(resposta_whatsapp)
        except Exception as e:
            sucesso = False
            erro_msg = str(e)

        # Registra no histórico
        with transaction.atomic():
            HistoricoCobranca.objects.create(
                candidato=candidato,
                data_envio=timezone.now(),
                documentos_cobrados=list(docs_pendentes),
                sucesso=sucesso,
                mensagem_enviada=mensagem,
                erro=erro_msg if not sucesso else None
            )
            
            # Atualiza a data da última cobrança
            controle = ControleCobrancaCandidato.objects.get(candidato=candidato)
            controle.data_ultima_cobranca = timezone.now()
            controle.save()
            
        logger.info(f"Cobrança enviada para {candidato.nome}: {'Sucesso' if sucesso else 'Falha'}")

# Instância global do sistema de automação
automacao_cobranca = AutomacaoCobranca()
'''