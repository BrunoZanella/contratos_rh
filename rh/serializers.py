# sua_app/serializers.py

from rest_framework import serializers
from .models import AvaliacaoPeriodoExperiencia

class CriarAvaliacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = AvaliacaoPeriodoExperiencia
        
        # Campos que a API irá ACEITAR na requisição para criar uma nova avaliação
        fields = [
            'primeira_segunda_avaliacao',
            'data_termino_experiencia',
            'gestor_avaliador',
            'colaborador',
            'data_admissao',
            'cargo',
        ]