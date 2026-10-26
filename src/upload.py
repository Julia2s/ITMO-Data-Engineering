from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_s3_client, S3_BUCKET, VACANCIES_KEY, Boto3S3Client


def upload_file(local_path: str, key: str = VACANCIES_KEY, chunk_mib: int = 8) -> dict:
    cli = get_s3_client()
    size = os.path.getsize(local_path)
    if isinstance(cli, Boto3S3Client):
        s3 = cli._client_get()
        upload_id = s3.create_multipart_upload(Bucket=S3_BUCKET, Key=key)["UploadId"]
        parts = []
        part_size = chunk_mib * 1024 * 1024
        with open(local_path, "rb") as f:
            part_num = 1
            while True:
                chunk = f.read(part_size)
                if not chunk:
                    break
                resp = s3.upload_part(
                    Bucket=S3_BUCKET, Key=key,
                    UploadId=upload_id, PartNumber=part_num, Body=chunk,
                )
                parts.append({"PartNumber": part_num, "ETag": resp["ETag"]})
                part_num += 1
        s3.complete_multipart_upload(
            Bucket=S3_BUCKET, Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )
        method = f"boto3 multipart ({len(parts)} parts × {chunk_mib} MiB)"
    else:
        with open(local_path, "rb") as f:
            data = f.read()
        cli.put_object(key, data, content_type="text/csv; charset=utf-8")
        method = "LocalFS put_object"
    info = cli.head_object(key)
    return {
        "bucket": S3_BUCKET,
        "key": key,
        "size_bytes": info.size if info else 0,
        "size_mib": round((info.size if info else 0) / 1024 / 1024, 2),
        "method": method,
    }


def list_bucket() -> list[dict]:
    cli = get_s3_client()
    objs = cli.list_objects(prefix="")
    return [{"key": o.key, "size": o.size, "size_mib": round(o.size / 1024 / 1024, 2)} for o in objs]


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("file", nargs="?", default="data/it_vacancies_2024.csv")
    p.add_argument("--key", default=VACANCIES_KEY)
    p.add_argument("--list", action="store_true")
    args = p.parse_args()

    if args.list:
        for o in list_bucket():
            print(f"  {o['key']:50s} {o['size']:>12} B  ({o['size_mib']} MiB)")
        sys.exit(0)

    stats = upload_file(args.file, args.key)
    print("=== Upload complete ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print("\nBucket contents:")
    for o in list_bucket():
        print(f"  {o['key']:50s} {o['size']:>12} B  ({o['size_mib']} MiB)")
