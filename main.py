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

from app.api import routes as api_routes
from app.config import settings, settings_dict, validate_security_settings, yaml_unknown_keys
from app.database.db import db_manager
from app.security.middleware import (
    GeneralRateLimitMiddleware,
    RequestValidationMiddleware,
    SecurityHeadersMiddleware,
    get_secure_cors_options,
)
from app.security.rate_limiter import api_rate_limiter
from app.security.redaction import CredentialRedactionFilter, redact_url_credentials
from app.services.alerts import CameraOfflineMonitor
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

    # Senha de câmera (rtsp://usuario:senha@...) não pode chegar a nenhum
    # destino de log, venha de que módulo vier.
    redacao = CredentialRedactionFilter()

    console = logging.StreamHandler()
    console.setFormatter(formato)
    console.addFilter(redacao)
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
        arquivo.addFilter(redacao)
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

                # Grava a saída de quem não é visto há mais que o timeout.
                encerradas = await asyncio.to_thread(db_manager.close_stale_presence)
                if encerradas:
                    logger.info("Presença: %d visita(s) encerrada(s) por timeout", encerradas)

                # Retenção configurada (0 = guardar para sempre).
                retencao = settings_dict.get("retention", {})
                apagados = await asyncio.to_thread(
                    db_manager.purge_expired,
                    retencao.get("access_log_days", 0),
                    retencao.get("presence_days", 0),
                    retencao.get("alert_days", 0),
                )
                if any(apagados.values()):
                    logger.info("Retenção: registros apagados %s", apagados)
                
                logger.debug("Limpeza periódica concluída")
            except Exception as e:
                logger.error(f"Erro na limpeza periódica: {e}")

    background_task = asyncio.create_task(cleanup_task())

    alert_service = api_routes.alert_service
    alert_service.start()
    if alert_service.enabled:
        logger.info("Alertas ativos nos canais: %s", ", ".join(alert_service.channel_names) or "nenhum")

    camera_worker = None
    camera_settings = settings_dict.get("server_camera", {})
    if camera_settings.get("enabled"):
        source = resolve_camera_source(camera_settings.get("source", ""))
        if source is None:
            logger.warning("SERVER_CAMERA_ENABLED=true mas SERVER_CAMERA_SOURCE não configurado - captura no servidor desativada")
        else:
            camera_id = camera_settings.get("camera_id", "server-cam")
            monitor = CameraOfflineMonitor(
                alert_service,
                threshold_seconds=settings_dict.get("alerts", {}).get("camera_offline_seconds", 60),
            )
            monitor.register(camera_id)
            alert_service.add_tick_hook(monitor.check)
            camera_worker = CameraWorker(
                source=source,
                camera_id=camera_id,
                interval_seconds=camera_settings.get("interval_seconds", 1.0),
                face_service=face_service,
                performance_tracker=api_routes.performance_tracker,
                handle_results_fn=api_routes.handle_detection_results,
                status_listener=monitor.on_status,
            )
            camera_worker.start()
            api_routes.camera_worker = camera_worker
            logger.info(
                "Captura de câmera no servidor iniciada (fonte: %s)",
                redact_url_credentials(source),
            )

    yield

    logger.info("Encerrando sistema...")
    background_task.cancel()
    if camera_worker:
        camera_worker.stop()
    alert_service.stop()


# Validate security settings on startup
is_secure, warnings = validate_security_settings()
if warnings:
    for warning in warnings:
        logger.warning(f"Security: {warning}")

for chave in yaml_unknown_keys():
    logger.warning("config.yaml: chave '%s' não é lida por nenhuma configuração (ignorada)", chave)

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


def _render_html_with_nonce(filename: str, request: Request) -> HTMLResponse:
    """Read a template file and tag its <script> tag with this request's CSP nonce.

    Needed because these routes serve pre-rendered HTML files directly (not via
    Jinja2Templates) and app/security/middleware.py's CSP only allows scripts that
    carry the current request's nonce.
    """
    try:
        with open(templates_path / filename, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        # Antes havia ~450 linhas de HTML embutido como "reserva" para este
        # caso - desatualizado, anunciando recursos que não existem e sem
        # nonce, então nem funcionava sob o CSP. Template ausente é instalação
        # quebrada: melhor dizer isso.
        logger.error("Template ausente: %s", templates_path / filename)
        return HTMLResponse(
            "<h1>Instalação incompleta</h1><p>Template não encontrado em app/templates.</p>",
            status_code=500,
        )
    nonce = getattr(request.state, "csp_nonce", "")
    html = html.replace("<script>", f'<script nonce="{nonce}">', 1)
    return HTMLResponse(html)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return _render_html_with_nonce("index.html", request)


@app.get("/monitor", response_class=HTMLResponse)
async def monitor_page(request: Request):
    """Página de monitoramento 24/7"""
    return _render_html_with_nonce("monitor.html", request)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return _render_html_with_nonce("dashboard.html", request)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return _render_html_with_nonce("login.html", request)


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
