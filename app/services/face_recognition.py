import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)

try:
    from insightface.app import FaceAnalysis
    HAS_INSIGHTFACE = True
except ImportError:
    HAS_INSIGHTFACE = False
    logger.warning("insightface não disponível")

# Try DeepFace first (best accuracy)
try:
    from deepface import DeepFace
    from deepface.commons import distance as dst
    HAS_DEEPFACE = True
    logger.info("DeepFace loaded successfully")
except ImportError as e:
    HAS_DEEPFACE = False
    logger.warning(f"DeepFace not available: {e}")

# Fallback to face_recognition (dlib)
try:
    import face_recognition
    HAS_FACE_RECOGNITION = True
except ImportError:
    HAS_FACE_RECOGNITION = False
    logger.warning("face_recognition (dlib) não disponível")

# Fallback to MediaPipe
try:
    import mediapipe as mp
    import mediapipe.solutions.face_detection as mp_face_detection
    HAS_MEDIAPIPE = True
except (ImportError, AttributeError):
    HAS_MEDIAPIPE = False
    logger.warning("mediapipe não disponível ou incompleto")


@dataclass
class FaceDetection:
    confidence: float
    x: int
    y: int
    w: int
    h: int
    landmarks: dict[str, tuple[int, int]] | None = None

    #: Embedding já calculado pelo detector, quando o backend produz os dois de
    #: uma vez (caso do InsightFace, cujo `.get()` devolve bbox e embedding na
    #: mesma passada). `extract_embedding()` reaproveita este valor em vez de
    #: rodar o modelo outra vez — e, mais importante, em vez de tentar detectar
    #: rosto de novo dentro de um recorte já apertado, o que NÃO funciona: o
    #: detector do InsightFace não encontra nada num crop onde o rosto ocupa
    #: quase todo o quadro, e o embedding acabava caindo no fallback HOG.
    embedding: np.ndarray | None = None


@dataclass
class FaceQualityMetrics:
    """Quality metrics for a detected face."""
    sharpness: float  # Laplacian variance
    brightness: float  # Mean pixel value
    contrast: float  # Standard deviation
    face_size_ratio: float  # Face area relative to image
    is_good_quality: bool


