from reconhecer_imagem import analisar_arquivo

def main():
    # Caminho do arquivo a ser analisado
    caminho_arquivo = "media/documentos_padrao/Carteira_de_Trabalho.png"  # Substitua pelo caminho do seu arquivo
    
    # Analisar o documento
    print(f"Analisando arquivo: {caminho_arquivo}")
    resultado = analisar_arquivo(caminho_arquivo)
    
    # Mostrar resultado
    print(f"\nTipo de Documento: {resultado}")

if __name__ == "__main__":
    main()
