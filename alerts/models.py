from dataclasses import dataclass, field


@dataclass
class Job:
    """One job posting, normalised across every source."""

    company: str
    id: str
    title: str
    location: str
    url: str
    posted: str = ""
    tags: list = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.company}:{self.id}"


class FetchError(Exception):
    """A source could not be fetched or parsed."""
