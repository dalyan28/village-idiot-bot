"""One-shot: convert planet JPGs (with baked-in checker background) to transparent PNGs.

Planets are round, so we fit a circle around the non-background pixels and
mask everything outside it. Much cleaner than per-pixel checker detection,
which left the planet edge fuzzy and kept any matching gray inside.

Steps:
 1. Detect "not checker" pixels (saturated, or gray values away from 230/255).
 2. Take the bounding box of the largest such region → circle center and radius.
 3. Render a soft-edged disk as the alpha channel.
"""
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = Path(__file__).resolve().parent.parent / "images" / "Planets"

VALUE_TOL = 8       # how far from 230/255 still counts as checker
SAT_TOL = 8         # max(R,G,B)-min(R,G,B) <= this counts as desaturated
RADIUS_PAD = 2      # extra pixels added to the detected radius
FEATHER_PX = 1.5    # soft-edge width for anti-aliasing


def detect_planet_mask(arr: np.ndarray) -> np.ndarray:
    """Boolean mask of pixels that belong to the planet (not the checker bg)."""
    desaturated = (arr.max(axis=-1) - arr.min(axis=-1)) <= SAT_TOL
    gray = arr.mean(axis=-1)
    near_checker = (np.abs(gray - 230) <= VALUE_TOL) | (np.abs(gray - 255) <= VALUE_TOL)
    checkerish = desaturated & near_checker

    # Keep only checker regions connected to the border; anything else is planet.
    labels, _ = ndimage.label(checkerish, structure=np.ones((3, 3), dtype=bool))
    border_labels = set(np.unique(labels[0, :])) | set(np.unique(labels[-1, :])) \
        | set(np.unique(labels[:, 0])) | set(np.unique(labels[:, -1]))
    border_labels.discard(0)
    background = np.isin(labels, list(border_labels))
    return ~background


def fit_circle(mask: np.ndarray) -> tuple[float, float, float]:
    ys, xs = np.where(mask)
    cy = (ys.min() + ys.max()) / 2.0
    cx = (xs.min() + xs.max()) / 2.0
    # Use the larger half-extent so we never clip the planet.
    radius = max(ys.max() - ys.min(), xs.max() - xs.min()) / 2.0 + RADIUS_PAD
    return cx, cy, radius


def circular_alpha(shape: tuple[int, int], cx: float, cy: float, radius: float) -> np.ndarray:
    h, w = shape
    yy, xx = np.ogrid[:h, :w]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    # Linear ramp across FEATHER_PX at the circle edge for anti-aliasing.
    alpha = np.clip((radius - dist) / FEATHER_PX + 0.5, 0.0, 1.0) * 255.0
    return alpha.astype(np.uint8)


def convert(path: Path) -> None:
    img = Image.open(path).convert("RGB")
    arr = np.asarray(img, dtype=np.int16)

    planet_mask = detect_planet_mask(arr)
    cx, cy, radius = fit_circle(planet_mask)
    alpha = circular_alpha(arr.shape[:2], cx, cy, radius)

    rgba = np.dstack([arr.astype(np.uint8), alpha])
    out = Image.fromarray(rgba, mode="RGBA")

    dst = path.with_suffix(".png")
    out.save(dst, optimize=True)
    print(f"{path.name} -> {dst.name}  center=({cx:.0f},{cy:.0f}) r={radius:.0f}")


def main() -> None:
    for jpg in sorted(SRC.glob("*.jpg")):
        convert(jpg)


if __name__ == "__main__":
    main()
