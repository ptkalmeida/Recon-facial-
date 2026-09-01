# Face Recognition Pro 3.0

## Sistema Profissional de Reconhecimento Facial

### Visão Geral

Sistema completo de reconhecimento facial utilizando Inteligência Artificial moderna, com backend FastAPI e frontend responsivo. Substitui o sistema antigo baseado em Haar Cascade + histogramas por uma solução robusta com DeepFace.

---

## Requisitos do Sistema

### Hardware
- Processador: Intel Core i5 ou superior (mínimo)
- Memória RAM: 8GB (mínimo recomendado)
- Espaço em disco: 2GB (para dependências + banco de dados)
- Webcam ou câmera IP compatível com OpenCV

### Software
- Windows 10/11 ou Linux
- Python 3.10+
- pip (gerenciador de pacotes Python)

---

## Instalação

### 1. Clone ou baixe o projeto

### 2. Criar ambiente virtual (recomendado)

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python -m venv venv
source venv/bin/activate
```

### 3. Instalar dependências

```bash
# Aplicação (obrigatório)
pip install -r requirements.txt

# Backend de reconhecimento facial (necessário em produção — ver aviso abaixo)
pip install -r requirements-recognition.txt

# Só para rodar os testes
pip install -r requirements-dev.txt
```

**Nota:** A primeira execução baixa o modelo de reconhecimento (~300MB para o
InsightFace `buffalo_l`).

> ### ⚠️ Sem o backend de reconhecimento, o sistema sobe em modo degradado
>
> `requirements.txt` traz só a detecção base (OpenCV). Sem
> `requirements-recognition.txt`, o serviço cai num fallback que **detecta rosto
> mas não identifica pessoa**: os "embeddings" são histogramas de intensidade,
> não vetores biométricos, e o reconhecimento passa a ser essencialmente
> aleatório.
>
> Esse estado é sinalizado, não silencioso — o log de startup registra
> `RECONHECIMENTO DEGRADADO` e `GET /api/health` responde:
>
> ```json
> {
>   "status": "degraded",
>   "recognition": { "degraded": true, "embedding_backend": "opencv-hog (sem valor biométrico)" }
> }
> ```
>
> **Cheque isso após instalar.** Se `recognition.degraded` for `true`, o sistema
> não está reconhecendo ninguém de verdade.

> ### Sobre a versão do Python
>
> O padrão em `config.yaml` (`face_model: Facenet512`) depende de
> DeepFace + TensorFlow, e **TensorFlow não tem wheel para Python 3.14**. Em
> Python 3.14 use o InsightFace (opção A do
> `requirements-recognition.txt`, que é a prioridade 0 do código e não precisa de
> TensorFlow). Para usar Facenet512, rode a aplicação em Python 3.12 ou 3.13.
>
> Trocar de backend invalida os rostos já cadastrados — embeddings de modelos
> diferentes não são comparáveis. É preciso recadastrar as pessoas.

> ### Validação do reconhecimento (InsightFace `buffalo_l`)
>
> Medido com fotos reais de cadastro, embeddings de 512 dimensões:
>
> | par | distância de cosseno | veredito |
> |---|---|---|
> | pessoa A × pessoa B | 0.9046 | pessoas diferentes |
> | pessoa A × outra foto da pessoa A | 0.1847 | mesma pessoa |
> | pessoa B × outra foto da pessoa A | 0.8564 | pessoas diferentes |
>
> O limiar em uso (`FACE_THRESHOLD=0.4`) fica com boa margem dos dois lados.

### 4. Configuração de Segurança (IMPORTANTE!)

```bash
# Copie o arquivo de exemplo
cp .env.example .env

# Edite o arquivo .env com seus valores seguros
# NUNCA compartilhe ou commit este arquivo!
```

**Variáveis obrigatórias**:
- `JWT_SECRET_KEY`: Chave secreta para tokens (mínimo 32 caracteres)
- `ADMIN_PASSWORD`: Senha forte para admin

Gere uma chave segura:
```bash
openssl rand -base64 32
```

---

## Configuração

### Arquivo `config.yaml` (Não-sensível)

⚠️ **AVISO**: Não armazene segredos no `config.yaml`! Use o arquivo `.env` para todas as configurações sensíveis.

**Precedência de configuração:**

```
variável de ambiente  >  .env  >  config.yaml  >  default do código
```

Use o `config.yaml` para a configuração versionada da instalação e o `.env`
para segredos e ajustes por máquina. O mapeamento entre o formato aninhado do
YAML e os campos de `Settings` é explícito (`YAML_TO_FIELD` em
[app/config.py](app/config.py)); chave não mapeada é reportada, não ignorada em
silêncio, e há teste que reprova chave órfã.

> Até a versão anterior este arquivo era decorativo: o YAML era carregado e
> nunca usado, então editá-lo não surtia efeito — o arquivo dizia
> `threshold: 0.3` enquanto o valor real era 0.4. O `app/database/db.py` ainda
> o carregava em paralelo, com regras próprias. Hoje há uma fonte só.


Para detalhes completos de segurança, consulte [SECURITY.md](SECURITY.md).

```yaml
app_name: "Face Recognition Pro 3.0"
version: "3.0.0"

server:
  host: "0.0.0.0"
  port: 8001
  reload: false

database:
  path: "data/face_recognition.db"   # sobreposto por DATABASE_PATH

face_recognition:
  model: "Facenet512"        # usado só no caminho DeepFace; ignorado com InsightFace
  detector: "retinaface"
  distance_metric: "cosine"
  threshold: 0.4             # validado com fotos reais (ver acima)
  min_sharpness: 40          # nitidez mínima para aceitar o rosto
  confirmation_min_frames: 3 # quadros para confirmar antes de registrar
  allow_insecure_hog_embeddings: false

