import logging
import face_recognition
import numpy as np
from PIL import Image
import io
import os
import fitz # Import PyMuPDF

logger = logging.getLogger(__name__)

def _load_image_from_input(image_input):
    """
    Helper function to load an image from various inputs (file path, bytes, PIL.Image object),
    including converting the first page of a PDF to an image.
    Returns a NumPy array representing the image in RGB format.
    Raises ValueError or FileNotFoundError on failure.
    """
    if isinstance(image_input, str):
        if not os.path.exists(image_input):
            raise FileNotFoundError(f"Arquivo não encontrado: {image_input}")
        
        if image_input.lower().endswith('.pdf'):
            logger.info(f"Processando arquivo PDF: {image_input}")
            try:
                doc = fitz.open(image_input)
                if not doc.page_count:
                    raise ValueError("PDF não contém páginas.")
                page = doc.load_page(0) # Load the first page
                # Render page to a high-resolution pixmap (e.g., 300 DPI)
                pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72)) 
                img_bytes = pix.tobytes("png") # Convert to PNG bytes
                pil_image = Image.open(io.BytesIO(img_bytes))
                if pil_image.mode != 'RGB':
                    pil_image = pil_image.convert('RGB')
                doc.close()
                return np.array(pil_image)
            except Exception as e:
                raise ValueError(f"Erro ao processar PDF para imagem: {e}")
        else:
            logger.info(f"Processando arquivo de imagem: {image_input}")
            return face_recognition.load_image_file(image_input)
    elif isinstance(image_input, bytes):
        logger.info("Processando bytes de imagem")
        try:
            pil_image = Image.open(io.BytesIO(image_input))
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')
            return np.array(pil_image)
        except Exception as e:
            raise ValueError(f"Erro ao processar bytes da imagem: {e}")
    elif isinstance(image_input, Image.Image):
        logger.info("Processando objeto PIL Image")
        try:
            if image_input.mode != 'RGB':
                image_input = image_input.convert('RGB')
            return np.array(image_input)
        except Exception as e:
            raise ValueError(f"Erro ao processar objeto PIL Image: {e}")
    else:
        raise TypeError(f"Tipo de entrada não suportado: {type(image_input)}")

def recognize_face_in_image(image_input):
    """
    Reconhece faces em uma imagem e retorna informações sobre elas.
    Suporta arquivos de imagem e PDF (primeira página).
    """
    try:
        image = _load_image_from_input(image_input)

        logger.info("Detectando faces na imagem...")
        face_locations = face_recognition.face_locations(image)
        logger.info(f"Detectadas {len(face_locations)} face(s) na imagem.")
        
        if not face_locations:
            return True, "Nenhuma face detectada na imagem.", []
        
        logger.info("Extraindo encodings das faces...")
        face_encodings = face_recognition.face_encodings(image, face_locations)
        
        if len(face_encodings) != len(face_locations):
            logger.warning(f"Número de encodings ({len(face_encodings)}) diferente do número de faces ({len(face_locations)})")
        
        faces_info = []
        for i, (location, encoding) in enumerate(zip(face_locations, face_encodings)):
            face_info = {
                'location': location,  # (top, right, bottom, left)
                'encoding': encoding   # numpy array com 128 dimensões
            }
            faces_info.append(face_info)
            logger.debug(f"Face {i+1}: localização {location}, encoding shape: {encoding.shape}")
        
        logger.info(f"Processamento concluído: {len(faces_info)} face(s) processada(s) com sucesso.")
        return True, f"Detectadas {len(faces_info)} face(s) com sucesso.", faces_info
        
    except (FileNotFoundError, ValueError, TypeError) as e:
        logger.error(f"Erro ao carregar imagem para reconhecimento facial: {e}", exc_info=True)
        return False, f"Erro ao carregar imagem: {str(e)}", []
    except Exception as e:
        logger.error(f"Erro crítico ao processar imagem para reconhecimento facial: {e}", exc_info=True)
        return False, f"Erro crítico ao processar imagem: {str(e)}", []

