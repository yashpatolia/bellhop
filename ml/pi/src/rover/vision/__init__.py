import os

from rover import config

# OpenMP reads this once, when torch/ncnn/cv2 load, so it must be set before any vision module.
os.environ.setdefault("OMP_NUM_THREADS", str(config.VISION_OMP_THREADS))
