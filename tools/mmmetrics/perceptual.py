"""Standard image metrics on matching sRGB renders, using upstream implementations."""

from importlib.metadata import version

import numpy as np


class ImageMetrics:
    def __init__(self, ppd=67., threads=2):
        import flip_evaluator
        import lpips
        import torch
        from skimage.metrics import structural_similarity

        if not np.isfinite(ppd) or ppd <= 0:
            raise ValueError("FLIP pixels per degree must be positive")
        torch.set_num_threads(threads)
        self.torch, self.flip, self.ssim = torch, flip_evaluator, structural_similarity
        self.model = lpips.LPIPS(net="squeeze", version="0.1", pretrained=True,
                                pnet_rand=False, verbose=False).eval()
        self.ppd = float(ppd)
        self.settings = {"input": "8-bit sRGB, RGB in [0,1]",
                         "ssim": "Gaussian sigma=1.5, population covariance, K1=.01 K2=.03",
                         "flip": "LDR-FLIP", "flip_ppd": self.ppd,
                         "lpips": "calibrated SqueezeNet, version 0.1, [-1,1] RGB",
                         "packages": {name: version(name) for name in (
                             "flip-evaluator", "lpips", "scikit-image", "torch", "torchvision")}}

    def __call__(self, reference, candidate, union=None):
        reference, candidate = np.asarray(reference), np.asarray(candidate)
        if (reference.shape != candidate.shape or reference.ndim != 3 or reference.shape[2] != 3
                or min(reference.shape[:2]) < 32 or not np.isfinite(reference).all()
                or not np.isfinite(candidate).all() or reference.min() < 0 or candidate.min() < 0
                or reference.max() > 1 or candidate.max() > 1):
            raise ValueError("Expected matching finite sRGB arrays with at least 32 pixels per side")
        difference = reference.astype(np.float64)-candidate.astype(np.float64)
        mse = float(np.mean(difference**2))
        # JSON null represents exact identity rather than nonstandard JSON Infinity.
        psnr = None if mse == 0 else float(-10*np.log10(mse))
        _, flip_mean, _ = self.flip.evaluate(
            reference.astype(np.float32), candidate.astype(np.float32), "LDR",
            inputsRGB=True, applyMagma=False, parameters={"ppd": self.ppd})
        def tensor(image):
            return self.torch.from_numpy(np.array(image, dtype=np.float32, copy=True)).permute(
                2, 0, 1).unsqueeze(0)*2-1
        with self.torch.inference_mode():
            lpips = float(self.model(tensor(reference), tensor(candidate)).item())
        ssim = self.ssim(reference, candidate, data_range=1., channel_axis=2,
                         gaussian_weights=True, sigma=1.5, use_sample_covariance=False)
        row = {"psnr_db": psnr, "identical": mse == 0, "mse": mse, "ssim": float(ssim),
               "flip": float(flip_mean), "lpips_squeeze": lpips}
        if union is not None and np.any(union):
            foreground_mse = float(np.mean(difference[union]**2))
            row["foreground_psnr_db"] = None if foreground_mse == 0 else float(
                -10*np.log10(foreground_mse))
        return row
