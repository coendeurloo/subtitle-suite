# -*- coding: utf-8 -*-

import copy
import re
import time
from bisect import bisect_left

LOW_CONFIDENCE_THRESHOLD = 0.70
RAW_MISMATCH_MEDIAN_MS = 2200
RAW_MISMATCH_OFFSET_MS = 1500
MATCH_OK_THRESHOLD_MS = 1200
WINDOW_HALF_MS = 180000
WINDOW_STEP_MS = 120000
WINDOW_MIN_POINTS = 6
OUTLIER_OFFSET_DELTA_MS = 120000
MAX_OFFSET_SCAN_MS = 600000
NEAREST_PAIR_MAX_ERROR_MS = 45000
NEAREST_PAIR_STRICT_ERROR_MS = 18000
GLOBAL_SCAN_COARSE_STEP_MS = 1000
GLOBAL_SCAN_FINE_STEP_MS = 250
GLOBAL_SCAN_FINE_RANGE_MS = 2500
LOCAL_WINDOW_SCAN_STEP_MS = 250
LOCAL_WINDOW_SCAN_RANGE_MS = 30000
LOCAL_SYNC_P90_LOW_CONFIDENCE_MS = 3000
KNOT_JUMP_LOW_CONFIDENCE_MS = 45000
KNOT_SPAN_LOW_CONFIDENCE_MS = 90000
FPS_RATIO_MARGIN_THRESHOLD = 0.15
FPS_DETECTION_SAMPLE_ITEMS = 96
FPS_DETECTION_OFFSET_STEP_MS = 2000
FRAME_RATE_RATIOS = (
    ('1.0', 1.0),
    ('25/23.976', 25.0 / 23.976),
    ('23.976/25', 23.976 / 25.0),
    ('25/24', 25.0 / 24.0),
    ('24/25', 24.0 / 25.0),
    ('24/23.976', 24.0 / 23.976),
    ('23.976/24', 23.976 / 24.0),
    ('30/29.97', 30.0 / 29.97),
    ('29.97/30', 29.97 / 30.0),
)


def _as_text(value):
    if value is None:
        return u''

    try:
        if isinstance(value, bytes):
            return value.decode('utf-8', 'replace')
    except Exception:
        pass

    try:
        return u'%s' % (value)
    except Exception:
        return u''


def _normalize_text(text):
    cleaned = _as_text(text)
    cleaned = cleaned.replace('\\N', ' ')
    cleaned = re.sub(r'\{\\[^}]*\}', ' ', cleaned)
    cleaned = re.sub(r'<[^>]+>', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def _median(values):
    if not values:
        return 0.0

    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[middle])
    return (float(ordered[middle - 1]) + float(ordered[middle])) / 2.0


def _percentile(values, ratio):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * ratio))
    if index < 0:
        index = 0
    if index >= len(ordered):
        index = len(ordered) - 1
    return float(ordered[index])


def _clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def _subtitle_points(subs):
    points = []
    events = getattr(subs, 'events', [])
    for index, event in enumerate(events):
        text = _normalize_text(getattr(event, 'text', ''))
        if not text:
            continue
        start = int(max(0, getattr(event, 'start', 0)))
        end = int(max(start + 1, getattr(event, 'end', start + 1)))
        points.append({
            'id': index,
            'order': len(points),
            'start': start,
            'end': end,
            'text': text,
        })
    return points


def _point_lookup(points):
    lookup = {}
    starts = []
    index_by_start = {}
    for point in points:
        lookup[point['id']] = point
        starts.append(point['start'])
        index_by_start[point['start']] = point
    starts.sort()
    return lookup, starts, index_by_start


def _interval_overlap_score(reference_intervals, target_intervals, offset_ms):
    if not reference_intervals or not target_intervals:
        return 0.0

    i = 0
    j = 0
    score = 0.0
    reference_count = len(reference_intervals)
    target_count = len(target_intervals)
    while i < reference_count and j < target_count:
        reference_start, reference_end = reference_intervals[i]
        target_start = target_intervals[j][0] + offset_ms
        target_end = target_intervals[j][1] + offset_ms

        if target_end <= reference_start:
            j += 1
            continue
        if reference_end <= target_start:
            i += 1
            continue

        overlap = min(reference_end, target_end) - max(reference_start, target_start)
        if overlap > 0:
            score += float(overlap)

        if reference_end < target_end:
            i += 1
        else:
            j += 1

    return score