class FaceRecognitionService:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.fr_config = config.get("face_recognition", {})
        
        # DeepFace configuration
        self.model_name = self.fr_config.get("model", "Facenet512")
        self.detector_backend = self.fr_config.get("detector", "retinaface")
        self.distance_metric = self.fr_config.get("distance_metric", "cosine")
        self.threshold = self.fr_config.get("threshold", 0.4)
        self.enforce_detection = self.fr_config.get("enforce_detection", True)
        self.align = self.fr_config.get("align", True)
        self.normalization = self.fr_config.get("normalization", "base")
        
        self.anti_spoofing_config = config.get("anti_spoofing", {})
        self.anti_spoofing_enabled = self.anti_spoofing_config.get("enabled", True)

        # Permite (só para demonstração) que o fallback de histograma volte a
        # gerar "embeddings". Padrão: recusar - ver extract_embedding().
        self.allow_insecure_hog_embeddings = bool(
            self.fr_config.get("allow_insecure_hog_embeddings", False)
        )

        # Nitidez mínima (variância do Laplaciano) para aceitar um rosto.
        #
        # Calibrado contra fotos reais de cadastro, não escolhido no chute: o
        # valor anterior (100, fixo no código) recusava capturas de webcam
        # 640x480 com nitidez 66 e 87 que produzem embeddings perfeitamente
        # utilizáveis - as duas casaram entre si a distância 0.18, com o limiar de
        # reconhecimento em 0.40. Recusá-las significa que a pessoa não consegue
        # nem se cadastrar nem ser reconhecida. 40 mantém margem para barrar
        # borrão de verdade sem rejeitar rosto bom.
        self.min_sharpness = float(self.fr_config.get("min_sharpness", 40.0))
        
        self._initialized = False
        self._lock = threading.Lock()

        # Backend REALMENTE em uso, preenchido por initialize(). `model_name`/
        # `detector_backend` acima são o que foi *pedido* na configuração - se a
        # biblioteca correspondente não estiver instalada, o serviço cai para um
        # fallback e os dois valores deixam de descrever a realidade. Sem
        # registrar isso, /api/health anunciava "Facenet512" enquanto rodava
        # Haar cascade + histograma.
        self.detection_backend: str = "não inicializado"
        self.embedding_backend: str = "não inicializado"
        
        self._known_embeddings: dict[int, np.ndarray] = {}
        self._known_users: dict[int, str] = {}
        self._insightface_app = None
        
        # Frame history per camera for liveness detection
        self._frame_history: dict[str, np.ndarray] = {}
        
    #: Backend de embedding sem valor biométrico real: `_extract_hog_features()`
    #: devolve um histograma de intensidade em grade, não um vetor de identidade.
    #: Comparar isso com limiar de cosseno equivale a comparar textura e
    #: iluminação — reconhecimento nesse modo não é confiável.
    HOG_EMBEDDING_BACKEND = "opencv-hog (sem valor biométrico)"

    def _resolve_embedding_backend(self) -> str:
        """Qual backend `extract_embedding()` vai usar de fato.

        Espelha a ordem de prioridade de `extract_embedding()`. Fica separado de
        `detection_backend` porque os dois divergem: com MediaPipe, a detecção é
        MediaPipe mas o embedding cai em HOG.
        """
        if self._insightface_app is not None:
            return "insightface:buffalo_l"
        if HAS_DEEPFACE:
            return f"deepface:{self.model_name}"
        if HAS_FACE_RECOGNITION:
            return "face_recognition:dlib"
        return self.HOG_EMBEDDING_BACKEND

    @property
    def recognition_degraded(self) -> bool:
        """True quando os embeddings não têm valor biométrico (fallback HOG)."""
        return self.embedding_backend == self.HOG_EMBEDDING_BACKEND

    def get_backend_info(self) -> dict[str, Any]:
        """O que está REALMENTE em uso, para /api/health e para o log de startup."""
        return {
            "detection_backend": self.detection_backend,
            "embedding_backend": self.embedding_backend,
            "configured_model": self.model_name,
            "configured_detector": self.detector_backend,
            "degraded": self.recognition_degraded,
        }

    def _finish_initialization(self, detection_backend: str) -> bool:
        self.detection_backend = detection_backend
        self.embedding_backend = self._resolve_embedding_backend()
        self._initialized = True

        if self.recognition_degraded:
            logger.error(
                "RECONHECIMENTO DEGRADADO: detecção via '%s' e embeddings via "
                "'%s'. A configuração pede '%s'/'%s', mas nenhuma biblioteca de "
                "reconhecimento (insightface, deepface+tensorflow, "
                "face_recognition/dlib) está instalada. Os embeddings são "
                "histogramas de intensidade, não vetores de identidade: o "
                "sistema NÃO reconhece pessoas de forma confiável neste estado.",
                detection_backend, self.embedding_backend,
                self.model_name, self.detector_backend,
            )
        else:
            logger.info(
                "FaceRecognitionService pronto: detecção via '%s', embeddings via '%s'",
                detection_backend, self.embedding_backend,
            )
        return True

    def initialize(self) -> bool:
        global HAS_MEDIAPIPE
        if self._initialized:
            return True

        # Priority 0: InsightFace
        if HAS_INSIGHTFACE:
            try:
                self._insightface_app = FaceAnalysis(name="buffalo_l")
                self._insightface_app.prepare(ctx_id=0, det_size=(640, 640))
                return self._finish_initialization("insightface:buffalo_l")
            except Exception as e:
                logger.error(f"Error initializing InsightFace: {e}")
                self._insightface_app = None

        # Priority 1: DeepFace (best accuracy)
        if HAS_DEEPFACE:
            try:
                # Test DeepFace with a blank image to trigger model download
                logger.info("Initializing DeepFace models (this may take a moment)...")
                test_img = np.ones((100, 100, 3), dtype=np.uint8) * 128
                try:
                    DeepFace.detectFace(test_img, detector_backend=self.detector_backend, enforce_detection=False)
                except:
                    pass  # Expected to fail on blank image

                return self._finish_initialization(f"deepface:{self.detector_backend}")
            except Exception as e:
                logger.error(f"Error initializing DeepFace: {e}")
        
        # Priority 2: face_recognition (dlib)
        if HAS_FACE_RECOGNITION:
            return self._finish_initialization("face_recognition:dlib")
        
        # Priority 3: MediaPipe
        if HAS_MEDIAPIPE:
            try:
                self.mp_face_detection = mp.solutions.face_detection.FaceDetection(
                    model_selection=1, min_detection_confidence=0.5
                )
                # MediaPipe só detecta: o embedding cai no fallback HOG. É por
                # isso que _finish_initialization avalia os dois separadamente.
                return self._finish_initialization("mediapipe")
            except Exception as e:
                logger.error(f"Error initializing MediaPipe: {e}")
                HAS_MEDIAPIPE = False
            
        # Fallback 4: OpenCV Haar Cascades.
        # O OpenCV 5.0 removeu CascadeClassifier das bindings Python, então este
        # último recurso pode simplesmente não existir. Sem o guarda, a
        # AttributeError sobe de initialize() e o serviço não inicializa de forma
        # nenhuma — pior que assumir o estado degradado e dizê-lo.
        if not hasattr(cv2, "CascadeClassifier"):
            self.face_cascade = None
            logger.error(
                "Nenhum backend de detecção disponível: cv2.CascadeClassifier não "
                "existe nesta versão do OpenCV (%s, removido na linha 5.x) e nenhuma "
                "biblioteca de reconhecimento está instalada. Instale "
                "requirements-recognition.txt ou fixe opencv-python na linha 4.x.",
                cv2.__version__,
            )
            return self._finish_initialization("nenhum (OpenCV sem CascadeClassifier)")

        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        self.face_cascade = cv2.CascadeClassifier(cascade_path)
        return self._finish_initialization("opencv-haar")
    
    def load_known_faces(self, embeddings_data: list[dict[str, Any]]) -> bool:
        try:
            with self._lock:
                self._known_embeddings.clear()
                self._known_users.clear()
                
                for emb_data in embeddings_data:
                    user_id = emb_data.get("user_id")
                    embedding = emb_data.get("embedding_data")
                    
                    if user_id and embedding:
                        self._known_embeddings[user_id] = np.array(embedding)
                        self._known_users[user_id] = emb_data.get("user_name", "")
                
                logger.info(f"Carregados {len(self._known_embeddings)} rostos conhecidos")
                return True
        except Exception as e:
            logger.error(f"Erro ao carregar rostos conhecidos: {e}")
            return False
    
    @staticmethod
    def _iou(box_a: tuple[int, int, int, int], box_b: tuple[int, int, int, int]) -> float:
        """Interseção sobre união de duas caixas (x, y, w, h)."""
        ax, ay, aw, ah = box_a
        bx, by, bw, bh = box_b
        ix1, iy1 = max(ax, bx), max(ay, by)
        ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0.0
        union = aw * ah + bw * bh - inter
        return inter / union if union > 0 else 0.0

    def _insightface_embedding_for(
        self, frame: np.ndarray, detection: FaceDetection, min_iou: float = 0.3
    ) -> np.ndarray | None:
        """Embedding do InsightFace para a detecção pedida, rodando no frame todo.

        Roda `.get()` na imagem completa (a única forma que funciona: o detector
        precisa do contexto ao redor do rosto) e devolve o embedding do rosto com
        maior sobreposição com `detection`.
        """
        faces = self._insightface_app.get(frame)
        if not faces:
            return None

        target = (detection.x, detection.y, detection.w, detection.h)
        best, best_iou = None, 0.0
        for face in faces:
            fx1, fy1, fx2, fy2 = [int(v) for v in face.bbox]
            iou = self._iou(target, (fx1, fy1, max(0, fx2 - fx1), max(0, fy2 - fy1)))
            if iou > best_iou:
                best, best_iou = face, iou

        if best is None or best_iou < min_iou:
            return None
        emb = getattr(best, "normed_embedding", None)
        return None if emb is None else np.asarray(emb, dtype=np.float32)

    def _normalize_embedding(self, embedding: np.ndarray) -> np.ndarray:
        """L2 normalize an embedding vector."""
        norm = np.linalg.norm(embedding)
        if norm > 0:
            return embedding / norm
        return embedding
    
    def detect_faces(self, frame: np.ndarray) -> list[FaceDetection]:
        """Detect faces using available backend (DeepFace priority)."""
        detections = []

        # Priority 0: InsightFace
        if self._insightface_app is not None:
            try:
                faces = self._insightface_app.get(frame)
                for face in faces:
                    x1, y1, x2, y2 = [int(v) for v in face.bbox]
                    # `normed_embedding` já vem pronto e L2-normalizado (512-d):
                    # carregamos junto para extract_embedding() não precisar
                    # redetectar num recorte (onde falharia).
                    emb = getattr(face, "normed_embedding", None)
                    detections.append(
                        FaceDetection(
                            confidence=float(getattr(face, "det_score", 0.9)),
                            x=x1,
                            y=y1,
                            w=max(0, x2 - x1),
                            h=max(0, y2 - y1),
                            embedding=(
                                None if emb is None
                                else np.asarray(emb, dtype=np.float32)
                            ),
                        )
                    )
                return detections
            except Exception as e:
                logger.error(f"InsightFace detection error: {e}")
        
        # Priority 1: DeepFace
        if HAS_DEEPFACE:
            try:
                face_objs = DeepFace.extract_faces(
                    frame,
                    detector_backend=self.detector_backend,
                    enforce_detection=False,
                    align=self.align,
                    expand_percentage=10
                )
                
                for face_obj in face_objs:
                    facial_area = face_obj.get("facial_area", {})
                    confidence = face_obj.get("confidence", 0.8)
                    
                    x = facial_area.get("x", 0)
                    y = facial_area.get("y", 0)
                    w = facial_area.get("w", 0)
                    h = facial_area.get("h", 0)
                    
                    detections.append(FaceDetection(
                        confidence=float(confidence),
                        x=int(x),
                        y=int(y),
                        w=int(w),
                        h=int(h)
                    ))
                return detections
            except Exception as e:
                logger.error(f"DeepFace detection error: {e}")
        
        # Priority 2: face_recognition (dlib)
        if HAS_FACE_RECOGNITION:
            try:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                face_locations = face_recognition.face_locations(rgb_frame, model="hog")
                
                for face_location in face_locations:
                    top, right, bottom, left = face_location
                    detections.append(FaceDetection(
                        confidence=0.9,
                        x=left,
                        y=top,
                        w=right - left,
                        h=bottom - top
                    ))
            except Exception as e:
                logger.error(f"Erro na detecção com face_recognition: {e}")
                
        elif HAS_MEDIAPIPE:
            try:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = self.mp_face_detection.process(rgb_frame)
                
                if results.detections:
                    h_frame, w_frame, _ = frame.shape
                    for detection in results.detections:
                        bbox = detection.location_data.relative_bounding_box
                        detections.append(FaceDetection(
                            confidence=detection.score[0],
                            x=int(bbox.xmin * w_frame),
                            y=int(bbox.ymin * h_frame),
                            w=int(bbox.width * w_frame),
                            h=int(bbox.height * h_frame)
                        ))
            except Exception as e:
                logger.error(f"Erro na detecção com MediaPipe: {e}")
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
            )
            
            for (x, y, w, h) in faces:
                detections.append(FaceDetection(
                    confidence=0.7,
                    x=x,
                    y=y,
                    w=w,
                    h=h
                ))
        
        return detections
    
    def assess_face_quality(self, frame: np.ndarray, face_detection: FaceDetection) -> FaceQualityMetrics:
        """Assess the quality of a detected face (sharpness, brightness, contrast, size)."""
        try:
            x, y, w, h = face_detection.x, face_detection.y, face_detection.w, face_detection.h
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(frame.shape[1], x + w), min(frame.shape[0], y + h)

            face_crop = frame[y1:y2, x1:x2]
            if face_crop.size == 0:
                return FaceQualityMetrics(0, 0, 0, 0, False)

            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)

            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            brightness = np.mean(gray)
            contrast = np.std(gray)

            img_area = frame.shape[0] * frame.shape[1]
            face_area = w * h
            size_ratio = face_area / img_area if img_area > 0 else 0

            is_good = (
                laplacian_var > self.min_sharpness and
                40 < brightness < 250 and  # Not too dark/bright
                contrast > 20 and  # Some variation
                size_ratio > 0.01  # Face is at least 1% of image
            )

            return FaceQualityMetrics(
                sharpness=float(laplacian_var),
                brightness=float(brightness),
                contrast=float(contrast),
                face_size_ratio=float(size_ratio),
                is_good_quality=is_good
            )
        except Exception as e:
            logger.error(f"Error assessing face quality: {e}")
            return FaceQualityMetrics(0, 0, 0, 0, False)

    def extract_embedding(self, frame: np.ndarray, face_detection: FaceDetection,
                          skip_quality_check: bool = False) -> np.ndarray | None:
        """Extract face embedding using available backend (DeepFace priority)."""
        try:
            if not skip_quality_check:
                quality = self.assess_face_quality(frame, face_detection)
                if not quality.is_good_quality:
                    logger.info(
                        f"Rosto descartado por qualidade insuficiente "
                        f"(nitidez={quality.sharpness:.1f}, brilho={quality.brightness:.1f}, "
                        f"contraste={quality.contrast:.1f}, tamanho={quality.face_size_ratio:.3f})"
                    )
                    return None

            x, y, w, h = face_detection.x, face_detection.y, face_detection.w, face_detection.h

            padding_x = int(w * 0.1)
            padding_y = int(h * 0.1)

            x1 = max(0, x - padding_x)
            y1 = max(0, y - padding_y)
            x2 = min(frame.shape[1], x + w + padding_x)
            y2 = min(frame.shape[0], y + h + padding_y)

            face_crop = frame[y1:y2, x1:x2]

            if face_crop.size == 0:
                return None

            # Priority 0: InsightFace, reaproveitando o embedding que o próprio
            # detector já produziu para esta detecção.
            #
            # A versão anterior chamava `.get(face_crop)` aqui: pedir ao detector
            # que achasse um rosto dentro de um recorte onde o rosto ocupa quase
            # todo o quadro devolve ZERO rostos (verificado com fotos reais), e o
            # embedding caía silenciosamente no fallback HOG. Ou seja: o sistema
            # rodava com InsightFace instalado e ativo e ainda assim comparava
            # histogramas de intensidade.
            if face_detection.embedding is not None:
                return self._normalize_embedding(face_detection.embedding)

            if self._insightface_app is not None:
                try:
                    # Sem embedding pré-calculado (ex.: detecção veio de outro
                    # backend): rode no frame COMPLETO e escolha o rosto de maior
                    # sobreposição com a detecção pedida - nunca no recorte.
                    emb = self._insightface_embedding_for(frame, face_detection)
                    if emb is not None:
                        return self._normalize_embedding(emb)
                    logger.warning(
                        "InsightFace não encontrou rosto correspondente à detecção "
                        "(%d,%d,%d,%d) no frame; caindo para o próximo backend",
                        x, y, w, h,
                    )
                except Exception as e:
                    logger.error(f"InsightFace embedding error: {e}")

            # Priority 1: DeepFace
            if HAS_DEEPFACE:
                try:
                    embedding_objs = DeepFace.represent(
                        face_crop,
                        model_name=self.model_name,
                        enforce_detection=False,
                        detector_backend=self.detector_backend,
                        align=self.align,
                        normalization=self.normalization
                    )
                    
                    if embedding_objs and len(embedding_objs) > 0:
                        embedding = np.array(embedding_objs[0]["embedding"], dtype=np.float32)
                        return self._normalize_embedding(embedding)
                except Exception as e:
                    logger.error(f"DeepFace embedding error: {e}")
            
            # Priority 2: face_recognition (dlib)
            if HAS_FACE_RECOGNITION:
                rgb_face = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
                encodings = face_recognition.face_encodings(rgb_face)
                
                if encodings and len(encodings) > 0:
                    return encodings[0]
            
            # Fallback: features de histograma (HOG-like).
            #
            # NÃO é embedding facial: é a distribuição de intensidade do recorte.
            # Num sistema de controle de acesso, usar isso como identidade pode
            # liberar a porta para a pessoa errada, então por padrão recusamos e
            # devolvemos None — que os chamadores já tratam ("Nenhum rosto válido
            # encontrado"). Falhar visivelmente é melhor que identificar errado.
            # Quem quiser o comportamento antigo (só faz sentido em demonstração)
            # liga ALLOW_INSECURE_HOG_EMBEDDINGS=true.
            if not self.allow_insecure_hog_embeddings:
                logger.error(
                    "Nenhum backend de reconhecimento produziu embedding e o "
                    "fallback de histograma está desativado: rosto recusado. "
                    "Instale requirements-recognition.txt (ou defina "
                    "ALLOW_INSECURE_HOG_EMBEDDINGS=true, apenas para demonstração)."
                )
                return None

            logger.warning(
                "Embedding gerado pelo fallback de histograma — identificação NÃO "
                "confiável (ALLOW_INSECURE_HOG_EMBEDDINGS=true)."
            )
            return self._extract_hog_features(face_crop)
                    
        except Exception as e:
            logger.error(f"Erro ao extrair embedding: {e}")
            
        return None
    
    def _extract_hog_features(self, face_crop: np.ndarray) -> np.ndarray | None:
        """Extração de características espaciais (Grid-based Histogram) para maior precisão"""
        try:
            # Redimensionar para tamanho padrão
            face_resized = cv2.resize(face_crop, (128, 128))
            
            # Converter para tons de cinza e equalizar para normalizar iluminação
            gray = cv2.cvtColor(face_resized, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            
            # Dividir a imagem em uma grade 4x4 (16 células)
            # Isso preserva a informação espacial (onde está o olho, nariz, etc)
            grid_size = 4
            h, w = gray.shape
            cell_h, cell_w = h // grid_size, w // grid_size
            
            spatial_features = []
            
            for i in range(grid_size):
                for j in range(grid_size):
                    cell = gray[i*cell_h:(i+1)*cell_h, j*cell_w:(j+1)*cell_w]
                    
                    # Calcular histograma local para esta célula
                    hist = cv2.calcHist([cell], [0], None, [16], [0, 256])
                    hist = cv2.normalize(hist, hist).flatten()
                    spatial_features.append(hist)
            
            # Concatenar todos os histogramas locais em um único vetor (embedding)
            features = np.concatenate(spatial_features)
            
            return features
            
        except Exception as e:
            logger.error(f"Erro ao extrair features espaciais: {e}")
            return None
    
    def verify_face(self, embedding: np.ndarray) -> tuple[int | None, float, str]:
        """Verify face against known embeddings."""
        if not self._known_embeddings:
            return None, 0.0, "unknown"
        
        if embedding is None or embedding.size == 0:
            return None, 0.0, "unknown"
        
        # Normalize query embedding
        embedding = self._normalize_embedding(embedding)
        
        best_match = None
        best_distance = float("inf")
        
        with self._lock:
            for user_id, known_embedding in self._known_embeddings.items():
                try:
                    # Skip if dimensions don't match
                    if len(embedding) != len(known_embedding):
                        continue
                    
                    # Calculate distance based on metric
                    if self.distance_metric == "cosine":
                        similarity = np.dot(embedding, known_embedding)
                        distance = 1 - similarity
                    else:
                        distance = np.linalg.norm(embedding - known_embedding)
                    
                    if distance < best_distance:
                        best_distance = distance
                        best_match = user_id
                        
                except Exception as e:
                    logger.error(f"Erro ao comparar embeddings: {e}")
                    continue
        
        # Check against threshold
        if best_match is not None and best_distance < self.threshold:
            confidence = 1.0 - (best_distance / self.threshold)
            confidence = max(0.0, min(confidence, 1.0))
            return best_match, confidence, "known"
        
        # Return unknown with rejection confidence
        rejection_confidence = 1.0 - min(best_distance / (self.threshold * 1.5), 1.0)
        rejection_confidence = max(0.0, min(rejection_confidence, 1.0))
        return None, rejection_confidence, "unknown"

    def calibrate_threshold(self, embeddings: list[np.ndarray]) -> float | None:
        """Auto-calibrate threshold using intra-class distances from registration images.
        
        Returns the calibrated threshold value WITHOUT modifying the service's
        global threshold. The caller decides how to use this value.
        """
        if len(embeddings) < 2:
            return None
        vectors = [self._normalize_embedding(np.array(e, dtype=np.float32)) for e in embeddings]
        distances: list[float] = []
        for i in range(len(vectors)):
            for j in range(i + 1, len(vectors)):
                distances.append(1.0 - float(np.dot(vectors[i], vectors[j])))
        if not distances:
            return None
        p95 = float(np.percentile(distances, 95))
        calibrated = min(max(p95 * 1.35, 0.20), 0.55)
        logger.info(f"Calibrated threshold for registration: {calibrated:.4f} (global remains {self.threshold})")
        return calibrated
    
    def check_liveness(self, frame: np.ndarray, face_detection: FaceDetection,
                       camera_id: str = "default") -> dict[str, Any]:
        """Check if the face is live using frame-to-frame motion analysis.

        Compares the current frame against the previous frame for this camera_id.
        Real faces exhibit micro-movements; a perfectly static photo shows none.

        Honest limitation: this is a simple pixel-difference heuristic, not a real
        anti-spoofing model. A video or photo played back on a screen also produces
        frame-to-frame differences (camera noise, screen glare, slight hand movement)
        and can pass this check. Treat it only as a filter against trivial static
        photos, not as protection against a deliberate presentation attack.

        Args:
            frame: Current BGR frame.
            face_detection: Detected face bounding box.
            camera_id: Camera identifier for per-camera frame history.

        Returns:
            Dict with is_live, details.
        """
        result = {"is_live": True, "details": {}}
        
        if not self.anti_spoofing_enabled:
            return result
            
        try:
            previous_frame = self._frame_history.get(camera_id)
            
            if previous_frame is not None and previous_frame.shape == frame.shape:
                # Calculate overall frame difference
                diff = cv2.absdiff(frame, previous_frame)
                motion_score = float(np.mean(diff))
                
                # Calculate face-region specific motion
                x, y, w, h = face_detection.x, face_detection.y, face_detection.w, face_detection.h
                x1, y1 = max(0, x), max(0, y)
                x2, y2 = min(frame.shape[1], x + w), min(frame.shape[0], y + h)
                
                face_diff = diff[y1:y2, x1:x2]
                face_motion = float(np.mean(face_diff)) if face_diff.size > 0 else 0.0
                
                result["details"]["motion_score"] = motion_score
                result["details"]["face_motion"] = face_motion

                # Requires motion specifically in the face region (not just anywhere
                # in the frame, which whole-frame sensor noise can trigger on its
                # own) above a stricter threshold than before - filters out a
                # perfectly static photo, nothing more (see docstring above).
                result["is_live"] = face_motion > 4.0
            
            # Store current frame for next comparison (per camera)
            self._frame_history[camera_id] = frame.copy()
                
        except Exception as e:
            logger.error(f"Erro no check de liveness: {e}")
            
        return result
    
    def process_frame(self, frame: np.ndarray, camera_id: str = "default") -> dict[str, Any]:
        start_time = time.time()
        
        detections = self.detect_faces(frame)

        results = {
            "frame_id": int(time.time() * 1000),
            "faces_detected": len(detections),
            "detections": [],
        }

        for detection in detections:
            embedding = self.extract_embedding(frame, detection)
            
            if embedding is None:
                continue
                
            user_id, confidence, match_type = self.verify_face(embedding)
            
            # Use persistent frame history per camera (not local var)
            liveness_result = self.check_liveness(frame, detection, camera_id)
            
            result_entry = {
                "x": detection.x,
                "y": detection.y,
                "w": detection.w,
                "h": detection.h,
                "confidence": detection.confidence,
                "user_id": user_id,
                "user_name": self._known_users.get(user_id) if user_id else "Desconhecido",
                "match_confidence": confidence,
                "match_type": match_type,
                "is_live": liveness_result.get("is_live", True),
                "liveness_details": liveness_result.get("details", {})
            }
            
            results["detections"].append(result_entry)

        results["processing_time_ms"] = (time.time() - start_time) * 1000

        return results
    
    def register_face(self, image) -> np.ndarray | None:
        """Register a face from an image and return its embedding.
        
        Args:
            image: Either a file path (str) or a BGR image (np.ndarray).
            
        Returns:
            Face embedding as numpy array, or None if no face found.
        """
        try:
            # Accept both file path and pre-loaded image
            if isinstance(image, str):
                img = cv2.imread(image)
                if img is None:
                    logger.error(f"Não foi possível carregar imagem: {image}")
                    return None
                source_label = image
            elif isinstance(image, np.ndarray):
                img = image
                if img.size == 0:
                    logger.error("Imagem vazia recebida para registro")
                    return None
                source_label = f"ndarray({img.shape})"
            else:
                logger.error(f"Tipo de imagem não suportado: {type(image)}")
                return None
                
            detections = self.detect_faces(img)
            
            if not detections:
                logger.warning(f"Nenhum rosto detectado em: {source_label}")
                return None
            
            # Use the best detection (highest confidence)
            detection = max(detections, key=lambda d: d.confidence)
            embedding = self.extract_embedding(img, detection)
            
            if embedding is not None:
                logger.info(f"Rosto registrado com sucesso: {source_label}")
                
            return embedding
            
        except Exception as e:
            logger.error(f"Erro ao registrar rosto: {e}")
            return None


class CameraCapture:
    def __init__(self, source: int = 0, fps_limit: int = 30):
        self.source = source
        self.fps_limit = fps_limit
        self.cap = None
        self.running = False
        self.current_frame = None
        self.lock = threading.Lock()
        
    def start(self) -> bool:
        try:
            self.cap = cv2.VideoCapture(self.source)
            
            if not self.cap.isOpened():
                logger.error(f"Não foi possível abrir a câmera: {self.source}")
                return False
                
            self.running = True
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            return True
            
        except Exception as e:
            logger.error(f"Erro ao iniciar captura: {e}")
            return False
            
    def _capture_loop(self):
        frame_time = 1.0 / self.fps_limit
        
        while self.running:
            start = time.time()
            
            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret:
                    with self.lock:
                        self.current_frame = frame.copy()
            
            elapsed = time.time() - start
            if elapsed < frame_time:
                time.sleep(frame_time - elapsed)
                
    def get_frame(self) -> np.ndarray | None:
        with self.lock:
            return self.current_frame.copy() if self.current_frame is not None else None
            
    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()
            self.cap = None
