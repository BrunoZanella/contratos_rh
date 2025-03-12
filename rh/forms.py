from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from .models import Candidato, Documento

class CandidatoForm(forms.ModelForm):
    class Meta:
        model = Candidato
        fields = ['nome', 'telefone', 'email']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300'}),
            'telefone': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300',
                'placeholder': '(11) 91234-5678'
            }),
            'email': forms.EmailInput(attrs={'class': 'w-full rounded-md border-gray-300'})
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