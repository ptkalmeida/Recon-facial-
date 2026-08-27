# API HTTP

Contrato do backend FastAPI (`app/api/routes.py`, montado em `main.py` sob o prefixo `/api`).
Mudanças incompatíveis devem atualizar este documento e o dashboard (`app/templates/dashboard.html`)
no mesmo pull request. Para detalhes de autenticação, CORS, rate limiting e headers de
segurança, veja [SECURITY.md](../SECURITY.md) — este documento não duplica esse conteúdo.

## Autenticação

A maioria das rotas exige `Authorization: Bearer <token>` (JWT emitido por
`POST /api/auth/login`). Rotas marcadas **admin** exigem além disso `role == "admin"` no
token. `GET /api/health` é a única rota pública.

## Estados do `/api/health`

| `status` | Significado |
|---|---|
| `ok` | banco de dados, orquestrador e modelo de reconhecimento facial operacionais |
| `degraded` | pelo menos um subsistema com problema (banco, orquestrador ou modelo não inicializado) — o serviço continua respondendo, mas com funcionalidade reduzida |

O HTTP status code de `/api/health` é sempre `200`, mesmo em `degraded` — use o campo
`status` do corpo da resposta para decidir alertas de monitoramento, não o status code.

## `POST /api/auth/login`

Rate limitado (ver `SECURITY.md`). Corpo: `{"username": str, "password": str}`.
Resposta `200`: `{"access_token": str, "token_type": "bearer", "user": {...}}`.
`401` em credenciais inválidas, `429` em excesso de tentativas.

## `POST /api/auth/change-password`

Autenticado. Form fields `old_password`, `new_password`. `401` se a senha atual estiver
incorreta; `400` se a nova senha não atender aos requisitos de força.

## `GET /api/users`

Autenticado. Query opcional `active_only` (default `true`). Lista usuários cadastrados.

## `POST /api/users` — admin

Corpo: `{"name": str, "email": str?, "role": str}`. Cria um usuário sem foto/embedding
(use `POST /api/users_register` para cadastro com reconhecimento facial).

## `GET /api/users/{user_id}`, `PUT /api/users/{user_id}` — admin, `DELETE /api/users/{user_id}` — admin

CRUD padrão de usuário.

## `POST /api/users_register` — admin

`multipart/form-data`: `name`, `email?`, `images[]` (uma ou mais fotos do rosto). Extrai o
embedding facial médio das fotos válidas, calibra o threshold de reconhecimento e recarrega
o cache de rostos conhecidos. `400` se nenhuma imagem tiver um rosto detectável.

## `GET /api/presence/current`

Autenticado. Lista as pessoas atualmente presentes (calculado a partir do último registro de
presença dentro da janela de timeout configurada).

## `GET /api/presence/history`

Autenticado. Query opcional `user_id`, `date` (`YYYY-MM-DD`).

## `GET /api/access-logs`

Autenticado. Query opcional `user_id`, `limit` (default `100`), `after_id` — quando
informado, retorna só logs com `id > after_id` (usado pelo dashboard para polling
incremental do feed de eventos ao vivo, a cada 3s).

## `POST /api/recognition/detect`

Autenticado, rate limitado por usuário+IP. `multipart/form-data`: `image` (frame JPEG),
`camera_id?` (identifica a fonte — webcam do navegador, ou `server-cam`/id configurado
quando a captura do lado do servidor está habilitada, ver `SERVER_CAMERA_*` no
`.env.example`). Detecta e reconhece rostos no frame; para cada pessoa reconhecida com
confiança acima do threshold, aplica confirmação multi-frame e cooldown
(`RecognitionOrchestrator`) antes de logar acesso/presença e, acima de 80% de confiança,
abrir a porta. Detecções sem correspondência geram `action=unknown_detected` no log de
acesso e, se `ALERTS_ENABLED=true`, disparam um alerta por e-mail (rate-limitado por
câmera).

Resposta: `{"frame_id": int, "faces_detected": int, "detections": [...], "processing_time_ms": float}`.

## `GET /api/stats`

Autenticado. `{"total_users", "active_users", "present_today", "access_today",
"unknown_detections_today", "avg_detection_latency_ms", "detection_fps"}` — os dois últimos
campos vêm de uma janela deslizante das últimas ~200 chamadas de reconhecimento
(`PerformanceTracker`), não são uma média histórica completa.

## `POST /api/export`

Autenticado. Corpo: `{"start_date", "end_date", "export_type": "access_logs"|"presence",
"format": "xlsx"|"pdf", "user_id"?}`. Retorna o arquivo como stream binário.

## `POST /api/hardware/open-door`

Autenticado. Abre a porta manualmente por 5s e loga a ação.

## `GET /api/health`

Pública. Resposta `200`:

```json
{
  "status": "ok",
  "service": "Face Recognition Pro 3.0",
  "database": "ok",
  "orchestrator": {"cache_size": 0, "buckets_size": 0},
  "active_provider": "Facenet512",
  "model_ready": true,
  "model_error": null,
  "uptime_seconds": 12.3,
  "version": "3.0.0"
}
```

`model_ready=false` indica que `FaceRecognitionService` não conseguiu inicializar nenhum
provedor de reconhecimento facial (InsightFace/DeepFace/dlib/MediaPipe) — `/api/recognition/detect`
continuará respondendo, mas sem detectar rostos. `model_error` traz a mensagem de erro
quando aplicável.
