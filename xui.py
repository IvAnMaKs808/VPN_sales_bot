"""Клиент 3x-ui API.

Работает с панелью MHSanaei/3x-ui: логин по сессии + endpoints /panel/api/inbounds/*.
Клиенты добавляются в один инбаунд (VLESS Reality). Ссылка-подписка для Happ
строится как {XUI_SUB_BASE_URL}/{subId}.
"""
import json
import uuid as uuidlib
import secrets
import logging

import aiohttp

from config import (
    XUI_BASE_URL, XUI_USERNAME, XUI_PASSWORD, XUI_INBOUND_ID,
    XUI_SUB_BASE_URL, XUI_FLOW, TRAFFIC_LIMIT_GB,
)

log = logging.getLogger("xui")

GB = 1024 ** 3


class XUIError(Exception):
    pass


def new_uuid() -> str:
    return str(uuidlib.uuid4())


def new_sub_id() -> str:
    return secrets.token_hex(8)


def sub_link(sub_id: str) -> str:
    return f"{XUI_SUB_BASE_URL}/{sub_id}"


class XUIClient:
    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
        self._logged_in = False

    async def _session_obj(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # ssl=False — панели часто используют самоподписанный сертификат
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(connector=connector)
            self._logged_in = False
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _login(self):
        session = await self._session_obj()
        async with session.post(
            f"{XUI_BASE_URL}/login",
            data={"username": XUI_USERNAME, "password": XUI_PASSWORD},
        ) as resp:
            data = await resp.json(content_type=None)
        if not data or not data.get("success"):
            raise XUIError(f"Не удалось войти в панель 3x-ui: {data}")
        self._logged_in = True

    async def _post(self, path: str, payload: dict) -> dict:
        session = await self._session_obj()
        if not self._logged_in:
            await self._login()
        url = f"{XUI_BASE_URL}{path}"
        async with session.post(url, json=payload) as resp:
            data = await resp.json(content_type=None)
        # если сессия протухла — перелогин и повтор
        if data is None or (isinstance(data, dict) and data.get("success") is False
                            and "login" in str(data.get("msg", "")).lower()):
            await self._login()
            async with session.post(url, json=payload) as resp:
                data = await resp.json(content_type=None)
        if not isinstance(data, dict) or not data.get("success"):
            raise XUIError(f"3x-ui вернул ошибку на {path}: {data}")
        return data

    def _client_settings(self, client_uuid: str, email: str, sub_id: str, expiry_ms: int) -> str:
        total_bytes = TRAFFIC_LIMIT_GB * GB if TRAFFIC_LIMIT_GB > 0 else 0
        client = {
            "id": client_uuid,
            "flow": XUI_FLOW,
            "email": email,
            "limitIp": 0,
            "totalGB": total_bytes,
            "expiryTime": expiry_ms,
            "enable": True,
            "tgId": "",
            "subId": sub_id,
            "reset": 0,
        }
        return json.dumps({"clients": [client]})

    async def add_client(self, email: str, client_uuid: str, sub_id: str, expiry_ms: int):
        payload = {
            "id": XUI_INBOUND_ID,
            "settings": self._client_settings(client_uuid, email, sub_id, expiry_ms),
        }
        await self._post("/panel/api/inbounds/addClient", payload)

    async def update_client(self, client_uuid: str, email: str, sub_id: str, expiry_ms: int):
        payload = {
            "id": XUI_INBOUND_ID,
            "settings": self._client_settings(client_uuid, email, sub_id, expiry_ms),
        }
        await self._post(f"/panel/api/inbounds/updateClient/{client_uuid}", payload)

    async def delete_client(self, client_uuid: str):
        await self._post(f"/panel/api/inbounds/{XUI_INBOUND_ID}/delClient/{client_uuid}", {})


# единый экземпляр на всё приложение
xui = XUIClient()
