from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from .models import Candidato, Documento, MovimentacaoPessoal, Setor, PerfilUsuario, TipoDocumento, ConfiguracaoCobranca, ControleCobrancaCandidato
from django.db.models import Q

class CandidatoForm(forms.ModelForm):
    class Meta:
        model = Candidato
        fields = ['nome', 'telefone', 'email', 'tipo_contratacao']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'telefone': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300',
                'placeholder': '(11) 91234-5678'
            }),
            'email': forms.EmailInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'tipo_contratacao': forms.Select(attrs={'class': 'hidden'})  # Será controlado pelo toggle
        }

    def clean_telefone(self):
        telefone = self.cleaned_data['telefone']
        # Remove todos os caracteres não numéricos
        telefone = ''.join(filter(str.isdigit, telefone))
        
        # Verifica se o número tem o tamanho correto
        if len(telefone) not in [10, 11]:
            raise forms.ValidationError('Número de telefone inválido')
            
        return telefone

class DocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ['tipo', 'arquivo', 'status', 'observacoes']
        widgets = {
            'tipo': forms.Select(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'arquivo': forms.FileInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'status': forms.Select(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'observacoes': forms.Textarea(attrs={
                'class': 'w-full rounded-md border-gray-300',
                'rows': 3
            })
        }
    
    def __init__(self, *args, **kwargs):
        candidato = kwargs.pop('candidato', None)
        super().__init__(*args, **kwargs)
        
        # Filtrar tipos de documentos baseado no tipo de contratação do candidato
        if candidato and candidato.tipo_contratacao:
            self.fields['tipo'].queryset = TipoDocumento.get_documentos_por_tipo(candidato.tipo_contratacao)
        else:
            self.fields['tipo'].queryset = TipoDocumento.objects.filter(ativo=True)

class LoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'w-full rounded-md border-gray-300'})
    )

class RegisterForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'w-full rounded-md border-gray-300'})
    )
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']
        
    def __init__(self, *args, **kwargs):
        super(RegisterForm, self).__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'class': 'w-full rounded-md border-gray-300'})
        self.fields['password1'].widget.attrs.update({'class': 'w-full rounded-md border-gray-300'})
        self.fields['password2'].widget.attrs.update({'class': 'w-full rounded-md border-gray-300'})

class SetorForm(forms.ModelForm):
    class Meta:
        model = Setor
        fields = ['nome', 'acesso_completo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'acesso_completo': forms.CheckboxInput(attrs={'class': 'rounded border-gray-300 text-indigo-600'}),
        }

class UsuarioForm(forms.ModelForm):
    setor = forms.ModelChoiceField(
        queryset=Setor.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'w-full rounded-md border-gray-300'})
    )
    is_staff = forms.BooleanField(
        required=False, 
        label="Administrador",
        widget=forms.CheckboxInput(attrs={'class': 'rounded border-gray-300 text-indigo-600'})
    )
    
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'is_active', 'is_staff']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'email': forms.EmailInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'first_name': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'last_name': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'rounded border-gray-300 text-indigo-600'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            try:
                self.fields['setor'].initial = self.instance.perfil.setor
            except (PerfilUsuario.DoesNotExist, AttributeError):
                pass
    
    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            setor = self.cleaned_data.get('setor')
            perfil, created = PerfilUsuario.objects.get_or_create(usuario=user)
            perfil.setor = setor
            perfil.save()
        return user

class RegisterFormExtended(RegisterForm):
    setor = forms.ModelChoiceField(
        queryset=Setor.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'w-full rounded-md border-gray-300'})
    )
    
    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            setor = self.cleaned_data.get('setor')
            perfil, created = PerfilUsuario.objects.get_or_create(usuario=user)
            perfil.setor = setor
            perfil.save()
        return user

