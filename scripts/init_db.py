#!/usr/bin/env python3
"""
Инициализация датасета: загружает изображения в PostgreSQL+pgvector и MinIO S3
"""
import os
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image
from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.ml_utils import embed_image
from app.db_utils import VectorDB, S3Storage

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/cats")
DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "cat_images"))

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://minio:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
S3_BUCKET = os.getenv("S3_BUCKET", "cats")


def init_dataset():
    data_dir = Path(DATA_DIR)
    if not data_dir.is_dir():
        print(f"Image directory not found: {data_dir}", file=sys.stderr)
        return False

    image_extensions = {'.jpg', '.jpeg', '.png'}
    image_files = sorted([
        f for f in data_dir.iterdir()
        if f.is_file() and f.suffix.lower() in image_extensions
    ])

    if not image_files:
        print(f"No images found in {data_dir}")
        return False

    db = VectorDB(DATABASE_URL)
    db.init_table()

    s3 = S3Storage(S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET)
    s3.ensure_bucket_exists()

    loaded = 0
    for index, image_path in enumerate(tqdm(image_files, desc="Loading images", unit="img")):
        image_id = str(index)
        try:
            jpeg = BytesIO()
            with Image.open(image_path) as source:
                image = source.convert("RGB")
                embedding = embed_image(image)
                image.save(jpeg, format="JPEG")
            jpeg.seek(0)
            s3.upload_image(jpeg, f"{image_id}.jpg")
            db.insert_image(embedding, image_id, replace=True)
            loaded += 1
        except Exception as error:
            print(f"Failed to process {image_path}: {error}", file=sys.stderr)

    print(f"Loaded {loaded} of {len(image_files)} images")
    return loaded == len(image_files)


if __name__ == "__main__":
    success = init_dataset()
    sys.exit(0 if success else 1)