def _scan_best_global_offset(reference_points, target_points, coarse_step=None, fine_step=None, return_score=False):
    if not reference_points or not target_points:
        return (0.0, 0.0) if return_score else 0.0

    if coarse_step is None:
        coarse_step = GLOBAL_SCAN_COARSE_STEP_MS
    if fine_step is None:
        fine_step = GLOBAL_SCAN_FINE_STEP_MS

    reference_intervals = [(item['start'], item['end']) for item in reference_points]
    target_intervals = [(item['start'], item['end']) for item in target_points]

    best_offset = 0
    best_score = -1.0

    offset = -MAX_OFFSET_SCAN_MS
    while offset <= MAX_OFFSET_SCAN_MS:
        score = _interval_overlap_score(reference_intervals, target_intervals, offset)
        if score > best_score:
            best_score = score
            best_offset = offset
        offset += coarse_step

    if fine_step and fine_step > 0:
        fine_start = best_offset - GLOBAL_SCAN_FINE_RANGE_MS
        fine_end = best_offset + GLOBAL_SCAN_FINE_RANGE_MS
        offset = fine_start
        while offset <= fine_end:
            score = _interval_overlap_score(reference_intervals, target_intervals, offset)
            if score > best_score:
                best_score = score
                best_offset = offset
            offset += fine_step

    if return_score:
        return float(best_offset), float(best_score)
    return float(best_offset)


def _window_intervals(points, window_start, window_end):
    intervals = []
    for point in points:
        start = point['start']
        end = point['end']
        if end <= window_start:
            continue
        if start >= window_end:
            break
        intervals.append((start, end))
    return intervals


def _best_offset_for_window(reference_intervals, target_window_intervals, seed_offset):
    if len(reference_intervals) == 0 or len(target_window_intervals) == 0:
        return seed_offset, 0.0

    best_offset = seed_offset
    best_score = -1.0
    scan_start = int(round(seed_offset - LOCAL_WINDOW_SCAN_RANGE_MS))
    scan_end = int(round(seed_offset + LOCAL_WINDOW_SCAN_RANGE_MS))

    offset = scan_start
    while offset <= scan_end:
        score = _interval_overlap_score(reference_intervals, target_window_intervals, offset)
        if score > best_score:
            best_score = score
            best_offset = float(offset)
        offset += LOCAL_WINDOW_SCAN_STEP_MS

    return best_offset, best_score


def _sample_points(points, max_items):
    if max_items <= 1:
        if points:
            return [points[0]]
        return []

    if len(points) <= max_items:
        return points

    sampled = []
    step = float(len(points) - 1) / float(max_items - 1)
    seen = {}
    for i in range(max_items):
        index = int(round(i * step))
        if index >= len(points):
            index = len(points) - 1
        if index < 0:
            index = 0
        if index in seen:
            continue
        seen[index] = True
        sampled.append(points[index])
    return sampled


def _scale_points(points, factor):
    scaled = []
    for point in points:
        item = dict(point)
        item['start'] = int(round(float(point['start']) * factor))
        item['end'] = max(item['start'] + 1, int(round(float(point['end']) * factor)))
        scaled.append(item)
    return scaled


def _scale_subtitle_timings(subs, factor):
    scaled = copy.deepcopy(subs)
    for event in getattr(scaled, 'events', []):
        start = int(round(float(getattr(event, 'start', 0)) * factor))
        end = int(round(float(getattr(event, 'end', start + 1)) * factor))
        event.start = max(0, start)
        event.end = max(event.start + 1, end)
    return scaled


