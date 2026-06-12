from __future__ import annotations

from abc import ABC, abstractmethod

from job_source_mcp.models import JobListing


class JobSourceAdapter(ABC):
    name: str

    @abstractmethod
    async def search(
        self,
        keyword: str,
        page: int = 1,
        limit: int = 20,
        location: str | None = None,
    ) -> list[JobListing]:
        raise NotImplementedError
