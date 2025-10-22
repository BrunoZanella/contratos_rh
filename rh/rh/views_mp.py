from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.models import User
from .models import MovimentacaoPessoal, Candidato, PerfilUsuario
from .forms import MovimentacaoPessoalForm
from django.template.loader import render_to_string
from django.db.models import Q

@login_required
def movimentacao_pessoal_form(request):
    """View para criar uma nova movimentação de pessoal"""
    if request.method == 'POST':
        form = MovimentacaoPessoalForm(request.POST)
        if form.is_valid():
            mp = form.save(commit=False)
            mp.criado_por = request.user
            
            # Obter o candidato selecionado
            candidato_id = request.POST.get('candidato')
            if candidato_id:
                try:
                    candidato = Candidato.objects.get(id=candidato_id)
                    # Atribuir o candidato ao campo nome_candidato (que é uma ForeignKey)
                    mp.nome_candidato = candidato
                    
                    # Atualizar os dados do candidato
                    candidato.nome = form.cleaned_data['nome_candidato']
                    candidato.email = form.cleaned_data['email_candidato']
                    candidato.telefone = form.cleaned_data['telefone_candidato']
                    candidato.save()
                except Candidato.DoesNotExist:
                    messages.error(request, "Candidato não encontrado.")
                    return render(request, 'movimentacao_pessoal_form.html', {
                        'form': form,
                        'is_new': True
                    })
            
            mp.save()
            messages.success(request, 'Movimentação de Pessoal criada com sucesso!')
            return redirect('lista_movimentacoes')
        else:
            # Se o formulário não for válido, exibir mensagens de erro
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro no campo {field}: {error}")
    else:
        form = MovimentacaoPessoalForm()
    
    return render(request, 'movimentacao_pessoal_form.html', {
        'form': form,
        'is_new': True
    })

@login_required
def editar_movimentacao_pessoal(request, mp_id):
    """View para editar uma movimentação de pessoal existente"""
    mp = get_object_or_404(MovimentacaoPessoal, id=mp_id)
    
    # Verificar se o usuário tem permissão para editar esta movimentação
    if not tem_permissao_movimentacao(request.user, mp):
        messages.error(request, "Você não tem permissão para editar esta movimentação.")
        return redirect('lista_movimentacoes')
    
    if request.method == 'POST':
        form = MovimentacaoPessoalForm(request.POST, instance=mp)
        if form.is_valid():
            mp = form.save(commit=False)
            
            # Obter o candidato selecionado
            candidato_id = request.POST.get('candidato')
            if candidato_id:
                try:
                    candidato = Candidato.objects.get(id=candidato_id)
                    # Atribuir o candidato ao campo nome_candidato (que é uma ForeignKey)
                    mp.nome_candidato = candidato
                    
                    # Atualizar os dados do candidato
                    candidato.nome = form.cleaned_data['nome_candidato']
                    candidato.email = form.cleaned_data['email_candidato']
                    candidato.telefone = form.cleaned_data['telefone_candidato']
                    candidato.save()
                except Candidato.DoesNotExist:
                    messages.error(request, "Candidato não encontrado.")
                    return render(request, 'movimentacao_pessoal_form.html', {
                        'form': form,
                        'mp': mp,
                        'is_new': False
                    })
            
            mp.save()
            messages.success(request, 'Movimentação de Pessoal atualizada com sucesso!')
            return redirect('lista_movimentacoes')
        else:
            # Se o formulário não for válido, exibir mensagens de erro
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro no campo {field}: {error}")
    else:
        form = MovimentacaoPessoalForm(instance=mp)
    
    return render(request, 'movimentacao_pessoal_form.html', {
        'form': form,
        'mp': mp,
        'is_new': False
    })

@login_required
def lista_movimentacoes(request):
    """View para listar todas as movimentações de pessoal"""
    # Verificar se o usuário é admin ou tem acesso completo
    if request.user.is_staff or tem_acesso_completo(request.user):
        # Admin ou usuário com acesso completo vê todas as movimentações
        movimentacoes = MovimentacaoPessoal.objects.all().order_by('-data_criacao')
    else:
        # Usuário normal vê apenas suas próprias movimentações
        movimentacoes = MovimentacaoPessoal.objects.filter(criado_por=request.user).order_by('-data_criacao')
    
    return render(request, 'lista_movimentacoes.html', {
        'movimentacoes': movimentacoes
    })

