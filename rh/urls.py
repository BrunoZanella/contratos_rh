from django.urls import path
from . import views
from . import views_mp, views_ai

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('candidatos/', views.lista_candidatos, name='lista_candidatos'),
    path('candidatos/<int:candidato_id>/', views.detalhe_candidato, name='detalhe_candidato'),
    path('candidatos/<int:candidato_id>/editar/', views.editar_candidato, name='editar_candidato'),
    path('candidatos/<int:candidato_id>/iniciar/', views.iniciar_processo, name='iniciar_processo'), 
    path('candidatos/<int:candidato_id>/documentos/novo/', 
         views.documento_crud, name='novo_documento'),
    path('candidatos/<int:candidato_id>/documentos/<int:documento_id>/editar/', 
         views.documento_crud, name='editar_documento'),
    path('candidatos/<int:candidato_id>/excluir/', 
         views.excluir_candidato, name='excluir_candidato'),
#     path('webhook', views.webhook, name='webhook'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('candidatos/<int:candidato_id>/documentos/<int:documento_id>/atualizar-status/', views.atualizar_status_documento, name='atualizar_status_documento'),
    path('estatisticas/', views.estatisticas, name='estatisticas'),

    # path('candidatos/<int:candidato_id>/captura-foto/', views.captura_foto, name='captura_foto'),
    # path('candidatos/<int:candidato_id>/salvar-foto/', views.salvar_foto, name='salvar_foto'),
    path('candidato/<int:candidato_id>/timeline/', views.timeline_candidato, name='timeline_candidato'),

    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-dashboard/setor/novo/', views.gerenciar_setor, name='novo_setor'),
    path('admin-dashboard/setor/<int:setor_id>/editar/', views.gerenciar_setor, name='editar_setor'),
    path('admin-dashboard/setor/<int:setor_id>/excluir/', views.excluir_setor, name='excluir_setor'),
    
    # Adicionar a URL para novo_usuario
    path('admin-dashboard/usuario/novo/', views.novo_usuario, name='novo_usuario'),
    
    path('admin-dashboard/usuario/<int:usuario_id>/editar/', views.gerenciar_usuario, name='editar_usuario'),
    path('admin-dashboard/usuario/<int:usuario_id>/excluir/', views.excluir_usuario, name='excluir_usuario'),
    path('admin-dashboard/usuario/<int:usuario_id>/ativar/', views.ativar_usuario, name='ativar_usuario'),
    path('meus-candidatos/', views.meus_candidatos, name='meus_candidatos'),
    
    # Novas URLs para listas filtradas
    path('admin-dashboard/setores/', views.listar_setores, name='listar_setores'),
    path('admin-dashboard/usuarios/', views.listar_usuarios, name='listar_usuarios'),
    path('admin-dashboard/administradores/', views.listar_administradores, name='listar_administradores'),
    path('admin-dashboard/usuarios-ativos/', views.listar_usuarios_ativos, name='listar_usuarios_ativos'),
    path('admin-dashboard/usuarios-pendentes/', views.listar_usuarios_pendentes, name='listar_usuarios_pendentes'),
    
    # Movimentação de Pessoal URLs
    path('movimentacao-pessoal/', views_mp.lista_movimentacoes, name='lista_movimentacoes'),
    path('movimentacao-pessoal/novo/', views_mp.movimentacao_pessoal_form, name='movimentacao_pessoal_form'),
    path('movimentacao-pessoal/<int:mp_id>/editar/', views_mp.editar_movimentacao_pessoal, name='editar_movimentacao'),
    path('movimentacao-pessoal/<int:mp_id>/', views_mp.detalhe_movimentacao, name='detalhe_movimentacao'),
    path('movimentacao-pessoal/<int:mp_id>/excluir/', views_mp.excluir_movimentacao, name='excluir_movimentacao'),
    path('get-usuario-info/', views_mp.get_usuario_info, name='get_usuario_info'),
    path('get-candidato-info/', views_mp.get_candidato_info, name='get_candidato_info'),
    path('search-candidatos/', views_mp.search_candidatos, name='search_candidatos'),
    
    # Tipos de Documentos
    path('tipos-documentos/', views.listar_tipos_documentos, name='listar_tipos_documentos'),
    path('tipos-documentos/novo/', views.gerenciar_tipo_documento, name='novo_tipo_documento'),
    path('tipos-documentos/<int:tipo_id>/', views.gerenciar_tipo_documento, name='editar_tipo_documento'),
    path('tipos-documentos/<int:tipo_id>/excluir/', views.excluir_tipo_documento, name='excluir_tipo_documento'),
    path('tipos-documentos/<int:tipo_id>/alternar-status/', views.alternar_status_tipo_documento, name='alternar_status_tipo_documento'),
    path('ajax/criar-tipo-documento/', views.ajax_criar_tipo_documento, name='ajax_criar_tipo_documento'),

    # Novas URLs para funcionalidades de IA
    path('documento/<int:documento_id>/analisar/', views_ai.analisar_documento, name='analisar_documento'),
    path('documento/<int:documento_id>/validar-ai/', views_ai.validar_documento_ai, name='validar_documento_ai'),
    path('documentos/validar-pendentes/', views_ai.validar_documentos_pendentes, name='validar_documentos_pendentes'),
    path('api/analisar-documento/', views_ai.api_analisar_documento, name='api_analisar_documento'),

    # URLs para configuração de cobrança (admin)
    path('admin-dashboard/cobranca/', views.configuracao_cobranca, name='configuracao_cobranca'),
    path('admin-dashboard/cobranca/historico/', views.historico_cobranca, name='historico_cobranca'),
    
    # URLs para controle individual de cobrança
    path('candidatos/<int:candidato_id>/pausar-cobranca/', views.pausar_cobranca_candidato, name='pausar_cobranca_candidato'),
    path('candidatos/<int:candidato_id>/reativar-cobranca/', views.reativar_cobranca_candidato, name='reativar_cobranca_candidato'),
    
    # URL para executar cobrança manual (para testes)
    path('admin-dashboard/cobranca/executar/', views.executar_cobranca_manual, name='executar_cobranca_manual'),
    
    path('admin-dashboard/cobranca/testar/', views.testar_envio_cobranca, name='testar_envio_cobranca'),

    path("candidatos/<int:candidato_id>/rejeitar/", views.rejeitar_candidato, name="rejeitar_candidato"),
    path("candidatos/<int:candidato_id>/remover_rejeicao/", views.remover_rejeicao_candidato, name="remover_rejeicao_candidato"),


    path('avaliacao/<str:token>/', views.avaliacao_experiencia, name='avaliacao_experiencia'),
    path('criar-avaliacao/', views.CriarAvaliacaoAPIView.as_view(), name='api_criar_avaliacao'),
    path('pesquisa/', views.pesquisa, name='pesquisa'),
    path('pesquisa-details/<str:token>', views.get_pesquisa_details, name='get_pesquisa_details'),

]
