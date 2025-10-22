from django.db import models
from django.utils import timezone
import re
from django.core.exceptions import ValidationError

# Adicione este import no topo do arquivo
from django.db.models.signals import post_save
from django.dispatch import receiver

# Estender o modelo de usuário do Django
from django.contrib.auth.models import User

from datetime import datetime, date

def clean_phone_number(phone):
    """Limpa o número de telefone, removendo caracteres não numéricos"""
    # Remove todos os caracteres não numéricos
    phone = ''.join(filter(str.isdigit, phone))

    # Remove o 55 do início se existir
    if phone.startswith('55'):
        phone = phone[2:]
        
    # Verifica se o número tem o tamanho correto
    if len(phone) not in [10, 11]:
        raise ValueError("Número de telefone inválido")
        
    return phone

class Candidato(models.Model):
    STATUS_CHOICES = [
        ('ativo', 'Ativo'),
        ('aguardando_inicio', 'Aguardando Início'),
        ('em_andamento', 'Em Andamento'),
        ('documentos_pendentes', 'Documentos Pendentes'),
        ('documentos_invalidos', 'Documentos Inválidos'),
        ('concluido', 'Concluído'),
        ('rejeitado', 'Rejeitado'),
    ]
 
    TIPO_CONTRATACAO_CHOICES = [
        ('clt', 'CLT'),
        ('pj', 'PJ'),
    ]

    nome = models.CharField(max_length=200)
    telefone = models.CharField(max_length=20)
    email = models.EmailField()
    tipo_contratacao = models.CharField(
        max_length=3,
        choices=TIPO_CONTRATACAO_CHOICES,
        default='clt',
        verbose_name='Tipo de Contratação'
    )
    status = models.CharField(
        max_length=50, 
        choices=STATUS_CHOICES,
        default='ativo'  # Alterado para iniciar como ativo
    )
    data_cadastro = models.DateTimeField(default=timezone.now)
    data_ultima_atualizacao = models.DateTimeField(auto_now=True)
    mensagem_enviada = models.BooleanField(default=False)
    ultima_tentativa_mensagem = models.DateTimeField(null=True, blank=True)
    # Adicionar campo para rastrear o criador do candidato
    criado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='candidatos_criados')
    
    def __str__(self):
        return f"{self.nome} - {self.get_status_display()}"

    class Meta:
        verbose_name = 'Candidato'
        verbose_name_plural = 'Candidatos'
        ordering = ['-data_cadastro'] # <-- Esta linha garante a ordenação do mais recente para o mais antigo

    def clean(self):
        if self.telefone:
            try:
                numero_limpo = clean_phone_number(self.telefone)
                # Formata o número
                if len(numero_limpo) == 11:  # Celular
                    self.telefone = f"({numero_limpo[:2]}) {numero_limpo[2:7]}-{numero_limpo[7:]}"
                elif len(numero_limpo) == 10:  # Telefone fixo
                    self.telefone = f"({numero_limpo[:2]}) {numero_limpo[2:6]}-{numero_limpo[6:]}"
            except ValueError as e:
                raise ValidationError({'telefone': str(e)})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    @property
    def telefone_limpo(self):
        """Retorna o telefone apenas com números, sem o 55"""
        numero = ''.join(filter(str.isdigit, self.telefone))
        if numero.startswith('55'):
            numero = numero[2:]
        return numero

    @property
    def telefone_formatado(self):
        """Formata o telefone para exibição"""
        numero = self.telefone_limpo
        if len(numero) == 11:  # Celular
            return f"({numero[:2]}) {numero[2:7]}-{numero[7:]}"
        elif len(numero) == 10:  # Telefone fixo
            return f"({numero[:2]}) {numero[2:6]}-{numero[6:]}"
        return self.telefone
 
    @property
    def documentos_validados(self):
        """Retorna a quantidade de documentos validados"""
        return self.documentos.filter(status='validado').count()
    
    @property
    def documentos_pendentes(self):
        """Retorna a quantidade de documentos pendentes"""
        return self.documentos.filter(status='pendente').count()
    
    @property
    def documentos_recebidos(self):
        """Retorna a quantidade de documentos recebidos (não validados ainda)"""
        return self.documentos.filter(status='recebido').count()
    
    @property
    def documentos_invalidos(self):
        """Retorna a quantidade de documentos inválidos"""
        return self.documentos.filter(status='invalido').count()
    
    @property
    def total_documentos(self):
        """Retorna o total de documentos"""
        return self.documentos.count()
    
    @property
    def status_documentos_display(self):
        """
        Retorna uma string formatada com a contagem de documentos de acordo com o status do candidato
        """
        if self.status == 'documentos_pendentes':
            # Mostra quantos documentos ainda estão pendentes
            return f"{self.documentos_pendentes}/{self.total_documentos} pendentes"
        
        elif self.status == 'documentos_invalidos':
            # Mostra quantos documentos estão inválidos
            if self.documentos_invalidos == 1:
                return f"{self.documentos_invalidos} inválido"
            else:
                return f"{self.documentos_invalidos} inválidos"
        
        elif self.status == 'concluido':
            # Mostra o total de documentos validados
            if self.documentos_validados == 1:
                return f"{self.documentos_validados} validado"
            else:
                return f"{self.documentos_validados} validados"
        
        else:
            # Para outros status, mostra a contagem geral
            return f"{self.documentos_validados}/{self.total_documentos}"

