from flask import Flask, request, jsonify
import os
from io import BytesIO
from PIL import Image, UnidentifiedImageError
from app.db_utils import VectorDB, S3Storage
from app.ml_utils import embed_image
import uuid

app = Flask(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@postgres:5432/cats",
)
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://minio:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
S3_BUCKET = os.getenv("S3_BUCKET", "cats")

db = VectorDB(DATABASE_URL)
s3 = S3Storage(S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET)

db.init_table()
s3.ensure_bucket_exists()


@app.route("/similar", methods=["POST"])
def similar():
    """
    POST /similar — принимает изображение, возвращает список похожих записей
    """
    try:
        if "image" not in request.files:
            return jsonify({"error": "No image provided"}), 400

        file = request.files["image"]
        if file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        with Image.open(BytesIO(file.read())) as image:
            query_embedding = embed_image(image)

        rows = db.find_similar(query_embedding, limit=5)

        results = []
        for row in rows:
            img_id, distance = row
            object_name = f"{img_id}.jpg"
            presigned_url = s3.get_presigned_url(object_name)
            results.append(
                {
                    "id": int(img_id) if img_id.isdecimal() else img_id,
                    "distance": float(distance),
                    "url": presigned_url,
                }
            )

        return jsonify({"similar": results}), 200
    except UnidentifiedImageError:
        return jsonify({"error": "Invalid image"}), 400
    except Exception:
        app.logger.exception("Image request failed")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/upload", methods=["POST"])
def upload():
    """
    POST /upload — загружает одно изображение, сохраняет в S3 и в БД
    """
    try:
        if "image" not in request.files:
            return jsonify({"error": "No image provided"}), 400

        file = request.files["image"]
        if file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        jpeg = BytesIO()
        with Image.open(BytesIO(file.read())) as source:
            image = source.convert("RGB")
            embedding = embed_image(image)
            image.save(jpeg, format="JPEG")
        jpeg.seek(0)

        image_id = str(uuid.uuid4())
        object_name = f"{image_id}.jpg"
        url = s3.get_presigned_url(object_name)
        s3.upload_image(jpeg, object_name)
        try:
            db.insert_image(embedding, image_id)
        except Exception:
            try:
                s3.delete_image(object_name)
            except Exception:
                app.logger.exception("Failed to remove image %s after database error", image_id)
            raise

        return (
            jsonify(
                {
                    "id": image_id,
                    "url": url,
                    "message": "Image uploaded successfully",
                }
            ),
            200,
        )
    except UnidentifiedImageError:
        return jsonify({"error": "Invalid image"}), 400
    except Exception:
        app.logger.exception("Image request failed")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/stats", methods=["GET"])
def stats():
    """
    GET /stats - возвращает статистику по БД
    """
    try:
        return jsonify({"total_images": db.count_images()}), 200
    except Exception:
        app.logger.exception("Failed to count images")
        return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    API_PORT = int(os.getenv("API_PORT", "5000"))
    app.run(host="0.0.0.0", port=API_PORT)
