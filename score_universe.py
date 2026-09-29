from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from bci_common import pct_return, read_tail_records, stdev, to_float
from score_bci_recommendations import build_bci_recommendation_themes


WEIGHTS = {
    "momentum": 0.35,
    "trend": 0.20,
    "stability": 0.15,
    "drawdown": 0.10,
    "liquidity": 0.10,
    "quality": 0.10,
}

RECOMMENDATION_LOOKBACK_DAYS = 10
RECOMMENDATION_LIMIT = 100


@dataclass
class RawScore:
    symbol: str
    display_symbol: str
    name: str
    market: str
    country: str
    exchange: str
    source: str
    path: str
    last_date: str
    last_close: float
    rows: int
    ret_1m: float | None
    ret_3m: float | None
    ret_6m: float | None
    ret_12m: float | None
    momentum_raw: float | None
    trend_raw: float | None
    volatility_raw: float | None
    drawdown_raw: float | None
    liquidity_raw: float | None
    quality_raw: float
    spark: list[float]


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def daily_returns(closes: list[float]) -> list[float]:
    result: list[float] = []
    for previous, current in zip(closes, closes[1:]):
        if previous > 0:
            result.append(current / previous - 1.0)
    return result


def max_drawdown(closes: list[float]) -> float | None:
    if len(closes) < 2:
        return None
    peak = closes[0]
    worst = 0.0
    for close in closes:
        if close > peak:
            peak = close
        if peak > 0:
            worst = min(worst, close / peak - 1.0)
    return worst


def percentile_map(items: list[tuple[str, float]], invert: bool = False) -> dict[str, float]:
    clean = [(key, value) for key, value in items if value is not None and math.isfinite(value)]
    if not clean:
        return {}
    clean.sort(key=lambda pair: pair[1])
    count = len(clean)
    result: dict[str, float] = {}
    for rank, (key, _) in enumerate(clean):
        score = 0.5 if count == 1 else rank / (count - 1)
        result[key] = 1.0 - score if invert else score
    return result


def score_one(path: Path, country: str) -> RawScore | None:
    rows = read_tail_records(path)
    parsed: list[dict[str, object]] = []
    for row in rows:
        close = to_float(row.get("close"))
        if close is None:
            continue
        parsed.append(
            {
                "date": str(row.get("date", "")),
                "close": close,
                "volume": to_float(row.get("volume")),
                "raw": row,
            }
        )

    if len(parsed) < 30:
        return None

    closes = [float(row["close"]) for row in parsed]
    volumes = [float(row["volume"] or 0.0) for row in parsed]
    last = parsed[-1]
    raw = last["raw"]
    assert isinstance(raw, dict)

    ret_1m = pct_return(closes, 21)
    ret_3m = pct_return(closes, 63)
    ret_6m = pct_return(closes, 126)
    ret_12m = pct_return(closes, 252)

    momentum_parts = [
        (ret_1m, 0.15),
        (ret_3m, 0.25),
        (ret_6m, 0.30),
        (ret_12m, 0.30),
    ]
    momentum_values = [(value, weight) for value, weight in momentum_parts if value is not None]
    momentum_raw = None
    if momentum_values:
        weight_sum = sum(weight for _, weight in momentum_values)
        momentum_raw = sum(value * weight for value, weight in momentum_values) / weight_sum

    sma_50 = mean(closes[-50:]) if len(closes) >= 50 else None
    sma_200 = mean(closes[-200:]) if len(closes) >= 200 else None
    trend_values: list[float] = []
    if sma_50 and sma_50 > 0:
        trend_values.append(closes[-1] / sma_50 - 1.0)
    if sma_200 and sma_200 > 0:
        trend_values.append(closes[-1] / sma_200 - 1.0)
    trend_raw = mean(trend_values)

    rets = daily_returns(closes[-64:])
    vol = stdev(rets)
    volatility_raw = vol * math.sqrt(252) if vol is not None else None
    drawdown_raw = max_drawdown(closes[-252:])

    dollar_volume = [close * volume for close, volume in zip(closes[-20:], volumes[-20:]) if volume > 0]
    liquidity_raw = median(dollar_volume) if dollar_volume else None
    quality_raw = min(len(parsed) / 252.0, 1.0)

    if country == "KR":
        symbol = str(raw.get("ticker") or path.stem).zfill(6)
        name = str(raw.get("name") or symbol)
        market = str(raw.get("market") or "")
        exchange = market
        display_symbol = symbol
    else:
        symbol = str(raw.get("symbol") or path.stem)
        name = str(raw.get("name") or symbol)
        exchange = str(raw.get("exchange") or "")
        market = exchange
        display_symbol = symbol

    return RawScore(
        symbol=symbol,
        display_symbol=display_symbol,
        name=name,
        market=market,
        country=country,
        exchange=exchange,
        source=str(raw.get("source") or ""),
        path=str(path.as_posix()),
        last_date=str(last["date"]),
        last_close=float(last["close"]),
        rows=len(parsed),
        ret_1m=ret_1m,
        ret_3m=ret_3m,
        ret_6m=ret_6m,
        ret_12m=ret_12m,
        momentum_raw=momentum_raw,
        trend_raw=trend_raw,
        volatility_raw=volatility_raw,
        drawdown_raw=drawdown_raw,
        liquidity_raw=liquidity_raw,
        quality_raw=quality_raw,
        spark=[round(value, 4) for value in closes[-90:]],
    )


