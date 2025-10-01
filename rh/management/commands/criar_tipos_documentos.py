from django.core.management.base import BaseCommand
from rh.models import TipoDocumento

class Command(BaseCommand):
    help = 'Cria os tipos de documentos padrão para CLT e PJ'

    def handle(self, *args, **options):
        # Documentos para CLT
        documentos_clt = [
            ('foto_3x4', 'Foto 3x4'),
            ('carteira_trabalho_digital', 'Carteira de Trabalho Digital'),
            ('extrato_pis', 'Extrato do PIS - Caixa Econômica'),
            ('aso', 'ASO - Atestado de Saúde Ocupacional'),
            ('conta_salario', 'Conta Salário'),
            ('rg', 'RG - Carteira de Identidade'),
            ('cpf', 'CPF'),
            ('titulo_eleitor', 'Título de Eleitor'),
            ('reservista', 'Certificado de Reservista'),
            ('comprovante_escolaridade', 'Comprovante de Escolaridade'),
            ('certificados_cursos', 'Certificados de Cursos e NRs'),
            ('cnh', 'CNH - Carteira de Motorista'),
            ('cartao_vacinas', 'Cartão de Vacinas Atualizado'),
            ('comprovante_residencia', 'Comprovante de Residência'),
            ('certidao_casamento', 'Certidão de Casamento'),
            ('rg_cpf_esposa', 'RG e CPF da Esposa'),
            ('certidao_nascimento_filhos', 'Certidão de Nascimento dos Filhos'),
            ('carteira_vacinacao_filhos', 'Carteira de Vacinação dos Filhos'),
            ('declaracao_matricula_filhos', 'Declaração de Matrícula Escolar dos Filhos'),
        ]

        # Documentos para PJ
        documentos_pj = [
            ('foto_3x4', 'Foto 3x4'),
            ('cnpj', 'CNPJ'),
        #    ('conta_pix', 'Número da Conta e PIX'),
        #    ('email_contrato', 'E-mail para Envio do Contrato'),
            ('rg', 'RG - Carteira de Identidade'),
            ('cpf', 'CPF'),
            ('titulo_eleitor', 'Título de Eleitor'),
            ('comprovante_escolaridade', 'Comprovante de Escolaridade'),
            ('cnh', 'CNH - Carteira de Motorista'),
            ('comprovante_residencia', 'Comprovante de Residência'),
            ('reservista', 'Certificado de Reservista'),
            ('cartao_vacinas', 'Cartão de Vacinas Atualizado'),
            ('certidao_casamento', 'Certidão de Casamento'),
            ('rg_cpf_conjuge', 'RG e CPF do Cônjuge'),
            ('rg_cpf_filhos', 'RG e CPF dos Filhos'),
        ]

        self.stdout.write('Criando tipos de documentos para CLT...')
        for codigo, nome in documentos_clt:
            tipo_doc, created = TipoDocumento.objects.get_or_create(
                nome=codigo,
                defaults={
                    'nome_exibicao': nome,
                    'tipo_contratacao': 'clt',
                    'ativo': True
                }
            )
            if created:
                self.stdout.write(f'  ✓ Criado: {nome}')
            else:
                self.stdout.write(f'  - Já existe: {nome}')

        self.stdout.write('\nCriando tipos de documentos para PJ...')
        for codigo, nome in documentos_pj:
            tipo_doc, created = TipoDocumento.objects.get_or_create(
                nome=codigo,
                defaults={
                    'nome_exibicao': nome,
                    'tipo_contratacao': 'pj',
                    'ativo': True
                }
            )
            if created:
                self.stdout.write(f'  ✓ Criado: {nome}')
            else:
                # Atualizar se já existe mas com tipo diferente
                if tipo_doc.tipo_contratacao != 'pj':
                    tipo_doc.tipo_contratacao = 'ambos'
                    tipo_doc.save()
                    self.stdout.write(f'  ↻ Atualizado para "ambos": {nome}')
                else:
                    self.stdout.write(f'  - Já existe: {nome}')

        self.stdout.write(self.style.SUCCESS('\n✅ Tipos de documentos criados com sucesso!'))