def detect_frame_rate_ratio(reference_subs, target_subs):
    """Choose a safe known frame-rate ratio using sampled interval overlap.

    ``ratio`` follows the historical conversion notation; the target timeline
    is scaled by ``1 / ratio`` before evaluating its best global offset.
    """
    reference_points = _sample_points(_subtitle_points(reference_subs), FPS_DETECTION_SAMPLE_ITEMS)
    target_points = _sample_points(_subtitle_points(target_subs), FPS_DETECTION_SAMPLE_ITEMS)
    result = {
        'ratio': 1.0,
        'name': '1.0',
        'offset_ms': 0,
        'score': 0.0,
        'runner_up_score': 0.0,
        'margin': 0.0,
        'applied': False,
    }
    if not reference_points or not target_points:
        return result

    candidates = []
    for name, ratio in FRAME_RATE_RATIOS:
        scaled_target = _scale_points(target_points, 1.0 / ratio)
        offset, score = _scan_best_global_offset(
            reference_points,
            scaled_target,
            coarse_step=FPS_DETECTION_OFFSET_STEP_MS,
            fine_step=0,
            return_score=True,
        )
        candidates.append({
            'ratio': float(ratio),
            'name': name,
            'offset_ms': int(round(offset)),
            'score': float(score),
        })

    # Prefer no correction for an exact tie, which makes doing nothing the
    # safe default for ordinary in-sync or plain-offset subtitle pairs.
    candidates.sort(key=lambda item: (-item['score'], 0 if item['ratio'] == 1.0 else 1, abs(item['ratio'] - 1.0)))
    winner = candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else {'score': 0.0}
    margin = 0.0
    if winner['score'] > 0:
        margin = (winner['score'] - runner_up['score']) / winner['score']

    result.update({
        'ratio': winner['ratio'],
        'name': winner['name'],
        'offset_ms': winner['offset_ms'],
        'score': winner['score'],
        'runner_up_score': runner_up['score'],
        'margin': round(margin, 4),
        'applied': bool(winner['ratio'] != 1.0 and margin > FPS_RATIO_MARGIN_THRESHOLD),
    })
    if not result['applied']:
        result['ratio'] = 1.0
        result['name'] = '1.0'
    return result


def _nearest_reference_point(reference_starts, reference_start_lookup, value):
    if not reference_starts:
        return None

    position = bisect_left(reference_starts, value)
    candidates = []
    if position < len(reference_starts):
        candidates.append(reference_starts[position])
    if position > 0:
        candidates.append(reference_starts[position - 1])
    if not candidates:
        return None

    nearest_start = min(candidates, key=lambda item: abs(item - value))
    return reference_start_lookup.get(nearest_start)


def _collect_nearest_offsets(reference_points, target_points, hint_offset=0.0, max_error_ms=NEAREST_PAIR_MAX_ERROR_MS, max_items=360):
    _, reference_starts, reference_start_lookup = _point_lookup(reference_points)
    if not reference_starts or not target_points:
        return []

    sampled_target = _sample_points(target_points, min(max_items, len(target_points)))
    offsets = []
    for target_point in sampled_target:
        shifted_time = target_point['start'] + hint_offset
        reference_point = _nearest_reference_point(reference_starts, reference_start_lookup, shifted_time)
        if reference_point is None:
            continue
        nearest_error = abs(reference_point['start'] - shifted_time)
        if nearest_error > max_error_ms:
            continue
        offsets.append({
            'time': float(target_point['start']),
            'offset': float(reference_point['start'] - target_point['start']),
            'error': float(nearest_error),
        })
    return offsets


