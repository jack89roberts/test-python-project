"""
Make some dummy image data to use in tests.
"""
from __future__ import annotations

import string

import numpy as np
from datasets import ClassLabel, Dataset
from dummy_config import config
from PIL import Image

test_seed = config["test_seed"]
rng = np.random.default_rng(test_seed)

n_images = config["n_images"]
image_size = config["image_size"]
num_channels = config["num_channels"]
img_bits = config["img_bits"]

# Note: PIL expects colour channel to be last. After processing with HuggingFace
# defaults this will be converted to first.
img_array = rng.integers(
    0, 2**img_bits, (n_images, image_size, image_size, num_channels)
)
img_PIL = [Image.fromarray(img, mode="RGB") for img in img_array]

n_classes = config["n_classes"]
names = list(string.ascii_lowercase)[:n_classes]
labels = rng.choice(names, n_images)

dataset = Dataset.from_dict(
    mapping={
        "image": img_PIL,
        "label": labels,
    },
)

# convert "label" feature to ClassLabel, which provides functionality for converting
# between class names and indices and is the expected input format for locomoset
# functions
dataset = dataset.cast_column("label", ClassLabel(names=names))

# Note: Not using dataset.save_to_disk() here, because then HuggingFace wants you to use
# Dataset.load_from_disk() instead of Dataset.load_dataset(), see
# https://github.com/huggingface/datasets/issues/5044.
dataset.to_parquet("dummy_dataset/dummy_dataset.parquet")