class TipoDocumento(models.Model):
    TIPO_CONTRATACAO_CHOICES = [
        ('clt', 'CLT'),
        ('pj', 'PJ'),
        ('ambos', 'Ambos'),
    ]

    nome = models.CharField(max_length=100)
    nome_exibicao = models.CharField(max_length=200, blank=True)
    tipo_contratacao = models.CharField(
        max_length=5,
        choices=TIPO_CONTRATACAO_CHOICES,
        default='ambos',
        verbose_name='Tipo de Contratação'
    )
    ativo = models.BooleanField(default=True)
    obrigatorio = models.BooleanField(default=True, verbose_name='Obrigatório') # NOVO CAMPO

    def __str__(self):
        return self.nome_exibicao or self.nome
    
    def get_nome_exibicao(self):
        """Retorna o nome formatado para exibição"""
        if self.nome_exibicao:
            return self.nome_exibicao
        # Se não tiver nome_exibicao, formata o nome para exibição
        return self.nome.replace('_', ' ').title()
    
    @classmethod
    def get_documentos_por_tipo(cls, tipo_contratacao):
        """Retorna documentos filtrados por tipo de contratação"""
        return cls.objects.filter(
            models.Q(tipo_contratacao=tipo_contratacao) | models.Q(tipo_contratacao='ambos'),
            ativo=True
        )
    
    class Meta:
        verbose_name = 'Tipo de Documento'
        verbose_name_plural = 'Tipos de Documentos'

class Documento(models.Model):
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('recebido', 'Recebido'),
        ('invalido', 'Inválido'),
        ('validado', 'Validado'),
        ('nao_possui', 'Não Possui'),
    ]

    candidato = models.ForeignKey(
        Candidato, 
        on_delete=models.CASCADE,
        related_name='documentos'
    )
    tipo = models.ForeignKey(
        TipoDocumento,
        on_delete=models.PROTECT,
        related_name='documentos'
    )
    arquivo = models.FileField(upload_to='documentos/', null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pendente'
    )
    observacoes = models.TextField(blank=True)
    data_envio = models.DateTimeField(null=True, blank=True)
    data_validacao = models.DateTimeField(null=True, blank=True)
    
    # NOVO CAMPO: Contador de tentativas de revalidação
    tentativas_revalidacao = models.IntegerField(
        default=0,
        verbose_name='Tentativas de Revalidação',
        help_text='Número de tentativas automáticas de revalidação realizadas pela IA'
    )

    def __str__(self):
        return f"{self.candidato.nome} - {self.tipo.nome}"

    class Meta:
        verbose_name = 'Documento'
        verbose_name_plural = 'Documentos'
    
    def pode_ser_revalidado(self):
        """
        Verifica se o documento pode ser revalidado automaticamente.
        Retorna True se ainda não atingiu o limite máximo de tentativas.
        """
        MAX_TENTATIVAS = 5
        return self.tentativas_revalidacao < MAX_TENTATIVAS
    
    def incrementar_tentativa_revalidacao(self):
        """
        Incrementa o contador de tentativas de revalidação.
        """
        self.tentativas_revalidacao += 1
        self.save(update_fields=['tentativas_revalidacao'])
    
    def resetar_tentativas_revalidacao(self):
        """
        Reseta o contador de tentativas de revalidação.
        Usado quando o documento é validado com sucesso.
        """
        if self.tentativas_revalidacao > 0:
            self.tentativas_revalidacao = 0
            self.save(update_fields=['tentativas_revalidacao'])