@login_required
def detalhe_movimentacao(request, mp_id):
    """View para exibir os detalhes de uma movimentação de pessoal"""
    mp = get_object_or_404(MovimentacaoPessoal, id=mp_id)
    
    # Verificar se o usuário tem permissão para ver esta movimentação
    if not tem_permissao_movimentacao(request.user, mp):
        messages.error(request, "Você não tem permissão para visualizar esta movimentação.")
        return redirect('lista_movimentacoes')
    
    return render(request, 'detalhe_movimentacao.html', {
        'mp': mp
    })

@login_required
def excluir_movimentacao(request, mp_id):
    """View para excluir uma movimentação de pessoal"""
    mp = get_object_or_404(MovimentacaoPessoal, id=mp_id)
    
    # Verificar se o usuário tem permissão para excluir esta movimentação
    if not tem_permissao_movimentacao(request.user, mp):
        messages.error(request, "Você não tem permissão para excluir esta movimentação.")
        return redirect('lista_movimentacoes')
    
    if request.method == 'POST':
        mp.delete()
        messages.success(request, 'Movimentação de Pessoal excluída com sucesso!')
        return redirect('lista_movimentacoes')
    
    return redirect('detalhe_movimentacao', mp_id=mp_id)

@login_required
def get_usuario_info(request):
    """View para obter informações do usuário via HTMX"""
    usuario_id = request.GET.get('usuario')
    
    if not usuario_id:
        return HttpResponse('')
    
    try:
        usuario = User.objects.get(id=usuario_id)
        
        # Retorna os dados do usuário em formato HTML para atualizar o formulário
        context = {
            'nome': usuario.get_full_name() or usuario.username,
            'email': usuario.email,
            'telefone': getattr(usuario, 'telefone', '')
        }
        
        return HttpResponse(render_to_string('usuario_info_snippet.html', context))
    
    except User.DoesNotExist:
        return HttpResponse('')

@login_required
def get_candidato_info(request):
    """View para obter informações do candidato via AJAX"""
    candidato_id = request.GET.get('candidato')
    
    if not candidato_id:
        return JsonResponse({})
    
    try:
        candidato = Candidato.objects.get(id=candidato_id)
        
        # Retorna os dados do candidato em formato JSON
        data = {
            'nome': candidato.nome,
            'email': candidato.email,
            'telefone': candidato.telefone
        }
        
        return JsonResponse(data)
    
    except Candidato.DoesNotExist:
        return JsonResponse({}, status=404)

@login_required
def search_candidatos(request):
    """View para buscar candidatos via AJAX"""
    term = request.GET.get('term', '')
    
    if not term:
        candidatos = Candidato.objects.all().order_by('nome')[:5]
    else:
        candidatos = Candidato.objects.filter(
            Q(nome__icontains=term) | 
            Q(email__icontains=term)
        ).order_by('nome')[:5]
    
    results = []
    for candidato in candidatos:
        results.append({
            'id': candidato.id,
            'nome': f"{candidato.nome} ({candidato.email})"
        })
    
    return JsonResponse(results, safe=False)

# Funções auxiliares para verificação de permissões
def tem_acesso_completo(usuario):
    """Verifica se o usuário tem acesso completo através do seu setor"""
    try:
        perfil = PerfilUsuario.objects.get(usuario=usuario)
        return perfil.setor and perfil.setor.acesso_completo
    except PerfilUsuario.DoesNotExist:
        return False

def tem_permissao_movimentacao(usuario, movimentacao):
    """Verifica se o usuário tem permissão para acessar uma movimentação específica"""
    # Admin ou criador da movimentação sempre tem acesso
    if usuario.is_staff or movimentacao.criado_por == usuario:
        return True
    
    # Usuário com acesso completo também tem acesso
    return tem_acesso_completo(usuario)
