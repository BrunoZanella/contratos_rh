# main/urls.py



from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
# from django.contrib.auth import views as auth_views # Removido se não estiver em uso
# from rh import views # Removido se não estiver em uso, pois 'rh.urls' já é incluído

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('rh.urls')), # Inclui as URLs do seu aplicativo 'rh'
]

if settings.DEBUG:
    # Em desenvolvimento, o runserver do Django já serve arquivos estáticos de STATICFILES_DIRS.
    # Precisamos apenas servir explicitamente os arquivos de mídia aqui.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # A linha `urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)`
    # FOI REMOVIDA daqui para DEBUG=True, pois causa conflitos se 'collectstatic' não foi executado.
else:
    # Em produção, arquivos estáticos e de mídia devem ser servidos por um servidor web dedicado (ex: Nginx, Apache).
    # Esta configuração abaixo é para demonstração/pequenas implantações e NÃO é recomendada para produção em larga escala.
    from django.views.static import serve
    from django.urls import re_path
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
        re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT}), # Adicionado para servir estáticos em produção
    ]


'''
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings

from django.contrib.auth import views as auth_views
from rh import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('rh.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    from django.views.static import serve
    from django.urls import re_path

    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
'''