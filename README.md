# Face Recognition Pro 2.0

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
pip install -r requirements.txt
```

**Nota:** A primeira execução pode levar alguns minutos pois o DeepFace irá baixar os modelos de reconhecimento facial (cerca de 500MB).

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

Para detalhes completos de segurança, consulte [SECURITY.md](SECURITY.md).

```yaml
app_name: "Face Recognition Pro 2.0"
version: "2.0.0"

server:
  host: "0.0.0.0"
  port: 8000
  reload: true

database:
  type: "sqlite"
  path: "data/face_recognition.db"

face_recognition:
  model: "Facenet512"      # Modelo de embedding
  detector: "retina"       # Detector de rosto (retina, mtcnn, opencv)
  distance_metric: "cosine"
  threshold: 0.4           # Limite de confiança (0-1, menor = mais rigoroso)

anti_spoofing:
  enabled: true
  blink_detection: true

video:
  default_source: 0       # 0 = webcam padrão
  fps_limit: 30

presence:
  timeout_seconds: 60      # Tempo para considerar ausente

security:
  jwt_secret: "sua-chave-secreta-aqui"
  admin_username: "admin"
  # Configure a senha real no .env, nunca no config.yaml
```

---

## Como Executar

### Iniciar o servidor

```bash
python main.py
```

O sistema estará disponível em:
- **Dashboard:** http://localhost:8000/dashboard
- **Documentação API:** http://localhost:8000/docs
- **Página inicial:** http://localhost:8000

### Credenciais de Administrador

Defina `ADMIN_USERNAME` e `ADMIN_PASSWORD` no arquivo `.env` antes de iniciar o sistema.

**IMPORTANTE:** Nao use senha padrao ou senha de exemplo em ambiente real.

---

## Funcionalidades

### 1. Motor de Reconhecimento Facial
- ✅ Utiliza DeepFace com modelo Facenet512
- ✅ Embeddings faciais de alta precisão
- ✅ Suporte a barba, óculos, variações de ângulo e iluminação
- ✅ Comparação por similaridade cosseno

### 2. Detecção Facial
- ✅ RetinaFace (recomendado) - alta precisão
- ✅ MTCNN alternativo
- ✅ Fallback para OpenCV Haar Cascade

### 3. Anti-Spoofing
- ✅ Detecção de vivacidade (liveness)
- ✅ Verificação de piscadas
- ✅ Análise de movimento

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
requirements.txt - Dependências
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