door:                        # porta física
  min_confidence: 0.8
  require_liveness: true     # exige vivacidade, não só confiança

presence:
  timeout_seconds: 60

logging:
  level: "INFO"
  log_file: "logs/face_recognition.log"
  max_size_mb: 10            # rotação
  backup_count: 5

security:
  auth_max_attempts: 5
  trusted_proxies: ""        # IPs de proxy que podem enviar X-Forwarded-For
  # Segredos NUNCA aqui: JWT_SECRET_KEY e ADMIN_PASSWORD vão no .env
```

---

## Como Executar

### Iniciar o servidor

```bash
python main.py
```

O sistema estará disponível em:
- **Dashboard:** http://localhost:8001/dashboard
- **Documentação API:** http://localhost:8001/docs
- **Página inicial:** http://localhost:8001

### Credenciais de Administrador

Defina `ADMIN_USERNAME` e `ADMIN_PASSWORD` no arquivo `.env` antes de iniciar o sistema.

**IMPORTANTE:** Nao use senha padrao ou senha de exemplo em ambiente real.

---

## Funcionalidades

### 1. Motor de Reconhecimento Facial
- ✅ InsightFace `buffalo_l` (ArcFace, embeddings de 512 dimensões) via onnxruntime
- ✅ DeepFace/Facenet512 como alternativa (exige TensorFlow, e portanto Python ≤ 3.13)
- ✅ Comparação por distância de cosseno, limiar validado com fotos reais
- ✅ Estado real do backend exposto em `GET /api/health` (`recognition.degraded`)

### 2. Detecção Facial
- ✅ RetinaFace (recomendado) - alta precisão
- ✅ MTCNN alternativo
- ✅ Fallback para OpenCV Haar Cascade

### 3. Anti-Spoofing
- ✅ Checagem de vivacidade por movimento entre quadros consecutivos
- ✅ Exigida para acionar a porta física (`DOOR_REQUIRE_LIVENESS`), com a
  tentativa bloqueada registrada em auditoria
- ⚠️ **Filtro modesto**: barra foto 100% estática, não ataque de apresentação
  planejado (vídeo em tela passa). Ver SECURITY.md — não há detecção de piscada,
  moiré, textura ou profundidade.

### 4. Cadastro de Pessoas
- ✅ Interface web para cadastro
- ✅ Suporte a múltiplas fotos por pessoa
- ✅ Extração automática de embeddings
- ✅ Armazenamento seguro no banco de dados

### 5. Controle de Presença
- ✅ Registro automático de entrada/saída
- ✅ Status em tempo real (presente/ausente)
- ✅ Histórico de presença por dia

### 6. Logs e Auditoria
- ✅ Registro de todos os acessos
- ✅ Tentativas de acesso não autorizado
- ✅ Detecções de desconhecidos
- ✅ Histórico completo com data/hora

### 7. Dashboard Web
- ✅ Interface moderna e responsiva
- ✅ Estatísticas em tempo real
- ✅ Lista de presença atual
- ✅ Histórico de acessos
- ✅ Cadastro de novos usuários

### 8. Relatórios
- ✅ Exportação para Excel (.xlsx)
- ✅ Exportação para PDF
- ✅ Filtragem por período
- ✅ Filtragem por usuário

---

## Estrutura do Projeto

```
/app
  /api           - Rotas da API REST
  /services      - Lógica de negócio
  /models        - Schemas Pydantic
  /database      - Gerenciamento do banco
  /security      - Autenticação e autorização
  /templates     - Templates HTML
  /static        - Arquivos estáticos
  /utils         - Utilitários
main.py          - Ponto de entrada
config.yaml      - Configurações
requirements.txt - Dependências da aplicação
requirements-recognition.txt - Backend de reconhecimento (opcional/produção)
requirements-dev.txt - Dependências de teste
```

---

## APIs Disponíveis

Contrato completo, exemplos de request/response e estados do `/api/health` em
[docs/API.md](docs/API.md).

### Autenticação
- `POST /api/auth/login` - Login
- `POST /api/auth/change-password` - Alterar senha

### Usuários
- `GET /api/users` - Listar usuários
- `POST /api/users` - Criar usuário
- `GET /api/users/{id}` - Ver usuário
- `PUT /api/users/{id}` - Atualizar usuário
- `DELETE /api/users/{id}` - Deletar usuário
- `POST /api/users_register` - Cadastrar com foto

### Presença
- `GET /api/presence/current` - Presença atual
- `GET /api/presence/history` - Histórico de presença

### Acesso
- `GET /api/access-logs` - Logs de acesso

### Reconhecimento
- `POST /api/recognition/detect` - Detectar rosto

### Relatórios
- `GET /api/stats` - Estatísticas do sistema
- `POST /api/export` - Exportar relatório

---

## Solução de Problemas

### Erro ao importar DeepFace
```bash
pip install deepface
```

### Erro com RetinaFace
```bash
pip install retina-face
```

### Webcam não detectada
Verifique se a câmera está funcionando com outro aplicativo.
O parâmetro `video.default_source` pode ser alterado no config.yaml.

### Porta já em uso
Altere a porta no config.yaml:
```yaml
server:
  port: 8001
```

---

## Extensões Futuras Suportadas

O código já inclui estrutura para:
- Múltiplas câmeras IP
- RTSP streaming
- Controle de ponto
- Exportação Excel/PDF

---

## Tecnologias Utilizadas

- **Backend:** FastAPI + Uvicorn
- **Frontend:** HTML5 + CSS3 + JavaScript
- **Database:** SQLite (via SQLAlchemy)
- **IA:** DeepFace, RetinaFace, MTCNN
- **Auth:** JWT + bcrypt

---

## Licença

MIT License - Uso livre para fins comerciais e educacionais.
