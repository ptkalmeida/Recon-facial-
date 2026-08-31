# Guia de Segurança - Face Recognition Pro 3.0

## Visão Geral

Este documento descreve as medidas de segurança implementadas no Face Recognition Pro 3.0
e orienta uma implantação segura. Ele foi revisado para refletir o que está **de fato**
implementado no código — não apenas o que foi planejado. As divergências encontradas numa
auditoria em 2026-08-27 (ver changelog da versão 3.0) já foram corrigidas; o que resta como
limitação real e deliberada está marcado explicitamente no texto abaixo.

## Recursos de Segurança Implementados

### 1. Gerenciamento Seguro de Configuração

**Problema resolvido**: segredos hardcoded em arquivos de configuração.

**Solução**:
- Todos os segredos ficam no arquivo `.env` (nunca commitar esse arquivo!).
- `config.yaml` contém apenas configurações não sensíveis.
- Variáveis de ambiente têm precedência sobre a configuração em arquivo.
- Validação automática de configurações de segurança na inicialização.

**Variáveis de ambiente obrigatórias**:

```bash
# Críticas - gere valores aleatórios fortes
JWT_SECRET_KEY=<string aleatória de no mínimo 32 caracteres>
ADMIN_PASSWORD=<senha forte de no mínimo 8 caracteres>

# Opcionais, com valores padrão
ALLOWED_ORIGINS=http://localhost:8001
RATE_LIMIT_MAX_REQUESTS=100
```

**Alertas por e-mail (opcional)**: desabilitados por padrão (`ALERTS_ENABLED=false`). Quando
habilitados, um e-mail é enviado para `ALERT_EMAIL_TO` sempre que um rosto desconhecido é
detectado, com limite de repetição por câmera controlado por `ALERT_COOLDOWN_SECONDS`.
Exige `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` e `SMTP_FROM` configurados com
uma conta SMTP real — nunca commite credenciais SMTP reais, mantenha-as só no `.env`.

**Captura de câmera no servidor (opcional)**: desabilitada por padrão
(`SERVER_CAMERA_ENABLED=false`). Quando habilitada, o servidor abre diretamente uma webcam
local ou um stream RTSP/arquivo (`SERVER_CAMERA_SOURCE`) e roda reconhecimento contínuo,
usando exatamente as mesmas regras de log/presença/alerta da rota HTTP. Como qualquer fonte
de vídeo adicional, avalie o acesso físico/de rede a essa fonte antes de habilitar em
produção — ver [docs/API.md](docs/API.md) para o contrato de `/api/health` quando ativa.

### 2. Autenticação e Autorização

**Funcionalidades**:
- Autenticação baseada em JWT com geração segura de token.
- Validação de força de senha (mínimo 8 caracteres, maiúscula, minúscula, dígito e caractere
  especial) — aplicada tanto na troca de senha (`POST /api/auth/change-password`) quanto na
  senha admin inicial definida via `ADMIN_PASSWORD` no `.env`: em produção, o sistema recusa
  subir se ela for fraca; fora de produção, só avisa no log e segue.
- Hash de senha com bcrypt (fator de custo adaptativo).
- Limite de tentativas de autenticação (5 tentativas por 5 minutos, bloqueio de 15 minutos).
- Bloqueio automático e temporário após tentativas falhas.

**Limites de requisição (rate limits)**:

| Rota | Limite | Janela | Duração do bloqueio |
|---|---|---|---|
| Login | 5 tentativas | 5 minutos | 15 minutos |
| Reconhecimento (`/api/recognition/detect`) | 60 requisições | 1 minuto | 1 minuto |
| API geral | 100 requisições | 1 minuto | — |

Os três limites acima estão ativos: login e reconhecimento honram
`AUTH_MAX_ATTEMPTS`/`AUTH_BLOCK_DURATION` do `.env`, e a API geral é de fato aplicada por um
middleware dedicado (`GeneralRateLimitMiddleware`) a todas as rotas `/api/*`, exceto
`/api/auth/login` e `/api/recognition/detect` (já protegidas por limiters próprios) e
`/api/health` (sempre acessível para monitoramento).

### 3. Segurança de API

**Proteções implementadas**:
- Limite de tamanho de requisição (10MB por padrão).
- Rate limiting por rota (ver ressalva acima sobre a API geral).
- Rastreamento de requisições por IP e por usuário.
- Toda consulta ao banco passa pelo ORM (SQLAlchemy) com parâmetros vinculados — não há
  concatenação de SQL em nenhum ponto do código.
