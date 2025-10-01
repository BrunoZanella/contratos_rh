#!/usr/bin/env python
"""
Script para reconhecimento e validação de documentos usando IA.
Este script pode ser executado diretamente para testar o reconhecimento
de documentos ou ser importado como módulo.
"""

import os
import sys
import argparse
from PIL import Image
import django

# Configurar o ambiente Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'main.settings')
django.setup()

from rh.utils.document_recognition import (
    process_document_file,
    validate_document_file,
    extract_data_from_document,
    get_normalized_document_type
)

from rh.models import Documento, TipoDocumento

def reconhecer_documento(caminho_arquivo):
    """
    Reconhece o tipo de um documento a partir do caminho do arquivo.
    
    Args:
        caminho_arquivo: Caminho para o arquivo do documento
        
    Returns:
        Resultado do reconhecimento
    """
    sucesso, mensagem, dados = process_document_file(caminho_arquivo)
    
    if sucesso:
        print(f"✅ {mensagem}")
        print(f"Confiança: {dados.get('confianca', 'N/A')}%")
        print(f"Qualidade: {dados.get('qualidade', 'N/A')}")
        
        # Verificar se há descrição especial
        if "descricao_especial" in dados:
            print(f"Descrição especial: {dados['descricao_especial']}")
    else:
        print(f"❌ {mensagem}")
    
    return dados

def validar_documento(caminho_arquivo, tipo_documento):
    """
    Valida um documento a partir do caminho do arquivo.
    
    Args:
        caminho_arquivo: Caminho para o arquivo do documento
        tipo_documento: Tipo de documento esperado
        
    Returns:
        Resultado da validação
    """
    tipo_normalizado = get_normalized_document_type(tipo_documento)
    valido, mensagem, dados = validate_document_file(caminho_arquivo, tipo_normalizado)
    
    if valido:
        print(f"✅ Documento válido: {tipo_normalizado}")
        print("Dados extraídos:")
        for chave, valor in dados.get("dados", {}).items():
            print(f"  {chave}: {valor}")
    else:
        print(f"❌ Documento inválido: {mensagem}")
    
    return dados

def validar_documentos_pendentes():
    """
    Valida todos os documentos pendentes no sistema.
    
    Returns:
        Número de documentos validados com sucesso
    """
    documentos_pendentes = Documento.objects.filter(status='recebido')
    total = documentos_pendentes.count()
    
    if total == 0:
        print("Não há documentos pendentes para validação.")
        return 0
    
    print(f"Encontrados {total} documentos pendentes para validação.")
    
    validados = 0
    for doc in documentos_pendentes:
        print(f"\nProcessando documento #{doc.id} - {doc.tipo.nome if doc.tipo else 'Tipo desconhecido'}")
        
        if not doc.arquivo:
            print("❌ Documento sem arquivo. Pulando...")
            continue
        
        try:
            from rh.utils.document_recognition import auto_validate_document
            
            sucesso, mensagem = auto_validate_document(doc)
            
            if sucesso:
                print(f"✅ Documento validado automaticamente: {mensagem}")
                doc.status = 'validado'
                doc.save()
                validados += 1
                
                # Registrar evento na timeline
                from rh.utils.timeline import registrar_evento
                registrar_evento(
                    candidato=doc.candidato,
                    tipo_evento='documento_validado',
                    documento=doc,
                    status_anterior='recebido',
                    status_novo='validado',
                    observacoes="Validação automática pela IA"
                )
            else:
                print(f"❌ Falha na validação automática: {mensagem}")
                
                # Se o documento for do tipo "outros" e tiver uma descrição especial
                if doc.tipo.nome.upper() == "OUTROS" and "militar" in doc.observacoes.lower():
                    print("🔍 Documento militar detectado, marcando como válido...")
                    doc.status = 'validado'
                    doc.save()
                    validados += 1
                    
                    # Registrar evento na timeline
                    from rh.utils.timeline import registrar_evento
                    registrar_evento(
                        candidato=doc.candidato,
                        tipo_evento='documento_validado',
                        documento=doc,
                        status_anterior='recebido',
                        status_novo='validado',
                        observacoes="Validação manual de documento militar"
                    )
        
        except Exception as e:
            print(f"❌ Erro ao processar documento: {str(e)}")
    
    print(f"\nResultado: {validados} de {total} documentos validados com sucesso.")
    return validados

def main():
    """Função principal para execução via linha de comando"""
    parser = argparse.ArgumentParser(description='Reconhecimento e validação de documentos')
    
    subparsers = parser.add_subparsers(dest='comando', help='Comandos disponíveis')
    
    # Comando para reconhecer um documento
    reconhecer_parser = subparsers.add_parser('reconhecer', help='Reconhecer tipo de documento')
    reconhecer_parser.add_argument('arquivo', help='Caminho para o arquivo do documento')
    
    # Comando para validar um documento
    validar_parser = subparsers.add_parser('validar', help='Validar um documento')
    validar_parser.add_argument('arquivo', help='Caminho para o arquivo do documento')
    validar_parser.add_argument('tipo', help='Tipo de documento esperado')
    
    # Comando para validar todos os documentos pendentes
    subparsers.add_parser('validar_pendentes', help='Validar todos os documentos pendentes')
    
    args = parser.parse_args()
    
    if args.comando == 'reconhecer':
        reconhecer_documento(args.arquivo)
    elif args.comando == 'validar':
        validar_documento(args.arquivo, args.tipo)
    elif args.comando == 'validar_pendentes':
        validar_documentos_pendentes()
    else:
        # Menu interativo se nenhum comando for fornecido
        while True:
            print("\n=== SISTEMA DE RECONHECIMENTO DE DOCUMENTOS ===")
            print("1. Reconhecer um documento")
            print("2. Validar um documento")
            print("3. Validar todos os documentos pendentes")
            print("0. Sair")
            
            opcao = input("\nEscolha uma opção: ")
            
            if opcao == "1":
                arquivo = input("Caminho do arquivo: ")
                reconhecer_documento(arquivo)
            elif opcao == "2":
                arquivo = input("Caminho do arquivo: ")
                tipo = input("Tipo de documento esperado: ")
                validar_documento(arquivo, tipo)
            elif opcao == "3":
                validar_documentos_pendentes()
            elif opcao == "0":
                break
            else:
                print("Opção inválida!")

if __name__ == "__main__":
    main()
