import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

os.environ['PYTHONIOENCODING'] = 'utf-8'

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import routes as api_routes
from app.config import settings, settings_dict, validate_security_settings
from app.database.db import db_manager
from app.security.middleware import (
    GeneralRateLimitMiddleware,
    RequestValidationMiddleware,
    SecurityHeadersMiddleware,
    get_secure_cors_options,
)
from app.security.rate_limiter import api_rate_limiter
from app.services.camera_worker import CameraWorker, resolve_camera_source

def setup_logging() -> None:
    """Configura o logging a partir das settings (nível + console + arquivo rotativo).

    Antes era `logging.basicConfig(level=logging.INFO, format=...)`: o nível era
    fixo — `LOG_LEVEL` não tinha efeito — e não havia handler de arquivo, então a
    aplicação nunca escrevia log em disco. Num sistema de controle de acesso isso
    significa perder o log operacional ao fechar o console.
    """
    nivel = getattr(logging, str(settings.log_level).upper(), logging.INFO)
    formato = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    for handler in list(raiz.handlers):
        raiz.removeHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(formato)
    raiz.addHandler(console)

    try:
        caminho = Path(settings.log_file)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        arquivo = RotatingFileHandler(
            caminho,
            maxBytes=settings.log_max_size_mb * 1024 * 1024,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
        arquivo.setFormatter(formato)
        raiz.addHandler(arquivo)
    except (OSError, ValueError) as e:
        # Disco cheio, permissão, caminho inválido: seguir só com console é
        # melhor que não subir. `ValueError` entra na lista porque caminho com
        # caractere nulo levanta ValueError, não OSError.
        raiz.warning("Não foi possível abrir %s para log: %s", settings.log_file, e)


setup_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Inicializando Face Recognition Pro 3.0...")
    
    face_service = api_routes.face_service
    try:
        if face_service.initialize():
            embeddings_data = db_manager.get_all_embeddings_data()
            face_service.load_known_faces(embeddings_data)
            logger.info(f"Carregados {len(embeddings_data)} rostos conhecidos")
            # initialize() devolve True até no fallback HOG, que não reconhece
            # ninguém de forma confiável. Tratar isso como "modelo pronto"
            # esconderia o problema: /api/health dizia ok rodando Haar+HOG.
            if face_service.recognition_degraded:
                api_routes.service_status["model_ready"] = False
                api_routes.service_status["model_error"] = (
                    "Nenhuma biblioteca de reconhecimento instalada "
                    f"(embeddings via {face_service.embedding_backend}); "
                    f"a configuração pede {face_service.model_name}"
                )
            else:
                api_routes.service_status["model_ready"] = True
                api_routes.service_status["model_error"] = None
        else:
            logger.warning("FaceRecognitionService não pôde ser inicializado completamente")
            api_routes.service_status["model_ready"] = False
            api_routes.service_status["model_error"] = "Falha ao inicializar o serviço de reconhecimento facial"
    except Exception as e:
        logger.error(f"Erro ao inicializar FaceRecognitionService: {e}")
        api_routes.service_status["model_ready"] = False
        api_routes.service_status["model_error"] = str(e)
    
    if api_routes.service_status["model_ready"]:
        logger.info("Sistema pronto!")
    else:
        logger.warning(
            "Sistema no ar em modo DEGRADADO: %s",
            api_routes.service_status["model_error"],
        )
    
    # Inicia tarefa de limpeza periódica (Fase 3 - Performance)
    import asyncio
    async def cleanup_task():
        while True:
            await asyncio.sleep(300) # 5 minutos
            try:
                # Limpa rate limiters
                api_rate_limiter.cleanup_old_entries()
                api_routes.auth_rate_limiter.cleanup_old_entries()
                api_routes.recognition_rate_limiter.cleanup_old_entries()
                
                # Limpa estados internos (last_log, confirmation_states)
                api_routes.cleanup_internal_states()
                
                logger.debug("Limpeza periódica concluída")
            except Exception as e:
                logger.error(f"Erro na limpeza periódica: {e}")

    background_task = asyncio.create_task(cleanup_task())

    camera_worker = None
    camera_settings = settings_dict.get("server_camera", {})
    if camera_settings.get("enabled"):
        source = resolve_camera_source(camera_settings.get("source", ""))
        if source is None:
            logger.warning("SERVER_CAMERA_ENABLED=true mas SERVER_CAMERA_SOURCE não configurado - captura no servidor desativada")
        else:
            camera_worker = CameraWorker(
                source=source,
                camera_id=camera_settings.get("camera_id", "server-cam"),
                interval_seconds=camera_settings.get("interval_seconds", 1.0),
                face_service=face_service,
                performance_tracker=api_routes.performance_tracker,
                handle_results_fn=api_routes.handle_detection_results
            )
            camera_worker.start()
            api_routes.camera_worker = camera_worker
            logger.info(f"Captura de câmera no servidor iniciada (fonte: {source})")

    yield

    logger.info("Encerrando sistema...")
    background_task.cancel()
    if camera_worker:
        camera_worker.stop()


# Validate security settings on startup
is_secure, warnings = validate_security_settings()
if warnings:
    for warning in warnings:
        logger.warning(f"Security: {warning}")

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Sistema Profissional de Reconhecimento Facial 3.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None
)