- Respostas de erro 500 não incluem a mensagem da exceção interna.

**Autorização por rota**: rotas que expõem o cadastro de pessoas ou acionam hardware exigem
papel de admin (`require_admin`), não apenas um token válido:

| Rota | Dependência |
|---|---|
| `GET/POST/PUT/DELETE /api/users*` | `require_admin` |
| `GET /api/access-logs`, `GET /api/presence/history` | `require_admin` |
| `POST /api/export` | `require_admin` |
| `POST /api/hardware/open-door` | `require_admin` |
| `GET /api/stats`, `GET /api/presence/current`, `POST /api/recognition/detect` | `get_current_user` (operacional) |
| `POST /api/auth/change-password` | `get_current_user` (auto-serviço) |

Coberto por `tests/test_route_authorization.py`, que reprova qualquer rota da primeira lista
que volte a aceitar um token com `role != "admin"`.

### 3b. Tratamento de Entrada e Saída (XSS / injeção de fórmula)

- **Escape na saída**: `dashboard.html` e `monitor.html` passam todo valor vindo da API por
  `escapeHtml()` antes de interpolar em `innerHTML` (nomes, e-mails, ações e status nas
  tabelas de presença, logs e usuários, e no overlay de detecção). Sem isso, um nome de
  pessoa contendo `<img src=x onerror=...>` executaria script na sessão de quem abrisse o
  dashboard — e como o JWT fica no `localStorage`, resultaria em roubo de sessão.
- **Validação na entrada** (segunda camada): `validate_person_name()`
  (`app/models/schemas.py`) restringe nome de pessoa a letras, números, espaço, hífen,
  apóstrofo e ponto — rejeitando `<`, `>`, `&`, `"`, `=` e caracteres de controle. Aplicada
  em `UserCreate`/`UserUpdate` e explicitamente em `POST /api/users_register`, que recebe
  `Form` e por isso não passa por schema Pydantic.
- **Exportação**: `sanitize_cell()` (`app/utils/export.py`) prefixa com apóstrofo qualquer
  célula iniciada por `=`, `+`, `-` ou `@`, neutralizando CSV/Excel Formula Injection
  (CWE-1236) na planilha exportada.
- Coberto por `tests/test_input_validation.py` e `tests/test_export_sanitization.py`.

### 4. Cabeçalhos de Segurança

