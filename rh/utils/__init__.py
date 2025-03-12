import cv2
import numpy as np
from google.cloud import vision
import io
from PIL import Image
import tensorflow as tf
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
from tensorflow.keras.applications import MobileNetV2
import requests

class ImageProcessor:
    def __init__(self):
        self.face_client = vision.ImageAnnotatorClient()
        self.model = MobileNetV2(weights='imagenet', include_top=True)
    
    def download_image(self, url):
        """Download imagem da URL do WhatsApp"""
        response = requests.get(url)
        if response.status_code == 200:
            return Image.open(io.BytesIO(response.content))
        return None
    
    def detect_face(self, image):
        """Detecta rosto usando Google Cloud Vision API"""
        if isinstance(image, str):  # Se for URL
            image = self.download_image(image)
            if image is None:
                return False, None
        
        # Converter para formato do Vision API
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format=image.format)
        img_byte_arr = img_byte_arr.getvalue()
        
        vision_image = vision.Image(content=img_byte_arr)
        
        try:
            # Detectar faces
            response = self.face_client.face_detection(image=vision_image)
            faces = response.face_annotations
            
            if not faces:
                return False, None
            
            # Verificar qualidade da primeira face
            face = faces[0]
            
            # Critérios de qualidade
            is_good_quality = (
                face.detection_confidence > 0.9 and  # Alta confiança na detecção
                face.landmarking_confidence > 0.9 and  # Pontos faciais bem definidos
                abs(face.roll_angle) < 15 and  # Rosto não muito inclinado
                abs(face.tilt_angle) < 15 and  # Rosto não muito inclinado
                abs(face.pan_angle) < 15 and  # Rosto olhando para frente
                face.under_exposed_likelihood <= 3 and  # Não subexposta
                face.blurred_likelihood <= 3  # Não borrada
            )
            
            return is_good_quality, face
            
        except Exception as e:
            print(f"Erro na detecção facial: {str(e)}")
            return False, None
    
    def is_document_photo(self, image):
        """Verifica se a imagem é de um documento"""
        if isinstance(image, str):  # Se for URL
            image = self.download_image(image)
            if image is None:
                return False
        
        # Converter para array numpy
        img_array = tf.keras.preprocessing.image.img_to_array(image)
        img_array = tf.image.resize(img_array, (224, 224))
        img_array = preprocess_input(img_array)
        img_array = tf.expand_dims(img_array, 0)
        
        # Fazer predição
        predictions = self.model.predict(img_array)
        decoded_predictions = tf.keras.applications.mobilenet_v2.decode_predictions(predictions)
        
        # Verificar se alguma das principais predições é relacionada a documentos
        document_related = ['id', 'passport', 'book', 'paper', 'document']
        for _, label, score in decoded_predictions[0]:
            if any(doc in label for doc in document_related) and score > 0.3:
                return True
        
        return False
    
    def validate_face_photo(self, image_url):
        """Valida se a imagem é uma boa foto de rosto"""
        try:
            # Detectar rosto
            is_good_quality, face = self.detect_face(image_url)
            if not is_good_quality:
                return False, "Qualidade da foto não atende aos requisitos"
            
            # Verificar se é foto de documento
            if self.is_document_photo(image_url):
                return False, "Parece ser uma foto de documento. Precisamos de uma foto do rosto"
            
            return True, "Foto válida"
            
        except Exception as e:
            return False, f"Erro ao processar imagem: {str(e)}"
