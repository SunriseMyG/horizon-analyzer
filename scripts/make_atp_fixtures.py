"""Génère les fichiers de test de scenarios/atp.yaml dans scenarios/fixtures/.

- e2e-checker.png : damier 256x256, la texture posée sur le cube (F19).
- e2e-skybox.png  : bande verticale de 6 faces de 128x128 (128x768), dans l'ordre que le jeu
  attend pour une skybox (+X, -X, +Y, -Y, +Z, -Z) : il la réinterprète en cubemap (F34). Une
  image ordinaire ne marche pas en skybox (voir ENGINE-skybox-texture dans engine.yaml).
- e2e-loading.png : l'image de chargement du jeu (F54), 640x360.
- e2e-noop.wasm   : le plus petit script valide, une fonction `run` exportée qui ne fait rien
  (F4 l'importe, F51 l'attache à un objet).

    python scripts/make_atp_fixtures.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

FIXTURES = Path(__file__).resolve().parent.parent / "scenarios" / "fixtures"

# Module wasm : en-tête, un type () -> (), une fonction de ce type, exportée sous le nom
# « run », dont le corps est vide.
NOOP_WASM = bytes(
    [0x00, 0x61, 0x73, 0x6D, 0x01, 0x00, 0x00, 0x00]  # \0asm, version 1
    + [0x01, 0x04, 0x01, 0x60, 0x00, 0x00]  # section type : 1 type, func () -> ()
    + [0x03, 0x02, 0x01, 0x00]  # section fonction : 1 fonction, type 0
    + [0x07, 0x07, 0x01, 0x03, 0x72, 0x75, 0x6E, 0x00, 0x00]  # export "run" = fonction 0
    + [0x0A, 0x04, 0x01, 0x02, 0x00, 0x0B]  # code : 1 corps, aucune variable locale, end
)


def checker() -> Image.Image:
    image = Image.new("RGB", (256, 256), "#F2F2F2")
    draw = ImageDraw.Draw(image)
    for row in range(8):
        for col in range(8):
            if (row + col) % 2:
                draw.rectangle((col * 32, row * 32, col * 32 + 31, row * 32 + 31), fill="#E0503C")
    return image


def skybox() -> Image.Image:
    size = 128
    # Un ciel : faces latérales bleues avec un horizon clair, haut bleu foncé, bas vert.
    faces = ["side", "side", "top", "bottom", "side", "side"]
    image = Image.new("RGB", (size, size * 6))
    draw = ImageDraw.Draw(image)
    for index, face in enumerate(faces):
        top = index * size
        for y in range(size):
            if face == "top":
                color = (40, 70, 150)
            elif face == "bottom":
                color = (70, 110, 60)
            else:
                t = y / (size - 1)  # 0 en haut de la face, 1 à l'horizon (en bas)
                color = (int(60 + 150 * t), int(110 + 110 * t), int(200 + 40 * t))
            draw.line((0, top + y, size - 1, top + y), fill=color)
    return image


def loading() -> Image.Image:
    image = Image.new("RGB", (640, 360), "#1B2A4A")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 150, 600, 210), outline="#F2B134", width=4)
    draw.rectangle((48, 158, 380, 202), fill="#F2B134")
    draw.text((40, 230), "e2e loading screen", fill="#FFFFFF")
    return image


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    checker().save(FIXTURES / "e2e-checker.png")
    skybox().save(FIXTURES / "e2e-skybox.png")
    loading().save(FIXTURES / "e2e-loading.png")
    (FIXTURES / "e2e-noop.wasm").write_bytes(NOOP_WASM)
    for name in ("e2e-checker.png", "e2e-skybox.png", "e2e-loading.png", "e2e-noop.wasm"):
        print(f"{FIXTURES / name} ({(FIXTURES / name).stat().st_size} octets)")


if __name__ == "__main__":
    main()