class MovimentacaoPessoalForm(forms.ModelForm):
    """Form para criar e editar movimentações de pessoal."""
    # Campos para edição dos dados do candidato
    nome_candidato = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
        required=False  # Alterado para False, validação será feita via JavaScript
    )
    
    email_candidato = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
        required=False  # Alterado para False, validação será feita via JavaScript
    )
    
    telefone_candidato = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
        required=False  # Alterado para False, validação será feita via JavaScript
    )
    
    candidato = forms.ModelChoiceField(
        queryset=Candidato.objects.all().order_by('nome'),
        required=False,
        empty_label="Selecione um candidato",
        widget=forms.Select(attrs={
            'class': 'w-full rounded-md border-gray-300',
            'hx-get': '/get-candidato-info/',
            'hx-target': '#candidato-info',
            'hx-trigger': 'change'
        })
    )
    
    class Meta:
        model = MovimentacaoPessoal
        exclude = ['criado_por', 'data_criacao', 'data_atualizacao', 'nome_candidato']  # Excluímos nome_candidato do formulário
        widgets = {
            'data_emissao': forms.DateInput(attrs={'class': 'w-full rounded-md border-gray-300', 'type': 'date'}),
            'ocorrencia': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300',
                'onchange': 'mostrarCamposRelevantes()'
            }),
            'cargo_proposto': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'area_proposta': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'centro_custo_proposto': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'salario_proposto': forms.NumberInput(attrs={'class': 'w-full rounded-md border-gray-300', 'step': '0.01'}),
            'salario_por_hora': forms.CheckboxInput(attrs={'class': 'rounded border-gray-300 text-indigo-600'}),
            'data_admissao': forms.DateInput(attrs={'class': 'w-full rounded-md border-gray-300', 'type': 'date'}),
            
            'nome_colaborador_substituido': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'registro_substituido': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'cargo_atual': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'area_atual': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'centro_custo_atual': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'salario_atual': forms.NumberInput(attrs={'class': 'w-full rounded-md border-gray-300', 'step': '0.01'}),
            
            'ultimo_dia_trabalho': forms.DateInput(attrs={'class': 'w-full rounded-md border-gray-300', 'type': 'date'}),
            'motivo_desligamento': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            
            'data_ultimo_reajuste': forms.DateInput(attrs={'class': 'w-full rounded-md border-gray-300', 'type': 'date'}),
            'percentual_reajuste': forms.NumberInput(attrs={'class': 'w-full rounded-md border-gray-300', 'step': '0.01'}),
            
            'registro_admissao': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'visto_data_admissao': forms.DateInput(attrs={'class': 'w-full rounded-md border-gray-300', 'type': 'date'}),
            
            'horario': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'idade': forms.NumberInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'sexo': forms.Select(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'estado_civil': forms.Select(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'escolaridade': forms.Select(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'experiencia': forms.Textarea(attrs={'class': 'w-full rounded-md border-gray-300', 'rows': 3}),
            'outros_requisitos': forms.Textarea(attrs={'class': 'w-full rounded-md border-gray-300', 'rows': 3}),
            
            'codigo_cargo': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'grupo_faixa': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'confidencial': forms.CheckboxInput(attrs={'class': 'rounded border-gray-300 text-indigo-600'}),
            'previsao_orcamentaria': forms.CheckboxInput(attrs={'class': 'rounded border-gray-300 text-indigo-600'}),
            
            'observacoes_recrutamento': forms.Textarea(attrs={'class': 'w-full rounded-md border-gray-300', 'rows': 3}),
            
            'data_assinatura_coordenacao': forms.DateInput(attrs={'class': 'w-full rounded-md border-gray-300', 'type': 'date'}),
            'data_assinatura_gerencia': forms.DateInput(attrs={'class': 'w-full rounded-md border-gray-300', 'type': 'date'}),
            'data_assinatura_diretoria': forms.DateInput(attrs={'class': 'w-full rounded-md border-gray-300', 'type': 'date'}),
            'data_assinatura_rh': forms.DateInput(attrs={'class': 'w-full rounded-md border-gray-300', 'type': 'date'}),
            
            'data_fechamento_vaga': forms.DateInput(attrs={'class': 'w-full rounded-md border-gray-300', 'type': 'date'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Tornar campos não obrigatórios para permitir o preenchimento dinâmico
        for field in self.fields:
            self.fields[field].required = False
        
        # Se já temos uma instância, preencher os campos do candidato
        if self.instance and self.instance.pk and self.instance.nome_candidato:
            candidato = self.instance.nome_candidato
            self.fields['candidato'].initial = candidato
            self.fields['nome_candidato'].initial = candidato.nome
            self.fields['email_candidato'].initial = candidato.email
            self.fields['telefone_candidato'].initial = candidato.telefone
    
    def clean(self):
        cleaned_data = super().clean()
        ocorrencia = cleaned_data.get('ocorrencia')
        
        # Validar campos obrigatórios com base na ocorrência
        if ocorrencia in ['admissao_aumento', 'admissao_substituicao']:
            # Validar campos da seção A
            nome_candidato = cleaned_data.get('nome_candidato')
            email_candidato = cleaned_data.get('email_candidato')
            telefone_candidato = cleaned_data.get('telefone_candidato')
            
            if not nome_candidato:
                self.add_error('nome_candidato', 'Este campo é obrigatório para admissões.')
            
            if not email_candidato:
                self.add_error('email_candidato', 'Este campo é obrigatório para admissões.')
            
            if not telefone_candidato:
                self.add_error('telefone_candidato', 'Este campo é obrigatório para admissões.')
        
        return cleaned_data
    
    def save(self, commit=True):
        mp = super().save(commit=False)
        
        # Salvar as alterações no candidato
        candidato_id = self.cleaned_data.get('candidato')
        if candidato_id:
            candidato = candidato_id  # Já é um objeto Candidato
            candidato.nome = self.cleaned_data['nome_candidato']
            candidato.email = self.cleaned_data['email_candidato']
            candidato.telefone = self.cleaned_data['telefone_candidato']
            if commit:
                candidato.save()
        
        if commit:
            mp.save()
        
        return mp

class TipoDocumentoForm(forms.ModelForm):
    class Meta:
        model = TipoDocumento
        fields = ['nome', 'nome_exibicao', 'tipo_contratacao', 'ativo', 'obrigatorio'] # Adicionado 'obrigatorio'
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'nome_exibicao': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'tipo_contratacao': forms.Select(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'rounded border-gray-300 text-indigo-600'}),
            'obrigatorio': forms.CheckboxInput(attrs={'class': 'rounded border-gray-300 text-indigo-600'}) # Adicionado widget
        }
        help_texts = {
            'nome': 'Código interno do tipo de documento (ex: RG, CPF, CTPS)',
            'nome_exibicao': 'Nome amigável para exibição (ex: Carteira de Identidade, Carteira de Trabalho)',
            'tipo_contratacao': 'Para qual tipo de contratação este documento é necessário',
            'obrigatorio': 'Marque se este documento for obrigatório para a conclusão do processo.' # Adicionado help_text
        }

class ConfiguracaoCobrancaForm(forms.ModelForm):
    """Formulário para configurar o sistema de cobrança automática"""
    
    class Meta:
        model = ConfiguracaoCobranca
        fields = ['ativo', 'mensagem_template']
        widgets = {
            'ativo': forms.CheckboxInput(attrs={
                'class': 'rounded border-gray-300 text-indigo-600'
            }),
            'mensagem_template': forms.Textarea(attrs={
                'class': 'w-full rounded-md border-gray-300',
                'rows': 6,
                'placeholder': 'Digite o template da mensagem...'
            })
        }
        labels = {
            'ativo': 'Sistema Ativo',
            'mensagem_template': 'Template da Mensagem'
        }
        help_texts = {
            'mensagem_template': 'Use {nome} para o nome do candidato e {documentos} para a lista de documentos pendentes'
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.fields['mensagem_template'].required = False
        
        if not self.instance.mensagem_template:
            self.fields['mensagem_template'].initial = 'Olá {nome}, você ainda possui documentos pendentes: {documentos}. Por favor, envie-os o mais breve possível.'
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        if hasattr(self, 'data'):
            # Processar dias da semana
            dias_semana = []
            dias_map = {
                'segunda': 0, 'terca': 1, 'quarta': 2, 'quinta': 3,
                'sexta': 4, 'sabado': 5, 'domingo': 6
            }
            
            for dia_nome, dia_num in dias_map.items():
                if self.data.get(dia_nome):
                    dias_semana.append(dia_num)
            
            if dias_semana:
                instance.dias_semana = dias_semana
            
            # Processar horários - corrigido para usar 'horario_envio' em vez de 'horarios'
            horario_envio = self.data.get('horario_envio')
            if horario_envio:
                # Salvar como lista com um único horário
                instance.horarios = [horario_envio]
        
        if commit:
            instance.save()
        
        return instance

class ControleCobrancaCandidatoForm(forms.ModelForm):
    """Formulário para pausar/reativar cobrança de candidato específico"""
    
    class Meta:
        model = ControleCobrancaCandidato
        fields = ['cobranca_pausada', 'motivo_pausa']
        widgets = {
            'cobranca_pausada': forms.CheckboxInput(attrs={
                'class': 'rounded border-gray-300 text-indigo-600'
            }),
            'motivo_pausa': forms.Textarea(attrs={
                'class': 'w-full rounded-md border-gray-300',
                'rows': 3,
                'placeholder': 'Motivo para pausar a cobrança automática...'
            })
        }
        help_texts = {
            'cobranca_pausada': 'Marque para pausar as cobranças automáticas para este candidato',
            'motivo_pausa': 'Opcional: descreva o motivo da pausa'
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Tornar motivo_pausa obrigatório apenas se cobranca_pausada for True
        self.fields['motivo_pausa'].required = False
    
    def clean(self):
        cleaned_data = super().clean()
        cobranca_pausada = cleaned_data.get('cobranca_pausada')
        motivo_pausa = cleaned_data.get('motivo_pausa')
        
        # Se pausar cobrança, motivo é recomendado mas não obrigatório
        if cobranca_pausada and not motivo_pausa:
            cleaned_data['motivo_pausa'] = 'Pausado pelo usuário'
        
        return cleaned_data
