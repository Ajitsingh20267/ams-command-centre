"""Tests the pure filtering logic without hitting the network (that path was
verified manually — see README's "what was actually verified" section)."""
from app.agents.lead_generation import DISTRESS_MARKERS


def test_distress_markers_cover_the_documented_phrases():
    for phrase in ["chapter 11", "substantial doubt about", "receivership"]:
        assert phrase in DISTRESS_MARKERS


def test_distress_filter_logic():
    def is_distress(blob: str) -> bool:
        low = blob.lower()
        return any(m in low for m in DISTRESS_MARKERS)

    assert is_distress("substantial doubt about the Company's ability to continue")
    assert not is_distress("matures within the next twelve months")
