"""Baixa para dentro do projeto os assets de front-end antes servidos por CDN.

Motivo: as páginas carregavam a fonte Inter de fonts.googleapis.com e os ícones
do Font Awesome de cdnjs.cloudflare.com. Num sistema de controle de acesso
on-premise isso significa (a) interface quebrada sem internet — sem nenhum ícone —
e (b) um terceiro servindo CSS para a tela administrativa. Servindo localmente, o
CSP volta a `style-src 'self'` / `font-src 'self'`.

Uso:
    python scripts/vendor_assets.py

Idempotente: só baixa o que ainda não existe. Rode de novo para atualizar versão
(apague app/static/vendor/ antes).
"""

import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "app" / "static" / "vendor"

FA_VERSION = "6.4.0"
FA_BASE = f"https://cdnjs.cloudflare.com/ajax/libs/font-awesome/{FA_VERSION}"
FA_WEBFONTS = [
    "fa-brands-400.woff2",
    "fa-regular-400.woff2",
    "fa-solid-900.woff2",
    "fa-v4compatibility.woff2",
]

INTER_CSS_URL = (
    "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap"
)
# Sem User-Agent de browser, o Google devolve @font-face apontando para .ttf.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
# Subsets que interessam ao português; os demais (cyrillic, greek, vietnamese)
# só somariam peso.
INTER_SUBSETS = ("latin", "latin-ext")


def fetch(url: str, ua: str | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ua} if ua else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def vendor_fontawesome() -> None:
    css_dir = VENDOR / "fontawesome" / "css"
    fonts_dir = VENDOR / "fontawesome" / "webfonts"
    css_dir.mkdir(parents=True, exist_ok=True)
    fonts_dir.mkdir(parents=True, exist_ok=True)

    css_path = css_dir / "all.min.css"
    if not css_path.exists():
        css = fetch(f"{FA_BASE}/css/all.min.css").decode("utf-8")
        # Remove os fallbacks .ttf: só baixamos woff2 (suportado por todo
        # navegador atual) e referência morta viraria 404.
        css = re.sub(
            r',url\(\.\./webfonts/[^)]*\.ttf\) format\("truetype"\)', "", css
        )
        css_path.write_text(css, encoding="utf-8")
        print(f"  css/all.min.css ({len(css) // 1024} KB)")

    for nome in FA_WEBFONTS:
        destino = fonts_dir / nome
        if destino.exists():
            continue
        destino.write_bytes(fetch(f"{FA_BASE}/webfonts/{nome}"))
        print(f"  webfonts/{nome} ({destino.stat().st_size // 1024} KB)")


def vendor_inter() -> None:
    out_dir = VENDOR / "inter"
    out_dir.mkdir(parents=True, exist_ok=True)
    css_path = out_dir / "inter.css"
    if css_path.exists():
        return

    css = fetch(INTER_CSS_URL, ua=BROWSER_UA).decode("utf-8")

    # O CSS do Google vem comentado por subset: /* latin */ @font-face {...}
    partes = re.split(r"/\* ([a-z\-]+) \*/", css)
    blocos = [
        (partes[i], partes[i + 1])
        for i in range(1, len(partes) - 1, 2)
        if partes[i] in INTER_SUBSETS
    ]
    if not blocos:
        sys.exit("nenhum subset reconhecido no CSS do Google Fonts")

    baixados = 0
    saida = [
        "/* Inter — servido localmente (subsets latin e latin-ext).\n"
        "   Gerado por scripts/vendor_assets.py; não edite à mão. */\n"
    ]
    for nome, corpo in blocos:
        def troca(m):
            nonlocal baixados
            arquivo = m.group(1).rsplit("/", 1)[-1]
            destino = out_dir / arquivo
            if not destino.exists():
                destino.write_bytes(fetch(m.group(1)))
                baixados += 1
            return f"url(./{arquivo}) format('woff2')"

        corpo = re.sub(
            r"url\((https://fonts\.gstatic\.com/[^)]+)\) format\('woff2'\)",
            troca, corpo,
        )
        saida.append(f"/* {nome} */{corpo}")

    css_path.write_text("".join(saida), encoding="utf-8")
    print(f"  inter/inter.css + {baixados} arquivo(s) woff2")


def main() -> int:
    print("Font Awesome:")
    vendor_fontawesome()
    print("Inter:")
    vendor_inter()

    total = sum(f.stat().st_size for f in VENDOR.rglob("*") if f.is_file())
    print(f"\nTotal em app/static/vendor/: {total / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