def _estimate_global_offset(reference_points, target_points):
    overlap_offset = _scan_best_global_offset(reference_points, target_points)
    baseline = _collect_nearest_offsets(
        reference_points,
        target_points,
        hint_offset=0.0,
        max_error_ms=NEAREST_PAIR_STRICT_ERROR_MS,
        max_items=420
    )
    baseline_offset = 0.0
    if len(baseline) >= 6:
        baseline_offset = _median([item['offset'] for item in baseline])

    candidate_offsets = []
    seen_candidate_keys = {}
    for item in [overlap_offset, baseline_offset, 0.0]:
        key = int(round(item))
        if key in seen_candidate_keys:
            continue
        seen_candidate_keys[key] = True
        candidate_offsets.append(float(item))

    best_candidate_offset = candidate_offsets[0]
    best_candidate_score = (99999999.0, 99999999.0, -1)
    for candidate_offset in candidate_offsets:
        sampled = _collect_nearest_offsets(
            reference_points,
            target_points,
            hint_offset=candidate_offset,
            max_error_ms=NEAREST_PAIR_STRICT_ERROR_MS,
            max_items=420
        )
        if len(sampled) == 0:
            continue
        sampled_errors = [item['error'] for item in sampled]
        candidate_score = (_median(sampled_errors), _percentile(sampled_errors, 0.9), -len(sampled))
        if candidate_score < best_candidate_score:
            best_candidate_score = candidate_score
            best_candidate_offset = _median([item['offset'] for item in sampled])

    coarse = _collect_nearest_offsets(
        reference_points,
        target_points,
        hint_offset=best_candidate_offset,
        max_error_ms=NEAREST_PAIR_MAX_ERROR_MS,
        max_items=420
    )
    if len(coarse) < 6:
        return overlap_offset

    coarse_median = _median([item['offset'] for item in coarse if abs(item['offset']) <= MAX_OFFSET_SCAN_MS])
    refined = _collect_nearest_offsets(
        reference_points,
        target_points,
        hint_offset=coarse_median,
        max_error_ms=NEAREST_PAIR_STRICT_ERROR_MS,
        max_items=420
    )
    if len(refined) < 6:
        return coarse_median

    refined_offsets = [item['offset'] for item in refined if abs(item['offset']) <= MAX_OFFSET_SCAN_MS]
    if len(refined_offsets) < 4:
        return coarse_median
    return _median(refined_offsets)


def _estimate_opening_index_offset(reference_points, target_points, max_items=180, trim_ms=8000, min_samples=60):
    sample_count = min(max_items, len(reference_points), len(target_points))
    if sample_count < min_samples:
        return None

    offsets = []
    for index in range(sample_count):
        offsets.append(float(reference_points[index]['start'] - target_points[index]['start']))

    center = _median(offsets)
    kept = [offset for offset in offsets if abs(offset - center) <= trim_ms]
    if len(kept) < min_samples:
        return None

    opening_offset = _median(kept)
    spread = _median([abs(offset - opening_offset) for offset in kept])
    return {
        'offset': float(opening_offset),
        'spread': float(spread),
        'count': len(kept),
    }


def _build_offset_knots(reference_points, target_points, global_offset):
    if not target_points:
        return [{'time': 0.0, 'offset': float(global_offset), 'count': 0}]

    start_time = target_points[0]['start']
    end_time = target_points[-1]['start']
    reference_intervals = [(item['start'], item['end']) for item in reference_points]
    if len(reference_intervals) == 0:
        return [{'time': float(start_time), 'offset': float(global_offset), 'count': len(target_points)}]

    knots = []

    center = start_time
    previous_offset = float(global_offset)
    while center <= end_time:
        target_window_intervals = _window_intervals(target_points, center - WINDOW_HALF_MS, center + WINDOW_HALF_MS)
        count = len(target_window_intervals)
        if count >= WINDOW_MIN_POINTS:
            best_offset, best_score = _best_offset_for_window(reference_intervals, target_window_intervals, previous_offset)
            if best_score > 0:
                if abs(best_offset - global_offset) > OUTLIER_OFFSET_DELTA_MS:
                    best_offset = float(global_offset)
                previous_offset = best_offset
                knots.append({
                    'time': float(center),
                    'offset': float(best_offset),
                    'count': count,
                })
        center += WINDOW_STEP_MS

    if not knots:
        # Fallback to nearest-pair smoothing when window overlap scanning cannot produce any usable knot.
        pair_offsets = _collect_nearest_offsets(
            reference_points,
            target_points,
            hint_offset=global_offset,
            max_error_ms=NEAREST_PAIR_MAX_ERROR_MS,
            max_items=len(target_points)
        )
        for item in pair_offsets:
            knots.append({
                'time': float(item['time']),
                'offset': float(item['offset']),
                'count': 1,
            })

    if not knots:
        return [{'time': float(start_time), 'offset': float(global_offset), 'count': len(target_points)}]

    if knots[0]['time'] > start_time:
        knots.insert(0, {'time': float(start_time), 'offset': knots[0]['offset'], 'count': knots[0]['count']})
    if knots[-1]['time'] < end_time:
        knots.append({'time': float(end_time), 'offset': knots[-1]['offset'], 'count': knots[-1]['count']})

    return knots


