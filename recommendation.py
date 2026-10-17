from __future__ import annotations

import json
import math
import random
import re
import statistics
from collections import Counter
from typing import Any

import requests

from api import fetch_user_b50, fetch_user_brief, fetch_user_r30, load_songlist
from config.config import Config

DIFFICULTY_NAMES = {
    0: "PST",
    1: "PRS",
    2: "FTR",
    3: "BYD",
    4: "ETR",
}


SCORE_EXCELLENT = 9_900_000
SCORE_STABLE = 9_700_000
SCORE_STRETCH = 9_500_000


class RecommendationError(RuntimeError):
    pass


def _median(values: list[float], default: float = 0.0) -> float:
    return statistics.median(values) if values else default


def _mean(values: list[float], default: float = 0.0) -> float:
    return statistics.fmean(values) if values else default


# Calculate an Arcaea play rating from CC and score.
def calculate_play_rating(chart_constant: float, score: int) -> float:
    if score >= 10_000_000:
        return chart_constant + 2.0

    if score < 9_800_000:
        return max(chart_constant + (score - 9_500_000) / 300_000, 0.0)

    return chart_constant + 1.0 + (score - 9_800_000) / 200_000


def _score_band(score: int) -> str:
    if score >= 10_000_000:
        return "PM+"

    if score >= SCORE_EXCELLENT:
        return "excellent"

    if score >= SCORE_STABLE:
        return "stable"

    if score >= SCORE_STRETCH:
        return "stretch"

    return "struggle"


def _safe_record(record: dict[str, Any]) -> dict[str, Any] | None:
    cc = record.get("chart_constant")

    if cc is None:
        return None

    try:
        cc = float(cc)
        score = int(record.get("score", 0))
    except (TypeError, ValueError):
        return None

    if cc < 0 or score <= 0:
        return None

    return record | {
        "chart_constant": cc,
        "score": score,
    }


