"""Offline regression tests for historical level selection."""
import asyncio
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "custom_components/otodata_tank_monitor_history/history_workaround.py"
spec = importlib.util.spec_from_file_location("history_workaround", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False
    def raise_for_status(self):
        return None
    async def json(self, content_type=None):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = payloads
    def get(self, url, **kwargs):
        return FakeResponse(self.payloads[url.rsplit("/", 1)[-1]])


class HistoryTests(unittest.TestCase):
    def test_latest_dated_graph_point(self):
        payload = {"CurrentLevel": 40, "GraphLevelsData": [
            {"Date": "/Date(1763800000000)/", "Level": 30},
            {"Date": "/Date(1763900000000)/", "Level": 38},
        ]}
        chosen = module._choose_history(payload, "graph")
        self.assertEqual(chosen["level"], 38)
        self.assertEqual(chosen["source"], "history_graph")

    def test_current_preference(self):
        payload = {"CurrentLevel": 41, "GraphLevelsData": [
            {"Date": "/Date(1763900000000)/", "Level": 38}]}
        self.assertEqual(module._choose_history(payload, "current")["level"], 41)

    def test_fallback_to_current(self):
        self.assertEqual(module._choose_history({"CurrentLevel": 47}, "graph")["level"], 47)

    def test_zero_is_valid(self):
        self.assertEqual(module._level(0), 0)
        self.assertIsNone(module._level(-1))
        self.assertIsNone(module._level(101))
        self.assertIsNone(module._level(True))

    def test_merge_preserves_metadata(self):
        tanks = [{"Id": "abc", "Level": 6, "TankCapacity": 1211.2}]
        session = FakeSession({"abc": {"CurrentLevel": 38}})
        result = asyncio.run(module.async_apply_history_levels(
            session, None, tanks, 30, "graph", {}))
        self.assertEqual(result[0]["Level"], 38)
        self.assertEqual(result[0]["_SummaryLevel"], 6)
        self.assertEqual(result[0]["TankCapacity"], 1211.2)

    def test_multiple_tanks(self):
        tanks = [{"Id": "a", "Level": 6}, {"Id": "b", "Level": 7}]
        session = FakeSession({"a": {"CurrentLevel": 50}, "b": {"CurrentLevel": 60}})
        result = asyncio.run(module.async_apply_history_levels(
            session, None, tanks, 30, "graph", {}))
        self.assertEqual([t["Level"] for t in result], [50, 60])

    def test_cached_reading_on_failure(self):
        tanks = [{"Id": "a", "Level": 6}]
        cache = {}
        first = asyncio.run(module.async_apply_history_levels(
            FakeSession({"a": {"CurrentLevel": 44}}), None, tanks, 30, "graph", cache))
        second = asyncio.run(module.async_apply_history_levels(
            FakeSession({"a": {}}), None, tanks, 30, "graph", cache))
        self.assertEqual(first[0]["Level"], second[0]["Level"])
        self.assertEqual(second[0]["_HistoryStatus"], "cached")

    def test_missing_history_does_not_reuse_summary(self):
        result = asyncio.run(module.async_apply_history_levels(
            FakeSession({"a": {}}), None, [{"Id": "a", "Level": 6}], 30, "graph", {}))
        self.assertIsNone(result[0]["Level"])

    def test_summary_mode_skips_history(self):
        tanks = [{"Id": "a", "Level": 6}]
        result = asyncio.run(module.async_apply_history_levels(
            None, None, tanks, 30, "summary", {}))
        self.assertEqual(result, tanks)


if __name__ == "__main__":
    unittest.main()
