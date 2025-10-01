
'''

# rh/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import PerfilUsuario

@receiver(post_save, sender=User)
def ensure_perfil_usuario(sender, instance, created, **kwargs):
    # NÃO execute durante fixtures (loaddata/dumpdata) ou saves "raw"
    if kwargs.get('raw'):
        return
    # Garante 1:1 de forma idempotente
    PerfilUsuario.objects.get_or_create(usuario=instance)


from rh.models import Candidato, ControleCobrancaCandidato

@receiver(post_save, sender=Candidato)
def ensure_controle_cobranca(sender, instance, created, **kwargs):
    # NÃO rodar durante loaddata/dumpdata/etc (Django passa raw=True)
    if kwargs.get('raw'):
        return
    # Cria só quando o candidato é criado; idempotente
    if created:
        ControleCobrancaCandidato.objects.get_or_create(candidato=instance)


'''

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import PerfilUsuario

@receiver(post_save, sender=User)
def criar_perfil_usuario(sender, instance, created, **kwargs):
    if created:
        PerfilUsuario.objects.create(usuario=instance)

@receiver(post_save, sender=User)
def salvar_perfil_usuario(sender, instance, **kwargs):
    try:
        instance.perfil.save()
    except PerfilUsuario.DoesNotExist:
        PerfilUsuario.objects.create(usuario=instance)