def _offset_at_time(knots, timestamp):
    if not knots:
        return 0.0

    if timestamp <= knots[0]['time']:
        return knots[0]['offset']
    if timestamp >= knots[-1]['time']:
        return knots[-1]['offset']

    for index in range(1, len(knots)):
        left = knots[index - 1]
        right = knots[index]
        if timestamp <= right['time']:
            span = right['time'] - left['time']
            if span <= 0:
                return right['offset']
            ratio = (timestamp - left['time']) / float(span)
            return left['offset'] + (right['offset'] - left['offset']) * ratio
    return knots[-1]['offset']


def _apply_knots(target_subs, knots):
    synced = copy.deepcopy(target_subs)
    previous_start = -1
    for event in getattr(synced, 'events', []):
        start = int(getattr(event, 'start', 0))
        end = int(getattr(event, 'end', start + 1))
        offset_start = _offset_at_time(knots, start)
        offset_end = _offset_at_time(knots, end)

        new_start = int(round(start + offset_start))
        new_end = int(round(end + offset_end))
        duration = max(80, end - start)

        if new_start < 0:
            new_start = 0
        if previous_start >= 0 and new_start < previous_start:
            new_start = previous_start

        if new_end <= new_start:
            new_end = new_start + duration
        if new_end - new_start < 80:
            new_end = new_start + 80

        event.start = new_start
        event.end = new_end
        previous_start = new_start
    return synced


def _knot_instability(knots):
    offsets = [float(item.get('offset', 0.0)) for item in knots or []]
    if len(offsets) < 2:
        return {
            'unstable': False,
            'max_jump_ms': 0,
            'span_ms': int(round(abs(offsets[0]))) if offsets else 0,
        }

    jumps = [abs(offsets[index] - offsets[index - 1]) for index in range(1, len(offsets))]
    max_jump = max(jumps) if jumps else 0.0
    span = max(offsets) - min(offsets)
    return {
        'unstable': max_jump >= KNOT_JUMP_LOW_CONFIDENCE_MS or span >= KNOT_SPAN_LOW_CONFIDENCE_MS,
        'max_jump_ms': int(round(max_jump)),
        'span_ms': int(round(span)),
    }


def _evaluate_alignment(reference_points, synced_points):
    if not reference_points or not synced_points:
        return {
            'median_error_ms': 999999,
            'p90_error_ms': 999999,
            'match_ratio': 0.0,
            'confidence': 0.0,
            'matched_points': 0,
            'total_points': len(synced_points),
        }

    errors = []
    matched = 0
    for item in _collect_nearest_offsets(
        reference_points,
        synced_points,
        hint_offset=0.0,
        max_error_ms=MAX_OFFSET_SCAN_MS,
        max_items=min(360, len(synced_points))
    ):
        error = abs(int(item['offset']))
        errors.append(error)
        if error <= MATCH_OK_THRESHOLD_MS:
            matched += 1

    if not errors:
        return {
            'median_error_ms': 999999,
            'p90_error_ms': 999999,
            'match_ratio': 0.0,
            'confidence': 0.0,
            'matched_points': 0,
            'total_points': len(synced_points),
        }

    median_error = _median(errors)
    p90_error = _percentile(errors, 0.9)
    match_ratio = float(matched) / float(len(errors))

    confidence = (
        0.5 * match_ratio +
        0.3 * (1.0 - _clamp(median_error / 3000.0, 0.0, 1.0)) +
        0.2 * (1.0 - _clamp(p90_error / 5000.0, 0.0, 1.0))
    )
    confidence = _clamp(confidence, 0.0, 1.0)

    return {
        'median_error_ms': int(round(median_error)),
        'p90_error_ms': int(round(p90_error)),
        'match_ratio': round(match_ratio, 4),
        'confidence': round(confidence, 4),
        'matched_points': matched,
        'total_points': len(errors),
    }


