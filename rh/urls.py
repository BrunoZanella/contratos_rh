from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('candidatos/', views.lista_candidatos, name='lista_candidatos'),
    path('candidatos/<int:candidato_id>/', views.detalhe_candidato, name='detalhe_candidato'),
    path('candidatos/<int:candidato_id>/editar/', views.editar_candidato, name='editar_candidato'),
    path('candidatos/<int:candidato_id>/documentos/novo/', 
         views.documento_crud, name='novo_documento'),
    path('candidatos/<int:candidato_id>/documentos/<int:documento_id>/editar/', 
         views.documento_crud, name='editar_documento'),
    path('candidatos/<int:candidato_id>/excluir/', 
         views.excluir_candidato, name='excluir_candidato'),
    path('webhook', views.webhook, name='webhook'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('candidatos/<int:candidato_id>/documentos/<int:documento_id>/atualizar-status/', views.atualizar_status_documento, name='atualizar_status_documento'),
    path('estatisticas/', views.estatisticas, name='estatisticas'),

     # path('candidatos/<int:candidato_id>/captura-foto/', views.captura_foto, name='captura_foto'),
     # path('candidatos/<int:candidato_id>/salvar-foto/', views.salvar_foto, name='salvar_foto'),
     path('candidato/<int:candidato_id>/timeline/', views.timeline_candidato, name='timeline_candidato'),
]