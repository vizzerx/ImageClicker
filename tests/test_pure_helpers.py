# -*- coding: utf-8 -*-
"""
ทดสอบฟังก์ชันล้วน (pure) ของฟีเจอร์: หยุดอัตโนมัติ / ตัวช่วยคำนวณ / รายงาน Telegram
ฟังก์ชันเหล่านี้ไม่พึ่ง Tkinter หรือ self จึงทดสอบได้ตรง ๆ โดยไม่ต้องเปิดหน้าต่างแอป
"""
import time
from datetime import datetime

import pytest

from image_clicker import (
    compute_stop_at_from_duration,
    compute_stop_at_from_clock,
    parse_hhmm,
    format_remaining,
    compute_avg_round_seconds,
    compute_hearts_estimate,
    sum_results,
    format_telegram_report,
    build_telegram_url,
)


# ---------------- compute_stop_at_from_duration ----------------

def test_duration_adds_hours_in_seconds():
    now = 1000.0
    assert compute_stop_at_from_duration(now, 1.0) == now + 3600.0


def test_duration_supports_fractional_hours():
    now = 0.0
    assert compute_stop_at_from_duration(now, 0.5) == 1800.0


def test_duration_rejects_zero_or_negative():
    with pytest.raises(ValueError):
        compute_stop_at_from_duration(0.0, 0)
    with pytest.raises(ValueError):
        compute_stop_at_from_duration(0.0, -1)


# ---------------- compute_stop_at_from_clock ----------------

def test_clock_today_when_time_still_ahead():
    now_dt = datetime(2026, 1, 1, 10, 0, 0)
    now_ts = now_dt.timestamp()
    stop_ts = compute_stop_at_from_clock(now_ts, 12, 30)
    stop_dt = datetime.fromtimestamp(stop_ts)
    assert stop_dt == datetime(2026, 1, 1, 12, 30, 0)


def test_clock_rolls_to_tomorrow_when_time_already_passed():
    now_dt = datetime(2026, 1, 1, 22, 0, 0)
    now_ts = now_dt.timestamp()
    stop_ts = compute_stop_at_from_clock(now_ts, 8, 0)
    stop_dt = datetime.fromtimestamp(stop_ts)
    assert stop_dt == datetime(2026, 1, 2, 8, 0, 0)


def test_clock_rolls_to_tomorrow_when_time_exactly_now():
    now_dt = datetime(2026, 1, 1, 9, 0, 0)
    now_ts = now_dt.timestamp()
    stop_ts = compute_stop_at_from_clock(now_ts, 9, 0)
    stop_dt = datetime.fromtimestamp(stop_ts)
    assert stop_dt == datetime(2026, 1, 2, 9, 0, 0)


# ---------------- parse_hhmm ----------------

@pytest.mark.parametrize("text,expected", [
    ("09:05", (9, 5)),
    ("23:59", (23, 59)),
    ("0:00", (0, 0)),
    (" 12:30 ", (12, 30)),
])
def test_parse_hhmm_valid(text, expected):
    assert parse_hhmm(text) == expected


@pytest.mark.parametrize("text", ["", "24:00", "12:60", "abc", "12-30", None])
def test_parse_hhmm_invalid(text):
    with pytest.raises(ValueError):
        parse_hhmm(text)


# ---------------- format_remaining ----------------

def test_format_remaining_basic():
    assert format_remaining(3600) == (1, 0)
    assert format_remaining(90 * 60) == (1, 30)


def test_format_remaining_rounds_up_partial_seconds():
    # 59.5 วินาที ควรปัดขึ้นเป็นเกือบ 1 นาที ไม่ใช่ 0
    h, m = format_remaining(3599.5)
    assert (h, m) == (1, 0)


def test_format_remaining_never_negative():
    assert format_remaining(-10) == (0, 0)


# ---------------- compute_avg_round_seconds ----------------

def test_avg_round_seconds_empty_returns_none():
    assert compute_avg_round_seconds([]) is None


def test_avg_round_seconds_ignores_non_numeric_elapsed():
    results = [
        {"elapsed": 10},
        {"elapsed": "invalid"},
        {"elapsed": 20},
    ]
    assert compute_avg_round_seconds(results) == 15.0


def test_avg_round_seconds_all_invalid_returns_none():
    results = [{"elapsed": None}, {"elapsed": "x"}]
    assert compute_avg_round_seconds(results) is None


# ---------------- compute_hearts_estimate ----------------

def test_hearts_estimate_multiplies():
    assert compute_hearts_estimate(30.0, 10) == 300.0


def test_hearts_estimate_rejects_negative():
    with pytest.raises(ValueError):
        compute_hearts_estimate(-1, 5)
    with pytest.raises(ValueError):
        compute_hearts_estimate(5, -1)


def test_hearts_estimate_zero_hearts_is_zero():
    assert compute_hearts_estimate(30.0, 0) == 0.0


# ---------------- sum_results ----------------

def test_sum_results_basic():
    results = [
        {"coins": 100, "xp": 10},
        {"coins": 200, "xp": 20},
    ]
    assert sum_results(results) == (300, 30)


def test_sum_results_skips_non_int_values():
    results = [
        {"coins": 100, "xp": 10},
        {"coins": "", "xp": ""},   # OCR อ่านไม่ออก
    ]
    assert sum_results(results) == (100, 10)


def test_sum_results_empty_list():
    assert sum_results([]) == (0, 0)


# ---------------- format_telegram_report / build_telegram_url ----------------

def test_format_telegram_report_shape():
    text = format_telegram_report(1234, 56, 7)
    assert text == (
        "รายงานผลการเล่น\n"
        "รอบที่เล่นแล้ว: 7\n"
        "รวม Coins: 1,234\n"
        "รวม XP: 56"
    )


def test_format_telegram_report_without_prefix_unchanged():
    text = format_telegram_report(1234, 56, 7, prefix="")
    assert text == (
        "รายงานผลการเล่น\n"
        "รอบที่เล่นแล้ว: 7\n"
        "รวม Coins: 1,234\n"
        "รวม XP: 56"
    )


def test_format_telegram_report_with_prefix_prepends_line():
    text = format_telegram_report(1234, 56, 7, prefix="HOST-01")
    assert text == (
        "HOST-01\n"
        "รายงานผลการเล่น\n"
        "รอบที่เล่นแล้ว: 7\n"
        "รวม Coins: 1,234\n"
        "รวม XP: 56"
    )


def test_build_telegram_url():
    assert build_telegram_url("ABC123") == "https://api.telegram.org/botABC123/sendMessage"
