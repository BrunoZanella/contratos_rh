from django.contrib import admin
from .models import Candidato, Documento, RegistroTempo, Setor, PerfilUsuario, MovimentacaoPessoal, TipoDocumento, ConfiguracaoCobranca, ControleCobrancaCandidato, HistoricoCobranca, AvaliacaoPeriodoExperiencia
from .utils.timeline import formatar_duracao # Importa a função de formatação

class DocumentoInline(admin.TabularInline):
    model = Documento
    extra = 0

class RegistroTempoInline(admin.TabularInline):
    model = RegistroTempo
    extra = 0
    # Define um método customizado para exibir o tempo formatado
    def tempo_desde_alteracao_anterior_formatado(self, obj):
        return formatar_duracao(obj.tempo_desde_evento_anterior)
    tempo_desde_alteracao_anterior_formatado.short_description = 'Tempo desde alteração anterior' # Define o cabeçalho da coluna

    # Usa o método customizado nos campos somente leitura
    readonly_fields = ('data_hora', 'tipo_evento', 'status_anterior', 'status_novo', 'tempo_desde_alteracao_anterior_formatado', 'observacoes')

class DocumentoAdmin(admin.ModelAdmin):
    list_display = ('candidato', 'tipo', 'status', 'data_envio', 'data_validacao', 'tentativas_revalidacao')
    list_filter = ('status', 'tipo', 'tipo__tipo_contratacao')
    search_fields = ('candidato__nome', 'observacoes')

class CandidatoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'email', 'telefone', 'tipo_contratacao', 'status', 'data_cadastro')
    list_filter = ('status', 'tipo_contratacao', 'data_cadastro')
    search_fields = ('nome', 'email', 'telefone')
#    inlines = [DocumentoInline, RegistroTempoInline]
    inlines = [DocumentoInline]

class RegistroTempoAdmin(admin.ModelAdmin):
    # Define o método customizado para exibir o tempo formatado AQUI TAMBÉM
    def tempo_desde_alteracao_anterior_formatado(self, obj):
        return formatar_duracao(obj.tempo_desde_evento_anterior)
    tempo_desde_alteracao_anterior_formatado.short_description = 'Tempo desde alteração anterior' # Define o cabeçalho da coluna

    list_display = ('candidato', 'tipo_evento', 'data_hora', 'tempo_desde_alteracao_anterior_formatado')
    list_filter = ('tipo_evento', 'data_hora')
    search_fields = ('candidato__nome', 'observacoes')
    # Se você quiser que 'observacoes' seja somente leitura na lista principal, adicione-o aqui:
    # readonly_fields = ('tempo_desde_alteracao_anterior_formatado', 'observacoes')

class SetorAdmin(admin.ModelAdmin):
    list_display = ('nome', 'acesso_completo')
    list_filter = ('acesso_completo',)
    search_fields = ('nome',)

class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'setor', 'data_criacao')
    list_filter = ('setor', 'data_criacao')
    search_fields = ('usuario__username', 'usuario__email')

class MovimentacaoPessoalAdmin(admin.ModelAdmin):
    list_display = ('ocorrencia', 'nome_candidato', 'data_emissao', 'criado_por')
    list_filter = ('ocorrencia', 'data_emissao')
    search_fields = ('nome_candidato__nome', 'cargo_proposto', 'area_proposta')

class TipoDocumentoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'nome_exibicao', 'tipo_contratacao', 'ativo', 'obrigatorio')
    list_filter = ('ativo', 'tipo_contratacao', 'obrigatorio')
    search_fields = ('nome', 'nome_exibicao')
    list_editable = ('ativo', 'obrigatorio') # Adicionado para edição direta na lista

class ConfiguracaoCobrancaAdmin(admin.ModelAdmin):
    list_display = ('ativo', 'get_dias_semana', 'get_horarios', 'data_atualizacao')
    fieldsets = (
        ('Configurações Gerais', {
            'fields': ('ativo', 'dias_semana', 'horarios')
        }),
        ('Mensagem', {
            'fields': ('mensagem_template',)
        }),
    )
    
    def get_dias_semana(self, obj):
        dias_nomes = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
        return ', '.join([dias_nomes[dia] for dia in obj.dias_semana]) if obj.dias_semana else 'Nenhum'
    get_dias_semana.short_description = 'Dias da Semana'
    
    def get_horarios(self, obj):
        return ', '.join(obj.horarios) if obj.horarios else 'Nenhum'
    get_horarios.short_description = 'Horários'

class ControleCobrancaCandidatoAdmin(admin.ModelAdmin):
    list_display = ('candidato', 'cobranca_pausada', 'data_pausa', 'pausado_por')
    list_filter = ('cobranca_pausada', 'data_pausa')
    search_fields = ('candidato__nome', 'candidato__email')
    readonly_fields = ('data_criacao', 'data_atualizacao')

class HistoricoCobrancaAdmin(admin.ModelAdmin):
    list_display = ('candidato', 'data_envio', 'documentos_cobrados_count', 'sucesso')
    list_filter = ('sucesso', 'data_envio')
    search_fields = ('candidato__nome', 'candidato__email')
    readonly_fields = ('data_envio', 'documentos_cobrados', 'mensagem_enviada', 'sucesso', 'erro')
    
    def documentos_cobrados_count(self, obj):
        return len(obj.documentos_cobrados) if obj.documentos_cobrados else 0
    documentos_cobrados_count.short_description = 'Qtd Docs Cobrados'

class AvaliacaoPeriodoExperienciaAdmin(admin.ModelAdmin):
    list_display = ('data_avaliacao','data_termino_experiencia','gestor_avaliador','colaborador','data_admissao','cargo','respondido')
    list_filter = ('gestor_avaliador', 'colaborador', 'cargo', 'respondido')
    search_fields = ('gestor_avaliador', 'colaborador', 'cargo', 'respondido')


admin.site.register(Candidato, CandidatoAdmin)
admin.site.register(Documento, DocumentoAdmin)
admin.site.register(RegistroTempo, RegistroTempoAdmin)
admin.site.register(Setor, SetorAdmin)
admin.site.register(PerfilUsuario, PerfilUsuarioAdmin)
admin.site.register(MovimentacaoPessoal, MovimentacaoPessoalAdmin)
admin.site.register(TipoDocumento, TipoDocumentoAdmin)
admin.site.register(ConfiguracaoCobranca, ConfiguracaoCobrancaAdmin)
admin.site.register(ControleCobrancaCandidato, ControleCobrancaCandidatoAdmin)
admin.site.register(HistoricoCobranca, HistoricoCobrancaAdmin)
admin.site.register(AvaliacaoPeriodoExperiencia, AvaliacaoPeriodoExperienciaAdmin)