class RegistroTempo(models.Model):
    """
    Modelo para registrar o histórico de tempo de cada etapa do processo
    """
    # TIPO_EVENTO_CHOICES = [
    #     ('cadastro', 'Cadastro do Candidato'),
    #     ('mensagem_enviada', 'Mensagem Enviada'),
    #     ('documento_solicitado', 'Documento Solicitado'),
    #     ('documento_recebido', 'Documento Recebido'),
    #     ('documento_validado', 'Documento Validado'),
    #     ('documento_invalidado', 'Documento Invalidado'),
    #     ('processo_concluido', 'Processo Concluído'),
    # ]

    TIPO_EVENTO_CHOICES = [
        ('cadastro', 'Cadastro do Candidato'),
        ('mensagem_enviada', 'Mensagem Enviada'),
        ('documento_solicitado', 'Documento Solicitado'),
        ('documento_recebido', 'Documento Recebido'),
        ('documento_validado', 'Documento Validado'),
        ('documento_invalidado', 'Documento Invalidado'),
        ('processo_concluido', 'Processo Concluído'),
        ('candidato_status_alterado', 'Status do Candidato Alterado'), # Adicionado
        ('documento_removido_substituido', 'Documento Removido/Substituído'), # Adicionado
        ('documento_nao_possui', 'Documento Não Possui'), # Adicionado
    ]
    candidato = models.ForeignKey(
        Candidato, 
        on_delete=models.CASCADE,
        related_name='registros_tempo'
    )
    documento = models.ForeignKey(
        Documento, 
        on_delete=models.CASCADE,
        related_name='registros_tempo',
        null=True, 
        blank=True
    )
    tipo_evento = models.CharField(max_length=50, choices=TIPO_EVENTO_CHOICES)
    data_hora = models.DateTimeField(default=timezone.now)
    status_anterior = models.CharField(max_length=50, blank=True, null=True)
    status_novo = models.CharField(max_length=50, blank=True, null=True)
    tempo_desde_evento_anterior = models.DurationField(null=True, blank=True)
    observacoes = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Registro de Tempo'
        verbose_name_plural = 'Registros de Tempo'
        ordering = ['-data_hora']

    def __str__(self):
        if self.documento:
            return f"{self.candidato.nome} - {self.get_tipo_evento_display()} - {self.documento.tipo.nome}"
        return f"{self.candidato.nome} - {self.get_tipo_evento_display()}"


class Setor(models.Model):
    nome = models.CharField(max_length=100)
    acesso_completo = models.BooleanField(default=False, help_text="Se marcado, usuários deste setor terão acesso ao dashboard, estatísticas e candidatos")
    
    def __str__(self):
        return self.nome
    
    class Meta:
        verbose_name = 'Setor'
        verbose_name_plural = 'Setores'

class PerfilUsuario(models.Model):
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    setor = models.ForeignKey(Setor, on_delete=models.SET_NULL, null=True, blank=True, related_name='usuarios')
    data_criacao = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.usuario.username} - {self.setor.nome if self.setor else 'Sem setor'}"
    
    class Meta:
        verbose_name = 'Perfil de Usuário'
        verbose_name_plural = 'Perfis de Usuários'

