from django.db import models
from django.utils import timezone
import re
from django.core.exceptions import ValidationError

# Adicione este import no topo do arquivo
from django.db.models.signals import post_save
from django.dispatch import receiver


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
        ('ativo', 'Ativo'),  # Novo status para candidatos cadastrados sem mensagem enviada
        ('aguardando_inicio', 'Aguardando Início'),
        ('em_andamento', 'Em Andamento'),
        ('documentos_pendentes', 'Documentos Pendentes'),
        ('documentos_invalidos', 'Documentos Inválidos'),
        ('concluido', 'Concluído'),
    ]

    nome = models.CharField(max_length=200)
    telefone = models.CharField(max_length=20)
    email = models.EmailField()
    status = models.CharField(
        max_length=50, 
        choices=STATUS_CHOICES,
        default='ativo'  # Alterado para iniciar como ativo
    )
    data_cadastro = models.DateTimeField(default=timezone.now)
    data_ultima_atualizacao = models.DateTimeField(auto_now=True)
    mensagem_enviada = models.BooleanField(default=False)
    ultima_tentativa_mensagem = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.nome} - {self.get_status_display()}"

    class Meta:
        verbose_name = 'Candidato'
        verbose_name_plural = 'Candidatos'

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

class Documento(models.Model):
    TIPO_CHOICES = [
        ('rg', 'RG'),
        ('cpf', 'CPF'),
        ('cnh', 'CNH'),
        ('ctps', 'Carteira de Trabalho'),
        ('comprovante_residencia', 'Comprovante de Residência'),
        ('titulo_eleitor', 'Título de Eleitor'),
        ('foto_rosto', 'Foto do Rosto'),  # Novo tipo
        ('outros', 'Outros'),
    ]

    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('recebido', 'Recebido'),
        ('invalido', 'Inválido'),
        ('validado', 'Validado'),
    ]

    candidato = models.ForeignKey(
        Candidato, 
        on_delete=models.CASCADE,
        related_name='documentos'
    )
    tipo = models.CharField(max_length=50, choices=TIPO_CHOICES)
    arquivo = models.FileField(upload_to='documentos/', null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pendente'
    )
    observacoes = models.TextField(blank=True)
    data_envio = models.DateTimeField(null=True, blank=True)
    data_validacao = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.candidato.nome} - {self.get_tipo_display()}"

    class Meta:
        verbose_name = 'Documento'
        verbose_name_plural = 'Documentos'

class RegistroTempo(models.Model):
    """
    Modelo para registrar o histórico de tempo de cada etapa do processo
    """
    TIPO_EVENTO_CHOICES = [
        ('cadastro', 'Cadastro do Candidato'),
        ('mensagem_enviada', 'Mensagem Enviada'),
        ('documento_solicitado', 'Documento Solicitado'),
        ('documento_recebido', 'Documento Recebido'),
        ('documento_validado', 'Documento Validado'),
        ('documento_invalidado', 'Documento Invalidado'),
        ('processo_concluido', 'Processo Concluído'),
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
            return f"{self.candidato.nome} - {self.get_tipo_evento_display()} - {self.documento.get_tipo_display()}"
        return f"{self.candidato.nome} - {self.get_tipo_evento_display()}"

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
            observacoes=f"Documento {instance.get_tipo_display()} criado"
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