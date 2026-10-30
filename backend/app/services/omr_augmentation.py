import math
import random
from pathlib import Path
from typing import Union
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


def simulate_page_fold(image: Image.Image, intensity: float = 0.4, fold_position: float = 0.2) -> Image.Image:
    """
    Simulate a page fold or binding gutter shadow across sheet music.

    Args:
        image: Source PIL Image.
        intensity: Depth of shadow (0.0 to 1.0).
        fold_position: Horizontal fraction where fold line falls (0.0 to 1.0).

    Returns:
        Augmented PIL Image with curved gutter shadow.
    """
    img = image.convert("RGB")
    w, h = img.size
    np_img = np.array(img, dtype=np.float32)

    fold_x = int(w * fold_position)
    shadow_width = max(20, int(w * 0.15))

    # Compute horizontal distance to fold line
    x_coords = np.arange(w)
    dist = np.abs(x_coords - fold_x)
    shadow_factor = np.exp(-((dist / (shadow_width / 2.0)) ** 2))
    shadow_factor = np.clip(shadow_factor * intensity, 0.0, 1.0)

    # Darken pixels near fold
    multiplier = 1.0 - shadow_factor[np.newaxis, :, np.newaxis]
    np_augmented = np.clip(np_img * multiplier, 0, 255).astype(np.uint8)

    return Image.fromarray(np_augmented)


def simulate_bleed_through(image: Image.Image, intensity: float = 0.25) -> Image.Image:
    """
    Simulate ink bleed-through from reverse page of sheet music.

    Args:
        image: Source PIL Image.
        intensity: Opacity of bleed-through notation (0.0 to 1.0).

    Returns:
        Augmented PIL Image with faint mirrored bleed-through.
    """
    img = image.convert("RGB")
    w, h = img.size

    # Flip horizontally and blur to create reverse-page ghost notation
    ghost = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    ghost = ghost.filter(ImageFilter.GaussianBlur(radius=2.5))

    # Blend ghost into image
    blended = Image.blend(img, ghost, alpha=intensity * 0.5)
    return blended


def simulate_lighting_gradient(image: Image.Image, direction: str = "horizontal") -> Image.Image:
    """
    Simulate non-uniform ambient illumination gradient across the score.

    Args:
        image: Source PIL Image.
        direction: 'horizontal', 'vertical', or 'diagonal'.

    Returns:
        Augmented PIL Image with lighting variation.
    """
    img = image.convert("RGB")
    w, h = img.size
    np_img = np.array(img, dtype=np.float32)

    if direction == "horizontal":
        gradient = np.linspace(0.80, 1.05, w)[np.newaxis, :, np.newaxis]
    elif direction == "vertical":
        gradient = np.linspace(0.85, 1.05, h)[:, np.newaxis, np.newaxis]
    else:
        gx = np.linspace(0.85, 1.05, w)
        gy = np.linspace(0.85, 1.05, h)
        gradient = (gx[np.newaxis, :] * gy[:, np.newaxis] / 1.0)[:, :, np.newaxis]

    np_augmented = np.clip(np_img * gradient, 0, 255).astype(np.uint8)
    return Image.fromarray(np_augmented)


def simulate_scan_noise(image: Image.Image, speckle_prob: float = 0.003) -> Image.Image:
    """
    Simulate scan dust, paper grain, and salt-and-pepper sensor speckle noise.

    Args:
        image: Source PIL Image.
        speckle_prob: Probability of random dust particle per pixel.

    Returns:
        Augmented PIL Image with scanning artifacts.
    """
    img = image.convert("RGB")
    np_img = np.array(img)

    h, w, c = np_img.shape
    noise_mask = np.random.rand(h, w) < speckle_prob
    dust_mask = np.random.rand(h, w) < (speckle_prob * 0.5)

    # Black dust spots (common on vintage scanned scores)
    np_img[noise_mask] = 30
    # White dropouts
    np_img[dust_mask] = 245

    return Image.fromarray(np_img)


def simulate_subtle_skew(image: Image.Image, max_angle: float = 1.2) -> Image.Image:
    """
    Simulate slight document rotation skew with clean white background borders.

    Args:
        image: Source PIL Image.
        max_angle: Maximum rotation degrees (+/- max_angle).

    Returns:
        Augmented PIL Image.
    """
    angle = random.uniform(-max_angle, max_angle)
    # Expand=False keeps canvas size identical, filling corners with paper white (255, 255, 255)
    return image.rotate(angle, resample=Image.Resampling.BILINEAR, expand=False, fillcolor=(255, 255, 255))


def apply_training_augmentations(image: Union[Image.Image, Path, str]) -> Image.Image:
    """
    Apply a randomized sequence of synthetic augmentations to a sheet music score.

    Simulates realistic real-world degradation: page curvature, lighting unevenness,
    paper grain, and reverse-side ink bleed.
    """
    if isinstance(image, (str, Path)):
        img = Image.open(str(image))
    else:
        img = image

    img = img.convert("RGB")

    # 1. Subtle angle skew
    img = simulate_subtle_skew(img, max_angle=1.0)

    # 2. Lighting gradient
    direction = random.choice(["horizontal", "vertical", "diagonal"])
    img = simulate_lighting_gradient(img, direction=direction)

    # 3. Optional fold gutter shadow (60% probability)
    if random.random() < 0.6:
        fold_pos = random.uniform(0.1, 0.4)
        img = simulate_page_fold(img, intensity=random.uniform(0.2, 0.45), fold_position=fold_pos)

    # 4. Optional bleed-through (40% probability)
    if random.random() < 0.4:
        img = simulate_bleed_through(img, intensity=random.uniform(0.15, 0.3))

    # 5. Paper grain & speckle noise
    img = simulate_scan_noise(img, speckle_prob=0.002)

    return img