class MovimentacaoPessoal(models.Model):
    OCORRENCIA_CHOICES = [
        ('admissao_aumento', 'ADMISSÃO POR AUMENTO DE QUADRO'),
        ('admissao_substituicao', 'ADMISSÃO POR SUBSTITUIÇÃO'),
        ('desligamento', 'DESLIGAMENTO'),
        ('promocao', 'PROMOÇÃO / ENQUADRAMENTO'),
        ('transferencia', 'TRANSFERÊNCIA'),
    ]
    
    SEXO_CHOICES = [
        ('M', 'Masculino'),
        ('F', 'Feminino'),
        ('O', 'Outro'),
    ]
    
    ESTADO_CIVIL_CHOICES = [
        ('solteiro', 'Solteiro(a)'),
        ('casado', 'Casado(a)'),
        ('divorciado', 'Divorciado(a)'),
        ('viuvo', 'Viúvo(a)'),
        ('uniao_estavel', 'União Estável'),
    ]
    
    ESCOLARIDADE_CHOICES = [
        ('fundamental_incompleto', 'Fundamental Incompleto'),
        ('fundamental_completo', 'Fundamental Completo'),
        ('medio_incompleto', 'Médio Incompleto'),
        ('medio_completo', 'Médio Completo'),
        ('superior_incompleto', 'Superior Incompleto'),
        ('superior_completo', 'Superior Completo'),
        ('pos_graduacao', 'Pós-Graduação'),
        ('mestrado', 'Mestrado'),
        ('doutorado', 'Doutorado'),
    ]
    
    # Informações gerais
    data_emissao = models.DateField(default=timezone.now)
    ocorrencia = models.CharField(max_length=50, choices=OCORRENCIA_CHOICES)
    criado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='movimentacoes_criadas')
    
    # Campos para seleção do usuário
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='movimentacoes')
    
    # Campo A - Situação Proposta
    nome_candidato = models.ForeignKey(
        Candidato,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='movimentacoes'
    )
    
    # Campos para a seção A - Situação Proposta
    cargo_proposto = models.CharField(max_length=100, blank=True, null=True)
    area_proposta = models.CharField(max_length=100, blank=True, null=True)
    centro_custo_proposto = models.CharField(max_length=50, blank=True, null=True)
    salario_proposto = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    salario_por_hora = models.BooleanField(default=False)
    data_admissao = models.DateField(null=True, blank=True)
    
    # Campo B - Situação Atual (para substituição)
    nome_colaborador_substituido = models.CharField(max_length=200, blank=True, null=True)
    registro_substituido = models.CharField(max_length=50, blank=True, null=True)
    cargo_atual = models.CharField(max_length=100, blank=True, null=True)
    area_atual = models.CharField(max_length=100, blank=True, null=True)
    centro_custo_atual = models.CharField(max_length=50, blank=True, null=True)
    salario_atual = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Campo C - Desligamento
    ultimo_dia_trabalho = models.DateField(null=True, blank=True)
    motivo_desligamento = models.CharField(max_length=100, blank=True, null=True)
    
    # Campo D - Transferência/Promoção
    data_ultimo_reajuste = models.DateField(null=True, blank=True)
    percentual_reajuste = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    
    # Campo E - Admissão
    registro_admissao = models.CharField(max_length=50, blank=True, null=True)
    visto_data_admissao = models.DateField(null=True, blank=True)
    
    # Campo F - Requisitos do Cargo
    horario = models.CharField(max_length=50, blank=True, null=True)
    idade = models.IntegerField(null=True, blank=True)
    sexo = models.CharField(max_length=1, choices=SEXO_CHOICES, blank=True, null=True)
    estado_civil = models.CharField(max_length=20, choices=ESTADO_CIVIL_CHOICES, blank=True, null=True)
    escolaridade = models.CharField(max_length=30, choices=ESCOLARIDADE_CHOICES, blank=True, null=True)
    experiencia = models.TextField(blank=True, null=True)
    outros_requisitos = models.TextField(blank=True, null=True)
    
    # Campo G - Uso Exclusivo do RH
    codigo_cargo = models.CharField(max_length=50, blank=True, null=True)
    grupo_faixa = models.CharField(max_length=50, blank=True, null=True)
    confidencial = models.BooleanField(default=False)
    previsao_orcamentaria = models.BooleanField(default=False)
    
    # Campo H - Uso Exclusivo do Recrutamento e Seleção
    observacoes_recrutamento = models.TextField(blank=True, null=True)
    
    # Assinaturas e datas
    data_assinatura_coordenacao = models.DateField(null=True, blank=True)
    data_assinatura_gerencia = models.DateField(null=True, blank=True)
    data_assinatura_diretoria = models.DateField(null=True, blank=True)
    data_assinatura_rh = models.DateField(null=True, blank=True)
    
    # Fechamento da vaga
    data_fechamento_vaga = models.DateField(null=True, blank=True)
    
    # Metadados
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_atualizacao = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"MP-{self.id} - {self.get_ocorrencia_display()} - {self.nome_candidato}"
    
    class Meta:
        verbose_name = 'Movimentação de Pessoal'
        verbose_name_plural = 'Movimentações de Pessoal'

