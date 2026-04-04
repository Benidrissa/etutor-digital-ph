"""S3-compatible object storage service for MinIO (audio, images, files)."""

from __future__ import annotations

import structlog

from app.infrastructure.config.settings import settings

logger = structlog.get_logger(__name__)


class S3StorageService:
    """Async S3-compatible client for MinIO object storage.

    Uses aiobotocore (async botocore) to upload/download files from
    a MinIO instance configured via MINIO_* environment variables.
    """

    def __init__(self) -> None:
        self._endpoint = settings.minio_endpoint
        self._access_key = settings.minio_access_key
        self._secret_key = settings.minio_secret_key
        self._bucket = settings.minio_bucket_media
        self._public_url = settings.minio_public_url.rstrip("/")

    def _get_session(self):  # type: ignore[return]
        """Create an aiobotocore session."""
        import aiobotocore.session  # type: ignore[import-untyped]

        return aiobotocore.session.get_session()

    def public_url(self, key: str) -> str:
        """Return the public URL for a storage key."""
        return f"{self._public_url}/{self._bucket}/{key}"

    async def upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload raw bytes to MinIO under the given key.

        Args:
            key: Object key (path within bucket), e.g. "audio/module-uuid-fr.mp3"
            data: Raw bytes to upload
            content_type: MIME type of the content

        Returns:
            Public URL of the uploaded object
        """
        session = self._get_session()
        async with session.create_client(
            "s3",
            endpoint_url=self._endpoint,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
        ) as client:
            await self._ensure_bucket(client)
            await client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                ACL="public-read",
            )

        url = self.public_url(key)
        logger.info(
            "Uploaded object to MinIO",
            key=key,
            bucket=self._bucket,
            size_bytes=len(data),
            url=url,
        )
        return url

    async def delete_object(self, key: str) -> None:
        """Delete an object from MinIO.

        Args:
            key: Object key to delete
        """
        session = self._get_session()
        async with session.create_client(
            "s3",
            endpoint_url=self._endpoint,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
        ) as client:
            await client.delete_object(Bucket=self._bucket, Key=key)

        logger.info("Deleted object from MinIO", key=key, bucket=self._bucket)

    async def _ensure_bucket(self, client: object) -> None:
        """Create bucket if it does not exist and set a public-read policy."""
        import json

        try:
            await client.head_bucket(Bucket=self._bucket)  # type: ignore[union-attr]
        except Exception:
            await client.create_bucket(Bucket=self._bucket)  # type: ignore[union-attr]
            policy = json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"AWS": ["*"]},
                            "Action": ["s3:GetObject"],
                            "Resource": [f"arn:aws:s3:::{self._bucket}/*"],
                        }
                    ],
                }
            )
            await client.put_bucket_policy(Bucket=self._bucket, Policy=policy)  # type: ignore[union-attr]
            logger.info("Created MinIO bucket", bucket=self._bucket)
