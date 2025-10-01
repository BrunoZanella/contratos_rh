from django.apps import AppConfig
import os
import sys


class RhConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'rh'

    def ready(self):
        import rh.signals
        
        # Verifica se deve iniciar a tarefa de revalidação
        # Evita iniciar em contextos inadequados como migrações, testes, etc.
        if self._should_start_background_tasks():
            # Importa e inicia a tarefa em segundo plano
            from .tasks import start_document_revalidation_task
            start_document_revalidation_task()
            print('Código de verificação de 12 horas iniciado!')
            
            from .automacao_cobranca import automacao_cobranca
            automacao_cobranca.start()
            print('Sistema de automação de cobrança iniciado!')

        else:
            print('Contexto inadequado para iniciar tarefas em segundo plano. Pulando...')

    def _should_start_background_tasks(self):
        """
        Determina se as tarefas em segundo plano devem ser iniciadas.
        Retorna False para contextos como migrações, testes, comandos específicos, etc.
        """
        # Lista de comandos onde NÃO devemos iniciar tarefas em segundo plano
        skip_commands = [
            'migrate',
            'makemigrations', 
            'test',
            'collectstatic',
            'shell',
            'dbshell',
            'createsuperuser',
            'loaddata',
            'dumpdata',
            'flush',
            'inspectdb',
            'showmigrations',
            'sqlmigrate',
            'squashmigrations',
            'check',
            'diffsettings',
            'help',
        ]
        
        # Verifica se estamos executando algum comando que deve pular as tarefas
        if len(sys.argv) > 1:
            command = sys.argv[1]
            if command in skip_commands:
                return False
        
        # Verifica se estamos em modo de teste
        if 'test' in sys.argv or os.environ.get('TESTING'):
            return False
            
        # Verifica se estamos executando migrações
        if 'migrate' in sys.argv:
            return False
            
        # Verifica se é um processo de desenvolvimento com auto-reload
        # O Django usa RUN_MAIN para indicar o processo principal no desenvolvimento
        if os.environ.get('RUN_MAIN') == 'true':
            return True
            
        # Em produção (sem RUN_MAIN), permite iniciar
        if os.environ.get('RUN_MAIN') is None:
            return True
            
        # Por padrão, não inicia (processo secundário do auto-reload)
        return False

# Versão comentada anterior para referência
# class RhConfig(AppConfig):
#     default_auto_field = 'django.db.models.BigAutoField'
#     name = 'rh'

#     def ready(self):
#         import rh.signals
