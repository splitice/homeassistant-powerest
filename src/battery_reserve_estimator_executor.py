"""Regular Python helpers for executor-backed battery estimator calculations."""

from datetime import datetime, timedelta


SELL_BY_TIME = "20:00"
EXPORT_WINDOW_START_HOUR = 18
EXPORT_WINDOW_END_HOUR = 20
MAX_EXPORT_KWH_PER_HOUR = 10
MAX_DAYS = 7
HOUSE_CONSUMPTION_STATISTIC_ID = "sensor.goodwe_house_consumption"


def _coerce_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.lower() in {"", "none", "unknown", "unavailable"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt_value = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            dt_value = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt_value.tzinfo is not None:
        return dt_value.astimezone()
    return dt_value


def _hour_key(dt_value):
    dt_value = _parse_datetime(dt_value)
    if dt_value is None:
        return None
    if dt_value.tzinfo is not None:
        dt_value = dt_value.astimezone()
    return dt_value.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00:00")


def _timestamp(dt_value):
    dt_value = _parse_datetime(dt_value)
    if dt_value is None:
        return None
    if dt_value.tzinfo is not None:
        return dt_value.timestamp()
    return dt_value.replace(tzinfo=datetime.now().astimezone().tzinfo).timestamp()


def _date_from_hour_key(hour_key):
    return datetime.fromisoformat(hour_key[:10]).date()


def _get_sell_by_hour():
    if isinstance(SELL_BY_TIME, str) and ":" in SELL_BY_TIME:
        try:
            return int(SELL_BY_TIME.split(":", 1)[0])
        except ValueError:
            pass
    return 20


def _build_historical_usage_estimate(house_consumption_stats, daily_draw_kwh):
    daily_draw_wh = daily_draw_kwh * 1000 if daily_draw_kwh is not None else None
    stats_root = house_consumption_stats.get("statistics", {}) if isinstance(house_consumption_stats, dict) else {}
    rows = stats_root.get(HOUSE_CONSUMPTION_STATISTIC_ID, []) if isinstance(stats_root, dict) else []

    hours_by_day = {}
    totals = {}
    counts = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        start = row.get("start")
        usage = _coerce_float(row.get("mean"))
        if usage is not None and usage < 0:
            usage = 0.0

        if start is None or usage is None:
            continue

        start_local = _parse_datetime(start)
        if start_local is None:
            continue
        if start_local.tzinfo is not None:
            start_local = start_local.astimezone()

        day_key = start_local.strftime("%Y-%m-%d")
        hour_key = start_local.strftime("%H")

        hours_by_day.setdefault(day_key, {})[hour_key] = usage
        totals[day_key] = totals.get(day_key, 0.0) + usage
        counts[day_key] = counts.get(day_key, 0) + 1

    out_days = {}
    for day_key in sorted(hours_by_day):
        total = float(totals.get(day_key, 0.0))
        count = int(counts.get(day_key, 0))
        scale = 1.0

        if daily_draw_wh is not None and count == 24 and total > 0 and total < float(daily_draw_wh):
            scale = float(daily_draw_wh) / total

        out_days[day_key] = {
            "scale": scale,
            "hours": hours_by_day.get(day_key, {}),
        }

    return out_days


def _merge_forecast_hours(now_local, forecast_periods):
    merged = {}
    current_hour_ts = now_local.replace(minute=0, second=0, microsecond=0).timestamp()

    for wh_period in forecast_periods:
        if not isinstance(wh_period, dict):
            continue

        for ts, value in wh_period.items():
            ts_value = _timestamp(ts)
            if ts_value is None or ts_value < current_hour_ts:
                continue

            hour_key = _hour_key(ts)
            if hour_key is None:
                continue
            merged[hour_key] = merged.get(hour_key, 0.0) + (_coerce_float(value) or 0.0)

    return merged


def _hourly_usage_for_forecast(hour_key, historical_usage, today_day, hourly_draw_wh):
    forecast_day = hour_key[:10]
    historical_day = (_date_from_hour_key(hour_key) - timedelta(days=7)).isoformat()
    if historical_day >= today_day:
        historical_day = (datetime.fromisoformat(historical_day).date() - timedelta(days=7)).isoformat()

    historical_day_data = historical_usage.get(historical_day, {})
    historical_day_hours = historical_day_data.get("hours", {}) if isinstance(historical_day_data, dict) else {}
    historical_day_scale = _coerce_float(
        historical_day_data.get("scale") if isinstance(historical_day_data, dict) else 1
    )
    if historical_day_scale is None:
        historical_day_scale = 1.0

    historical_hour = hour_key[11:13] if forecast_day else None
    base_usage_wh = _coerce_float(historical_day_hours.get(historical_hour))
    if base_usage_wh is None:
        return float(hourly_draw_wh)
    return float(base_usage_wh) * float(historical_day_scale)


def _calculate_sufficiency_result(current_battery_wh, battery_floor_wh, hourly_draw_wh, historical_usage, merged, now_local):
    if current_battery_wh is None or battery_floor_wh is None or hourly_draw_wh is None:
        current_text = "none" if current_battery_wh is None else str(current_battery_wh)
        draw_text = "none" if hourly_draw_wh is None else str(hourly_draw_wh)
        return f"-1|0|0|0|{current_text}|{draw_text}"

    forecast_hours = sorted(merged)
    hours_found = len(forecast_hours)
    if hours_found == 0:
        return f"-1|0|0|0|{current_battery_wh}|{hourly_draw_wh}|0|0"

    forecast_days = []
    for hour_key in forecast_hours:
        forecast_day = hour_key[:10]
        if forecast_day not in forecast_days:
            forecast_days.append(forecast_day)
    forecast_days = forecast_days[:MAX_DAYS]
    usable_days_count = len(forecast_days)
    if usable_days_count == 0:
        return f"-1|0|{hours_found}|0|{current_battery_wh}|{hourly_draw_wh}"

    candidate_hours_full = [hour_key for hour_key in forecast_hours if hour_key[:10] in forecast_days]
    usable_hours_count = len(candidate_hours_full)
    if usable_hours_count == 0:
        return f"-1|0|{hours_found}|{usable_days_count}|{current_battery_wh}|{hourly_draw_wh}"

    best_hours = 0
    best_required = -1.0
    best_max_battery = float(current_battery_wh)
    today_day = now_local.strftime("%Y-%m-%d")

    for hour_count in range(usable_hours_count, 0, -1):
        hours_subset = candidate_hours_full[:hour_count]
        if not hours_subset:
            continue

        usage_by_hour = {
            hour_key: _hourly_usage_for_forecast(hour_key, historical_usage, today_day, hourly_draw_wh)
            for hour_key in hours_subset
        }

        required_before = float(battery_floor_wh)
        for hour_key in reversed(hours_subset):
            solar_wh = float(merged.get(hour_key, 0.0))
            hourly_usage_wh = float(usage_by_hour.get(hour_key, hourly_draw_wh))
            before = required_before + hourly_usage_wh - solar_wh
            if before < float(battery_floor_wh):
                before = float(battery_floor_wh)
            required_before = before

        if required_before > float(current_battery_wh):
            continue

        sim_level = float(current_battery_wh)
        sim_max = float(current_battery_wh)
        for hour_key in hours_subset:
            solar_wh = float(merged.get(hour_key, 0.0))
            hourly_usage_wh = float(usage_by_hour.get(hour_key, hourly_draw_wh))
            sim_level = sim_level + solar_wh - hourly_usage_wh
            if sim_level > sim_max:
                sim_max = sim_level

        best_hours = hour_count
        best_required = required_before
        best_max_battery = sim_max
        break

    if best_hours > 0:
        return (
            f"{round(best_required / 1000, 2)}|{best_hours}|{hours_found}|{usable_days_count}|"
            f"{best_max_battery}|{hourly_draw_wh}"
        )
    return f"-1|0|{hours_found}|{usable_days_count}|{current_battery_wh}|{hourly_draw_wh}"


def _calculate_export_result(current_battery_wh, sell_by_wh, hourly_draw_wh, historical_usage, merged, now_local):
    if current_battery_wh is None or hourly_draw_wh is None or sell_by_wh is None:
        return "0|0"

    forecast_hours = sorted(merged)
    if not forecast_hours:
        return "0|0"

    tomorrow_day = (now_local + timedelta(days=1)).strftime("%Y-%m-%d")
    today_day = now_local.strftime("%Y-%m-%d")
    sell_by_hour = _get_sell_by_hour()
    now_decimal_hour = (
        float(now_local.hour)
        + (float(now_local.minute) / 60.0)
        + (float(now_local.second) / 3600.0)
    )

    export_hours = 0.0
    if EXPORT_WINDOW_END_HOUR > EXPORT_WINDOW_START_HOUR:
        active_export_start = max(float(EXPORT_WINDOW_START_HOUR), now_decimal_hour)
        if active_export_start < EXPORT_WINDOW_END_HOUR:
            export_hours = float(EXPORT_WINDOW_END_HOUR) - active_export_start

    max_export_kwh_total = export_hours * float(MAX_EXPORT_KWH_PER_HOUR)
    level = float(current_battery_wh)
    level_at_sell_by = None

    for hour_key in forecast_hours:
        forecast_day = hour_key[:10]
        hourly_usage_wh = _hourly_usage_for_forecast(hour_key, historical_usage, today_day, hourly_draw_wh)
        solar_wh = float(merged.get(hour_key, 0.0))
        level = level + solar_wh - float(hourly_usage_wh)

        if forecast_day == tomorrow_day and int(hour_key[11:13]) == sell_by_hour:
            level_at_sell_by = level

    needs_export = level_at_sell_by is not None and float(level_at_sell_by) > float(sell_by_wh)
    safe_export_kwh = 0.0

    if needs_export and max_export_kwh_total > 0 and level_at_sell_by is not None:
        exportable_surplus_kwh = (float(level_at_sell_by) - float(sell_by_wh)) / 1000.0
        if exportable_surplus_kwh > 0:
            safe_export_kwh = min(exportable_surplus_kwh, max_export_kwh_total)

    return f"{1 if needs_export else 0}|{round(safe_export_kwh, 2)}"


def calculate_estimator_result(
    house_consumption_stats,
    daily_draw_kwh,
    current_battery_wh,
    battery_floor_wh,
    sell_by_wh,
    hourly_draw_wh,
    now_local,
    forecast_periods,
):
    historical_usage = _build_historical_usage_estimate(house_consumption_stats, daily_draw_kwh)
    merged = _merge_forecast_hours(now_local, forecast_periods)

    result_sufficiency = _calculate_sufficiency_result(
        current_battery_wh=current_battery_wh,
        battery_floor_wh=battery_floor_wh,
        hourly_draw_wh=hourly_draw_wh,
        historical_usage=historical_usage,
        merged=merged,
        now_local=now_local,
    )
    result_export = _calculate_export_result(
        current_battery_wh=current_battery_wh,
        sell_by_wh=sell_by_wh,
        hourly_draw_wh=hourly_draw_wh,
        historical_usage=historical_usage,
        merged=merged,
        now_local=now_local,
    )
    return f"{result_sufficiency}|{result_export}"