def assess_pair(reference_subs, target_subs):
    reference_points = _subtitle_points(reference_subs)
    target_points = _subtitle_points(target_subs)

    if not reference_points or not target_points:
        return {
            'likely_mismatch': False,
            'raw_median_error_ms': 0,
            'raw_p90_error_ms': 0,
            'estimated_global_offset_ms': 0,
            'raw_coverage': 0.0,
            'point_count': len(target_points),
        }

    raw_pairs = _collect_nearest_offsets(
        reference_points,
        target_points,
        hint_offset=0.0,
        max_error_ms=MAX_OFFSET_SCAN_MS,
        max_items=min(380, len(target_points))
    )
    raw_errors = [abs(int(item['offset'])) for item in raw_pairs]

    if not raw_errors:
        return {
            'likely_mismatch': False,
            'raw_median_error_ms': 0,
            'raw_p90_error_ms': 0,
            'estimated_global_offset_ms': 0,
            'raw_coverage': 0.0,
            'point_count': len(target_points),
        }

    global_offset = _estimate_global_offset(reference_points, target_points)
    raw_median = _median(raw_errors)
    raw_p90 = _percentile(raw_errors, 0.9)
    raw_coverage = float(sum(1 for err in raw_errors if err <= MATCH_OK_THRESHOLD_MS)) / float(len(raw_errors))
    reference_intervals = [(item['start'], item['end']) for item in reference_points]
    target_intervals = [(item['start'], item['end']) for item in target_points]
    overlap_zero = _interval_overlap_score(reference_intervals, target_intervals, 0)
    overlap_shifted = _interval_overlap_score(reference_intervals, target_intervals, int(round(global_offset)))
    if overlap_zero <= 0:
        overlap_improvement = 1.0 if overlap_shifted > 0 else 0.0
    else:
        overlap_improvement = (float(overlap_shifted) - float(overlap_zero)) / float(overlap_zero)

    likely_mismatch = (
        raw_median >= RAW_MISMATCH_MEDIAN_MS or
        (
            raw_p90 >= LOCAL_SYNC_P90_LOW_CONFIDENCE_MS and
            raw_coverage <= 0.65
        ) or
        (
            abs(global_offset) >= RAW_MISMATCH_OFFSET_MS and
            overlap_improvement >= 0.18 and
            raw_coverage <= 0.75
        )
    )
    return {
        'likely_mismatch': likely_mismatch,
        'raw_median_error_ms': int(round(raw_median)),
        'raw_p90_error_ms': int(round(raw_p90)),
        'estimated_global_offset_ms': int(round(global_offset)),
        'raw_coverage': round(raw_coverage, 4),
        'overlap_improvement': round(overlap_improvement, 4),
        'point_count': len(target_points),
    }