Todas as respostas incluem:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Content-Security-Policy: default-src 'self'; script-src 'self' 'nonce-<gerado por requisição>'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self';
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(self), microphone=(), ...
Strict-Transport-Security: max-age=31536000 (apenas em produção)
```

`script-src` não usa mais `'unsafe-inline'`/`'unsafe-eval'` — cada resposta gera um nonce
aleatório (`app/security/middleware.py`), e só a tag `<script>` das páginas do dashboard
carrega esse nonce; qualquer script injetado por um ataque de XSS não teria o nonce correto
e seria bloqueado pelo navegador. `style-src` mantém `'unsafe-inline'` deliberadamente — o
risco de XSS via `style` é bem menor que via `script`, e os templates usam bastante CSS
inline; reescrevê-los fica para uma rodada futura, se necessário.

### 5. Configuração de CORS

**Antes (inseguro)**:
```python
allow_origins=["*"]  # qualquer origem pode acessar
```

**Depois (seguro)**:
```python
# Apenas as origens configuradas são permitidas
# Controlado pela variável de ambiente ALLOWED_ORIGINS
allow_origins=["http://localhost:8001", "https://seudominio.com"]
```

### 6. Segurança do Reconhecimento Facial

**Anti-spoofing**:
- Checagem de vivacidade por análise de movimento entre frames consecutivos da mesma
  câmera (diferença de pixel na região do rosto).

> **Limitação deliberada e permanente**: essa checagem **não é** uma prevenção real de
> replay attack, e não pretende ser. Um vídeo ou foto exibido na tela de um celular também
> produz diferença de pixel entre frames e pode passar nessa checagem. Não há detecção de
> padrão de moiré de tela, análise de textura/frequência, nem estimativa de profundidade —
> isso exigiria um modelo de anti-spoofing dedicado, fora do escopo deste projeto. Trate
> esse recurso apenas como um filtro contra foto 100% estática, não como proteção contra um
> ataque de apresentação (presentation attack) planejado.

**Proteção de dados**:
- **Criptografia em repouso do dado biométrico**: quando `EMBEDDING_ENCRYPTION_KEY` está
  definida, cada embedding é criptografado com Fernet (AES-128-CBC + HMAC-SHA256) antes de
  ir para o banco — a chave é derivada por PBKDF2-HMAC-SHA256 (480.000 iterações) com salt
  aleatório guardado em `data/embedding_salt.key` (`app/security/crypto.py`). Sem a chave, o
  sistema grava em texto claro e registra um aviso no startup. Bancos criados antes desta
  versão continuam legíveis (o formato antigo é aceito na leitura); use
  `scripts/encrypt_embeddings.py` para criptografar o que já está gravado.

  > **Guarde `data/embedding_salt.key` junto do backup da chave.** Sem os dois, os
  > embeddings já gravados não podem ser recuperados.
- Embeddings faciais são armazenados no banco (não as imagens originais) —
  `app/api/routes.py`/`app/database/db.py` confirmam que nenhuma foto de cadastro é
  gravada em disco, apenas o vetor numérico do rosto.
- Normalização L2 para comparação consistente entre embeddings.
- Validação de qualidade de imagem (nitidez via variância do Laplaciano, brilho, contraste,
  tamanho mínimo do rosto) roda em `extract_embedding()` antes de qualquer cadastro ou
  reconhecimento — imagens borradas, muito escuras/claras ou com rosto pequeno demais são
  rejeitadas.

## Checklist de Implantação em Produção

1. **Copie e configure o `.env`**:
   ```bash
   cp .env.example .env
   # Edite o .env com valores seguros
   ```

2. **Gere segredos seguros**:
   ```bash
   # Chave JWT (mínimo 32 caracteres)
   openssl rand -base64 32

   # Chave de criptografia
   openssl rand -base64 16
   ```

3. **Configure o ambiente**:
   ```bash
   ENVIRONMENT=production
   ALLOWED_ORIGINS=https://seudominio.com
   ```

4. **Desabilite recursos de debug**:
   ```bash
   RELOAD=false
   ```

5. **Defina uma senha de admin forte** (mínimo 8 caracteres, maiúsculas, minúsculas,
   números e caracteres especiais, sem palavras de dicionário) — em `ENVIRONMENT=production`
   o sistema recusa iniciar se `ADMIN_PASSWORD` não atender a esses requisitos.

6. **Configure o firewall**:
   - Restrinja o acesso apenas às portas necessárias.
   - Considere usar um proxy reverso (nginx/traefik).
   - Habilite TLS/SSL.

7. **Configure monitoramento**:
   - Habilite log em arquivo.
   - Configure rotação de logs.
   - Monitore tentativas de autenticação falhas.

## Boas Práticas de Segurança

### Gerenciamento de senhas
- Troque a senha padrão de admin imediatamente após a configuração inicial.
- Use um gerenciador de senhas para senhas fortes e únicas.
- Rotacione segredos periodicamente.
- Nunca commite o arquivo `.env` no controle de versão.

### Segurança de rede
- Use HTTPS em produção.
- Coloque o serviço atrás de um proxy reverso com terminação TLS.
- Restrinja o CORS a origens específicas.
- Use VPN para acesso administrativo quando possível.

### Proteção de dados
- Faça backups regulares do banco de dados.
- Criptografe backups em repouso.
- Limite o acesso aos arquivos de banco de dados.
- Considere criptografia de banco para implantações sensíveis.

### Monitoramento
- Revise os logs de acesso regularmente.
- Configure alertas para atividade suspeita.
- Monitore bloqueios de rate limiting.
- Acompanhe detecções de rostos desconhecidos.

## Resposta a Incidentes de Segurança

### Se você suspeitar de uma violação

1. **Imediatamente**:
   - Troque a senha de admin.
   - Revogue todas as sessões ativas (reinicie o servidor).
   - Revise os logs de acesso.

2. **Investigue**:
   - Verifique tentativas de acesso não autorizado.
   - Revise os logs de reconhecimento facial.
   - Verifique a integridade do banco de usuários.

3. **Recupere**:
   - Restaure a partir de um backup limpo, se necessário.
   - Atualize todos os segredos.
   - Revise e reforce as configurações de segurança.

### Relatando vulnerabilidades de segurança

Se você descobrir uma vulnerabilidade de segurança:
1. Não crie uma issue pública.
2. Contate os mantenedores diretamente.
3. Forneça passos detalhados de reprodução.
4. Aguarde a correção antes de divulgar publicamente.

## Notas de Conformidade

### LGPD / Considerações de privacidade
- Embeddings faciais são considerados dados biométricos.
- Implemente políticas de retenção de dados.
- Forneça um mecanismo para exclusão de dados a pedido do titular.
- Considere acordos de tratamento de dados quando aplicável.

### Trilha de auditoria
Todos os eventos relevantes de segurança são registrados:
- Tentativas de autenticação (sucesso e falha).
- Alteração de senha.
- Cadastro/remoção de usuários.
- Detecções de rostos desconhecidos.
- Operações de abertura de porta.

## Limitação de Segurança Deliberada

O único item que continua fora do escopo, por decisão consciente (não por lacuna
não descoberta): a checagem de vivacidade (seção 6 acima) é um filtro simples contra foto
estática, não uma proteção real contra replay attack — isso exigiria um modelo de
anti-spoofing dedicado.

## Changelog

### Versão 3.0
- [x] Métricas de desempenho (`avg_detection_latency_ms`, `detection_fps`) em `/api/stats`.
- [x] Feed de eventos ao vivo no dashboard (polling incremental via `after_id`).
- [x] Alertas por e-mail em detecção de rosto desconhecido (opcional, desabilitado por
      padrão).
- [x] `/api/health` expõe o estado real do serviço de reconhecimento facial
      (`model_ready`/`model_error`).
- [x] Captura de câmera opcional do lado do servidor (webcam local ou RTSP/arquivo).
- [x] Auditoria interna (2026-08-27) identificou 6 divergências entre este documento e o
      código real; todas corrigidas na mesma revisão:
      rate limit de login e de API geral agora honram `.env`/são de fato aplicados;
      CSP usa nonce por requisição em vez de `unsafe-inline`/`unsafe-eval`;
      validação de qualidade de imagem ativada no serviço real (arquivo morto removido);
      liveness com limiar mais rigoroso e sem o campo `blink_detected` (nunca calculado);
      validação de força de senha também cobre a senha admin inicial via `.env`.
- [x] Auditoria de segurança completa (2026-08-31,
      `docs/security-audit/relatorio-auditoria-seguranca.pdf`) — os 5 achados foram
      corrigidos nesta mesma revisão:
      - XSS armazenado (crítico) via nome/e-mail de pessoa no dashboard e no monitor:
        `escapeHtml()` na saída + `validate_person_name()` na entrada.
      - Rotas sensíveis de leitura/ação promovidas de `get_current_user` para
        `require_admin`, com teste travando o contrato.
      - CSV/Excel Formula Injection na exportação: `sanitize_cell()`.
      - Senha admin hardcoded em `scripts/stress_test.py`: agora lida de
        `ADMIN_PASSWORD`, e o script recusa rodar sem ela.
      - `EMBEDDING_ENCRYPTION_KEY` deixou de ser configuração morta: os embeddings
        faciais são criptografados em repouso (`app/security/crypto.py`).
- [x] `DATABASE_PATH` do `.env` passou a ter precedência sobre `config.yaml` — antes o
      caminho vinha só do YAML e a variável de ambiente não tinha efeito nenhum.

### Versão 2.0 - Refatoração de Segurança
- [x] Removidos segredos hardcoded dos arquivos de configuração.
- [x] Configuração baseada em variáveis de ambiente.
- [x] Requisitos de força de senha adicionados.
- [x] Rate limiting implementado nas rotas críticas.
- [x] Cabeçalhos de segurança adicionados a todas as respostas.
- [x] Configuração de CORS restringida.
- [x] Algoritmo de reconhecimento facial unificado (DeepFace Facenet512).
- [x] Validação de qualidade de rosto adicionada (ativada de fato na versão 3.0).
- [x] Detecção de anti-spoofing implementada (ver limitação deliberada acima).
- [x] Middleware de validação de requisição adicionado.

## Referências

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Segurança no FastAPI](https://fastapi.tiangolo.com/tutorial/security/)
- [Documentação do DeepFace](https://github.com/serengil/deepface)
