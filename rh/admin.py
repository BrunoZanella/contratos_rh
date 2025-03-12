from django.contrib import admin
from django.utils.html import format_html
from .models import Candidato, Documento, RegistroTempo
from .whatsapp import enviar_mensagem_whatsapp
from django.utils import timezone
from .utils.timeline import registrar_evento, formatar_duracao

class RegistroTempoInline(admin.TabularInline):
    model = RegistroTempo
    fk_name = 'documento'
    extra = 0
    readonly_fields = ['tipo_evento', 'data_hora', 'status_anterior', 'status_novo', 'tempo_formatado', 'observacoes']
    fields = ['tipo_evento', 'data_hora', 'status_anterior', 'status_novo', 'tempo_formatado', 'observacoes']
    can_delete = False
    max_num = 0  # Não permite adicionar novos registros manualmente
    verbose_name = "Histórico de Status"
    verbose_name_plural = "Histórico de Status"
    ordering = ['-data_hora']  # Mostra os registros mais recentes primeiro
    
    def tempo_formatado(self, obj):
        """Formata a duração para exibição"""
        return formatar_duracao(obj.tempo_desde_evento_anterior)
    
    tempo_formatado.short_description = "Tempo desde status anterior"
    
    def has_add_permission(self, request, obj=None):
        return False

@admin.register(Candidato)
class CandidatoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'telefone', 'status', 'data_cadastro']
    list_filter = ['status', 'data_cadastro']
    search_fields = ['nome', 'telefone', 'email']
    readonly_fields = ['data_cadastro', 'data_ultima_atualizacao']

    class Media:
        js = ('js/admin_actions.js',)
        css = {
            'all': ('css/admin_custom.css',)
        }

@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = [
        'candidato', 'tipo', 'status', 
        'data_envio', 'data_validacao'
    ]
    list_filter = ['status', 'tipo', 'data_envio']
    search_fields = ['candidato__nome', 'tipo']
    readonly_fields = ['data_envio', 'data_validacao']
    inlines = [RegistroTempoInline]

    def save_model(self, request, obj, form, change):
        if change and 'status' in form.changed_data:
            # Obtém o status anterior
            old_obj = Documento.objects.get(pk=obj.pk)
            old_status = old_obj.status
            
            # Atualiza as datas conforme o status
            if obj.status == 'validado' and not obj.data_validacao:
                obj.data_validacao = timezone.now()
            elif obj.status == 'recebido' and not obj.data_envio:
                obj.data_envio = timezone.now()
            
            # Salva o objeto
            super().save_model(request, obj, form, change)
            
            # Determina o tipo de evento com base no novo status
            if obj.status == 'recebido':
                tipo_evento = 'documento_recebido'
            elif obj.status == 'validado':
                tipo_evento = 'documento_validado'
            elif obj.status == 'invalido':
                tipo_evento = 'documento_invalidado'
            else:
                tipo_evento = 'documento_solicitado'
            
            # Registra o evento na timeline
            registrar_evento(
                candidato=obj.candidato,
                tipo_evento=tipo_evento,
                documento=obj,
                status_anterior=old_status,
                status_novo=obj.status,
                observacoes=f"Status alterado de '{dict(Documento.STATUS_CHOICES).get(old_status)}' para '{dict(Documento.STATUS_CHOICES).get(obj.status)}' por {request.user.username}"
            )
        else:
            super().save_model(request, obj, form, change)
            
            # Se for uma criação, registra o evento
            if not change:
                registrar_evento(
                    candidato=obj.candidato,
                    tipo_evento='documento_solicitado',
                    documento=obj,
                    status_novo=obj.status,
                    observacoes=f"Documento {obj.get_tipo_display()} criado por {request.user.username}"
                )

@admin.register(RegistroTempo)
class RegistroTempoAdmin(admin.ModelAdmin):
    list_display = ['candidato', 'documento', 'tipo_evento', 'data_hora', 'status_anterior', 'status_novo', 'tempo_formatado']
    list_filter = ['tipo_evento', 'data_hora', 'candidato']
    search_fields = ['candidato__nome', 'documento__tipo']
    readonly_fields = ['candidato', 'documento', 'tipo_evento', 'data_hora', 'status_anterior', 'status_novo', 'tempo_desde_evento_anterior', 'observacoes']
    
    def tempo_formatado(self, obj):
        """Formata a duração para exibição na lista"""
        return formatar_duracao(obj.tempo_desde_evento_anterior)
    
    tempo_formatado.short_description = "Tempo desde evento anterior"
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False