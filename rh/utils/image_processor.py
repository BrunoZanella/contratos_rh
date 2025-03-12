import cv2
import numpy as np
import mediapipe as mp
from PIL import Image
import io
import requests
import tempfile
import os

class ImageProcessor:
    def __init__(self):
        # Inicializar detector facial do OpenCV
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        
        # Inicializar MediaPipe
        self.mp_face_detection = mp.solutions.face_detection
        self.mp_face = self.mp_face_detection.FaceDetection(
            min_detection_confidence=0.5,
            model_selection=1  # 0 para curta distância, 1 para até 5 metros
        )

    def download_image(self, url):
        """Download imagem da URL do WhatsApp"""
        try:
            response = requests.get(url)
            if response.status_code == 200:
                return Image.open(io.BytesIO(response.content))
            return None
        except Exception as e:
            print(f"Erro ao baixar imagem: {str(e)}")
            return None

    def convert_to_cv2(self, image):
        """Converte PIL Image para formato CV2"""
        if isinstance(image, str):  # Se for URL
            image = self.download_image(image)
            if image is None:
                return None
        elif isinstance(image, bytes):  # Se for bytes
            image = Image.open(io.BytesIO(image))
        elif not isinstance(image, Image.Image):  # Se não for PIL Image
            return None
        
        # Converter PIL para CV2
        opencv_img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        return opencv_img

    def detect_face_quality(self, image):
        """
        Detecta e analisa a qualidade da face usando OpenCV e MediaPipe
        Retorna: (bool, str) - (é_válida, mensagem)
        """
        try:
            cv2_image = self.convert_to_cv2(image)
            if cv2_image is None:
                return False, "Erro ao processar imagem"

            # Converter para RGB para MediaPipe
            rgb_image = cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB)
            height, width = cv2_image.shape[:2]

            # 1. Detecção com MediaPipe
            results = self.mp_face.process(rgb_image)
            
            if not results.detections:
                return False, "Nenhum rosto detectado na imagem"
            
            if len(results.detections) > 1:
                return False, "Mais de um rosto detectado na imagem"

            detection = results.detections[0]
            confidence = detection.score[0]

            if confidence < 0.7:
                return False, "Baixa confiança na detecção do rosto"

            # Obter coordenadas do rosto
            bbox = detection.location_data.relative_bounding_box
            x = int(bbox.xmin * width)
            y = int(bbox.ymin * height)
            w = int(bbox.width * width)
            h = int(bbox.height * height)

            # 2. Verificações de qualidade
            
            # Verificar tamanho relativo do rosto
            face_area_ratio = (w * h) / (width * height)
            if face_area_ratio < 0.1:
                return False, "Rosto muito pequeno na imagem, aproxime mais a câmera"
            if face_area_ratio > 0.7:
                return False, "Rosto muito próximo, afaste um pouco a câmera"

            # Verificar centralização
            center_x = x + w/2
            center_y = y + h/2
            
            if abs(center_x - width/2) > width * 0.2:
                return False, "Centralize melhor o rosto na imagem"
            
            if abs(center_y - height/2) > height * 0.2:
                return False, "Centralize melhor o rosto na imagem"

            # 3. Verificar iluminação
            face_roi = cv2_image[y:y+h, x:x+w]
            gray_roi = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
            
            # Calcular brilho médio
            brightness = np.mean(gray_roi)
            if brightness < 40:
                return False, "Imagem muito escura, melhore a iluminação"
            if brightness > 220:
                return False, "Imagem muito clara, evite luz direta"

            # Calcular contraste
            contrast = np.std(gray_roi)
            if contrast < 20:
                return False, "Baixo contraste na imagem, melhore a iluminação"

            return True, "Foto válida"

        except Exception as e:
            print(f"Erro ao processar imagem: {str(e)}")
            return False, f"Erro ao processar imagem: {str(e)}"

    def is_document_photo(self, image):
        """
        Verifica se a imagem parece ser de um documento
        usando características como proporção e bordas
        """
        try:
            cv2_image = self.convert_to_cv2(image)
            if cv2_image is None:
                return False

            # Converter para escala de cinza
            gray = cv2.cvtColor(cv2_image, cv2.COLOR_BGR2GRAY)
            
            # Detectar bordas
            edges = cv2.Canny(gray, 50, 150)
            
            # Encontrar contornos
            contours, _ = cv2.findContours(
                edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            
            if not contours:
                return False
            
            # Pegar maior contorno
            max_contour = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(max_contour)
            
            # Calcular proporção
            aspect_ratio = float(w)/h
            
            # Documentos geralmente têm proporção entre 1.4 e 1.7
            is_document_ratio = 1.3 <= aspect_ratio <= 1.8
            
            # Verificar se contorno ocupa maior parte da imagem
            area_ratio = (w * h) / (cv2_image.shape[0] * cv2_image.shape[1])
            has_document_area = area_ratio > 0.4
            
            return is_document_ratio and has_document_area

        except Exception as e:
            print(f"Erro ao verificar documento: {str(e)}")
            return False

    def validate_face_photo(self, image):
        """Valida se a imagem é uma boa foto de rosto"""
        try:
            # Primeiro verifica se é documento
            if self.is_document_photo(image):
                return False, "Parece ser uma foto de documento. Precisamos de uma foto do rosto"
            
            # Depois faz a análise facial
            is_valid, message = self.detect_face_quality(image)
            return is_valid, message
            
        except Exception as e:
            return False, f"Erro ao processar imagem: {str(e)}"