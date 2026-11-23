from PIL import Image
import numpy as np
a=np.array(Image.open('out/parallax-monkey45/detail-height.png'))
print(a.shape,a.dtype,a.min(),a.max(),float(a.mean()),float((a!=128).mean()))
