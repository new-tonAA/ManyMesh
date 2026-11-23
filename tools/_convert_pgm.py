from PIL import Image
from pathlib import Path
for p in Path('out').glob('mmgpu-gpucompaction-*/*.pgm'):
    im = Image.open(p)
    out = p.with_suffix('.png')
    im.save(out)
    print(out)