def fmt_pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100.0, 2)


def fmt_num(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def simple_moving_average(values: list[float | None], period: int) -> list[float | None]:
    result: list[float | None] = []
    window: list[float] = []
    for value in values:
        if value is None:
            window.clear()
            result.append(None)
            continue
        window.append(value)
        if len(window) > period:
            window.pop(0)
        result.append(sum(window) / period if len(window) == period else None)
    return result


def rolling_stdev(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < period:
            result.append(None)
            continue
        result.append(stdev(values[index + 1 - period : index + 1]))
    return result


def exponential_moving_average(values: list[float | None], period: int) -> list[float | None]:
    result: list[float | None] = []
    clean: list[float] = []
    multiplier = 2.0 / (period + 1)
    current: float | None = None

    for value in values:
        if value is None:
            result.append(None)
            continue
        if current is None:
            clean.append(value)
            if len(clean) < period:
                result.append(None)
                continue
            current = sum(clean[-period:]) / period
        else:
            current = (value - current) * multiplier + current
        result.append(current)
    return result


def latest_true(flags: list[bool], lookback_days: int) -> int | None:
    first_index = max(0, len(flags) - lookback_days - 1)
    for index in range(len(flags) - 1, first_index - 1, -1):
        if flags[index]:
            return index
    return None


def safe_last(values: list[float | None], default: float | None = None) -> float | None:
    return values[-1] if values and values[-1] is not None else default


def stock_identity(rows: list[dict[str, object]], base: dict[str, object]) -> dict[str, object]:
    ticker = str(rows[-1]["ticker"])
    return {
        "id": f"KR:{ticker}",
        "symbol": ticker,
        "displaySymbol": ticker,
        "name": str(base.get("name") or rows[-1]["name"]),
        "market": str(base.get("market") or rows[-1]["market"]),
        "lastDate": str(rows[-1]["date"]),
        "lastClose": round(float(rows[-1]["close"]), 4),
        "baseScore": round(float(base.get("score") or 0.0), 2),
    }


def make_recommendation_item(
    rows: list[dict[str, object]],
    base: dict[str, object],
    recommendation_score: float,
    primary_signal: str,
    secondary_signal: str,
    metric_label: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    item = stock_identity(rows, base)
    item.update(
        {
            "recommendationScore": round(recommendation_score, 2),
            "primarySignal": primary_signal,
            "secondarySignal": secondary_signal,
            "metricLabel": metric_label,
        }
    )
    if extra:
        item.update(extra)
    return item


def relative_strength_index(closes: list[float], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return result

    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(closes[:period], closes[1 : period + 1]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    def to_rsi(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0
        rs = gain / loss
        return 100.0 - (100.0 / (1.0 + rs))

    result[period] = to_rsi(avg_gain, avg_loss)
    for index in range(period + 1, len(closes)):
        change = closes[index] - closes[index - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        result[index] = to_rsi(avg_gain, avg_loss)
    return result


def latest_cross_up(
    values: list[float | None],
    signal: list[float | None],
    lookback_days: int,
) -> int | None:
    if len(values) != len(signal) or len(values) < 2:
        return None
    first_index = max(1, len(values) - lookback_days - 1)
    for index in range(len(values) - 1, first_index - 1, -1):
        previous_value = values[index - 1]
        previous_signal = signal[index - 1]
        current_value = values[index]
        current_signal = signal[index]
        if None in (previous_value, previous_signal, current_value, current_signal):
            continue
        assert previous_value is not None
        assert previous_signal is not None
        assert current_value is not None
        assert current_signal is not None
        if previous_value <= previous_signal and current_value > current_signal:
            return index
    return None


def parse_price_rows(path: Path, max_rows: int = 420) -> list[dict[str, object]]:
    records = read_tail_records(path, max_rows=max_rows)
    parsed: list[dict[str, object]] = []
    for row in records:
        close = to_float(row.get("close"))
        if close is None:
            continue
        parsed.append(
            {
                "date": str(row.get("date", "")),
                "close": close,
                "volume": to_float(row.get("volume")) or 0.0,
                "ticker": str(row.get("ticker") or path.stem).zfill(6),
                "name": str(row.get("name") or path.stem),
                "market": str(row.get("market") or ""),
                "source": str(row.get("source") or ""),
            }
        )
    return parsed


def build_kr_recommendation_themes(
    data_dir: Path,
    score_lookup: dict[str, dict[str, object]],
    limit: int = RECOMMENDATION_LIMIT,
) -> list[dict[str, object]]:
    themes = [
        {
            "id": "kr_macd_rsi_dual_golden_cross_10d",
            "title": "국내 MACD + RSI 골든크로스",
            "description": "최근 10거래일 안에 MACD 상향 돌파와 RSI 상향 돌파가 모두 발생한 국내 종목입니다.",
            "settings": {
                "lookbackTradingDays": RECOMMENDATION_LOOKBACK_DAYS,
                "macd": {"shortEma": 12, "longEma": 26, "signalEma": 9},
                "rsi": {"period": 14, "signalSma": 9, "lowerLine": 30, "upperLine": 70},
            },
            "items": [],
        },
        {
            "id": "kr_volume_price_breakout_20d",
            "title": "거래량 동반 20일 돌파",
            "description": "20거래일 종가 고점을 돌파하면서 거래량이 20일 중앙값의 2배 이상 붙은 종목입니다.",
            "settings": {"priceBreakoutDays": 20, "volumeMedianDays": 20, "volumeMultiple": 2.0},
            "items": [],
        },
        {
            "id": "kr_bollinger_squeeze_breakout",
            "title": "볼린저 스퀴즈 상방 돌파",
            "description": "최근 변동성이 낮아진 뒤 볼린저밴드 상단을 돌파한 종목입니다.",
            "settings": {"period": 20, "stdev": 2, "bandwidthLookback": 120, "bandwidthPercentileMax": 0.35},
            "items": [],
        },
        {
            "id": "kr_uptrend_alignment",
            "title": "정배열 추세 지속",
            "description": "20일, 60일, 120일 이동평균이 정배열이고 단기 추세가 상승 중인 종목입니다.",
            "settings": {"shortSma": 20, "midSma": 60, "longSma": 120},
            "items": [],
        },
        {
            "id": "kr_pullback_rebound_uptrend",
            "title": "상승 추세 눌림목 반등",
            "description": "중장기 상승 추세 안에서 20일선 위로 재돌파한 눌림목 반등 후보입니다.",
            "settings": {"reboundSma": 20, "trendSma": 120, "rsiRange": [40, 65]},
            "items": [],
        },
        {
            "id": "kr_rsi_oversold_recovery",
            "title": "RSI 과매도 회복",
            "description": "RSI 14가 최근 10거래일 안에 30선을 상향 회복한 종목입니다.",
            "settings": {"rsiPeriod": 14, "recoveryLine": 30, "lookbackTradingDays": RECOMMENDATION_LOOKBACK_DAYS},
            "items": [],
        },
        {
            "id": "kr_52week_high_momentum",
            "title": "52주 신고가 모멘텀",
            "description": "52주 종가 고점에 근접하거나 돌파했고 중기 수익률이 양호한 종목입니다.",
            "settings": {"highLookbackDays": 252, "nearHighPct": 2.0, "min3mReturnPct": 5.0},
            "items": [],
        },
    ]
    by_id = {str(theme["id"]): theme for theme in themes}

    for path in sorted((data_dir / "daily" / "kr" / "fdr").glob("*.csv")):
        rows = parse_price_rows(path, max_rows=520)
        if len(rows) < 80:
            continue

        closes = [float(row["close"]) for row in rows]
        dates = [str(row["date"]) for row in rows]
        volumes = [float(row["volume"]) for row in rows]
        last_index = len(rows) - 1
        last_close = closes[-1]
        ticker = str(rows[-1]["ticker"])
        key = f"KR:{ticker}"
        base = score_lookup.get(key, {})
        base_score = float(base.get("score") or 0.0)
        liquidity = float(base.get("metrics", {}).get("liquidity") or 0.0) if isinstance(base.get("metrics"), dict) else 0.0
        liquidity_score = min(1.0, math.log10(max(liquidity, 1.0)) / 12.0)

        sma20 = simple_moving_average(closes, 20)
        sma60 = simple_moving_average(closes, 60)
        sma120 = simple_moving_average(closes, 120)
        stdev20 = rolling_stdev(closes, 20)
        short_ema = exponential_moving_average(closes, 12)
        long_ema = exponential_moving_average(closes, 26)
        macd_line: list[float | None] = [
            None if short is None or long is None else short - long
            for short, long in zip(short_ema, long_ema)
        ]
        macd_signal = exponential_moving_average(macd_line, 9)
        rsi_line = relative_strength_index(closes, 14)
        rsi_signal = simple_moving_average(rsi_line, 9)
        rsi_current = safe_last(rsi_line)
        volume20 = median(volumes[-20:]) if len(volumes) >= 20 else None
        volume_multiple = volumes[-1] / volume20 if volume20 and volume20 > 0 else None

        macd_index = latest_cross_up(macd_line, macd_signal, RECOMMENDATION_LOOKBACK_DAYS)
        rsi_index = latest_cross_up(rsi_line, rsi_signal, RECOMMENDATION_LOOKBACK_DAYS)
        if macd_index is not None and rsi_index is not None:
            macd_days_ago = last_index - macd_index
            rsi_days_ago = last_index - rsi_index
            histogram = None
            if macd_line[-1] is not None and macd_signal[-1] is not None:
                histogram = macd_line[-1] - macd_signal[-1]
            previous_histogram = None
            if len(macd_line) > 1 and macd_line[-2] is not None and macd_signal[-2] is not None:
                previous_histogram = macd_line[-2] - macd_signal[-2]
            freshness = (RECOMMENDATION_LOOKBACK_DAYS * 2 - macd_days_ago - rsi_days_ago) / (
                RECOMMENDATION_LOOKBACK_DAYS * 2
            )
            rsi_position = 0.0
            if rsi_current is not None:
                if rsi_current < 30:
                    rsi_position = 1.0
                elif rsi_current <= 70:
                    rsi_position = 1.0 - abs(rsi_current - 45.0) / 35.0
                else:
                    rsi_position = max(0.0, 1.0 - ((rsi_current - 70.0) / 30.0))
            histogram_turn = 0.5
            if histogram is not None and previous_histogram is not None:
                histogram_turn = 1.0 if histogram > previous_histogram else 0.35
            recommendation_score = (
                freshness * 45.0
                + rsi_position * 20.0
                + histogram_turn * 15.0
                + (base_score / 100.0) * 15.0
                + liquidity_score * 5.0
            )
            by_id["kr_macd_rsi_dual_golden_cross_10d"]["items"].append(
                make_recommendation_item(
                    rows,
                    base,
                    recommendation_score,
                    f"MACD {macd_days_ago}일 전",
                    f"RSI {rsi_days_ago}일 전",
                    f"RSI {fmt_num(rsi_current, 2)} / {fmt_num(rsi_signal[-1], 2)}",
                    {
                        "macdCrossDate": dates[macd_index],
                        "macdDaysAgo": macd_days_ago,
                        "rsiCrossDate": dates[rsi_index],
                        "rsiDaysAgo": rsi_days_ago,
                        "rsi": fmt_num(rsi_current, 2),
                        "rsiSignal": fmt_num(rsi_signal[-1], 2),
                        "macd": fmt_num(macd_line[-1], 4),
                        "macdSignal": fmt_num(macd_signal[-1], 4),
                        "macdHistogram": fmt_num(histogram, 4),
                        "volume20dMedian": fmt_num(volume20, 0),
                    },
                )
            )

        if len(closes) >= 22 and volume_multiple is not None:
            prior_high_20 = max(closes[-21:-1])
            if last_close > prior_high_20 and volume_multiple >= 2.0 and (sma20[-1] is None or last_close > sma20[-1]):
                breakout_pct = last_close / prior_high_20 - 1.0
                recommendation_score = (
                    min(volume_multiple / 5.0, 1.0) * 35.0
                    + min(max(breakout_pct, 0.0) / 0.12, 1.0) * 25.0
                    + (base_score / 100.0) * 30.0
                    + liquidity_score * 10.0
                )
                by_id["kr_volume_price_breakout_20d"]["items"].append(
                    make_recommendation_item(
                        rows,
                        base,
                        recommendation_score,
                        "20일 고점 돌파",
                        f"거래량 {fmt_num(volume_multiple, 2)}배",
                        f"돌파폭 {fmt_pct(breakout_pct)}%",
                        {"breakoutPct": fmt_pct(breakout_pct), "volumeMultiple": fmt_num(volume_multiple, 2)},
                    )
                )

        if len(closes) >= 140 and sma20[-1] is not None and stdev20[-1] is not None and sma20[-1] > 0:
            upper_band = sma20[-1] + stdev20[-1] * 2.0
            lower_band = sma20[-1] - stdev20[-1] * 2.0
            bandwidth = (upper_band - lower_band) / sma20[-1]
            bandwidths = []
            for avg, dev in zip(sma20[-120:], stdev20[-120:]):
                if avg is not None and dev is not None and avg > 0:
                    bandwidths.append(((avg + dev * 2.0) - (avg - dev * 2.0)) / avg)
            bandwidth_rank = None
            if bandwidths:
                bandwidth_rank = sum(1 for value in bandwidths if value <= bandwidth) / len(bandwidths)
            if bandwidth_rank is not None and bandwidth_rank <= 0.35 and last_close > upper_band:
                band_break_pct = last_close / upper_band - 1.0
                volume_boost = min((volume_multiple or 1.0) / 2.5, 1.0)
                recommendation_score = (
                    (1.0 - bandwidth_rank) * 35.0
                    + min(max(band_break_pct, 0.0) / 0.08, 1.0) * 25.0
                    + volume_boost * 15.0
                    + (base_score / 100.0) * 20.0
                    + liquidity_score * 5.0
                )
                by_id["kr_bollinger_squeeze_breakout"]["items"].append(
                    make_recommendation_item(
                        rows,
                        base,
                        recommendation_score,
                        "밴드 상단 돌파",
                        f"폭 하위 {fmt_num(bandwidth_rank * 100, 1)}%",
                        f"상단 대비 {fmt_pct(band_break_pct)}%",
                        {
                            "bollingerBandwidth": fmt_pct(bandwidth),
                            "bandwidthRank": fmt_num(bandwidth_rank * 100, 1),
                            "upperBand": fmt_num(upper_band, 2),
                        },
                    )
                )

        if len(closes) >= 130 and all(value is not None for value in (sma20[-1], sma60[-1], sma120[-1], sma20[-11])):
            assert sma20[-1] is not None and sma60[-1] is not None and sma120[-1] is not None and sma20[-11] is not None
            if sma20[-1] > sma60[-1] > sma120[-1] and last_close > sma20[-1] and sma20[-1] > sma20[-11]:
                trend_gap = last_close / sma120[-1] - 1.0
                short_slope = sma20[-1] / sma20[-11] - 1.0
                recommendation_score = (
                    min(max(trend_gap, 0.0) / 0.35, 1.0) * 30.0
                    + min(max(short_slope, 0.0) / 0.10, 1.0) * 25.0
                    + (base_score / 100.0) * 35.0
                    + liquidity_score * 10.0
                )
                by_id["kr_uptrend_alignment"]["items"].append(
                    make_recommendation_item(
                        rows,
                        base,
                        recommendation_score,
                        "20 > 60 > 120",
                        f"20일선 {fmt_pct(short_slope)}%",
                        f"120일선 대비 {fmt_pct(trend_gap)}%",
                        {"trendGapPct": fmt_pct(trend_gap), "sma20SlopePct": fmt_pct(short_slope)},
                    )
                )

        if len(closes) >= 130 and all(value is not None for value in (sma20[-1], sma20[-2], sma60[-1], sma120[-1])) and rsi_current is not None:
            assert sma20[-1] is not None and sma20[-2] is not None and sma60[-1] is not None and sma120[-1] is not None
            crossed_back = closes[-2] <= sma20[-2] and last_close > sma20[-1]
            in_uptrend = sma60[-1] > sma120[-1] and last_close > sma120[-1]
            if crossed_back and in_uptrend and 40 <= rsi_current <= 65:
                rebound_pct = last_close / sma20[-1] - 1.0
                recommendation_score = (
                    min(max(rebound_pct, 0.0) / 0.08, 1.0) * 25.0
                    + (1.0 - abs(rsi_current - 52.0) / 25.0) * 25.0
                    + (base_score / 100.0) * 35.0
                    + liquidity_score * 15.0
                )
                by_id["kr_pullback_rebound_uptrend"]["items"].append(
                    make_recommendation_item(
                        rows,
                        base,
                        recommendation_score,
                        "20일선 재돌파",
                        "60일선 > 120일선",
                        f"RSI {fmt_num(rsi_current, 2)}",
                        {"reboundPct": fmt_pct(rebound_pct), "rsi": fmt_num(rsi_current, 2)},
                    )
                )

        rsi_recovery_flags = [
            index > 0
            and rsi_line[index - 1] is not None
            and rsi_line[index] is not None
            and rsi_line[index - 1] <= 30
            and rsi_line[index] > 30
            for index in range(len(rsi_line))
        ]
        rsi_recovery_index = latest_true(rsi_recovery_flags, RECOMMENDATION_LOOKBACK_DAYS)
        if rsi_recovery_index is not None and rsi_current is not None:
            recovery_days_ago = last_index - rsi_recovery_index
            price_turn = closes[-1] / closes[-2] - 1.0 if len(closes) >= 2 and closes[-2] > 0 else 0.0
            recommendation_score = (
                ((RECOMMENDATION_LOOKBACK_DAYS - recovery_days_ago) / RECOMMENDATION_LOOKBACK_DAYS) * 35.0
                + min(max(rsi_current - 30.0, 0.0) / 25.0, 1.0) * 25.0
                + min(max(price_turn, 0.0) / 0.08, 1.0) * 15.0
                + (base_score / 100.0) * 20.0
                + liquidity_score * 5.0
            )
            by_id["kr_rsi_oversold_recovery"]["items"].append(
                make_recommendation_item(
                    rows,
                    base,
                    recommendation_score,
                    f"RSI 30 회복 {recovery_days_ago}일 전",
                    f"현재 RSI {fmt_num(rsi_current, 2)}",
                    f"당일 {fmt_pct(price_turn)}%",
                    {"rsiRecoveryDate": dates[rsi_recovery_index], "rsi": fmt_num(rsi_current, 2), "priceTurnPct": fmt_pct(price_turn)},
                )
            )

        if len(closes) >= 252:
            high_52w = max(closes[-252:])
            near_high_pct = last_close / high_52w - 1.0 if high_52w > 0 else None
            ret_3m = pct_return(closes, 63)
            if near_high_pct is not None and near_high_pct >= -0.02 and ret_3m is not None and ret_3m >= 0.05:
                volume_boost = min((volume_multiple or 1.0) / 2.0, 1.0)
                recommendation_score = (
                    (1.0 + near_high_pct / 0.02) * 20.0
                    + min(ret_3m / 0.35, 1.0) * 30.0
                    + volume_boost * 10.0
                    + (base_score / 100.0) * 35.0
                    + liquidity_score * 5.0
                )
                by_id["kr_52week_high_momentum"]["items"].append(
                    make_recommendation_item(
                        rows,
                        base,
                        recommendation_score,
                        "52주 고점권",
                        f"3M {fmt_pct(ret_3m)}%",
                        f"고점 대비 {fmt_pct(near_high_pct)}%",
                        {"nearHighPct": fmt_pct(near_high_pct), "ret3m": fmt_pct(ret_3m)},
                    )
                )

    for theme in themes:
        items = theme["items"]
        assert isinstance(items, list)
        items.sort(
            key=lambda row: (
                row["recommendationScore"],
                row["baseScore"],
                row["lastClose"],
            ),
            reverse=True,
        )
        del items[limit:]
        for rank, row in enumerate(items, 1):
            row["recommendationRank"] = rank
        theme["market"] = "KR"
    return themes


def build_scores(raw_scores: list[RawScore]) -> list[dict[str, object]]:
    ids = [f"{item.country}:{item.symbol}" for item in raw_scores]
    raw_by_id = dict(zip(ids, raw_scores))

    momentum_rank = percentile_map([(key, raw_by_id[key].momentum_raw) for key in ids])
    trend_rank = percentile_map([(key, raw_by_id[key].trend_raw) for key in ids])
    stability_rank = percentile_map([(key, raw_by_id[key].volatility_raw) for key in ids], invert=True)
    drawdown_rank = percentile_map([(key, raw_by_id[key].drawdown_raw) for key in ids])

    liquidity_rank: dict[str, float] = {}
    for country in sorted({item.country for item in raw_scores}):
        group = [key for key in ids if raw_by_id[key].country == country]
        liquidity_rank.update(percentile_map([(key, raw_by_id[key].liquidity_raw) for key in group]))

    scored: list[dict[str, object]] = []
    for key in ids:
        item = raw_by_id[key]
        components = {
            "momentum": momentum_rank.get(key, 0.0),
            "trend": trend_rank.get(key, 0.0),
            "stability": stability_rank.get(key, 0.0),
            "drawdown": drawdown_rank.get(key, 0.0),
            "liquidity": liquidity_rank.get(key, 0.0),
            "quality": item.quality_raw,
        }
        score = sum(components[name] * weight for name, weight in WEIGHTS.items()) * 100.0
        scored.append(
            {
                "id": key,
                "symbol": item.symbol,
                "displaySymbol": item.display_symbol,
                "name": item.name,
                "country": item.country,
                "market": item.market,
                "exchange": item.exchange,
                "source": item.source,
                "lastDate": item.last_date,
                "lastClose": round(item.last_close, 4),
                "rows": item.rows,
                "score": round(score, 2),
                "components": {name: round(value * 100.0, 2) for name, value in components.items()},
                "returns": {
                    "1m": fmt_pct(item.ret_1m),
                    "3m": fmt_pct(item.ret_3m),
                    "6m": fmt_pct(item.ret_6m),
                    "12m": fmt_pct(item.ret_12m),
                },
                "metrics": {
                    "volatility": fmt_pct(item.volatility_raw),
                    "maxDrawdown": fmt_pct(item.drawdown_raw),
                    "liquidity": fmt_num(item.liquidity_raw, 0),
                },
                "spark": item.spark,
            }
        )

    scored.sort(key=lambda row: (row["score"], row["components"]["quality"]), reverse=True)
    for rank, row in enumerate(scored, 1):
        row["rank"] = rank
    return scored


def discover_files(data_dir: Path) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for path in sorted((data_dir / "daily" / "kr" / "fdr").glob("*.csv")):
        files.append((path, "KR"))
    return files


def write_csv_summary(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "rank",
        "score",
        "country",
        "symbol",
        "name",
        "market",
        "lastDate",
        "lastClose",
        "ret_1m",
        "ret_3m",
        "ret_6m",
        "ret_12m",
        "volatility",
        "maxDrawdown",
        "liquidity",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            returns = row["returns"]
            metrics = row["metrics"]
            writer.writerow(
                {
                    "rank": row["rank"],
                    "score": row["score"],
                    "country": row["country"],
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "market": row["market"],
                    "lastDate": row["lastDate"],
                    "lastClose": row["lastClose"],
                    "ret_1m": returns["1m"],
                    "ret_3m": returns["3m"],
                    "ret_6m": returns["6m"],
                    "ret_12m": returns["12m"],
                    "volatility": metrics["volatility"],
                    "maxDrawdown": metrics["maxDrawdown"],
                    "liquidity": metrics["liquidity"],
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score downloaded Korean daily OHLCV files.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--site-dir", default="local-output")
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir)
    site_dir = Path(args.site_dir)
    output_dir = site_dir / "data"
    output_dir.mkdir(parents=True, exist_ok=True)

    files = discover_files(data_dir)
    if args.limit:
        files = files[: args.limit]

    raw_scores: list[RawScore] = []
    failures: list[dict[str, str]] = []
    for index, (path, country) in enumerate(files, 1):
        if index == 1 or index % 1000 == 0:
            print(f"scoring {index}/{len(files)}: {path.name}")
        try:
            item = score_one(path, country)
            if item is None:
                failures.append({"path": str(path), "error": "not enough valid rows"})
            else:
                raw_scores.append(item)
        except Exception as exc:
            failures.append({"path": str(path), "error": str(exc)})

    scores = build_scores(raw_scores)
    score_lookup = {str(row["id"]): row for row in scores}
    recommendations = build_kr_recommendation_themes(data_dir, score_lookup)
    recommendations.extend(build_bci_recommendation_themes(data_dir, score_lookup))
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "model": {
            "weights": WEIGHTS,
            "description": "Korean daily OHLCV composite score: momentum, trend, stability, drawdown resilience, market-relative liquidity, and data quality.",
            "bci": {
                "description": "BCI MVP recommendation themes combine cached DART disclosures, Naver news, insider/major-holder keywords, and price-volume confirmation.",
                "requiresOptionalEnv": ["DART_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"],
            },
        },
        "counts": {
            "inputFiles": len(files),
            "scored": len(scores),
            "failed": len(failures),
            "kr": sum(1 for row in scores if row["country"] == "KR"),
            "us": 0,
        },
        "stocks": scores,
        "recommendations": recommendations,
    }
    (output_dir / "scores.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    write_csv_summary(output_dir / "scores.csv", scores)
    (output_dir / "score_failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"scored: {len(scores)} failed: {len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
