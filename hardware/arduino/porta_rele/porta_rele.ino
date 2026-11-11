/*
  porta_rele.ino - controlador da fechadura do Face Recognition Pro.

  Recebe comandos de 1 byte pela USB (serial 9600):
    'O'  abre  (aciona o rele)
    'C'  trava (desliga o rele)
    '?'  responde o estado: "ABERTA" ou "TRAVADA"

  Seguranca:
  - Liga sempre TRAVADO.
  - Trava sozinho depois de TEMPO_MAX_ABERTA_MS aberto, mesmo sem receber 'C'
    (PC travou, cabo saiu, programa caiu no meio da abertura).
  - O botao de saida/emergencia NAO passa por aqui: ele corta a energia da
    fechadura direto (ver docs/INSTALACAO_PORTA.md). Arduino travado ou sem
    energia nunca impede ninguem de sair.

  Ligacao: modulo rele no pino PINO_RELE, fechadura no contato do rele.
  Carregar com a IDE do Arduino (placa: Arduino Uno/Nano).
*/

// ---- ajuste aqui -----------------------------------------------------------
const int PINO_RELE = 7;

// A maioria dos modulos rele baratos (azul, com optoacoplador) aciona com
// nivel BAIXO. Se o rele clicar ao ligar o Arduino e soltar no comando 'O',
// troque para false.
const bool RELE_ACIONA_EM_NIVEL_BAIXO = true;

// Maior tempo que o rele pode ficar acionado sem um novo 'O'. Deve ser maior
// que door.open_seconds do config.yaml (padrao 5).
const unsigned long TEMPO_MAX_ABERTA_MS = 10000;
// ---------------------------------------------------------------------------

const int LED = LED_BUILTIN;  // aceso = porta aberta
bool aberta = false;
unsigned long abertaDesde = 0;

void aplicarRele(bool acionar) {
  int nivel;
  if (RELE_ACIONA_EM_NIVEL_BAIXO) {
    nivel = acionar ? LOW : HIGH;
  } else {
    nivel = acionar ? HIGH : LOW;
  }
  digitalWrite(PINO_RELE, nivel);
  digitalWrite(LED, acionar ? HIGH : LOW);
}

void abrir() {
  aberta = true;
  abertaDesde = millis();
  aplicarRele(true);
}

void travar() {
  aberta = false;
  aplicarRele(false);
}

void setup() {
  // Define o nivel de "desligado" ANTES de virar saida, para o rele nao dar
  // um pulso no boot.
  aplicarRele(false);
  pinMode(PINO_RELE, OUTPUT);
  pinMode(LED, OUTPUT);
  travar();
  Serial.begin(9600);
  Serial.println("PRONTO");
}

void loop() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == 'O') {
      abrir();
    } else if (c == 'C') {
      travar();
    } else if (c == '?') {
      Serial.println(aberta ? "ABERTA" : "TRAVADA");
    }
    // Qualquer outro byte (\r, \n, lixo) e ignorado.
  }

  // millis() da a volta a cada ~49 dias; a subtracao sem sinal continua certa.
  if (aberta && (millis() - abertaDesde >= TEMPO_MAX_ABERTA_MS)) {
    travar();
  }
}
