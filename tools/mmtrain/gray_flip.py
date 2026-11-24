"""Achromatic specialization of LDR-FLIP for display-sRGB uint8 images."""

import math

import numpy as np
from scipy.ndimage import correlate1d
from skimage.color import rgb2lab


# The LDR-FLIP normalization is defined by saturation colors, even for gray inputs.
def _hunt_distance_limit():
    colors = rgb2lab(np.array([[[0., 1., 0.], [0., 0., 1.]]]))[0]
    colors[:, 1:] *= colors[:, :1] * .01
    delta_l, delta_a, delta_b = colors[0] - colors[1]
    return (abs(delta_l) + math.hypot(delta_a, delta_b)) ** .7


_MAX_DISTANCE = _hunt_distance_limit()


def _kernel(radius, exponent):
    coordinates = np.arange(-radius, radius + 1, dtype=np.float64)
    return coordinates, np.exp(exponent * coordinates**2)


def _separable(image, horizontal, vertical):
    filtered = correlate1d(image, horizontal, axis=-1, mode="nearest")
    return correlate1d(filtered, vertical, axis=-2, mode="nearest")


def gray_flip(reference, candidate, pixels_per_degree=67.):
    """Mean gray-image FLIP. D65-neutral input has zero chroma in the color path."""
    images = np.stack((reference, candidate)).astype(np.float64) / 255.
    linear = np.where(images <= .04045, images / 12.92, ((images + .055) / 1.055) ** 2.4)

    spatial_radius = math.ceil(3 * math.sqrt(.04 / (2 * math.pi**2)) * pixels_per_degree)
    _, spatial = _kernel(spatial_radius, -math.pi**2 / (.0047 * pixels_per_degree**2))
    spatial /= spatial.sum()
    smoothed = _separable(linear, spatial, spatial)
    delta = 6 / 29
    lightness = 116 * np.where(smoothed > delta**3, np.cbrt(smoothed),
                               smoothed / (3 * delta**2) + 4 / 29) - 16
    delta_color = np.abs(lightness[0] - lightness[1]) ** .7
    cutoff = .4 * _MAX_DISTANCE
    color = np.where(delta_color < cutoff, .95 * delta_color / cutoff,
                     .95 + .05 * (delta_color - cutoff) / (_MAX_DISTANCE - cutoff))

    sigma = .5 * .082 * pixels_per_degree
    x, gaussian = _kernel(math.ceil(3 * sigma), -.5 / sigma**2)
    gaussian /= gaussian.sum()
    features = []
    for derivative in (-x, x**2 / sigma**2 - 1):
        weighted = derivative * gaussian
        positive = weighted > 0
        weighted[positive] /= weighted[positive].sum()
        weighted[~positive] /= -weighted[~positive].sum()
        magnitude = np.hypot(_separable(linear, weighted, gaussian),
                             _separable(linear, gaussian, weighted))
        features.append(np.abs(magnitude[0] - magnitude[1]))
    feature = np.sqrt(np.maximum(*features) / math.sqrt(2))
    return float(np.mean(color ** (1 - feature)))
