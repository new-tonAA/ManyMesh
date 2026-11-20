"""Local inference for the four-convolution RGB Tiny network."""

import numpy as np
import torch


RECEPTIVE_RADIUS = 4


@torch.inference_mode()
def infer(model, image):
    tensor = torch.from_numpy(np.ascontiguousarray(image.transpose(2, 0, 1))).unsqueeze(0)
    return model(tensor)[0].permute(1, 2, 0).numpy()


def local_prediction(model, image, reference, reference_prediction):
    """Reuse the reference prediction outside the influence of changed input pixels."""
    height, width = image.shape[:2]
    different = np.any(image != reference, axis=2)
    rows = np.flatnonzero(different.any(axis=1))
    if not len(rows):
        return reference_prediction, 0
    cols = np.flatnonzero(different.any(axis=0))

    # Input changes influence outputs within the receptive field. Those outputs
    # themselves require an additional halo of input on every artificial edge.
    r = RECEPTIVE_RADIUS
    y0, y1 = max(0, rows[0] - r), min(height, rows[-1] + r + 1)
    x0, x1 = max(0, cols[0] - r), min(width, cols[-1] + r + 1)
    top, bottom = max(0, y0 - r), min(height, y1 + r)
    left, right = max(0, x0 - r), min(width, x1 + r)
    area = (bottom - top) * (right - left)
    if area == height * width:
        return infer(model, image), area
    crop = infer(model, image[top:bottom, left:right])
    out = reference_prediction.copy()
    out[y0:y1, x0:x1] = crop[y0-top:y1-top, x0-left:x1-left]
    return out, area


def uniform_prediction(model, shape, color):
    """Predict a uniform input, preserving Tiny's actual zero-padded frame boundary."""
    height, width = shape[:2]
    r = RECEPTIVE_RADIUS
    template_height, template_width = min(height, 2*r + 1), min(width, 2*r + 1)
    patch = np.tile(color, (template_height, template_width, 1))
    pred = infer(model, patch)

    def indices(length, template_length):
        idx = np.arange(length)
        return np.minimum(idx, r) + np.maximum(0, idx - length + template_length - r)

    # For dimensions smaller than the receptive field, retain their exact length.
    y = np.arange(height) if height == template_height else indices(height, template_height)
    x = np.arange(width) if width == template_width else indices(width, template_width)
    return pred[y[:, None], x[None, :]]
