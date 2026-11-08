from dataclasses import replace

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from userbot.login import Login
from userbot.web import COOKIE, make_app


async def test_public_ipv4_origin_and_secure_login_cookie(service):
    service.settings = replace(service.settings, public_base_url="https://203.0.113.10")
    login = Login(service)
    client = TestClient(TestServer(make_app(login)))
    await client.start_server()
    try:
        url = await login.issue(100, "+15551234567")
        assert url.startswith("https://203.0.113.10/#")
        response = await client.post(
            "/api/exchange",
            json={"token": url.split("#")[1]},
            headers={"Host": "203.0.113.10", "Origin": "https://203.0.113.10"},
        )
        assert response.status == 200
        assert response.cookies[COOKIE]["secure"]
        assert response.cookies[COOKIE]["httponly"]
    finally:
        await client.close()
        await login.close()


@pytest_asyncio.fixture
async def web_client(service):
    login = Login(service)
    client = TestClient(TestServer(make_app(login)))
    await client.start_server()
    yield client, login
    await client.close()
    await login.close()


def headers():
    return {"Host": "login.example.test", "Origin": "https://login.example.test"}


async def test_host_validation(web_client):
    client, _ = web_client
    response = await client.get("/", headers={"Host": "evil.example.test"})
    assert response.status == 400


async def test_origin_validation(web_client):
    client, _ = web_client
    response = await client.post(
        "/api/exchange",
        json={"token": "bad"},
        headers={**headers(), "Origin": "https://evil.example.test"},
    )
    assert response.status == 403


async def test_security_headers_and_no_credential_fields_in_url(web_client):
    client, login = web_client
    response = await client.get("/", headers=headers())
    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    url = await login.issue(100, "+15551234567")
    assert "+15551234567" not in url and "?" not in url


async def test_secure_cookie_and_cancel(web_client):
    client, login = web_client
    url = await login.issue(100, "+15551234567")
    response = await client.post(
        "/api/exchange", json={"token": url.split("#")[1]}, headers=headers()
    )
    assert response.status == 200
    cookie = response.cookies[COOKIE]
    assert cookie["secure"] and cookie["httponly"] and cookie["samesite"] == "Strict"
    data = await response.json()
    response = await client.post(
        "/api/action",
        json={"action": "cancel"},
        headers={
            **headers(),
            "Cookie": f"{COOKIE}={cookie.value}",
            "X-CSRF-Token": data["csrf"],
        },
    )
    assert response.status == 200
    assert (await response.json())["step"] == "cancelled"


async def test_unknown_session_is_unauthorized(web_client):
    client, _ = web_client
    response = await client.post("/api/action", json={"action": "send"}, headers=headers())
    assert response.status == 401


async def test_non_json_and_malformed_json_rejected(web_client):
    client, _ = web_client
    response = await client.post("/api/exchange", data="token=bad", headers=headers())
    assert response.status == 415
    response = await client.post(
        "/api/exchange", data="{", headers={**headers(), "Content-Type": "application/json"}
    )
    assert response.status == 400
    response = await client.post("/api/exchange", json=["token"], headers=headers())
    assert response.status == 400


async def test_body_size_limit(web_client):
    client, _ = web_client
    response = await client.post("/api/exchange", json={"token": "x" * 10000}, headers=headers())
    assert response.status == 413
