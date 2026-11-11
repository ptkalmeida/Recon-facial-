# Instalação da fechadura (Arduino + relé)

Liga o reconhecimento facial a uma fechadura ou portão de verdade. O software
já está pronto: falta montar o hardware, carregar o Arduino e ligar
`door.enabled` no config.

```
 PC (servidor) ──USB── Arduino ──fios── Módulo relé ──contato seco── Fechadura / portão
```

O PC manda `O` (abrir) e `C` (travar) pela USB. O Arduino aciona o relé, e o
relé fecha o circuito da fechadura. O PC e o Arduino não encostam na energia da
fechadura: quem chaveia é o contato do relé.

## 1. Lista de compras (porta comum)

| Item | Observação |
|---|---|
| Arduino Uno ou Nano | Clone com chip CH340 funciona; pode pedir driver no Windows |
| Cabo USB do Arduino | Até ~3 m. Mais longe: hub USB com fonte ou extensor ativo |
| Módulo relé 1 canal 5 V | O comum, azul, com optoacoplador |
| Fechadura **fail-safe**: eletroímã (ex.: 150 kg, 12 V) ou fecho elétrico fail-safe | **Fail-safe** = destrava quando falta energia. Ver seção 2 |
| Fonte 12 V para a fechadura | Corrente acima do consumo da fechadura (eletroímã típico: 0,5 A → fonte de 1 A ou mais) |
| Botão de saída (NF) | Do lado de dentro, corta a energia da fechadura |
| Botoeira de emergência "quebre o vidro" (NF) | Exigida em rota de fuga |
| Diodo 1N4007 | Só se a fechadura for bobina sem proteção (fecho elétrico) |
| Jumpers macho-fêmea | Arduino ↔ relé |

## 2. Segurança: leia antes de comprar

- **Use fechadura fail-safe.** Faltou energia, deu pane ou o sistema
  travou: ela destrava e ninguém fica preso. Em porta de rota de fuga, isso é
  exigência das normas de incêndio (Corpo de Bombeiros). Fechadura
  *fail-secure*, que continua trancada sem energia, só vai em porta que não é
  saída, e com chave mecânica.
- **Saída e emergência não dependem do sistema.** O botão de saída e a
  botoeira de emergência ficam **em série com a alimentação da fechadura**.
  Apertou, a fechadura perde energia e abre, mesmo com o PC desligado.
- **O Arduino trava sozinho.** Se ficar aberto mais que 10 s sem novo
  comando, ele trava. Isso cobre o PC travar no meio de uma abertura.
- **Rede elétrica (127/220 V):** o módulo relé até suporta, mas a ligação de
  fechadura ou motor na rede deve ser feita por eletricista.
- **Limitação conhecida:** a checagem de "pessoa viva" barra foto impressa,
  mas um vídeo da pessoa no celular pode passar (ver `SECURITY.md`). Para sala
  sensível, combine com outro fator (cartão, senha).

## 3. Ligação

### Arduino → módulo relé

| Arduino | Módulo relé |
|---|---|
| 5V | VCC |
| GND | GND |
| Pino 7 | IN |

### Relé → fechadura (eletroímã fail-safe)

O eletroímã segura a porta **enquanto tem energia**. Para abrir, o relé
**corta** a energia: use os contatos **COM e NF** do relé.

```
 Fonte 12V (+) ── Botão saída (NF) ── Emergência (NF) ── COM [relé] NF ── (+) Eletroímã
 Fonte 12V (−) ─────────────────────────────────────────────────────────── (−) Eletroímã
```

- Relé parado: COM–NF fechado, eletroímã energizado, **porta travada**.
- Comando `O`: relé aciona, COM–NF abre, eletroímã solta, **porta abre**.

### Relé → fecho elétrico (abre quando recebe energia)

Use **COM e NA**: o relé fecha o circuito pelo tempo de abertura.

```
 Fonte 12V (+) ── COM [relé] NA ── (+) Fecho elétrico (−) ── Fonte 12V (−)
                                      └── diodo 1N4007 em paralelo com o fecho,
                                          faixa do diodo no (+)
```

## 4. Carregar o Arduino