# Adicione este código no final do arquivo, após a definição dos modelos
@receiver(post_save, sender=Documento)
def documento_post_save(sender, instance, created, **kwargs):
    """
    Signal para registrar eventos de tempo quando um documento é salvo
    """
    from .utils.timeline import registrar_evento
    
    # Se for uma criação, registra o evento de solicitação
    if created:
        registrar_evento(
            candidato=instance.candidato,
            tipo_evento='documento_solicitado',
            documento=instance,
            status_novo=instance.status,
            observacoes=f"Documento {instance.tipo.nome} criado"
        )
    else:
        # Se não for uma criação, verifica se o status mudou
        try:
            old_instance = Documento.objects.get(pk=instance.pk)
            if old_instance.status != instance.status:
                # Determina o tipo de evento com base no novo status
                if instance.status == 'recebido':
                    tipo_evento = 'documento_recebido'
                elif instance.status == 'validado':
                    tipo_evento = 'documento_validado'
                elif instance.status == 'invalido':
                    tipo_evento = 'documento_invalidado'
                elif instance.status == 'nao_possui':
                    tipo_evento = 'documento_nao_possui'
                else:
                    tipo_evento = 'documento_solicitado'
                
                registrar_evento(
                    candidato=instance.candidato,
                    tipo_evento=tipo_evento,
                    documento=instance,
                    status_anterior=old_instance.status,
                    status_novo=instance.status,
                    observacoes=f"Status alterado de {old_instance.get_status_display()} para {instance.get_status_display()}"
                )
        except Documento.DoesNotExist:
            pass  # Documento não existia antes, não há o que comparar

@receiver(post_save, sender=Candidato)
def criar_controle_cobranca_candidato(sender, instance, created, **kwargs):
    """
    Signal para criar automaticamente controle de cobrança para candidatos
    """
    if created:
        ControleCobrancaCandidato.objects.get_or_create(
            candidato=instance,
            defaults={
                'cobranca_pausada': False,  # Ativo por padrão para novos candidatos
            }
        )
    else:
        ControleCobrancaCandidato.objects.get_or_create(
            candidato=instance,
            defaults={
                'cobranca_pausada': True,  # Pausado por padrão para candidatos existentes
            }
        )

def criar_controles_candidatos_existentes():
    """
    Função para criar controles de cobrança para todos os candidatos existentes
    que não possuem controle, marcando-os como pausados
    """
    from django.utils import timezone
    
    candidatos_sem_controle = Candidato.objects.filter(controle_cobranca__isnull=True)
    controles_criados = 0
    
    for candidato in candidatos_sem_controle:
        # Determinar se é candidato antigo ou novo baseado na data de cadastro
        # Considerar candidatos cadastrados antes de hoje como "existentes" (pausados)
        hoje = timezone.now().date()
        eh_candidato_antigo = candidato.data_cadastro.date() < hoje
        
        ControleCobrancaCandidato.objects.create(
            candidato=candidato,
            cobranca_pausada=eh_candidato_antigo,  # True para antigos, False para novos
        )
        controles_criados += 1
    
    return controles_criados

