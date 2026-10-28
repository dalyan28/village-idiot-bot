"""Maße, Farben, Themes und Optiken des Skript-Blatts (Maße in pt bezogen auf A4; px = pt · dpi / 72)."""

from dataclasses import dataclass

A4_W, A4_H = 595.28, 841.89
DPI = 200  # 1654 × 2339 px: am Handy nach dem Antippen scharf zoombar

# Größen in pt bei Skalierung 1.0; COMPACT ersetzt einzelne Werte, wenn es deutlich größere Schrift erlaubt
SZ = {
    "head": 8, "head_gap": 5,
    "name": 11.5, "ability": 8.4, "lh": 1.2,
    "icon": 40, "marker": 10.5,
    "night_icon": 19, "night_label": 6.5,
    "footer": 6,
    "row_gap": 4.5, "section_gap": 10,
}
COMPACT = {"row_gap": 2.5, "section_gap": 6, "icon": 36, "head_gap": 3.5}
EXTRAS_SCALE = 0.8  # Fabled/Loric, Jinxes und Hausregeln kleiner als die Charaktere

# Die Inhaltsskalierung wird stufenlos zwischen K_MIN und K_MAX gesucht (so groß wie möglich, hilft am Handy).
# Passt es auch bei K_MIN nicht, wird die Seite in LONG_K länger; über MAX_LENGTH × A4 gibt es kein Bild.
K_MIN, K_MAX = 0.86, 1.1
LONG_K = 1.0
MAX_LENGTH = 2.0
SEARCH_STEPS = 6
JINX_LIMIT = 8  # (fancy) mehr Jinxes → die ersten JINX_LIMIT − 1 plus ein Feld „+ N more jinxes“

# Seitenmaße in pt (skalieren nicht mit dem Inhalt)
FRAME = 10       # Musterrand
MARGIN_X = 30    # Satzspiegel links/rechts
TITLE_X = 40     # Innenkante des Titelbereichs
GUTTER = 16      # Abstand zwischen den beiden Spalten

PAPER = (252, 250, 246)
INK = (34, 30, 28)
TITLE_INK = (40, 34, 30)
HEAD = (120, 112, 104)
HAIR = (218, 211, 201)
GREY = (138, 130, 122)
GOLD = (178, 142, 70)

# Gedeckte Namensfarben („Tinte“ statt Signalfarbe)
NAME_COLORS = {"Townsfolk": (34, 62, 112), "Outsider": (34, 62, 112), "Minion": (118, 30, 30),
               "Demon": (118, 30, 30), "Fabled": (146, 108, 30), "Loric": (64, 98, 44)}

# Themes nach Schwierigkeit: Rand (dark/light) und zarte Tönung hinter der Nachtreihenfolge (Optik „fancy“);
# vivid: Grund und Muster des Rands in der Optik „plain“, kräftig wie die Emojis 💚 🟡 🟥, nur etwas dunkler
THEMES = {
    "green": {"dark": (26, 44, 18), "light": (78, 106, 44), "tint": (236, 240, 228),
              "vivid": ((100, 152, 72), (78, 124, 54))},
    "yellow": {"dark": (70, 46, 6), "light": (150, 110, 28), "tint": (245, 239, 222),
               "vivid": ((222, 172, 52), (192, 142, 30))},
    "red": {"dark": (48, 8, 12), "light": (118, 28, 34), "tint": (245, 231, 229),
            "vivid": ((190, 36, 54), (152, 22, 38))},
}


@dataclass(frozen=True)
class Look:
    """Optik des Blatts. „plain“ ist seit 28.10.2026 der Standard (Dalyan): ohne Kleckse, ohne
    Nachtreihenfolge, ohne Goldrand, kräftiger Musterrand und dafür mehr Jinxes und größere Schrift."""
    washes: bool          # Tinten-Kleckse hinter spielprägenden Charakteren
    night: bool           # Nachtreihenfolge unten
    gold: bool            # goldene Doppellinie mit Eckstücken im Rand
    vivid: bool           # Musterrand in den kräftigen Theme-Farben statt dunkel mit Gold
    jinx_limits: tuple    # Obergrenzen der Jinxes, der Reihe nach probiert (None = alle), bis es auf A4 passt
    k_max: float          # größte Inhaltsskalierung


LOOKS = {
    "plain": Look(washes=False, night=False, gold=False, vivid=True, jinx_limits=(None, 20, 14, JINX_LIMIT),
                  k_max=1.3),
    "fancy": Look(washes=True, night=True, gold=True, vivid=False, jinx_limits=(JINX_LIMIT,), k_max=K_MAX),
}
DEFAULT_LOOK = "plain"


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


ORNAMENT_INK = mix(TITLE_INK, PAPER, 0.38)  # Ornamente treten hinter den Text zurück
