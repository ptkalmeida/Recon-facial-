"""
Face Recognition Service - DeepFace Implementation

Uses DeepFace library with Facenet512 model for accurate face recognition.
This replaces the previous inconsistent implementations.
"""

import os
import numpy as np
import cv2
import time
import threading
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
import logging

from app.config import settings

logger = logging.getLogger(__name__)

# DeepFace imports
try:
    from deepface import DeepFace
    from deepface.commons import distance as dst
    HAS_DEEPFACE = True
    logger.info("DeepFace loaded successfully")
except ImportError as e:
    HAS_DEEPFACE = False
    logger.error(f"DeepFace not available: {e}")


@dataclass
class FaceDetection:
    """Face detection result."""
    confidence: float
    x: int
    y: int
    w: int
    h: int
    landmarks: Optional[Dict[str, Tuple[int, int]]] = None


@dataclass  
class FaceQualityMetrics:
    """Quality metrics for a detected face."""
    sharpness: float  # Laplacian variance
    brightness: float  # Mean pixel value
    contrast: float  # Standard deviation
    face_size_ratio: float  # Face area relative to image
    is_good_quality: bool


class FaceRecognitionService:
    """
    Professional face recognition service using DeepFace.
    
    Features:
    - Consistent embedding extraction using Facenet512
    - Face quality assessment
    - Anti-spoofing detection
    - Thread-safe face database
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize the face recognition service."""
        self.config = config or settings_dict
        self.fr_config = self.config.get("face_recognition", {})
        
        # Model configuration
        self.model_name = self.fr_config.get("model", "Facenet512")
        self.detector_backend = self.fr_config.get("detector", "retinaface")
        self.distance_metric = self.fr_config.get("distance_metric", "cosine")
        self.threshold = self.fr_config.get("threshold", 0.4)
        self.enforce_detection = self.fr_config.get("enforce_detection", True)
        self.align = self.fr_config.get("align", True)
        self.normalization = self.fr_config.get("normalization", "base")
        
        # Anti-spoofing
        self.anti_spoofing_config = self.config.get("anti_spoofing", {})
        self.anti_spoofing_enabled = self.anti_spoofing_config.get("enabled", True)
        
        # State
        self._initialized = False
        self._lock = threading.Lock()
        self._known_embeddings: Dict[int, np.ndarray] = {}
        self._known_users: Dict[int, str] = {}
        
        # Detection cache for anti-spoofing
        self._frame_history: Dict[str, np.ndarray] = {}
        
        logger.info(f"FaceRecognitionService configured with model={self.model_name}, "
                   f"detector={self.detector_backend}, metric={self.distance_metric}")
    
    def initialize(self) -> bool:
        """Initialize the service and verify DeepFace is working."""
        if self._initialized:
            return True
        
        if not HAS_DEEPFACE:
            logger.error("DeepFace is required but not available")
            return False
        
        try:
            # Test DeepFace with a blank image to trigger model download
            logger.info("Initializing DeepFace models (this may take a moment)...")
            
            # Create a test image
            test_img = np.ones((100, 100, 3), dtype=np.uint8) * 128
            
            # Try to detect faces (will fail but download models)
            try:
                DeepFace.detectFace(
                    test_img,
                    detector_backend=self.detector_backend,
                    enforce_detection=False
                )
            except:
                pass  # Expected to fail on blank image
            
            self._initialized = True
            logger.info(f"FaceRecognitionService initialized with {self.model_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize DeepFace: {e}")
            return False
    
    def load_known_faces(self, embeddings_data: List[Dict[str, Any]]) -> bool:
        """Load known faces from database."""
        try:
            with self._lock:
                self._known_embeddings.clear()
                self._known_users.clear()
                
                loaded_count = 0
                for emb_data in embeddings_data:
                    user_id = emb_data.get("user_id")
                    embedding = emb_data.get("embedding_data")
                    
                    if user_id and embedding and isinstance(embedding, (list, np.ndarray)):
                        # Convert to numpy array and ensure correct shape
                        emb_array = np.array(embedding, dtype=np.float32)
                        
                        # Normalize the embedding
                        emb_array = self._normalize_embedding(emb_array)
                        
                        self._known_embeddings[user_id] = emb_array
                        self._known_users[user_id] = emb_data.get("user_name", f"User_{user_id}")
                        loaded_count += 1
                
                logger.info(f"Loaded {loaded_count} known faces from database")
                return True
                
        except Exception as e:
            logger.error(f"Error loading known faces: {e}")
            return False
    
    def _normalize_embedding(self, embedding: np.ndarray) -> np.ndarray:
        """L2 normalize an embedding vector."""
        norm = np.linalg.norm(embedding)
        if norm > 0:
            return embedding / norm
        return embedding
    
    def detect_faces(self, frame: np.ndarray) -> List[FaceDetection]:
        """Detect faces in a frame using DeepFace's detector."""
        detections = []
        
        if not HAS_DEEPFACE:
            logger.warning("DeepFace not available for face detection")
            return detections
        
        try:
            # Use DeepFace's face detection
            face_objs = DeepFace.extract_faces(
                frame,
                detector_backend=self.detector_backend,
                enforce_detection=False,
                align=self.align,
                expand_percentage=10  # Add 10% padding
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
                
        except Exception as e:
            logger.error(f"Error detecting faces: {e}")
        
        return detections
    
    def assess_face_quality(self, frame: np.ndarray, face_detection: FaceDetection) -> FaceQualityMetrics:
        """Assess the quality of a detected face."""
        try:
            # Extract face region
            x, y, w, h = face_detection.x, face_detection.y, face_detection.w, face_detection.h
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(frame.shape[1], x + w), min(frame.shape[0], y + h)
            
            face_crop = frame[y1:y2, x1:x2]
            if face_crop.size == 0:
                return FaceQualityMetrics(0, 0, 0, 0, False)
            
            # Convert to grayscale for quality metrics
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            
            # Sharpness (Laplacian variance)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            
            # Brightness (mean)
            brightness = np.mean(gray)
            
            # Contrast (std)
            contrast = np.std(gray)
            
            # Face size ratio
            img_area = frame.shape[0] * frame.shape[1]
            face_area = w * h
            size_ratio = face_area / img_area if img_area > 0 else 0
            
            # Quality thresholds
            is_good = (
                laplacian_var > 100 and  # Not too blurry
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
                         skip_quality_check: bool = False) -> Optional[np.ndarray]:
        """Extract face embedding using DeepFace."""
        if not HAS_DEEPFACE:
            logger.warning("DeepFace not available for embedding extraction")
            return None
        
        try:
            # Check face quality first
            if not skip_quality_check:
                quality = self.assess_face_quality(frame, face_detection)
                if not quality.is_good_quality:
                    logger.debug(f"Face quality too low: sharpness={quality.sharpness:.1f}, "
                               f"brightness={quality.brightness:.1f}")
                    return None
            
            # Extract face region
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
            
            # Use DeepFace to represent the face
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
                # Normalize the embedding
                return self._normalize_embedding(embedding)
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting embedding: {e}")
            return None
    
    def verify_face(self, embedding: np.ndarray) -> Tuple[Optional[int], float, str]:
        """
        Verify a face embedding against known faces.
        
        Returns: (user_id, confidence, match_type)
        """
        if not self._known_embeddings:
            return None, 0.0, "unknown"
        
        if embedding is None or embedding.size == 0:
            return None, 0.0, "unknown"
        
        # Ensure embedding is normalized
        embedding = self._normalize_embedding(embedding)
        
        best_match = None
        best_distance = float("inf")
        
        with self._lock:
            for user_id, known_embedding in self._known_embeddings.items():
                try:
                    # Calculate distance
                    if self.distance_metric == "cosine":
                        # Cosine distance = 1 - cosine similarity
                        similarity = np.dot(embedding, known_embedding)
                        distance = 1 - similarity
                    elif self.distance_metric == "euclidean":
                        distance = np.linalg.norm(embedding - known_embedding)
                    elif self.distance_metric == "euclidean_l2":
                        distance = np.linalg.norm(embedding - known_embedding)
                    else:
                        # Default to cosine
                        similarity = np.dot(embedding, known_embedding)
                        distance = 1 - similarity
                    
                    if distance < best_distance:
                        best_distance = distance
                        best_match = user_id
                        
                except Exception as e:
                    logger.error(f"Error comparing embeddings: {e}")
                    continue
        
        # Check against threshold
        if best_match is not None and best_distance < self.threshold:
            # Convert distance to confidence score (0-1)
            confidence = 1.0 - (best_distance / self.threshold)
            return best_match, confidence, "known"
        
        # Return unknown with rejection confidence
        rejection_confidence = 1.0 - min(best_distance / (self.threshold * 1.5), 1.0)
        return None, rejection_confidence, "unknown"
    
    def check_liveness(self, frame: np.ndarray, face_detection: FaceDetection,
                       camera_id: str = "default") -> Dict[str, Any]:
        """Check if the face is live (not a photo or video replay)."""
        result = {
            "is_live": True,
            "confidence": 1.0,
            "details": {}
        }
        
        if not self.anti_spoofing_enabled:
            return result
        
        try:
            # Get previous frame for this camera
            prev_frame = self._frame_history.get(camera_id)
            
            if prev_frame is not None and prev_frame.shape == frame.shape:
                # Calculate frame difference
                diff = cv2.absdiff(frame, prev_frame)
                motion_score = np.mean(diff)
                
                # Extract face region
                x, y, w, h = face_detection.x, face_detection.y, face_detection.w, face_detection.h
                x1, y1 = max(0, x), max(0, y)
                x2, y2 = min(frame.shape[1], x + w), min(frame.shape[0], y + h)
                
                face_diff = diff[y1:y2, x1:x2]
                face_motion = np.mean(face_diff) if face_diff.size > 0 else 0
                
                result["details"]["motion_score"] = float(motion_score)
                result["details"]["face_motion"] = float(face_motion)
                
                # Liveness heuristics
                # Real faces should have some micro-movements
                is_live = face_motion > 2.0 or motion_score > 5.0
                
                result["is_live"] = is_live
                result["confidence"] = min(face_motion / 10.0, 1.0) if is_live else 0.0
            
            # Store current frame for next comparison
            self._frame_history[camera_id] = frame.copy()
            
        except Exception as e:
            logger.error(f"Error in liveness check: {e}")
        
        return result
    
    def process_frame(self, frame: np.ndarray, camera_id: str = "default") -> Dict[str, Any]:
        """Process a video frame for face recognition."""
        start_time = time.time()
        
        # Detect faces
        detections = self.detect_faces(frame)
        
        results = {
            "frame_id": int(time.time() * 1000),
            "faces_detected": len(detections),
            "detections": [],
            "processing_time_ms": (time.time() - start_time) * 1000
        }
        
        for detection in detections:
            # Extract embedding
            embedding = self.extract_embedding(frame, detection)
            
            # Verify face
            if embedding is not None:
                user_id, confidence, match_type = self.verify_face(embedding)
            else:
                user_id, confidence, match_type = None, 0.0, "unknown"
            
            # Check liveness
            liveness_result = self.check_liveness(frame, detection, camera_id)
            
            # Get quality metrics
            quality = self.assess_face_quality(frame, detection)
            
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
                "liveness_confidence": liveness_result.get("confidence", 1.0),
                "quality": {
                    "sharpness": quality.sharpness,
                    "brightness": quality.brightness,
                    "contrast": quality.contrast,
                    "is_good": quality.is_good_quality
                }
            }
            
            results["detections"].append(result_entry)
        
        results["processing_time_ms"] = (time.time() - start_time) * 1000
        return results
    
    def register_face(self, image: np.ndarray, skip_quality_check: bool = False) -> Optional[np.ndarray]:
        """
        Register a face from an image and return its embedding.
        
        Args:
            image: BGR image (OpenCV format)
            skip_quality_check: If True, skip quality assessment
            
        Returns:
            Face embedding as numpy array, or None if no face found
        """
        if not HAS_DEEPFACE:
            logger.error("DeepFace not available for face registration")
            return None
        
        try:
            # Detect faces
            detections = self.detect_faces(image)
            
            if not detections:
                logger.warning("No face detected for registration")
                return None
            
            # Use the best detection (highest confidence)
            best_detection = max(detections, key=lambda d: d.confidence)
            
            # Check quality unless skipped
            if not skip_quality_check:
                quality = self.assess_face_quality(image, best_detection)
                if not quality.is_good_quality:
                    logger.warning(f"Face quality too low for registration: {quality}")
                    return None
            
            # Extract embedding
            embedding = self.extract_embedding(image, best_detection, skip_quality_check=True)
            
            if embedding is not None:
                logger.info(f"Face registered successfully: embedding dim={embedding.shape}")
            
            return embedding
            
        except Exception as e:
            logger.error(f"Error registering face: {e}")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        with self._lock:
            return {
                "initialized": self._initialized,
                "model": self.model_name,
                "detector": self.detector_backend,
                "known_faces": len(self._known_embeddings),
                "distance_metric": self.distance_metric,
                "threshold": self.threshold,
                "anti_spoofing": self.anti_spoofing_enabled
            }


class CameraCapture:
    """Threaded camera capture."""
    
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
                logger.error(f"Could not open camera: {self.source}")
                return False
            
            # Set camera properties
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps_limit)
            
            self.running = True
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            return True
            
        except Exception as e:
            logger.error(f"Error starting capture: {e}")
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
    
    def get_frame(self) -> Optional[np.ndarray]:
        with self.lock:
            return self.current_frame.copy() if self.current_frame is not None else None
    
    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()
            self.cap = None


# Import settings_dict for backward compatibility
from app.config import settings_dict
