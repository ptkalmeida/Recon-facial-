# Guia de Segurança - Face Recognition Pro 3.0

## Visão Geral

Este documento descreve as medidas de segurança implementadas no Face Recognition Pro 3.0
e orienta uma implantação segura. Ele foi revisado para refletir o que está **de fato**
implementado no código — não apenas o que foi planejado — incluindo uma seção de
[limitações conhecidas](#limitações-de-segurança-conhecidas) para itens que existem no
código mas não funcionam como o nome sugere, ou que estão parcialmente implementados.

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
  especial) — **aplicada na troca de senha** (`POST /api/auth/change-password`). A senha
  admin inicial, definida via `ADMIN_PASSWORD` no `.env`, **não passa por essa validação**
  no primeiro boot — garanta que ela já nasça forte.
- Hash de senha com bcrypt (fator de custo adaptativo).
- Limite de tentativas de autenticação (5 tentativas por 5 minutos, bloqueio de 15 minutos).
- Bloqueio automático e temporário após tentativas falhas.

**Limites de requisição (rate limits)**:

| Rota | Limite | Janela | Duração do bloqueio |
|---|---|---|---|
| Login | 5 tentativas | 5 minutos | 15 minutos |
| Reconhecimento (`/api/recognition/detect`) | 60 requisições | 1 minuto | 1 minuto |
| API geral | 100 requisições | 1 minuto | — |

> **Limitação conhecida**: os limites de login e reconhecimento acima estão implementados e
> ativos, mas os valores estão fixos no código (`app/security/rate_limiter.py`) — as
> variáveis `AUTH_MAX_ATTEMPTS`/`AUTH_BLOCK_DURATION` do `.env` existem e coincidem com os
> defaults, mas não têm efeito real se alteradas. O limite de "API geral" (100/min) está
> instanciado mas **não é aplicado a nenhuma rota** — hoje só é usado para uma limpeza
> periódica de memória, não para bloquear requisições. Veja
> [limitações conhecidas](#limitações-de-segurança-conhecidas).

### 3. Segurança de API

**Proteções implementadas**:
- Limite de tamanho de requisição (10MB por padrão).
- Rate limiting por rota (ver ressalva acima sobre a API geral).
- Rastreamento de requisições por IP e por usuário.

### 4. Cabeçalhos de Segurança

Todas as respostas incluem:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self';
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(self), microphone=(), ...
Strict-Transport-Security: max-age=31536000 (apenas em produção)
```

> **Limitação conhecida**: o CSP acima permite `'unsafe-inline'` e `'unsafe-eval'` em
> `script-src`, e `'unsafe-inline'` em `style-src`. Isso é necessário hoje porque o
> dashboard usa JavaScript inline, mas reduz significativamente a proteção que uma CSP
> normalmente oferece contra XSS — scripts injetados inline não seriam bloqueados por ela.

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
  câmera (diferença de pixel).

> **Limitação conhecida — importante**: essa checagem **não é** uma prevenção real de
> replay attack. Ela apenas compara a diferença de pixels entre dois frames consecutivos
> e considera "vivo" qualquer variação acima de um limiar baixo. Um vídeo ou foto exibido
> na tela de um celular também produz diferenças de pixel entre frames (ruído da câmera,
> reflexo, leve movimento) e pode facilmente passar nessa checagem. Não há detecção de
> padrão de moiré de tela, análise de textura/frequência, nem estimativa de profundidade.
> Trate esse recurso como uma redução de falsos positivos triviais (foto estática), não
> como proteção contra um ataque de apresentação (presentation attack) planejado.

**Proteção de dados**:
- Embeddings faciais são armazenados no banco (não as imagens originais) —
  `app/api/routes.py`/`app/database/db.py` confirmam que nenhuma foto de cadastro é
  gravada em disco, apenas o vetor numérico do rosto.
- Normalização L2 para comparação consistente entre embeddings.

> **Limitação conhecida**: existe código de validação de qualidade de imagem (nitidez via
> variância do Laplaciano, checagem de brilho) em `app/services/face_recognition_new.py`,
> mas esse arquivo **não é usado** pelo serviço realmente carregado em produção
> (`app/services/face_recognition.py`, importado por `app/api/routes.py`). Ou seja, hoje
> não há validação de qualidade antes de extrair um embedding — qualquer imagem em que um
> rosto seja detectado é processada, mesmo se borrada ou mal iluminada.

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
   números e caracteres especiais, sem palavras de dicionário) — lembre-se de que essa
   senha inicial não é validada automaticamente pelo sistema (ver seção 2 acima).

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

## Limitações de Segurança Conhecidas

Lista consolidada dos itens identificados em auditoria interna (2026-08-27) que existem no
código mas não funcionam exatamente como a documentação anterior sugeria:

1. `AUTH_MAX_ATTEMPTS`/`AUTH_BLOCK_DURATION` do `.env` não têm efeito — os valores do rate
   limiter de login estão fixos no código.
2. O rate limiter de "API geral" (100 req/min) não é aplicado a nenhuma rota — só roda
   limpeza periódica de memória.
3. CSP permite `'unsafe-inline'`/`'unsafe-eval'`, reduzindo a proteção contra XSS.
4. A checagem de "vivacidade" é uma diferença de pixel simples, não uma prevenção real de
   replay attack — ver seção 6.
5. A validação de qualidade de imagem existe em um arquivo não utilizado pelo serviço real
   (`face_recognition_new.py`), não no pipeline ativo.
6. A validação de força de senha não se aplica à senha admin inicial definida via `.env`.

Nenhum desses itens foi corrigido nesta revisão — o objetivo aqui foi deixar o documento
fiel ao comportamento real do sistema. A correção de cada um é um trabalho separado.

## Changelog

### Versão 3.0
- [x] Métricas de desempenho (`avg_detection_latency_ms`, `detection_fps`) em `/api/stats`.
- [x] Feed de eventos ao vivo no dashboard (polling incremental via `after_id`).
- [x] Alertas por e-mail em detecção de rosto desconhecido (opcional, desabilitado por
      padrão).
- [x] `/api/health` expõe o estado real do serviço de reconhecimento facial
      (`model_ready`/`model_error`).
- [x] Captura de câmera opcional do lado do servidor (webcam local ou RTSP/arquivo).
- [x] Documento de segurança revisado para refletir o comportamento real do código (ver
      seção de limitações conhecidas acima).

### Versão 2.0 - Refatoração de Segurança
- [x] Removidos segredos hardcoded dos arquivos de configuração.
- [x] Configuração baseada em variáveis de ambiente.
- [x] Requisitos de força de senha adicionados.
- [x] Rate limiting implementado nas rotas críticas.
- [x] Cabeçalhos de segurança adicionados a todas as respostas.
- [x] Configuração de CORS restringida.
- [x] Algoritmo de reconhecimento facial unificado (DeepFace Facenet512).
- [x] Validação de qualidade de rosto adicionada (ver limitação nº 5 acima).
- [x] Detecção de anti-spoofing implementada (ver limitação nº 4 acima).
- [x] Middleware de validação de requisição adicionado.

## Referências

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Segurança no FastAPI](https://fastapi.tiangolo.com/tutorial/security/)
- [Documentação do DeepFace](https://github.com/serengil/deepface)