# Security middleware (first to add headers to all responses)
app.add_middleware(SecurityHeadersMiddleware)

# Request validation middleware
app.add_middleware(RequestValidationMiddleware)

# General API rate limiting (excludes routes with their own dedicated limiter)
app.add_middleware(GeneralRateLimitMiddleware)

# CORS middleware with secure configuration
cors_options = get_secure_cors_options()
app.add_middleware(
    CORSMiddleware,
    **cors_options
)

app.include_router(api_routes.router, prefix="/api", tags=["API"])

static_path = Path(__file__).parent / "app" / "static"
templates_path = Path(__file__).parent / "app" / "templates"

if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

templates = Jinja2Templates(directory=str(templates_path)) if templates_path.exists() else None


def _render_html_with_nonce(filename: str, request: Request) -> HTMLResponse:
    """Read a template file and tag its <script> tag with this request's CSP nonce.

    Needed because these routes serve pre-rendered HTML files directly (not via
    Jinja2Templates) and app/security/middleware.py's CSP only allows scripts that
    carry the current request's nonce.
    """
    with open(templates_path / filename, "r", encoding="utf-8") as f:
        html = f.read()
    nonce = getattr(request.state, "csp_nonce", "")
    html = html.replace("<script>", f'<script nonce="{nonce}">', 1)
    return HTMLResponse(html)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if templates_path.exists():
        with open(templates_path / "index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Face Recognition Pro 3.0</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .container {
                background: white;
                border-radius: 20px;
                padding: 50px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                text-align: center;
                max-width: 600px;
            }
            h1 {
                color: #667eea;
                font-size: 2.5em;
                margin-bottom: 20px;
            }
            p { color: #666; margin-bottom: 30px; font-size: 1.1em; }
            .btn {
                display: inline-block;
                padding: 15px 40px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                text-decoration: none;
                border-radius: 50px;
                font-weight: bold;
                transition: transform 0.3s;
            }
            .btn:hover { transform: scale(1.05); }
            .features {
                margin-top: 40px;
                text-align: left;
            }
            .feature {
                padding: 15px;
                margin: 10px 0;
                background: #f8f9fa;
                border-radius: 10px;
                border-left: 4px solid #667eea;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔐 Face Recognition Pro 3.0</h1>
            <p>Sistema profissional de reconhecimento facial com IA</p>
            <a href="/dashboard" class="btn">Acessar Dashboard</a>
            <div class="features">
                <div class="feature">✓ Reconhecimento facial com DeepFace (Facenet512)</div>
                <div class="feature">✓ Detecção com RetinaFace</div>
                <div class="feature">✓ Anti-spoofing com detecção de vivacidade</div>
                <div class="feature">✓ Controle de presença automatizado</div>
                <div class="feature">✓ API RESTful completa</div>
            </div>
        </div>
    </body>
    </html>
    """


@app.get("/monitor", response_class=HTMLResponse)
async def monitor_page(request: Request):
    """Página de monitoramento 24/7"""
    if templates_path.exists():
        return _render_html_with_nonce("monitor.html", request)
    
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Monitoramento 24/7 - Face Recognition Pro 3.0</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'Segoe UI', sans-serif;
                background: #0f172a;
                color: white;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                flex-direction: column;
                gap: 20px;
            }
            h1 { color: #6366f1; }
            p { color: #94a3b8; }
            .btn {
                padding: 15px 30px;
                background: #6366f1;
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 1.1em;
                cursor: pointer;
            }
        </style>
    </head>
    <body>
        <h1>🔐 Monitoramento 24/7</h1>
        <p>Carregando interface de monitoramento...</p>
        <button class="btn" onclick="location.href='/dashboard'">Voltar ao Dashboard</button>
    </body>
    </html>
    """


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if templates_path.exists():
        return _render_html_with_nonce("dashboard.html", request)
    
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Dashboard - Face Recognition Pro 3.0</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'Segoe UI', sans-serif;
                background: #1a1a2e;
                color: white;
            }
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 20px 40px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .logo { font-size: 1.5em; font-weight: bold; }
            .user-info { display: flex; align-items: center; gap: 15px; }
            .main { padding: 30px; }
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }
            .stat-card {
                background: #16213e;
                padding: 25px;
                border-radius: 15px;
                text-align: center;
            }
            .stat-number { font-size: 2.5em; font-weight: bold; color: #667eea; }
            .stat-label { color: #aaa; margin-top: 10px; }
            .section {
                background: #16213e;
                padding: 25px;
                border-radius: 15px;
                margin-bottom: 20px;
            }
            .section h2 { margin-bottom: 20px; color: #667eea; }
            .camera-container {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 20px;
            }
            #videoContainer {
                position: relative;
                width: 640px;
                max-width: 100%;
                border-radius: 10px;
                overflow: hidden;
                border: 3px solid #667eea;
            }
            #webcamVideo { width: 100%; display: block; }
            #detectionCanvas {
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
            }
            .controls {
                display: flex;
                gap: 10px;
                margin-bottom: 20px;
            }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 15px; text-align: left; border-bottom: 1px solid #333; }
            th { color: #667eea; }
            .btn {
                padding: 10px 20px;
                background: #667eea;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
            }
            .status-present { color: #4caf50; }
            .status-absent { color: #f44336; }
        </style>
    </head>
    <body>
        <div class="header">
            <div class="logo">🔐 Face Recognition Pro 3.0</div>
            <div class="user-info">
                <span>Admin</span>
                <button class="btn" onclick="logout()">Sair</button>
            </div>
        </div>
        <div class="main">
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-number" id="totalUsers">0</div>
                    <div class="stat-label">Total de Usuários</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number" id="presentToday">0</div>
                    <div class="stat-label">Presentes Hoje</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number" id="accessToday">0</div>
                    <div class="stat-label">Acessos Hoje</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number" id="unknownToday">0</div>
                    <div class="stat-label">Desconhecidos</div>
                </div>
            </div>

            <div class="section">
                <h2>📺 Monitoramento em Tempo Real</h2>
                <div class="camera-container">
                    <div class="controls">
                        <button class="btn" id="startBtn" onclick="startCamera()">Iniciar Câmera</button>
                        <button class="btn" id="stopBtn" onclick="stopCamera()" style="background: #f44336; display: none;">Parar</button>
                    </div>
                    <div id="videoContainer">
                        <video id="webcamVideo" autoplay playsinline muted></video>
                        <canvas id="detectionCanvas"></canvas>
                    </div>
                    <div id="detectionStatus" style="color: #aaa;">Status: Câmera desligada</div>
                </div>
            </div>

            <div class="section">
                <h2>Presença Atual</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Nome</th>
                            <th>Status</th>
                            <th>Entrada</th>
                        </tr>
                    </thead>
                    <tbody id="presenceTable"></tbody>
                </table>
            </div>
            <div class="section">
                <h2>Últimos Acessos</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Data/Hora</th>
                            <th>Usuário</th>
                            <th>Ação</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody id="accessLogsTable"></tbody>
                </table>
            </div>
        </div>
        <script>
            function escapeHtml(text) {
                if (text === null || text === undefined) return '';
                const div = document.createElement('div');
                div.textContent = String(text);
                return div.innerHTML;
            }

            async function loadData() {
                const token = localStorage.getItem('token');
                if (!token) { window.location.href = '/login'; return; }
                
                try {
                    const [statsRes, presenceRes, logsRes] = await Promise.all([
                        fetch('/api/stats', { headers: { 'Authorization': 'Bearer ' + token } }),
                        fetch('/api/presence/current', { headers: { 'Authorization': 'Bearer ' + token } }),
                        fetch('/api/access-logs?limit=10', { headers: { 'Authorization': 'Bearer ' + token } })
                    ]);
                    
                    const stats = await statsRes.json();
                    const presence = await presenceRes.json();
                    const logs = await logsRes.json();
                    
                    document.getElementById('totalUsers').textContent = stats.total_users;
                    document.getElementById('presentToday').textContent = stats.present_today;
                    document.getElementById('accessToday').textContent = stats.access_today;
                    document.getElementById('unknownToday').textContent = stats.unknown_detections_today;
                    
                    const presenceHtml = presence.map(p => `
                        <tr>
                            <td>${escapeHtml(p.user.name)}</td>
                            <td class="${p.status === 'presente' ? 'status-present' : 'status-absent'}">${escapeHtml(p.status)}</td>
                            <td>${escapeHtml(p.check_in || '-')}</td>
                        </tr>
                    `).join('');
                    document.getElementById('presenceTable').innerHTML = presenceHtml || '<tr><td colspan="3">Nenhum registro</td></tr>';
                    
                    const logsHtml = logs.map(l => `
                        <tr>
                            <td>${escapeHtml(new Date(l.created_at).toLocaleString())}</td>
                            <td>${escapeHtml(l.user_name || 'Desconhecido')}</td>
                            <td>${escapeHtml(l.action)}</td>
                            <td>${escapeHtml(l.status)}</td>
                        </tr>
                    `).join('');
                    document.getElementById('accessLogsTable').innerHTML = logsHtml || '<tr><td colspan="4">Nenhum registro</td></tr>';
                } catch (e) {
                    console.error(e);
                }
            }
            
            function logout() {
                localStorage.removeItem('token');
                window.location.href = '/login';
            }
            
            // Lógica de Câmera e Detecção
            let stream = null;
            let detectionInterval = null;
            const video = document.getElementById('webcamVideo');
            const canvas = document.getElementById('detectionCanvas');
            const ctx = canvas.getContext('2d');
            const statusLabel = document.getElementById('detectionStatus');

            async function startCamera() {
                try {
                    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
                    video.srcObject = stream;
                    document.getElementById('startBtn').style.display = 'none';
                    document.getElementById('stopBtn').style.display = 'inline-block';
                    statusLabel.textContent = "Status: Processando reconhecimento...";
                    
                    // Ajustar canvas quando o vídeo carregar
                    video.onloadedmetadata = () => {
                        canvas.width = video.videoWidth;
                        canvas.height = video.videoHeight;
                        startDetectionLoop();
                    };
                } catch (e) {
                    alert("Erro ao acessar câmera: " + e.message);
                }
            }

            function stopCamera() {
                if (stream) {
                    stream.getTracks().forEach(track => track.stop());
                }
                clearInterval(detectionInterval);
                document.getElementById('startBtn').style.display = 'inline-block';
                document.getElementById('stopBtn').style.display = 'none';
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                statusLabel.textContent = "Status: Câmera desligada";
            }

            function startDetectionLoop() {
                const offscreenCanvas = document.createElement('canvas');
                offscreenCanvas.width = video.videoWidth;
                offscreenCanvas.height = video.videoHeight;
                const offscreenCtx = offscreenCanvas.getContext('2d');

                detectionInterval = setInterval(async () => {
                    if (!stream) return;

                    // Capturar frame atual
                    offscreenCtx.drawImage(video, 0, 0);
                    const blob = await new Promise(resolve => offscreenCanvas.toBlob(resolve, 'image/jpeg', 0.8));
                    
                    const formData = new FormData();
                    formData.append('image', blob, 'frame.jpg');

                    const token = localStorage.getItem('token');
                    try {
                        const res = await fetch('/api/recognition/detect', {
                            method: 'POST',
                            headers: { 'Authorization': 'Bearer ' + token },
                            body: formData
                        });
                        const data = await res.json();
                        drawDetections(data.detections);
                        // Atualizar estatísticas periodicamente
                        if (Math.random() > 0.9) loadData(); 
                    } catch (e) {
                        console.error("Erro na detecção:", e);
                    }
                }, 1000); // Processar a cada 1 segundo para não sobrecarregar
            }

            function drawDetections(detections) {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                
                detections.forEach(det => {
                    const isKnown = det.user_id !== null;
                    const color = isKnown ? '#4caf50' : '#f44336';
                    
                    ctx.strokeStyle = color;
                    ctx.lineWidth = 4;
                    ctx.strokeRect(det.x, det.y, det.w, det.h);
                    
                    ctx.fillStyle = color;
                    ctx.font = 'bold 16px Arial';
                    const label = `${escapeHtml(det.user_name)} (${Math.round(det.match_confidence * 100)}%)`;
                    ctx.fillText(label, det.x, det.y > 20 ? det.y - 10 : det.y + 20);
                });
            }

            loadData();
        </script>
    </body>
    </html>
    """


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if templates_path.exists():
        return _render_html_with_nonce("login.html", request)
    
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login - Face Recognition Pro 3.0</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'Segoe UI', sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .login-box {
                background: white;
                padding: 40px;
                border-radius: 20px;
                width: 400px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            }
            h1 { color: #667eea; text-align: center; margin-bottom: 30px; }
            input {
                width: 100%;
                padding: 15px;
                margin: 10px 0;
                border: 2px solid #ddd;
                border-radius: 10px;
                font-size: 1em;
            }
            input:focus { border-color: #667eea; outline: none; }
            .btn {
                width: 100%;
                padding: 15px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 1em;
                cursor: pointer;
                margin-top: 20px;
            }
            .btn:hover { opacity: 0.9; }
            .error { color: red; text-align: center; margin-top: 10px; }
        </style>
    </head>
    <body>
        <div class="login-box">
            <h1>🔐 Login</h1>
            <input type="text" id="username" placeholder="Usuário">
            <input type="password" id="password" placeholder="Senha">
            <button class="btn" onclick="login()">Entrar</button>
            <div class="error" id="error"></div>
        </div>
        <script>
            async function login() {
                const username = document.getElementById('username').value;
                const password = document.getElementById('password').value;
                const error = document.getElementById('error');
                
                try {
                    const res = await fetch('/api/auth/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, password })
                    });
                    
                    if (!res.ok) {
                        error.textContent = 'Credenciais inválidas';
                        return;
                    }
                    
                    const data = await res.json();
                    localStorage.setItem('token', data.access_token);
                    window.location.href = '/dashboard';
                } catch (e) {
                    error.textContent = 'Erro ao fazer login';
                }
            }
        </script>
    </body>
    </html>
    """


if __name__ == "__main__":
    import uvicorn
    
    server_config = settings_dict.get("server", {})
    host = server_config.get("host", "0.0.0.0")
    port = server_config.get("port", 8000)
    reload = server_config.get("reload", True)
    
    print()
    print("=" * 60)
    print("  FACE RECOGNITION PRO 3.0 - INICIANDO")
    print("=" * 60)
    print(f"  Servidor: http://{host}:{port}")
    print(f"  Dashboard: http://{host}:{port}/dashboard")
    print(f"  API Docs: http://{host}:{port}/docs")
    print("=" * 60)
    print()
    
    uvicorn.run("main:app", host=host, port=port, reload=reload)
