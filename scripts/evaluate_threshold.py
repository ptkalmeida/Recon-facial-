"""Mede o limiar de reconhecimento com fotos de sessões diferentes.

Responde: com o `threshold` atual, quantas vezes um estranho seria aceito como
alguém cadastrado, quantas vezes um cadastrado seria recusado e quantas vezes
seria confundido com outra pessoa.

Estrutura esperada da pasta (uma subpasta por pessoa, uma por sessão de fotos):

    fotos/
      ana/
        2026-11-01/  a1.jpg a2.jpg ...
        2026-11-08/  ...
      bruno/
        sessao1/ ...
        sessao2/ ...

A primeira sessão de cada pessoa (ordem alfabética) faz o cadastro. As fotos
das OUTRAS sessões são o teste. Fotos da mesma sessão nunca ficam dos dois
lados: frames vizinhos são quase idênticos, e a taxa de acerto sairia inflada
- o modelo estaria sendo testado com o que já viu. Pessoas com uma sessão só
entram apenas como cadastro (servem de alvo para os testes de impostor).

Cada foto de teste também conta como "impostor": ela é comparada com todos os
OUTROS cadastrados, simulando alguém de fora diante da câmera.

As fotos são dados biométricos (LGPD, art. 11): use só fotos de pessoas que
consentiram, e não as versione no repositório.

Uso:
    python scripts/evaluate_threshold.py fotos/
    python scripts/evaluate_threshold.py fotos/ --thresholds 0.3,0.35,0.4,0.45
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.face_recognition import (  # noqa: E402
    dedupe_embeddings,
    dedupe_image_bytes,
)

EXTENSOES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

#: pessoa -> sessão -> embeddings das fotos daquela sessão
Fotos = dict[str, dict[str, list[np.ndarray]]]


@dataclass
class Divisao:
    #: pessoa -> embedding de cadastro (média unitária da primeira sessão)
    cadastros: dict[str, np.ndarray]
    #: pessoa -> sessão usada no cadastro
    sessao_cadastro: dict[str, str]
    #: (pessoa, sessão, embedding) de cada foto de teste
    sondas: list[tuple[str, str, np.ndarray]]


@dataclass
class Resultado:
    threshold: float
    sondas: int
    #: cadastrado diante da câmera e ninguém reconhecido
    falsa_rejeicao: float
    #: cadastrado reconhecido como OUTRA pessoa
    troca_identidade: float
    #: estranho (pessoa fora dos cadastros) aceito como alguém
    falsa_aceitacao: float


def _unitario(vetor: np.ndarray) -> np.ndarray:
    vetor = np.asarray(vetor, dtype=np.float32)
    norma = np.linalg.norm(vetor)
    return vetor / norma if norma > 0 else vetor


def _distancia(a: np.ndarray, b: np.ndarray) -> float:
    return 1.0 - float(np.dot(_unitario(a), _unitario(b)))


def dividir(fotos: Fotos) -> Divisao:
    """Separa cadastro e teste POR SESSÃO, nunca por foto."""
    cadastros: dict[str, np.ndarray] = {}
    sessao_cadastro: dict[str, str] = {}
    sondas: list[tuple[str, str, np.ndarray]] = []
    for pessoa in sorted(fotos):
        sessoes = {s: e for s, e in fotos[pessoa].items() if e}
        if not sessoes:
            continue
        ordem = sorted(sessoes)
        primeira = ordem[0]
        # Mesmo pré-processamento do cadastro real: descarta quase-duplicatas
        # e tira a média.
        embeddings, _ = dedupe_embeddings(sessoes[primeira])
        cadastros[pessoa] = _unitario(np.mean(embeddings, axis=0))
        sessao_cadastro[pessoa] = primeira
        for sessao in ordem[1:]:
            for emb in sessoes[sessao]:
                sondas.append((pessoa, sessao, emb))
    return Divisao(cadastros, sessao_cadastro, sondas)


def avaliar(divisao: Divisao, thresholds: list[float]) -> list[Resultado]:
    """Taxas de erro em cada limiar, comparando como o reconhecimento faz (1:N)."""
    distancias = []  # (distância ao próprio cadastro, menor distância a outro)
    for pessoa, _sessao, emb in divisao.sondas:
        propria = _distancia(emb, divisao.cadastros[pessoa])
        outras = [_distancia(emb, cad) for p, cad in divisao.cadastros.items() if p != pessoa]
        distancias.append((propria, min(outras) if outras else float("inf")))

    resultados = []
    total = len(distancias)
    for t in thresholds:
        rejeitadas = trocas = aceitas_de_fora = 0
        for propria, outra in distancias:
            if min(propria, outra) >= t:
                rejeitadas += 1
            elif outra < propria:
                trocas += 1
            # Como impostor: a pessoa da foto não estaria cadastrada.
            if outra < t:
                aceitas_de_fora += 1
        resultados.append(Resultado(
            threshold=t,
            sondas=total,
            falsa_rejeicao=rejeitadas / total if total else 0.0,
            troca_identidade=trocas / total if total else 0.0,
            falsa_aceitacao=aceitas_de_fora / total if total else 0.0,
        ))
    return resultados


def carregar_fotos(raiz: Path, face_service) -> tuple[Fotos, int]:
    """Lê raiz/pessoa/sessão/*.jpg e extrai um embedding por foto.

    Devolve (fotos, quantas imagens não deram embedding).
    """
    import cv2

    fotos: Fotos = {}
    sem_rosto = 0
    for dir_pessoa in sorted(p for p in raiz.iterdir() if p.is_dir()):
        for dir_sessao in sorted(p for p in dir_pessoa.iterdir() if p.is_dir()):
            arquivos = sorted(
                a for a in dir_sessao.iterdir() if a.suffix.lower() in EXTENSOES
            )
            conteudos, _ = dedupe_image_bytes([a.read_bytes() for a in arquivos])
            embeddings = []
            for conteudo in conteudos:
                img = cv2.imdecode(np.frombuffer(conteudo, np.uint8), cv2.IMREAD_COLOR)
                emb = face_service.register_face(img) if img is not None else None
                if emb is None:
                    sem_rosto += 1
                else:
                    embeddings.append(emb)
            fotos.setdefault(dir_pessoa.name, {})[dir_sessao.name] = embeddings
    return fotos, sem_rosto


def _thresholds_padrao(atual: float) -> list[float]:
    valores = {round(v, 2) for v in np.arange(0.20, 0.701, 0.05)}
    valores.add(round(atual, 2))
    return sorted(valores)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("pasta", type=Path, help="raiz com pessoa/sessão/fotos")
    parser.add_argument("--thresholds", help="lista separada por vírgula, com ponto decimal (padrão: 0.20 a 0.70)")
    args = parser.parse_args()

    if not args.pasta.is_dir():
        print(f"Pasta não encontrada: {args.pasta}")
        return 2

    from app.config import settings, settings_dict
    from app.services.face_recognition import FaceRecognitionService

    face_service = FaceRecognitionService(settings_dict)
    if not face_service.initialize():
        print("Não foi possível inicializar o serviço de reconhecimento.")
        return 1
    if face_service.recognition_degraded:
        print("Reconhecimento degradado (HOG): as distâncias não medem identidade. Abortado.")
        return 1

    if args.thresholds:
        thresholds = sorted(float(v) for v in args.thresholds.split(","))
    else:
        thresholds = _thresholds_padrao(settings.face_threshold)

    fotos, sem_rosto = carregar_fotos(args.pasta, face_service)
    divisao = dividir(fotos)
    if len(divisao.cadastros) < 2 or not divisao.sondas:
        print("Dados insuficientes: são precisas ao menos 2 pessoas e alguma pessoa com 2+ sessões.")
        return 1

    print(f"Backend: {face_service.embedding_backend}")
    print(f"Pessoas cadastradas: {len(divisao.cadastros)} | fotos de teste: {len(divisao.sondas)}"
          f" | fotos sem rosto: {sem_rosto}")
    print()
    print(f"{'limiar':>7} {'falsa rejeição':>15} {'troca de pessoa':>16} {'estranho aceito':>16}")
    for r in avaliar(divisao, thresholds):
        marca = "  <- atual" if abs(r.threshold - settings.face_threshold) < 1e-9 else ""
        print(f"{r.threshold:>7.2f} {r.falsa_rejeicao:>15.1%} {r.troca_identidade:>16.1%}"
              f" {r.falsa_aceitacao:>16.1%}{marca}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
