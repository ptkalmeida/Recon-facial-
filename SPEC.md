# Especificação: Sistema de Reconhecimento Facial

## Visão Geral
Sistema de reconhecimento facial para controle de presença com segurança criptográfica.

## Requisitos Funcionais

### 1. Captura de Vídeo
- Webcam local (índice de dispositivo configurável)
- Câmera IP via RTSP (URL configurável)
- Modo de fallback automático entre fontes

### 2. Detecção e Reconhecimento
- Biblioteca: face_recognition (dlib) + OpenCV
- Bounding box em tempo real
- Nome da pessoa identificada sobreposto
- Threshold de confiança: 0.6 (configurável)

### 3. Registro de Presença
- Detecção de entrada: pessoa ausente por > 60 segundos retorna
- Detecção de saída: pessoa sai da zona e não retorna por > 60 segundos
- Log: nome, data, hora, tipo (entrada/saída)
- Banco SQLite local

### 4. Interface
- Janela OpenCV com feed de vídeo
- Controles de teclado (Q=sair, P=pausar)
- Exibição de FPS e status

## Requisitos de Segurança

### 1. Criptografia de Encodings
- Algoritmo: AES-256-GCM
- Biblioteca: cryptography
- Chave derivada de senha via PBKDF2
- Arquivo: `data/encodings.enc`

### 2. Banco de Dados Criptografado
- SQLite com extensão SQLCipher
- Senha configurada no arquivo de config
- Arquivo: `data/logs.db`

### 3. Logs de Acesso
- Registrar: usuário, timestamp, IP origem, ação
- Arquivo: `data/access.log`

### 4. Autenticação
- Senha mestra para cadastro/remoção de pessoas
- Armazenada com hash seguro (bcrypt)
- Arquivo: `data/auth.json`

### 5. Rate Limiting
- Bloqueio após 5 tentativas falhas
- Duração do bloqueio: 15 minutos
- Arquivo: `data/rate_limit.json`

## Scripts

### 1. `main.py` - Sistema principal
- Iniciar reconhecimento facial
- Monitorar presença
- Exibir interface

### 2. `register.py` - Cadastro de pessoas
- Receber nome e caminho de fotos
- Processar imagens e gerar encodings
- Criptografar e salvar
- Autenticação requerida

### 3. `remove.py` - Remoção de pessoas
- Listar pessoas cadastradas
- Remover encoding específico
- Autenticação requerida

### 4. `export_logs.py` - Exportação CSV
- Exportar logs de presença
- Filtrar por período (opcional)
- Salvar em arquivo CSV

### 5. `setup.py` - Configuração inicial
- Criar diretórios necessários
- Gerar chave mestra
- Inicializar banco de dados

## Estrutura de Dados

### encoding.json (criptografado)
```json
{
  "pessoa1": {"encoding": [...], "created_at": "timestamp"},
  "pessoa2": {"encoding": [...], "created_at": "timestamp"}
}
```

### logs.db (SQLite)
```sql
CREATE TABLE presence_log (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  date TEXT NOT NULL,
  time TEXT NOT NULL,
  type TEXT NOT NULL -- 'entrada' or 'saida'
);

CREATE TABLE access_log (
  id INTEGER PRIMARY KEY,
  user TEXT,
  action TEXT,
  ip TEXT,
  timestamp TEXT
);
```

## Parâmetros de Configuração
- `config.yaml` - Arquivo principal de configurações
- Threshold de confiança: 0.6
- Timeout de ausência: 60 segundos
- FPS mínimo para detecção: 1

## Dependências
- face-recognition
- opencv-python
- cryptography
- numpy
- bcrypt
- python-sqlcipher ouryptography para SQLite