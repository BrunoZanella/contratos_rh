"""
Middleware SSO para ser usado nos sites existentes.
Este arquivo deve ser copiado para cada um dos seus sites Django.
"""

import requests
import json
from django.shortcuts import redirect
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from django.contrib import messages
import logging

logger = logging.getLogger(__name__)

class SSOMiddleware(MiddlewareMixin):
    """
    Middleware para integração com o sistema SSO central
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        # Configurações do SSO (adicione no settings.py do seu site)
        self.sso_url = getattr(settings, 'SSO_URL', 'http://brg.datasetsolucoes.com.br:25002')
        self.site_domain = getattr(settings, 'SITE_DOMAIN', 'localhost')
        self.sso_enabled = getattr(settings, 'SSO_ENABLED', True)
        super().__init__(get_response)
    
    def process_request(self, request):
        """Processa requisições para verificar tokens SSO"""
        
        if not self.sso_enabled:
            return None
            
        # Verifica se há um token SSO na URL
        sso_token = request.GET.get('sso_token')
        
        if sso_token:
            return self.validate_sso_token(request, sso_token)
        
        # Se não está logado e não é uma página de API/admin, redireciona para SSO
        if not request.user.is_authenticated:
            # URLs que não precisam de autenticação
            exempt_urls = [
                '/api/',
                '/static/',
                '/media/',
                '/favicon.ico',
            ]
            
            # Verifica se a URL atual precisa de autenticação
            path = request.path
            if not any(path.startswith(url) for url in exempt_urls):
                # Redireciona para o sistema SSO
                sso_login_url = f"{self.sso_url}/login/?site={self.site_domain}&next={request.build_absolute_uri()}"
                return redirect(sso_login_url)
        
        return None
    
    def validate_sso_token(self, request, token):
        """Valida o token SSO com o servidor central"""
        try:
            # Faz requisição para validar o token
            response = requests.post(
                f"{self.sso_url}/api/validate-token/",
                json={
                    'token': token,
                    'site_domain': self.site_domain
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('valid'):
                    user_data = data.get('user')
                    
                    # Busca ou cria o usuário local
                    user, created = User.objects.get_or_create(
                        username=user_data['username'],
                        defaults={
                            'email': user_data['email'],
                            'first_name': user_data['first_name'],
                            'last_name': user_data['last_name'],
                            'is_staff': user_data['is_staff'],
                            'is_superuser': user_data['is_superuser'],
                        }
                    )
                    
                    # Atualiza dados do usuário se necessário
                    if not created:
                        user.email = user_data['email']
                        user.first_name = user_data['first_name']
                        user.last_name = user_data['last_name']
                        user.is_staff = user_data['is_staff']
                        user.is_superuser = user_data['is_superuser']
                        user.save()
                    
                    # Faz login do usuário
                    login(request, user)
                    
                    # Log do acesso
                    self.log_access(user_data['username'], True, request)
                    
                    # Remove o token da URL e redireciona
                    clean_url = request.build_absolute_uri().split('?')[0]
                    return redirect(clean_url)
                else:
                    # Token inválido
                    self.log_access('unknown', False, request, data.get('error', 'Token inválido'))
                    messages.error(request, 'Token de acesso inválido.')
                    return redirect(f"{self.sso_url}/login/?site={self.site_domain}")
            
        except requests.RequestException as e:
            # Erro na comunicação com o SSO
            logger.error(f"Erro na comunicação com SSO: {str(e)}")
            messages.error(request, 'Erro na autenticação. Tente novamente.')
            return redirect(f"{self.sso_url}/login/?site={self.site_domain}")
        
        return None
    
    def log_access(self, username, success, request, error_msg=''):
        """Registra tentativa de acesso no sistema central"""
        try:
            requests.post(
                f"{self.sso_url}/api/log-access/",
                json={
                    'username': username,
                    'site_domain': self.site_domain,
                    'success': success,
                    'ip_address': self.get_client_ip(request),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'observacoes': error_msg
                },
                timeout=5
            )
        except:
            pass  # Falha silenciosa no log
    
    def get_client_ip(self, request):
        """Obtém o IP do cliente"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
