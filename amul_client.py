import asyncio
import hashlib
import json
import logging
import random
import re
import time
from typing import Optional
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)

STORE_ID = "62fa94df8c13af2e242eba16"
BASE_URL = "https://shop.amul.com"

DEFAULT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9",
    "base_url": "https://shop.amul.com/en/browse/protein",
    "cache-control": "no-cache",
    "frontend": "1",
    "pragma": "no-cache",
    "priority": "u=1, i",
    "referer": "https://shop.amul.com/",
    "sec-ch-ua": '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "sec-gpc": "1",
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    ),
}

PRODUCT_FIELDS = [
    "name", "brand", "categories", "collections", "alias", "sku",
    "price", "compare_price", "original_price", "images", "metafields",
    "discounts", "catalog_only", "is_catalog", "seller", "available",
    "inventory_quantity", "net_quantity", "num_reviews", "avg_rating",
    "inventory_low_stock_quantity", "inventory_allow_out_of_stock",
    "default_variant", "variants", "lp_seller_ids",
]

# Substore alias → MongoDB ObjectId mapping (from StoreHippo substores)
SUBSTORE_ID_MAP = {
    "telangana": "66506004aa64743ceefbed25",
    "andhra-pradesh": "66505ff378117873bb53b542",
    "karnataka": "66505ff0998183e1b1935c75",
    "kerala": "66505ff2998183e1b1935ccd",
    "tamil-nadu": "66505ff578117873bb53b56a",
    "goa": "66506005147d6c73c1110115",
    "maharashtra": "665060028c13af2e242f9d6b",
    "gujarat": "6650600069aefe003660f5d7",
    "delhi": "665060068c13af2e242f9d9e",
    "rajasthan": "665060058c13af2e242f9d8e",
    "uttar-pradesh": "665060078c13af2e242f9dae",
    "west-bengal": "665060098c13af2e242f9dd6",
    "madhya-pradesh": "665060048c13af2e242f9d7e",
    "punjab": "665060068c13af2e242f9d9a",
    "haryana": "665060068c13af2e242f9d96",
}


def _build_products_url(substore_id: Optional[str] = None) -> str:
    parts = [f"fields[{f}]=1" for f in PRODUCT_FIELDS]
    parts += [
        "filters[0][field]=categories",
        "filters[0][value][0]=protein",
        "filters[0][operator]=in",
        "filters[0][original]=1",
        "facets=true",
        "facetgroup=default_category_facet",
        "limit=32",
        "total=1",
        "start=0",
        "cdc=1m",
        "v=2",
        "device_type=other",
    ]
    if substore_id:
        parts.append(f"substore={substore_id}")
    return f"{BASE_URL}/api/1/entity/ms.products?" + "&".join(parts)


class AmulClient:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._tid: Optional[str] = None
        self._pincode_record: Optional[dict] = None
        # unsafe=True so aiohttp doesn't drop cookies with mismatched domains
        self._jar = aiohttp.CookieJar(unsafe=True)
        self._initialized_at: float = 0.0

    # ------------------------------------------------------------------ #
    # Session lifecycle                                                    #
    # ------------------------------------------------------------------ #

    async def init(self, pincode: str):
        self._session = aiohttp.ClientSession(
            cookie_jar=self._jar,
            connector=aiohttp.TCPConnector(ssl=True),
        )
        await self._init_cookies()
        await self._setup_pincode(pincode)
        self._initialized_at = time.time()
        logger.info("AmulClient initialized for pincode %s (substore: %s)",
                    pincode, self._pincode_record.get("substore") if self._pincode_record else "?")

    async def reinit(self, pincode: str):
        await self.close()
        self._jar = aiohttp.CookieJar(unsafe=True)
        self._tid = None
        self._pincode_record = None
        await self.init(pincode)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    @property
    def session_age_days(self) -> float:
        if not self._initialized_at:
            return 0.0
        return (time.time() - self._initialized_at) / 86400

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _init_cookies(self):
        async with self._session.get(
            f"{BASE_URL}/en/browse/protein",
            headers=DEFAULT_HEADERS,
        ) as resp:
            logger.debug("Cookie bootstrap status: %s", resp.status)

        ts = int(time.time() * 1000)
        async with self._session.get(
            f"{BASE_URL}/user/info.js?_v={ts}",
            headers=DEFAULT_HEADERS,
        ) as resp:
            text = await resp.text()

        # Find the opening brace and balance-match to get the full JSON object
        start = text.find("{")
        if start == -1:
            raise RuntimeError("No JSON object found in Amul session response")
        depth = 0
        end = start
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break

        session_data = json.loads(text[start : end + 1])
        self._tid = session_data.get("tid")
        if not self._tid:
            raise RuntimeError("No TID in Amul session response")

    def _calc_tid(self) -> str:
        ts = int(time.time() * 1000)
        rand = random.randint(0, 999)
        raw = f"{STORE_ID}:{ts}:{rand}:{self._tid}"
        digest = hashlib.sha256(raw.encode()).hexdigest()
        return f"{ts}:{rand}:{digest}"

    def _headers(self, extra: Optional[dict] = None) -> dict:
        h = {**DEFAULT_HEADERS, "tid": self._calc_tid()}
        if extra:
            h.update(extra)
        return h

    async def _setup_pincode(self, pincode: str):
        records = await self._search_pincode(pincode)
        if not records:
            raise ValueError(f"Pincode {pincode!r} not found in Amul delivery network")
        record = records[0]
        self._pincode_record = record
        await self._set_substore(record["substore"])

    async def _search_pincode(self, pincode: str) -> list:
        url = (
            f"{BASE_URL}/entity/pincode?limit=50"
            f"&filters[0][field]=pincode"
            f"&filters[0][value]={pincode}"
            f"&filters[0][operator]=regex"
            f"&cf_cache=1h"
        )
        async with self._session.get(url, headers=self._headers()) as resp:
            data = await resp.json(content_type=None)
            return data.get("records", [])

    async def _set_substore(self, substore: str):
        url = f"{BASE_URL}/entity/ms.settings/_/setPreferences"
        payload = {"data": {"store": substore}}
        async with self._session.put(url, json=payload, headers=self._headers()) as resp:
            text = await resp.text()
            logger.debug("setPreferences response (%s): %s", resp.status, text[:100])

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def get_protein_products(self) -> list[dict]:
        substore_alias = (self._pincode_record or {}).get("substore")
        substore_id = SUBSTORE_ID_MAP.get(substore_alias) if substore_alias else None
        if not substore_id:
            logger.warning("No substore ID found for alias %r; fetching without it", substore_alias)

        url = _build_products_url(substore_id)
        async with self._session.get(url, headers=self._headers({"referer": "https://shop.amul.com/en/browse/protein"})) as resp:
            data = await resp.json(content_type=None)
            products = data.get("data", [])
            logger.info("Amul API → %d products fetched for substore %r", len(products), substore_alias)
            return products

    async def check_product(self, alias: str) -> Optional[dict]:
        products = await self.get_protein_products()
        for p in products:
            if p.get("alias") == alias:
                return p
        return None
