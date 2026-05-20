import json
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from django.test import Client
from django.urls import resolve

path = "/api/v1/mobile/driver/auth/login/"
print("resolve:", resolve(path).url_name)

body = json.dumps(
    {
        "email": "a@b.com",
        "password": "x",
        "device_platform": "Android",
    }
)
c = Client()
r = c.post(
    path,
    data=body,
    content_type="application/json",
    HTTP_HOST="127.0.0.1:8000",
)
print("status:", r.status_code)
print("content-type:", r.get("Content-Type"))
print("body_len:", len(r.content))
if r.status_code != 200:
    print("body_preview:", r.content[:500])
