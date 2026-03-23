from datetime import date

from usage_stats import UsageStatsStore


def test_usage_stats_store_tracks_daily_and_total_counts(tmp_path):
    store = UsageStatsStore(tmp_path / "logs" / "usage_stats.json")

    first = store.record_input(12, today=date(2026, 3, 22))
    second = store.record_input(8, today=date(2026, 3, 22))
    third = store.record_input(5, today=date(2026, 3, 23))

    assert first.today_chars == 12
    assert first.total_chars == 12
    assert second.today_chars == 20
    assert second.total_chars == 20
    assert third.today_chars == 5
    assert third.total_chars == 25
