from reconhecer_imagem import analisar_arquivo

def main():
    # Caminho do arquivo a ser analisado
    
#    caminho_arquivo = "media/documentos_padrao/RG_nova.jpg" 
#    caminho_arquivo = "/home/bruno/contratos_rh/media/documentos/CNH_bruno_XS0IVoS.pdf"
#    caminho_arquivo = "/home/bruno/contratos_rh/media/documentos/reservista_bruno_Zanella_4bUjOmX.jpg"
#    caminho_arquivo = "/home/bruno/contratos_rh/media/documentos/Crea.pdf"
#    caminho_arquivo = "/home/bruno/contratos_rh/media/documentos/image.png"
#    caminho_arquivo = "/home/bruno/contratos_rh/media/documentos/outros_41.jpg"
#    caminho_arquivo = "/home/bruno/contratos_rh/media/documentos/outros_16_YTkgnD0.jpg"
#    caminho_arquivo = "/home/bruno/contratos_rh/media/documentos/outros_35_qxDkec8.jpg"
    caminho_arquivo = "/home/bruno/contratos_rh/media/documentos/foto_3x4_96_LLgnnti.jpg" # foto do rosto
#    caminho_arquivo = "/home/bruno/contratos_rh/media/documentos/foto_3x4_96_F6T6Aq7.jpg" # foto de crianca negra
#    caminho_arquivo = "/home/bruno/contratos_rh/media/documentos/foto_3x4_95_8Baw6rN.jpg" # foto 3x4
#    caminho_arquivo = "/home/bruno/contratos_rh/media/documentos/outros_120.jpg" # comprovante de agencia bancaria
#    caminho_arquivo = "/home/bruno/contratos_rh/media/documentos/outros_149.jpg" # reservista
#    caminho_arquivo = "/home/bruno/contratos_rh/media/documentos/comprovante_residencia_42.jpg" # comprovante de residencia ilegivel
#    caminho_arquivo = "/home/bruno/contratos_rh/media/documentos/comprovante_residencia_32.jpg" # comprovante de residencia legivel

    # Analisar o documento
    print(f"Analisando arquivo: {caminho_arquivo}")
    resultado = analisar_arquivo(caminho_arquivo)
    
    # Mostrar resultado
    print(f"\nTipo de Documento: {resultado}")

if __name__ == "__main__":
    main()
