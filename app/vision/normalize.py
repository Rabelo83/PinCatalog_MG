"""Step 1 of detection: image normalisation.

The goal is to make photos taken under different lighting look alike to the
rest of the pipeline. Operations are deliberately mild; they only affect the
downscaled detection copy, never the saved crops.
"""

from __future__ import annotations

import cv2
import numpy as np


def gray_world_white_balance(image: np.ndarray, strength: float = 0.6) -> np.ndarray:
    """Reduce colour casts by nudging the average colour toward neutral grey.

    Args:
        image: RGB ``uint8`` image.
        strength: 0 = unchanged, 1 = full gray-world correction. A partial
            correction avoids over-correcting pages full of one colour.
    """
    pixels = image.astype(np.float32)
    means = pixels.reshape(-1, 3).mean(axis=0)
    gray = means.mean()
    gains = 1.0 + strength * (gray / np.maximum(means, 1.0) - 1.0)
    return np.clip(pixels * gains, 0, 255).astype(np.uint8)


def denoise(image: np.ndarray) -> np.ndarray:
    """Edge-preserving smoothing that removes sensor noise and felt texture."""
    return cv2.bilateralFilter(image, d=7, sigmaColor=40, sigmaSpace=7)


def normalize_contrast(image: np.ndarray, clip_limit: float = 2.0) -> np.ndarray:
    """Local contrast normalisation (CLAHE) on the lightness channel only."""
    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
    lightness, a_channel, b_channel = cv2.split(lab)
    tile = max(2, min(lab.shape[:2]) // 150)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile, tile))
    lab = cv2.merge((clahe.apply(lightness), a_channel, b_channel))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)


def normalize_image(image: np.ndarray) -> np.ndarray:
    """Run the full normalisation chain: white balance, denoise, contrast."""
    balanced = gray_world_white_balance(image)
    smoothed = denoise(balanced)
    return normalize_contrast(smoothed)