def sync_local(reference_subs, target_subs, enable_frame_rate_correction=True):
    detection_started_at = time.monotonic()
    if enable_frame_rate_correction:
        fps_detection = detect_frame_rate_ratio(reference_subs, target_subs)
    else:
        fps_detection = {
            'ratio': 1.0, 'name': '1.0', 'offset_ms': 0, 'score': 0.0,
            'runner_up_score': 0.0, 'margin': 0.0, 'applied': False,
        }
    fps_detection_ms = int(round((time.monotonic() - detection_started_at) * 1000.0))
    working_target_subs = target_subs
    if fps_detection['applied']:
        working_target_subs = _scale_subtitle_timings(target_subs, 1.0 / fps_detection['ratio'])

    reference_points = _subtitle_points(reference_subs)
    target_points = _subtitle_points(working_target_subs)

    global_offset = _estimate_global_offset(reference_points, target_points)
    opening_offset = _estimate_opening_index_offset(reference_points, target_points)
    if opening_offset is not None:
        # Prefer stable opening alignment when global overlap scan drifts to another section.
        if abs(global_offset - opening_offset['offset']) > 90000 and opening_offset['spread'] <= 3000:
            global_offset = opening_offset['offset']

    knots = _build_offset_knots(reference_points, target_points, global_offset)
    synced_subs = _apply_knots(working_target_subs, knots)
    synced_points = _subtitle_points(synced_subs)
    metrics = _evaluate_alignment(reference_points, synced_points)
    knot_quality = _knot_instability(knots)
    low_confidence = (
        metrics['confidence'] < LOW_CONFIDENCE_THRESHOLD or
        metrics['p90_error_ms'] >= LOCAL_SYNC_P90_LOW_CONFIDENCE_MS or
        knot_quality['unstable']
    )

    metrics.update({
        'method': 'local',
        'estimated_global_offset_ms': int(round(global_offset)),
        'knots': [{'time': int(round(k['time'])), 'offset': int(round(k['offset'])), 'count': int(k['count'])} for k in knots],
        'knot_max_jump_ms': knot_quality['max_jump_ms'],
        'knot_span_ms': knot_quality['span_ms'],
        'fps_ratio': fps_detection['ratio'],
        'fps_ratio_name': fps_detection['name'],
        'fps_margin': fps_detection['margin'],
        'fps_applied': fps_detection['applied'],
        'fps_detection_ms': fps_detection_ms,
        'synced_subs': synced_subs,
        'low_confidence': low_confidence,
    })
    return metrics


def build_ai_samples(subs, max_items=70):
    points = _subtitle_points(subs)
    sampled = _sample_points(points, max_items)
    payload = []
    for point in sampled:
        payload.append({
            'id': int(point['id']),
            'start_ms': int(point['start']),
            'text': point['text'][:140],
        })
    return payload


def sync_from_anchor_pairs(reference_subs, target_subs, anchor_pairs):
    reference_points = _subtitle_points(reference_subs)
    target_points = _subtitle_points(target_subs)
    reference_lookup, _, _ = _point_lookup(reference_points)
    target_lookup, _, _ = _point_lookup(target_points)

    anchor_knots = []
    for pair in anchor_pairs:
        try:
            reference_id = int(pair.get('reference_id'))
            target_id = int(pair.get('target_id'))
        except Exception:
            continue

        reference_point = reference_lookup.get(reference_id)
        target_point = target_lookup.get(target_id)
        if reference_point is None or target_point is None:
            continue

        anchor_knots.append({
            'time': float(target_point['start']),
            'offset': float(reference_point['start'] - target_point['start']),
            'count': 1,
        })

    if not anchor_knots:
        raise RuntimeError('No valid anchor pairs returned.')

    anchor_knots.sort(key=lambda knot: knot['time'])

    deduped = []
    for knot in anchor_knots:
        if not deduped or int(deduped[-1]['time']) != int(knot['time']):
            deduped.append(knot)
        else:
            merged_offset = _median([deduped[-1]['offset'], knot['offset']])
            deduped[-1]['offset'] = merged_offset
            deduped[-1]['count'] += 1

    if len(deduped) == 1:
        deduped.append({
            'time': deduped[0]['time'] + WINDOW_STEP_MS,
            'offset': deduped[0]['offset'],
            'count': deduped[0]['count'],
        })

    synced_subs = _apply_knots(target_subs, deduped)
    synced_points = _subtitle_points(synced_subs)
    metrics = _evaluate_alignment(reference_points, synced_points)
    metrics.update({
        'method': 'ai_anchor',
        'estimated_global_offset_ms': int(round(_median([k['offset'] for k in deduped]))),
        'knots': [{'time': int(round(k['time'])), 'offset': int(round(k['offset'])), 'count': int(k['count'])} for k in deduped],
        'synced_subs': synced_subs,
        'low_confidence': metrics['confidence'] < LOW_CONFIDENCE_THRESHOLD,
    })
    return metrics
