from contextlib import contextmanager
from typing import List
import psycopg2
import numpy as np
from PIL import Image
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from io import BytesIO


class VectorDB:
    def __init__(self, db_url: str):
        self.db_url = db_url

    @contextmanager
    def cursor(self):
        conn = psycopg2.connect(self.db_url)
        try:
            with conn, conn.cursor() as cursor:
                yield cursor
        finally:
            conn.close()

    def init_table(self):
        """Создаёт схему и обновляет существующую таблицу с SERIAL."""
        with self.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('cat_embeddings_schema'));")
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    id TEXT PRIMARY KEY,
                    embedding vector(1280) NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            cur.execute(
                """
                SELECT atttypid = 'integer'::regtype
                FROM pg_attribute
                WHERE attrelid = 'embeddings'::regclass AND attname = 'id';
                """
            )
            if cur.fetchone()[0]:
                cur.execute("ALTER TABLE embeddings ALTER COLUMN id DROP DEFAULT;")
                cur.execute("ALTER TABLE embeddings ALTER COLUMN id TYPE text USING id::text;")

            cur.execute("DROP INDEX IF EXISTS idx_embedding;")
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS embeddings_cosine_idx ON embeddings
                USING hnsw (embedding vector_cosine_ops);
                """
            )

    def insert_image(self, embedding: np.ndarray, image_id: str, *, replace: bool = False):
        vector = "[" + ",".join(map(str, embedding.tolist())) + "]"
        query = "INSERT INTO embeddings (id, embedding) VALUES (%s, %s::vector)"
        if replace:
            query += " ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding"

        with self.cursor() as cur:
            cur.execute(query, (image_id, vector))

    def find_similar(self, query_embedding: np.ndarray, limit: int = 5) -> list[tuple[str, float]]:
        vector = "[" + ",".join(map(str, query_embedding.tolist())) + "]"
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, embedding <=> %s::vector AS distance
                FROM embeddings ORDER BY distance LIMIT %s;
                """,
                (vector, limit),
            )
            return cur.fetchall()

    def count_images(self) -> int:
        with self.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM embeddings;")
            return cur.fetchone()[0]


class S3Storage:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str):
        """
        Инициализация S3-клиента

        Args:
            endpoint: URL S3-сервиса (ex: http://minio:9000)
            access_key: Access Key для S3
            secret_key: Secret Key для S3
            bucket: имя бакета для изображений
        """
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self.bucket = bucket
        self.endpoint = endpoint

    def ensure_bucket_exists(self):
        """Проверяет существование бакета, создаёт если нужно"""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket)
        except ClientError:
            try:
                self.s3_client.create_bucket(Bucket=self.bucket)
            except ClientError as e:
                raise Exception(f"Failed to create bucket: {e}")

    def upload_image(self, image_file, object_name: str) -> str:
        """
        Загружает изображение в S3

        Args:
            image_file: file-like объект или путь к файлу
            object_name: ключ объекта в S3

        Returns:
            str: URL загруженного объекта
        """
        try:
            if isinstance(image_file, str):
                with open(image_file, "rb") as f:
                    self.s3_client.put_object(
                        Bucket=self.bucket,
                        Key=object_name,
                        Body=f,
                        ContentType="image/jpeg",
                    )
            else:
                self.s3_client.put_object(
                    Bucket=self.bucket,
                    Key=object_name,
                    Body=image_file,
                    ContentType="image/jpeg",
                )
            return f"{self.endpoint}/{self.bucket}/{object_name}"
        except ClientError as e:
            raise Exception(f"Failed to upload image: {e}")

    def delete_image(self, object_name: str) -> None:
        self.s3_client.delete_object(Bucket=self.bucket, Key=object_name)

    def download_image(self, object_name: str) -> Image.Image:
        """Скачивает изображение из S3"""
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket,
                Key=object_name,
            )
            image_data = response["Body"].read()
            return Image.open(BytesIO(image_data))
        except ClientError as e:
            raise Exception(f"Failed to download image: {e}")

    def list_images(self, prefix: str = "") -> List[str]:
        """Список объектов в S3 по префиксу"""
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket,
                Prefix=prefix,
            )
            if "Contents" in response:
                return [obj["Key"] for obj in response["Contents"]]
            return []
        except ClientError as e:
            raise Exception(f"Failed to list images: {e}")

    def get_presigned_url(self, object_name: str, expiration: int = 3600) -> str:
        """
        Генерирует временный URL для доступа к объекту в S3

        Args:
            object_name: ключ объекта в S3
            expiration: время жизни URL в секундах (по умолчанию 1 час)

        Returns:
            str: Presigned URL для доступа к объекту
        """
        try:
            url = self.s3_client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self.bucket, "Key": object_name},
                ExpiresIn=expiration,
            )
            return url
        except ClientError as e:
            raise Exception(f"Failed to generate presigned URL: {e}")
