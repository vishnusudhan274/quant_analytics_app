from dataclasses import dataclass
from typing import Optional


@dataclass
class ZScoreAlert:
    threshold: float = 2.0

    def check(self, z_latest: Optional[float]) -> Optional[str]:
        if z_latest is None:
            return None
        if z_latest >= self.threshold:
            return f"ALERT: Z-score {z_latest:.2f} >= {self.threshold:.2f}"
        if z_latest <= -self.threshold:
            return f"ALERT: Z-score {z_latest:.2f} <= -{self.threshold:.2f}"
        return None