def compare_faces(face_encoding1, face_encoding2, tolerance=0.6):
    """
    Compara dois encodings de faces e determina se são da mesma pessoa.
    """
    try:
        if face_encoding1 is None or face_encoding2 is None:
            logger.error("Um dos encodings de face é None")
            return False, float('inf')
        
        if len(face_encoding1) == 0 or len(face_encoding2) == 0:
            logger.error("Um dos encodings de face está vazio")
            return False, float('inf')
        
        logger.debug("Calculando distância entre encodings...")
        distance = face_recognition.face_distance([face_encoding1], face_encoding2)[0]
        
        match = distance <= tolerance
        
        logger.info(f"Comparação facial: distância={distance:.4f}, tolerância={tolerance}, match={match}")
        
        return match, float(distance)
        
    except Exception as e:
        logger.error(f"Erro crítico ao comparar faces: {e}", exc_info=True)
        return False, float('inf')

def validate_image_format(image_input):
    """
    Valida se a entrada é uma imagem válida, incluindo a primeira página de PDFs.
    """
    try:
        image_info = {}
        
        # Try to open the image to get its properties without converting to numpy array
        if isinstance(image_input, str):
            if not os.path.exists(image_input):
                return False, f"Arquivo não encontrado: {image_input}", {}
            
            if image_input.lower().endswith('.pdf'):
                try:
                    doc = fitz.open(image_input)
                    if not doc.page_count:
                        return False, "PDF não contém páginas.", {}
                    page = doc.load_page(0)
                    pix = page.get_pixmap()
                    img_bytes = pix.tobytes("png")
                    with Image.open(io.BytesIO(img_bytes)) as img:
                        image_info = {
                            'format': 'PDF_PAGE_PNG', # Indicate it came from PDF
                            'mode': img.mode,
                            'size': img.size,
                            'path': image_input
                        }
                    doc.close()
                except Exception as e:
                    return False, f"Erro ao abrir arquivo PDF: {str(e)}", {}
            else:
                try:
                    with Image.open(image_input) as img:
                        image_info = {
                            'format': img.format,
                            'mode': img.mode,
                            'size': img.size,
                            'path': image_input
                        }
                except Exception as e:
                    return False, f"Erro ao abrir arquivo de imagem: {str(e)}", {}
                    
        elif isinstance(image_input, bytes):
            try:
                with Image.open(io.BytesIO(image_input)) as img:
                    image_info = {
                        'format': img.format,
                        'mode': img.mode,
                        'size': img.size,
                        'source': 'bytes'
                    }
            except Exception as e:
                return False, f"Erro ao processar bytes da imagem: {str(e)}", {}
                
        elif isinstance(image_input, Image.Image):
            image_info = {
                'format': image_input.format,
                'mode': image_input.mode,
                'size': image_input.size,
                'source': 'PIL.Image'
            }
        else:
            return False, f"Tipo de entrada não suportado: {type(image_input)}", {}
        
        supported_formats = ['JPEG', 'PNG', 'JPG', 'BMP', 'TIFF', 'PDF_PAGE_PNG']
        if image_info.get('format') not in supported_formats:
            return False, f"Formato de imagem não suportado: {image_info.get('format')}. Suportados: {supported_formats}", image_info
        
        width, height = image_info.get('size', (0, 0))
        if width < 50 or height < 50:
            return False, f"Imagem muito pequena: {width}x{height}px (mínimo: 50x50px)", image_info
        
        return True, "Imagem válida", image_info
        
    except Exception as e:
        logger.error(f"Erro ao validar formato da imagem: {e}", exc_info=True)
        return False, f"Erro ao validar imagem: {str(e)}", {}

def get_face_landmarks(image_input):
    """
    Extrai pontos de referência (landmarks) das faces em uma imagem.
    Suporta arquivos de imagem e PDF (primeira página).
    """
    try:
        image = _load_image_from_input(image_input)
        
        face_landmarks_list = face_recognition.face_landmarks(image)
        
        if not face_landmarks_list:
            return True, "Nenhuma face detectada para extração de landmarks.", []
        
        logger.info(f"Landmarks extraídos de {len(face_landmarks_list)} face(s).")
        return True, f"Landmarks extraídos de {len(face_landmarks_list)} face(s) com sucesso.", face_landmarks_list
        
    except (FileNotFoundError, ValueError, TypeError) as e:
        logger.error(f"Erro ao carregar imagem para extração de landmarks: {e}", exc_info=True)
        return False, f"Erro ao carregar imagem: {str(e)}", []
    except Exception as e:
        logger.error(f"Erro ao extrair landmarks: {e}", exc_info=True)
        return False, f"Erro ao extrair landmarks: {str(e)}", []
