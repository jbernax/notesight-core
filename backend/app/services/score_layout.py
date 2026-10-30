"""
Page layout produced by OMR: systems of staves in page pixel coordinates.

The layout links what OCR sees on the page image (voice labels, lyric lines) to the
parts in the recognised MusicXML: within a system, the n-th staff from the top is part n.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StaffBox:
    part: int
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    is_grandstaff: bool = False

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def line_spacing(self) -> float:
        """Distance between staff lines (a grand staff spans two staves plus a gap)."""
        return self.height / (10.0 if self.is_grandstaff else 4.0)


@dataclass(frozen=True)
class SystemLayout:
    staves: tuple[StaffBox, ...]
    barline_xs: tuple[float, ...] = ()

    @property
    def min_x(self) -> float:
        return min(s.min_x for s in self.staves)

    @property
    def max_x(self) -> float:
        return max(s.max_x for s in self.staves)


@dataclass(frozen=True)
class PageLayout:
    systems: tuple[SystemLayout, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.systems

    def staff_below(self, system_index: int, staff_index: int) -> StaffBox | None:
        """The next staff down the page (same system or the following one), if any."""
        system = self.systems[system_index]
        if staff_index + 1 < len(system.staves):
            return system.staves[staff_index + 1]
        if system_index + 1 < len(self.systems) and self.systems[system_index + 1].staves:
            return self.systems[system_index + 1].staves[0]
        return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PageLayout:
        systems = []
        for system in data.get("systems", []):
            staves = tuple(
                StaffBox(
                    part=int(s["part"]),
                    min_x=float(s["min_x"]),
                    max_x=float(s["max_x"]),
                    min_y=float(s["min_y"]),
                    max_y=float(s["max_y"]),
                    is_grandstaff=bool(s.get("is_grandstaff", False)),
                )
                for s in system.get("staves", [])
            )
            raw_barlines = system.get("barline_xs", [])
            barline_xs = tuple(
                sorted(float(x) for x in raw_barlines if isinstance(x, (int, float)))
            )
            if staves:
                systems.append(
                    SystemLayout(
                        staves=tuple(sorted(staves, key=lambda s: s.min_y)),
                        barline_xs=barline_xs,
                    )
                )
        systems.sort(key=lambda sys_: sys_.staves[0].min_y)
        return cls(systems=tuple(systems))

    @classmethod
    def load(cls, path: Path) -> PageLayout:
        """Load a layout sidecar; a missing or corrupt file yields an empty layout (logged)."""
        if not path.exists():
            return cls()
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("Ignoring unreadable OMR layout %s: %s", path, exc)
            return cls()
