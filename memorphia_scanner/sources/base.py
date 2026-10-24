from __future__ import annotations

from abc import ABC, abstractmethod

from memorphia_scanner.models import TokenSnapshot


class TokenSource(ABC):
    @abstractmethod
    def fetch_tokens(self) -> list[TokenSnapshot]:
        """Return normalized token snapshots from a market data provider."""