try:
    # Verificar se há candidatos sem controle de cobrança
    candidatos_sem_controle = Candidato.objects.filter(controle_cobranca__isnull=True).count()
    if candidatos_sem_controle > 0:
        controles_criados = criar_controles_candidatos_existentes()
        print(f"[AUTOMAÇÃO] Criados {controles_criados} controles de cobrança para candidatos existentes (pausados)")
except Exception as e:
    # Ignorar erros durante a inicialização (ex: tabelas não criadas ainda)
    pass

class ConfiguracaoCobranca(models.Model):
    """
    Configuração global do sistema de cobrança automática
    """
    DIAS_SEMANA_CHOICES = [
        (0, 'Segunda-feira'),
        (1, 'Terça-feira'),
        (2, 'Quarta-feira'),
        (3, 'Quinta-feira'),
        (4, 'Sexta-feira'),
        (5, 'Sábado'),
        (6, 'Domingo'),
    ]
    
    ativo = models.BooleanField(default=True, verbose_name='Automação Ativa')
    dias_semana = models.JSONField(
        default=list,  # Lista vazia como padrão
        verbose_name='Dias da Semana',
        help_text='Lista dos dias da semana para envio (0=Segunda, 1=Terça, etc.)'
    )
    horarios = models.JSONField(
        default=list,  # Lista vazia como padrão
        verbose_name='Horários de Disparo',
        help_text='Lista de horários no formato HH:MM'
    )
    mensagem_template = models.TextField(
        default='Olá {nome}, você ainda possui documentos pendentes: {documentos}. Por favor, envie-os o mais breve possível.',
        verbose_name='Template da Mensagem',
        help_text='Use {nome} para o nome do candidato e {documentos} para a lista de documentos'
    )
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_atualizacao = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Configuração de Cobrança'
        verbose_name_plural = 'Configurações de Cobrança'
    
    def __str__(self):
        status = "Ativa" if self.ativo else "Inativa"
        return f"Configuração de Cobrança - {status}"
    
    def save(self, *args, **kwargs):
        # Define valores padrão se as listas estiverem vazias
        if not self.dias_semana:
            self.dias_semana = [2]  # Quarta-feira como padrão
        if not self.horarios:
            self.horarios = ['10:00']  # 10:00 da manhã como padrão
        super().save(*args, **kwargs)
    
    def get_dias_semana_display(self):
        """Retorna os dias da semana formatados para exibição"""
        dias_nomes = {
            0: 'Segunda-feira',
            1: 'Terça-feira', 
            2: 'Quarta-feira',
            3: 'Quinta-feira',
            4: 'Sexta-feira',
            5: 'Sábado',
            6: 'Domingo'
        }
        if not self.dias_semana:
            return 'Nenhum dia selecionado'
        
        dias_selecionados = [dias_nomes.get(dia, f'Dia {dia}') for dia in self.dias_semana]
        return ', '.join(dias_selecionados)
    
    def get_horarios_display(self):
        """Retorna os horários formatados para exibição"""
        if not self.horarios:
            return 'Nenhum horário configurado'
        return ', '.join(self.horarios)

class ControleCobrancaCandidato(models.Model):
    """
    Controle individual de cobrança por candidato
    """
    candidato = models.OneToOneField(
        Candidato,
        on_delete=models.CASCADE,
        related_name='controle_cobranca'
    )
    cobranca_pausada = models.BooleanField(
        default=False,
        verbose_name='Cobrança Pausada'
    )
    data_pausa = models.DateTimeField(null=True, blank=True)
    pausado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cobranças_pausadas'
    )
    motivo_pausa = models.TextField(blank=True, null=True)
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_atualizacao = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Controle de Cobrança do Candidato'
        verbose_name_plural = 'Controles de Cobrança dos Candidatos'
    
    def __str__(self):
        status = "Pausada" if self.cobranca_pausada else "Ativa"
        return f"{self.candidato.nome} - Cobrança {status}"