def _aggregate_by_cc(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[float, list[dict[str, Any]]] = {}

    for record in records:
        clean = _safe_record(record)

        if clean is None:
            continue

        cc = round(clean["chart_constant"], 2)
        buckets.setdefault(cc, []).append(clean)

    result = []

    for cc, items in sorted(buckets.items()):
        scores = [x["score"] for x in items]

        result.append(
            {
                "chart_constant": cc,
                "plays": len(items),
                "avg_score": round(_mean(scores), 0),
                "median_score": round(_median(scores), 0),
                "best_score": max(scores),
                "min_score": min(scores),
                "avg_play_rating": round(
                    _mean([float(x.get("play_rating", 0.0)) for x in items]),
                    3,
                ),
                "score_bands": dict(Counter(_score_band(score) for score in scores)),
            }
        )

    return result


def _difficulty_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    return dict(
        Counter(
            DIFFICULTY_NAMES.get(
                int(r.get("difficulty", -1)),
                "UNKNOWN",
            )
            for r in records
        )
    )


def _recent_song_counts(records: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(r.get("song_id")) for r in records if r.get("song_id"))


# Estimate warm-up, base, and challenge CC targets.
def _estimate_training_cc(
    b50: list[dict[str, Any]],
    r30: list[dict[str, Any]],
    official_ptt: float,
) -> dict[str, float]:
    valid_b50 = [x for x in (_safe_record(record) for record in b50) if x is not None]

    valid_r30 = [x for x in (_safe_record(record) for record in r30) if x is not None]

    b50_cc = [x["chart_constant"] for x in valid_b50]
    r30_cc = [x["chart_constant"] for x in valid_r30]

    normal_recent = [
        x["chart_constant"] for x in valid_r30 if x["score"] >= SCORE_STABLE
    ]

    recent_center = _median(
        normal_recent,
        _median(r30_cc, _median(b50_cc, official_ptt)),
    )

    b50_sorted = sorted(b50_cc)

    if b50_sorted:
        upper_middle_index = max(
            0,
            min(
                len(b50_sorted) - 1,
                math.ceil(len(b50_sorted) * 0.65) - 1,
            ),
        )
        ceiling_center = b50_sorted[upper_middle_index]
    else:
        ceiling_center = recent_center

    base = (recent_center * 0.63) + (ceiling_center * 0.37)

    warmup = base - 0.75 + random.uniform(-0.13, 0.06)
    challenge = base + 0.4 + random.uniform(-0.06, 0.13)

    return {
        "warmup_cc": round(max(0.0, warmup), 2),
        "base_cc": round(max(0.0, base), 2),
        "challenge_cc": round(max(0.0, challenge), 2),
    }


# Build a player profile from B50 and R30 data.
def build_player_profile(
    brief: dict[str, Any],
    b50_response: dict[str, Any],
    r30_response: dict[str, Any],
) -> dict[str, Any]:
    b50 = b50_response.get("data", [])
    r30 = r30_response.get("data", [])

    official_ptt = float(brief.get("rating_ptt", 0.0))

    training = _estimate_training_cc(
        b50,
        r30,
        official_ptt,
    )

    valid_r30 = [x for x in (_safe_record(record) for record in r30) if x is not None]

    valid_b50 = [x for x in (_safe_record(record) for record in b50) if x is not None]

    recent_scores = [x["score"] for x in valid_r30]
    b50_scores = [x["score"] for x in valid_b50]

    recent_song_counts = _recent_song_counts(r30)
    repeated_recent = [song for song, count in recent_song_counts.items() if count > 1]

    return {
        "user_id": brief.get("user_id"),
        "name": brief.get("name", "Unknown"),
        "official_ptt": round(official_ptt, 5),
        "b50_ptt": round(
            float(b50_response.get("b50_ptt", 0.0)),
            5,
        ),
        "r10_ptt": round(
            float(r30_response.get("r10_ptt", 0.0)),
            5,
        ),
        "record_counts": {
            "b50": len(b50),
            "r30": len(r30),
        },
        "score_summary": {
            "b50_average": round(_mean(b50_scores), 0),
            "b50_median": round(_median(b50_scores), 0),
            "r30_average": round(_mean(recent_scores), 0),
            "r30_median": round(_median(recent_scores), 0),
        },
        "chart_constant_profile": {
            "b50": _aggregate_by_cc(b50),
            "r30": _aggregate_by_cc(r30),
        },
        "recent_behavior": {
            "difficulty_counts": _difficulty_counts(r30),
            "repeated_song_ids": repeated_recent,
            "unique_recent_songs": len(recent_song_counts),
        },
        "training_targets": training,
    }


def _chart_sort_key(
    chart: dict[str, Any],
) -> tuple[float, str, int]:
    return (
        float(chart.get("chart_constant") or -1),
        str(chart.get("song_id", "")),
        int(chart.get("difficulty", -1)),
    )


# Build the playable song/chart catalog.
def build_chart_catalog() -> list[dict[str, Any]]:
    from api import get_song_chart

    charts: list[dict[str, Any]] = []

    for song in load_songlist().get("songs", []):
        song_id = song.get("id")

        if not song_id:
            continue

        for diff in song.get("difficulties", []):
            difficulty = diff.get("ratingClass")

            if difficulty is None:
                continue

            chart = get_song_chart(
                song_id,
                int(difficulty),
            )

            if not chart or chart.get("chart_constant") is None:
                continue

            charts.append(chart)

    return sorted(
        charts,
        key=_chart_sort_key,
    )


def _target_for_bucket(
    profile: dict[str, Any],
    bucket: str,
) -> float:
    targets = profile["training_targets"]
    return float(targets[f"{bucket}_cc"])


# Score a chart candidate against the player's target.
def _candidate_score(
    chart: dict[str, Any],
    target_cc: float,
    recently_played: Counter[str],
    recent_records: list[dict[str, Any]],
) -> float:
    cc = float(chart["chart_constant"])

    distance = abs(cc - target_cc)
    score = max(
        0.0,
        4.0 - distance * 8.0,
    )

    song_id = chart["song_id"]
    recent_count = recently_played.get(
        song_id,
        0,
    )

    if recent_count:
        score -= 3.0 + recent_count

    previous_same_chart = sum(
        1
        for record in recent_records
        if record.get("song_id") == song_id
        and int(record.get("difficulty", -1)) == int(chart["difficulty"])
    )

    score -= previous_same_chart * 2.0

    recent_artists = {
        record.get("artist") for record in recent_records if record.get("artist")
    }

    if chart.get("artist") not in recent_artists:
        score += 0.25

    return score


# Build filtered candidate pools with fallbacks.
def build_candidates(
    profile: dict[str, Any],
    b50: list[dict[str, Any]],
    r30: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    recent_song_ids = _recent_song_counts(r30)

    played_charts = {
        (
            record.get("song_id"),
            int(record.get("difficulty", -1)),
        )
        for record in b50 + r30
    }

    buckets = {
        "warmup": _target_for_bucket(
            profile,
            "warmup",
        ),
        "base": _target_for_bucket(
            profile,
            "base",
        ),
        "challenge": _target_for_bucket(
            profile,
            "challenge",
        ),
    }

    candidate_count = Config.RECOMMENDATION_CANDIDATES_PER_BUCKET
    pool_size = candidate_count * 3

    cc_ranges = (
        0.35,
        0.60,
        1.00,
    )

    result: dict[str, list[dict[str, Any]]] = {}

    for bucket, target in buckets.items():
        selected_scored: list[tuple[float, dict[str, Any]]] = []

        for cc_range in cc_ranges:
            scored: list[tuple[float, dict[str, Any]]] = []

            for chart in catalog:
                key = (
                    chart["song_id"],
                    int(chart["difficulty"]),
                )

                if key in played_charts:
                    continue

                cc = float(chart["chart_constant"])

                if abs(cc - target) > cc_range:
                    continue

                candidate_score = _candidate_score(
                    chart,
                    target,
                    recent_song_ids,
                    r30,
                )

                scored.append(
                    (
                        candidate_score,
                        chart,
                    )
                )

            scored.sort(
                key=lambda item: (
                    -item[0],
                    _chart_sort_key(item[1]),
                )
            )

            if len(scored) >= candidate_count:
                selected_scored = scored[:pool_size]
                break

            if len(scored) > len(selected_scored):
                selected_scored = scored

        if len(selected_scored) < candidate_count:
            for cc_range in cc_ranges:
                scored: list[tuple[float, dict[str, Any]]] = []

                for chart in catalog:
                    cc = float(chart["chart_constant"])

                    if abs(cc - target) > cc_range:
                        continue

                    candidate_score = _candidate_score(
                        chart,
                        target,
                        recent_song_ids,
                        r30,
                    )

                    scored.append(
                        (
                            candidate_score,
                            chart,
                        )
                    )

                scored.sort(
                    key=lambda item: (
                        -item[0],
                        _chart_sort_key(item[1]),
                    )
                )

                if len(scored) >= candidate_count:
                    selected_scored = scored[:pool_size]
                    break

                if len(scored) > len(selected_scored):
                    selected_scored = scored

        if len(selected_scored) > candidate_count:
            selected = random.sample(
                selected_scored[:pool_size],
                candidate_count,
            )
        else:
            selected = selected_scored

        result[bucket] = [chart for _, chart in selected]

    return result


# Reduce the player profile for the LLM payload.
def _compact_profile_for_llm(
    profile: dict[str, Any],
) -> dict[str, Any]:
    b50_profile = profile["chart_constant_profile"]["b50"]

    r30_profile = profile["chart_constant_profile"]["r30"]

    return {
        "name": profile["name"],
        "official_ptt": profile["official_ptt"],
        "b50_ptt": profile["b50_ptt"],
        "r10_ptt": profile["r10_ptt"],
        "score_summary": profile["score_summary"],
        "recent_behavior": profile["recent_behavior"],
        "training_targets": profile["training_targets"],
        "b50_cc_profile": b50_profile,
        "r30_cc_profile": r30_profile,
    }


# Reduce candidate data for the LLM payload.
def _compact_candidates(
    candidates: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        bucket: [
            {
                "song_id": chart["song_id"],
                "song_name": chart["song_name"],
                "artist": chart["artist"],
                "difficulty": chart["difficulty_name"],
                "difficulty_class": chart["difficulty"],
                "chart_constant": chart["chart_constant"],
                "display_level": chart["display_level"],
                "chart_designer": chart.get(
                    "chart_designer",
                    "",
                ),
            }
            for chart in items
        ]
        for bucket, items in candidates.items()
    }


# Extract a JSON object from LLM output.
def _extract_json_object(
    text: str,
) -> dict[str, Any]:
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    try:
        value = json.loads(text)

        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    fenced = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        text,
        re.DOTALL | re.IGNORECASE,
    )

    if fenced:
        try:
            value = json.loads(fenced.group(1))

            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass

    start = text.find("{")

    while start >= 0:
        decoder = json.JSONDecoder()

        try:
            value, _ = decoder.raw_decode(text[start:])

            if isinstance(value, dict):
                return value

        except json.JSONDecodeError:
            pass

        start = text.find(
            "{",
            start + 1,
        )

    raise RecommendationError("LLM returned invalid JSON")


# Validate and normalize the LLM recommendation.
def _validate_llm_result(
    result: dict[str, Any],
    candidates: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    recommendations = result.get("recommendations")

    if not isinstance(
        recommendations,
        list,
    ):
        raise RecommendationError("LLM response has no recommendations list")

    allowed = {
        bucket: {item["song_id"] for item in items}
        for bucket, items in candidates.items()
    }

    normalized: dict[
        str,
        dict[str, Any],
    ] = {}

    for item in recommendations:
        if not isinstance(item, dict):
            continue

        bucket = str(
            item.get(
                "bucket",
                "",
            )
        ).lower()

        song_id = str(
            item.get(
                "song_id",
                "",
            )
        )

        if bucket not in allowed or song_id not in allowed[bucket]:
            continue

        if bucket in normalized:
            continue

        normalized[bucket] = {
            "bucket": bucket,
            "song_id": song_id,
        }

    missing = [
        bucket
        for bucket in (
            "warmup",
            "base",
            "challenge",
        )
        if bucket not in normalized
    ]

    if missing:
        raise RecommendationError("LLM omitted required buckets: " + ", ".join(missing))

    return {
        "recommendations": [
            normalized[bucket]
            for bucket in (
                "warmup",
                "base",
                "challenge",
            )
        ]
    }


# Ask the LLM to select one song per training bucket.
def ask_llm(
    profile: dict[str, Any],
    candidates: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    candidate_count = sum(len(items) for items in candidates.values())

    if candidate_count == 0:
        raise RecommendationError("No eligible song candidates were found")

    system_prompt = """
    You are Tachy.

    Your only task is to select one song_id from each candidate bucket.

    Select exactly:
    - one warmup song
    - one base song
    - one challenge song

    Use only the supplied candidates.
    Never invent song IDs.

    Choose:
    - warmup: a suitable candidate below the warmup target
    - base: a suitable candidate close to the base target
    - challenge: a suitable candidate above the challenge target

    Do not explain your choices.
    Do not provide reasons.
    Do not analyze.
    Do not output commentary.
    Do not output Markdown.
    Do not output code fences.

    Return ONLY this JSON object:

    {"recommendations":[{"bucket":"warmup","song_id":"VALID_ID"},{"bucket":"base","song_id":"VALID_ID"},{"bucket":"challenge","song_id":"VALID_ID"}]}
    """.strip()

    user_payload = {
        "player": _compact_profile_for_llm(profile),
        "candidates": _compact_candidates(candidates),
    }

    url = f"{Config.OPENAI_BASE_URL.rstrip('/')}" "/chat/completions"

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": json.dumps(
                user_payload,
                ensure_ascii=False,
            ),
        },
    ]

    last_error: RecommendationError | None = None

    for attempt in range(2):
        if attempt:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Invalid output. "
                        "Return only the required JSON object "
                        "with exactly three song selections. "
                        "Do not explain anything."
                    ),
                }
            )

        response = requests.post(
            url,
            headers={
                "Authorization": (f"Bearer {Config.OPENAI_API_KEY}"),
                "Content-Type": "application/json",
            },
            json={
                "model": Config.OPENAI_MODEL,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 1024,
                "reasoning_effort": "none",
                "response_format": {"type": "text"},
            },
            timeout=Config.OPENAI_TIMEOUT,
        )

        response.raise_for_status()

        payload = response.json()
        choices = payload.get("choices") or []

        if not choices:
            last_error = RecommendationError("LLM returned no choices")
            continue

        message = choices[0].get("message") or {}

        content = message.get("content") or ""

        if not isinstance(content, str) or not content.strip():
            last_error = RecommendationError("LLM returned empty content")
            continue

        try:
            result = _extract_json_object(content)

            return _validate_llm_result(
                result,
                candidates,
            )

        except RecommendationError as exc:
            last_error = exc

    raise (last_error or RecommendationError("LLM returned an invalid recommendation"))


# Build a profile, select candidates, and return recommendations.
def recommend_for_user(
    user_id: int,
) -> dict[str, Any]:
    brief = fetch_user_brief(user_id)
    b50 = fetch_user_b50(user_id)
    r30 = fetch_user_r30(user_id)

    profile = build_player_profile(
        brief,
        b50,
        r30,
    )

    catalog = build_chart_catalog()

    candidates = build_candidates(
        profile,
        b50["data"],
        r30["data"],
        catalog,
    )

    empty = [bucket for bucket, items in candidates.items() if not items]

    if empty:
        raise RecommendationError("No candidates available for: " + ", ".join(empty))

    llm_result = ask_llm(
        profile,
        candidates,
    )

    candidate_map = {
        (
            bucket,
            item["song_id"],
        ): item
        for bucket, items in candidates.items()
        for item in items
    }

    recommendations = []

    for item in llm_result["recommendations"]:
        chart = candidate_map[
            (
                item["bucket"],
                item["song_id"],
            )
        ]

        recommendations.append(
            {
                **chart,
                "bucket": item["bucket"],
            }
        )

    return {
        "profile": profile,
        "recommendations": recommendations,
    }
