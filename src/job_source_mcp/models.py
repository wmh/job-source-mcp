from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class JobListing:
    source: str
    id: str
    title: str
    company: str
    location: str
    salary: str
    url: str
    posted_at: str
    tags: list[str]
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
