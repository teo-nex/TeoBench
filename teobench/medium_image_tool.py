"""Trusted host bridge: bounded image read from exactly one owned container."""
import base64
import json
import os
import re
import sys
from .medium_container import Docker, ContainerError


def main():
    request=json.load(sys.stdin)
    if not re.fullmatch(r'[a-f0-9]{64}',request['container']):raise ValueError('invalid_container')
    # Reuse the launcher's already isolated, anonymous engine environment.
    docker=Docker.__new__(Docker);docker.executable=request['engine'];docker.env=os.environ.copy()
    data=docker.read_file(request['container'],request['path'],limit=4_000_000)
    if data.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
    elif data.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
    else:raise ContainerError('png_or_jpeg_required')
    print(json.dumps({'mimeType':mime,'data':base64.b64encode(data).decode()}))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,ContainerError):
        print(json.dumps({'error':'image_unavailable_convert_to_png_or_jpeg_under_4MB'}))
        raise SystemExit(1)
