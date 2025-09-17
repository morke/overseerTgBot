from typing import Any, Dict, List, Optional
from urllib.parse import quote

import aiohttp


class OverseerrClient:
    def __init__(self, base_url: str, api_key: str, session: Optional[aiohttp.ClientSession] = None) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self._session = session

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        self._session = aiohttp.ClientSession(headers={
            "X-Api-Key": self.api_key,
            "Accept": "application/json",
        })
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def search(self, query: str) -> Dict[str, Any]:
        session = await self._get_session()
        # Overseerr requires the 'query' param to be URL-encoded (spaces as %20, no reserved chars)
        encoded = quote(query.strip(), safe="")
        url = f"{self.base_url}/api/v1/search?query={encoded}"
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def create_request(
        self,
        media_id: int,
        media_type: str,
        seasons: Optional[List[int]] = None,
        is_4k: bool = False,
    ) -> Dict[str, Any]:
        session = await self._get_session()
        url = f"{self.base_url}/api/v1/request"
        payload: Dict[str, Any] = {"mediaId": media_id, "mediaType": media_type}
        if seasons:
            payload["seasons"] = seasons
        if is_4k:
            payload["is4k"] = True
        async with session.post(url, json=payload) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def approve_request(self, request_id: int, is_4k: bool = False) -> Dict[str, Any]:
        session = await self._get_session()
        url = f"{self.base_url}/api/v1/request/{request_id}/approve"
        payload = {"is4k": is_4k}
        async with session.post(url, json=payload) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_movie_details(self, tmdb_id: int) -> Dict[str, Any]:
        session = await self._get_session()
        url = f"{self.base_url}/api/v1/movie/{tmdb_id}"
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_tv_details(self, tmdb_id: int) -> Dict[str, Any]:
        session = await self._get_session()
        url = f"{self.base_url}/api/v1/tv/{tmdb_id}"
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_details(self, media_type: str, tmdb_id: int) -> Dict[str, Any]:
        if media_type == "movie":
            return await self.get_movie_details(tmdb_id)
        if media_type == "tv":
            return await self.get_tv_details(tmdb_id)
        return {}

    async def get_ratings(self, media_type: str, tmdb_id: int) -> Dict[str, Any]:
        session = await self._get_session()
        mt = "movie" if media_type == "movie" else "tv"
        url = f"{self.base_url}/api/v1/{mt}/{tmdb_id}/ratings"
        async with session.get(url) as resp:
            if resp.status == 404:
                return {}
            resp.raise_for_status()
            return await resp.json()

    async def get_tv_recommendations(self, tv_id: int, page: int = 1) -> Dict[str, Any]:
        session = await self._get_session()
        url = f"{self.base_url}/api/v1/tv/{tv_id}/recommendations"
        params = {"page": page}
        async with session.get(url, params=params) as resp:
            if resp.status == 404:
                return {"results": []}
            resp.raise_for_status()
            return await resp.json()

    async def get_movie_recommendations(self, movie_id: int, page: int = 1) -> Dict[str, Any]:
        session = await self._get_session()
        url = f"{self.base_url}/api/v1/movie/{movie_id}/recommendations"
        params = {"page": page}
        async with session.get(url, params=params) as resp:
            if resp.status == 404:
                return {"results": []}
            resp.raise_for_status()
            return await resp.json()


# (OMDb fallback removed)

