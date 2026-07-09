import boto3
from botocore.exceptions import ClientError
from app.config import settings


def make_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )


def ensure_bucket(client) -> None:
    try:
        client.head_bucket(Bucket=settings.s3_bucket_name)
    except ClientError:
        client.create_bucket(Bucket=settings.s3_bucket_name)


def upload_bytes(client, key: str, data: bytes, content_type: str) -> None:
    client.put_object(
        Bucket=settings.s3_bucket_name,
        Key=key,
        Body=data,
        ContentType=content_type,
    )


def download_to_path(client, key: str, dest_path: str) -> None:
    client.download_file(settings.s3_bucket_name, key, dest_path)


def delete_object(client, key: str) -> None:
    client.delete_object(Bucket=settings.s3_bucket_name, Key=key)
