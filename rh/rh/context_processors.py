from .views import tem_acesso_completo

def adicionar_variaveis_globais(request):
    """Adiciona variáveis globais ao contexto"""
    return {
        'tem_acesso_completo': tem_acesso_completo(request.user) if request.user.is_authenticated else False
    }
