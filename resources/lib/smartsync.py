# -*- coding: utf-8 -*-

import copy
import re
from bisect import bisect_left

LOW_CONFIDENCE_THRESHOLD = 0.55
RAW_MISMATCH_MEDIAN_MS = 2200
RAW_MISMATCH_OFFSET_MS = 1500
MATCH_OK_THRESHOLD_MS = 1200
WINDOW_HALF_MS = 180000
WINDOW_STEP_MS = 120000
WINDOW_MIN_POINTS = 6
OUTLIER_OFFSET_DELTA_MS = 120000
MAX_OFFSET_SCAN_MS = 600000


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


def _nearest_value(sorted_values, value):
    if not sorted_values:
        return None

    position = bisect_left(sorted_values, value)
    candidates = []
    if position < len(sorted_values):
        candidates.append(sorted_values[position])
    if position > 0:
        candidates.append(sorted_values[position - 1])
    if not candidates:
        return None
    return min(candidates, key=lambda item: abs(item - value))


def _point_lookup(points):
    lookup = {}
    starts = []
    for point in points:
        lookup[point['id']] = point
        starts.append(point['start'])
    starts.sort()
    return lookup, starts


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


def _progress_pairs(reference_points, target_points, max_items=320):
    if not reference_points or not target_points:
        return []

    sampled_target = _sample_points(target_points, min(max_items, len(target_points)))
    if len(sampled_target) == 0:
        return []

    ref_max = len(reference_points) - 1
    tgt_max = len(target_points) - 1
    pairs = []
    for target_point in sampled_target:
        if tgt_max <= 0:
            ratio = 0.0
        else:
            ratio = float(target_point['order']) / float(tgt_max)
        ref_index = int(round(ratio * ref_max))
        if ref_index < 0:
            ref_index = 0
        if ref_index > ref_max:
            ref_index = ref_max

        reference_point = reference_points[ref_index]
        pairs.append((reference_point, target_point))
    return pairs


def _estimate_global_offset(reference_points, target_points):
    pairs = _progress_pairs(reference_points, target_points, max_items=320)
    offsets = []
    for reference_point, target_point in pairs:
        offset = float(reference_point['start'] - target_point['start'])
        if abs(offset) <= MAX_OFFSET_SCAN_MS:
            offsets.append(offset)
    if len(offsets) < 4:
        return 0.0
    return _median(offsets)


def _build_offset_knots(reference_points, target_points, global_offset):
    if not target_points:
        return [{'time': 0.0, 'offset': float(global_offset), 'count': 0}]

    start_time = target_points[0]['start']
    end_time = target_points[-1]['start']
    pair_offsets = []
    for reference_point, target_point in _progress_pairs(reference_points, target_points, max_items=len(target_points)):
        pair_offsets.append({
            'time': target_point['start'],
            'offset': float(reference_point['start'] - target_point['start']),
        })

    if len(pair_offsets) == 0:
        return [{'time': float(start_time), 'offset': float(global_offset), 'count': len(target_points)}]

    knots = []

    center = start_time
    while center <= end_time:
        offsets = []
        count = 0
        for item in pair_offsets:
            if abs(item['time'] - center) > WINDOW_HALF_MS:
                continue
            offset = item['offset']
            if abs(offset - global_offset) > OUTLIER_OFFSET_DELTA_MS:
                continue
            offsets.append(offset)
            count += 1
        if count >= WINDOW_MIN_POINTS:
            knots.append({
                'time': float(center),
                'offset': float(_median(offsets)),
                'count': count,
            })
        center += WINDOW_STEP_MS

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

    pairs = _progress_pairs(reference_points, synced_points, max_items=min(320, len(synced_points)))
    errors = []
    matched = 0
    for reference_point, synced_point in pairs:
        error = abs(int(reference_point['start'] - synced_point['start']))
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

    raw_errors = []
    for reference_point, target_point in _progress_pairs(reference_points, target_points, max_items=min(320, len(target_points))):
        raw_errors.append(abs(int(reference_point['start'] - target_point['start'])))

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

    likely_mismatch = abs(global_offset) >= RAW_MISMATCH_OFFSET_MS or raw_median >= RAW_MISMATCH_MEDIAN_MS
    return {
        'likely_mismatch': likely_mismatch,
        'raw_median_error_ms': int(round(raw_median)),
        'raw_p90_error_ms': int(round(raw_p90)),
        'estimated_global_offset_ms': int(round(global_offset)),
        'raw_coverage': round(raw_coverage, 4),
        'point_count': len(target_points),
    }


def sync_local(reference_subs, target_subs):
    reference_points = _subtitle_points(reference_subs)
    target_points = _subtitle_points(target_subs)

    global_offset = _estimate_global_offset(reference_points, target_points)
    knots = _build_offset_knots(reference_points, target_points, global_offset)
    synced_subs = _apply_knots(target_subs, knots)
    synced_points = _subtitle_points(synced_subs)
    metrics = _evaluate_alignment(reference_points, synced_points)

    metrics.update({
        'method': 'local',
        'estimated_global_offset_ms': int(round(global_offset)),
        'knots': [{'time': int(round(k['time'])), 'offset': int(round(k['offset'])), 'count': int(k['count'])} for k in knots],
        'synced_subs': synced_subs,
        'low_confidence': metrics['confidence'] < LOW_CONFIDENCE_THRESHOLD,
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
    reference_lookup, _ = _point_lookup(reference_points)
    target_lookup, _ = _point_lookup(target_points)

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
