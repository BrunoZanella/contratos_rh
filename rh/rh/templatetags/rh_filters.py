# rh/templatetags/rh_filters.py
from django import template
from ..utils.timeline import formatar_duracao

register = template.Library()

@register.filter
def format_duration(value):
    """
    Filtro de template para formatar um objeto timedelta em uma string amigável.
    """
    return formatar_duracao(value)