1. Instale a [IDE do Arduino](https://www.arduino.cc/en/software).
2. Abra `hardware/arduino/porta_rele/porta_rele.ino`.
3. Ferramentas → Placa: *Arduino Uno* (ou *Nano*); Porta: a COM do Arduino.
4. Clique em **Carregar**.
5. Abra o Monitor Serial (9600): deve aparecer `PRONTO`. Digite `O` e o relé
   clica; digite `C` e ele solta.

**Relé invertido?** Se o relé clica ao ligar o Arduino e solta com `O`, troque
`RELE_ACIONA_EM_NIVEL_BAIXO` para `false` no início do sketch e carregue de
novo.

## 5. Testar de bancada (sem câmera)

Com o servidor **parado**, porque só um programa pode usar a porta serial por
vez:

```
pip install -r requirements.txt          # inclui pyserial
python scripts/test_door.py --list       # descubra a porta (ex.: COM4)
python scripts/test_door.py --port COM4  # abre por 5 s e trava
```

Esperado: `Arduino respondeu: TRAVADA`, depois o relé clica e a fechadura
solta por 5 s.

## 6. Ligar no sistema

No `config.yaml`, ou com as mesmas chaves no `.env` (`DOOR_ENABLED`,
`DOOR_SERIAL_PORT`...):

```yaml
door:
  enabled: true
  serial_port: COM4        # a porta encontrada no passo 5
  open_seconds: 5
```

Reinicie o servidor. No log deve aparecer
`Porta física conectada em COM4 (9600 baud), travada`. Confira em
`/api/health`:

```json
"door": {"enabled": true, "connected": true}
```

Com `enabled: true` e `connected: false`, o health fica `degraded`: o
reconhecimento funciona, mas a porta não abre. O sistema tenta reconectar
sozinho a cada abertura, então reconectar o cabo resolve.

O admin também pode abrir pelo painel (`POST /api/hardware/open-door`), e
fica registrado no log.

## 7. Portão automático

Funciona. Quase todo portão automático (deslizante, basculante, pivotante)
tem na central do motor uma entrada de **botoeira**: dois bornes que, quando
fechados por um instante, mandam o portão abrir. O relé faz o papel desse
botão.

1. Ligue os contatos **COM e NA** do relé em paralelo com a botoeira (bornes
   "BOT", "PUL" ou "BOTOEIRA" da central; consulte o manual do motor). O
   botão e o controle remoto continuam funcionando.
2. Configure um **pulso**, não um tempo aberto:
   ```yaml
   door:
     open_seconds: 1
   ```
   O fechamento fica por conta da central do portão (fechamento automático).
   Manter o contato fechado por 5 s pode fazer a central parar ou inverter o
   motor.
3. **Não altere os sensores do portão** (fotocélula, anti-esmagamento). O
   sistema só substitui o apertar do botão.

**Para pedestre:** câmera na altura do rosto, perto do portão (1 a 3 m),
com boa luz, inclusive à noite. Contraluz atrapalha muito.

**Para carro:** reconhecer o rosto através do para-brisa, de dentro do carro,
funciona mal (reflexo, ângulo, distância). Para veículo, o adequado é
leitura de placa ou tag/controle. O reconhecimento facial serve bem para o
portão de pedestre.

## 8. Problemas comuns

| Sintoma | Causa provável |
|---|---|
| `could not open port` / `Acesso negado` | Outro programa usando a porta (Monitor Serial da IDE, servidor rodando junto com o script de teste) ou COM errada |
| Arduino não aparece no `--list` | Cabo só de carga (sem dados) ou falta o driver CH340 |
| Relé clica mas a fechadura não mexe | Ligado em NA/NF trocado, ou fonte da fechadura fraca/desligada |
| Relé acionado o tempo todo | Lógica invertida: `RELE_ACIONA_EM_NIVEL_BAIXO` |
| Porta abre e tranca logo | `open_seconds` maior que o tempo-limite do Arduino (10 s): aumente `TEMPO_MAX_ABERTA_MS` |
| Arduino reinicia sozinho ao acionar o relé | Fechadura ligada na mesma fonte do Arduino: use fonte separada |
