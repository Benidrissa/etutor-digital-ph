"""Unit tests for the qbank image-proxy URL helper.

We don't exercise the streaming endpoint itself here — that requires a live
MinIO and is covered by the end-to-end Playwright run. These tests pin down
the URL-derivation behaviour, which is the piece that fixes #1603.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.api.v1.qbank import _image_url_for


def _fake_request(headers: dict, scheme: str = "http"):
    return SimpleNamespace(
        headers=headers,
        url=SimpleNamespace(scheme=scheme),
    )


def test_image_url_for_returns_none_when_storage_key_missing():
    req = _fake_request({"host": "api.example.com"})
    qid = uuid.uuid4()
    assert _image_url_for(req, qid, None) is None
    assert _image_url_for(req, qid, "") is None


def test_image_url_for_uses_forwarded_proto_and_host():
    req = _fake_request(
        {
            "x-forwarded-proto": "https",
            "x-forwarded-host": "api.elearning.portfolio2.kimbetien.com",
            "host": "backend:8000",
        }
    )
    qid = uuid.uuid4()
    url = _image_url_for(req, qid, "qbank/bank-id/images/1.webp")
    assert url == (
        f"https://api.elearning.portfolio2.kimbetien.com/api/v1/qbank/questions/{qid}/image"
    )


def test_image_url_for_falls_back_to_host_header_and_url_scheme():
    req = _fake_request({"host": "api.example.com"}, scheme="http")
    qid = uuid.uuid4()
    url = _image_url_for(req, qid, "qbank/b/1.webp")
    assert url == f"http://api.example.com/api/v1/qbank/questions/{qid}/image"


def test_image_url_for_returns_none_when_host_absent():
    # Starlette always populates host, but belt-and-braces.
    req = _fake_request({}, scheme="https")
    qid = uuid.uuid4()
    assert _image_url_for(req, qid, "qbank/b/1.webp") is None
