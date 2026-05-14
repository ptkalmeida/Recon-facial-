import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import yaml

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = 'config.yaml') -> Dict:

    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    return {
        'video_source': 0,
        'rtsp_url': '',
        'confidence_threshold': 0.6,
        'absence_timeout': 60,
        'detection_interval': 1,
        'log_rotation_days': 30,
        'rate_limit_max_attempts': 5,
        'rate_limit_block_duration': 900
    }


def get_system_password() -> str:
    password = os.environ.get('SYSTEM_PASSWORD')
    if not password:
        raise RuntimeError('SYSTEM_PASSWORD must be set before decrypting face encodings')
    return password