class HistoricoCobranca(models.Model):
    """
    Histórico de cobranças enviadas
    """
    candidato = models.ForeignKey(
        Candidato,
        on_delete=models.CASCADE,
        related_name='historico_cobranças'
    )
    documentos_cobrados = models.JSONField(
        verbose_name='Documentos Cobrados',
        help_text='Lista dos tipos de documentos que foram cobrados'
    )
    mensagem_enviada = models.TextField(verbose_name='Mensagem Enviada')
    data_envio = models.DateTimeField(default=timezone.now)
    sucesso = models.BooleanField(default=True)
    erro = models.TextField(blank=True, null=True)
    
    class Meta:
        verbose_name = 'Histórico de Cobrança'
        verbose_name_plural = 'Histórico de Cobranças'
        ordering = ['-data_envio']
    
    def __str__(self):
        return f"{self.candidato.nome} - {self.data_envio.strftime('%d/%m/%Y %H:%M')}"


class AvaliacaoPeriodoExperiencia(models.Model):
    AVALIACAO_CHOICES = (
        (1, 'Sempre'),
        (2, 'Frequentemente'),
        (3, 'Raramente'),
        (4, 'Nunca'),
    )

    APROVA_DEMITE_CHOICES = (
        (1, 'Aprovar'),
        (2, 'Demitir'),
    )

    PRIMEIRA_SEGUNDA_AV_CHOICES = (
        (1, 'Primeira'),
        (2, 'Segunda'),
    )

    primeira_segunda_avaliacao = models.IntegerField(choices=PRIMEIRA_SEGUNDA_AV_CHOICES, null=False, blank=False)
    data_avaliacao = models.DateField(blank=False, default=timezone.now, null=True)
    data_termino_experiencia = models.DateField(blank=False)
    gestor_avaliador = models.CharField(max_length=100, unique=False)
    colaborador = models.CharField(max_length=100, unique=False)
    data_admissao = models.DateField(null=False, blank=False)
    cargo = models.CharField(max_length=100, unique=False)
    respondido = models.BooleanField(default=False, null=True)
    token = models.CharField(max_length=64, unique=True, help_text="Token único para identificar a pesquisa no email")

    # Campos do Formulário do RH
    apresenta_iniciativa = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    organizado_atividades = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    adapta_novas_situacoes_clientes = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    interage_bem_colegas = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    aptidao_lideranca = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    talento_para_funcao = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    pronto_para_colaborar = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    resultados_esperados = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    colabora_membros_empresa = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    comportamento_etico = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    desiste_facil = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    reduz_despesas_desperdicios = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    comunica_claro_coerente = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    administra_tempo = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    autoconfiante = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    empenho_resultados_grupo = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    aceita_opinioes_divergentes = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    relutante_decisoes_grupo = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    expor_necessidades_perguntas = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    assiduo = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)
    aceita_ordens_gestor = models.IntegerField(choices=AVALIACAO_CHOICES, null=True)

    sugestao_critica_elogio = models.TextField(blank=True, null=True)

    aprova_demite = models.IntegerField(choices=APROVA_DEMITE_CHOICES, null=True, blank=False)
    
    class Meta:
        verbose_name = "Avaliação de Experiência"
        verbose_name_plural = "Avaliações de Experiência"
    
    
    def __str__(self):
        status = "Respondida" if self.respondido else "Pendente"
        return f"{self.gestor_avaliador} - Avaliação de {self.colaborador} - {status}"
    
    def gerar_token(self):
        """Gera um token único para a pesquisa"""
        import uuid
        import hashlib
        
        if not self.token:
            unique_id = f"{uuid.uuid4()}"
            self.token = hashlib.sha256(unique_id.encode()).hexdigest()
        
        return self.token
    
    def save(self, *args, **kwargs):
        # Gera o token se for um novo registro
        if not self.pk:
            self.gerar_token()
        
        # Se os campos de avaliação estiverem preenchidos e não estiver marcado como respondido
        # if not self.respondido:
        #     self.respondido = True
        #     self.data_resposta = datetime.now()
        
              
        super().save(*args, **kwargs)