# -*- coding: utf-8 -*-

import copy
import re
import time
from bisect import bisect_left
from .background_jobs import JobCancelled


def _report_progress(callback, stage, completed=0, total=1, cancel_event=None):
    if cancel_event is not None and cancel_event.is_set():
        raise JobCancelled()
    if callback is not None:
        callback(stage, completed, total)


def _scan_progress(callback, completed, total, cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise JobCancelled()
    if callback is not None:
        callback(completed, total)

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
FPS_RATIO_MARGIN_THRESHOLD = 0.06
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


def _scan_best_global_offset(reference_points, target_points, coarse_step=None, fine_step=None, return_score=False, progress_callback=None, cancel_event=None):
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
    total = (2 * MAX_OFFSET_SCAN_MS) // coarse_step + 1
    if fine_step and fine_step > 0:
        total += (2 * GLOBAL_SCAN_FINE_RANGE_MS) // fine_step + 1
    completed = 0
    _scan_progress(progress_callback, 0, total, cancel_event)

    offset = -MAX_OFFSET_SCAN_MS
    while offset <= MAX_OFFSET_SCAN_MS:
        if completed % 16 == 0:
            _scan_progress(progress_callback, completed, total, cancel_event)
        score = _interval_overlap_score(reference_intervals, target_intervals, offset)
        if score > best_score:
            best_score = score
            best_offset = offset
        offset += coarse_step
        completed += 1

    if fine_step and fine_step > 0:
        fine_start = best_offset - GLOBAL_SCAN_FINE_RANGE_MS
        fine_end = best_offset + GLOBAL_SCAN_FINE_RANGE_MS
        offset = fine_start
        while offset <= fine_end:
            if completed % 16 == 0:
                _scan_progress(progress_callback, completed, total, cancel_event)
            score = _interval_overlap_score(reference_intervals, target_intervals, offset)
            if score > best_score:
                best_score = score
                best_offset = offset
            offset += fine_step
            completed += 1

    _scan_progress(progress_callback, total, total, cancel_event)

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


def _best_offset_for_window(reference_intervals, target_window_intervals, seed_offset, progress_callback=None, cancel_event=None):
    if len(reference_intervals) == 0 or len(target_window_intervals) == 0:
        return seed_offset, 0.0

    best_offset = seed_offset
    best_score = -1.0
    scan_start = int(round(seed_offset - LOCAL_WINDOW_SCAN_RANGE_MS))
    scan_end = int(round(seed_offset + LOCAL_WINDOW_SCAN_RANGE_MS))
    total = (scan_end - scan_start) // LOCAL_WINDOW_SCAN_STEP_MS + 1
    completed = 0

    offset = scan_start
    while offset <= scan_end:
        if completed % 16 == 0:
            _scan_progress(progress_callback, completed, total, cancel_event)
        score = _interval_overlap_score(reference_intervals, target_window_intervals, offset)
        if score > best_score:
            best_score = score
            best_offset = float(offset)
        offset += LOCAL_WINDOW_SCAN_STEP_MS
        completed += 1

    _scan_progress(progress_callback, total, total, cancel_event)

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


def detect_frame_rate_ratio(reference_subs, target_subs, progress_callback=None, cancel_event=None,
                            unchanged_alignment=None):
    """Compare known frame-rate ratios on the full dialogue timelines.

    ``ratio`` follows the historical conversion notation; the target timeline
    is scaled by ``1 / ratio`` before evaluating its best global offset.
    """
    reference_points = _subtitle_points(reference_subs)
    target_points = _subtitle_points(target_subs)
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
    for index, (name, ratio) in enumerate(FRAME_RATE_RATIOS):
        def ratio_progress(done, total):
            _report_progress(progress_callback, 'speed', index + float(done) / total,
                             len(FRAME_RATE_RATIOS), cancel_event)
        if ratio == 1.0 and unchanged_alignment is not None:
            offset, score = unchanged_alignment
            scaled_target = target_points
        else:
            scaled_target = _scale_points(target_points, 1.0 / ratio)
            offset, score = _scan_best_global_offset(
                reference_points,
                scaled_target,
                coarse_step=FPS_DETECTION_OFFSET_STEP_MS,
                fine_step=GLOBAL_SCAN_FINE_STEP_MS,
                return_score=True,
                progress_callback=ratio_progress,
                cancel_event=cancel_event,
            )
        candidates.append({
            'ratio': float(ratio),
            'name': name,
            'offset_ms': int(round(offset)),
            'score': score / sum(point['end'] - point['start'] for point in scaled_target),
        })

    # Prefer no correction for an exact tie, which makes doing nothing the
    # safe default for ordinary in-sync or plain-offset subtitle pairs.
    candidates.sort(key=lambda item: (-item['score'], 0 if item['ratio'] == 1.0 else 1, abs(item['ratio'] - 1.0)))
    winner = candidates[0]
    runner_up = candidates[1]
    unchanged = next(item for item in candidates if item['ratio'] == 1.0)
    margin = 0.0
    if winner['score'] > 0:
        # PAL conversions for 24 and 23.976 are close enough that both can
        # score well. Measure the benefit against leaving the speed unchanged.
        margin = (winner['score'] - unchanged['score']) / winner['score']

    scaled_winner = _scale_points(target_points, 1.0 / winner['ratio'])

    result.update({
        'ratio': winner['ratio'],
        'name': winner['name'],
        'offset_ms': winner['offset_ms'],
        'score': winner['score'],
        'runner_up_score': runner_up['score'],
        'margin': round(margin, 4),
        'applied': (winner['ratio'] != 1.0 and margin > FPS_RATIO_MARGIN_THRESHOLD and
                    _stable_timeline(reference_points, scaled_winner, winner['offset_ms'], min_overlap=0.60)),
    })
    if not result['applied']:
        result['ratio'] = 1.0
        result['name'] = '1.0'
        result['offset_ms'] = unchanged['offset_ms']
    return result


def _stable_timeline(reference_points, target_points, offset, min_overlap=0.80, progress_callback=None):
    """Require dialogue overlap throughout the shared timeline."""
    if not reference_points:
        return False
    reference_intervals = [(point['start'], point['end']) for point in reference_points]
    first_reference_start = reference_points[0]['start']
    intervals = [(point['start'], point['end']) for point in target_points
                 if point['end'] + offset > first_reference_start]
    if len(intervals) < 36 or intervals[-1][0] - intervals[0][0] < 120000:
        return False
    for index in range(3):
        if progress_callback:
            progress_callback(index, 3)
        section = intervals[index * len(intervals) // 3:(index + 1) * len(intervals) // 3]
        duration = sum(end - start for start, end in section)
        if _interval_overlap_score(reference_intervals, section, offset) < min_overlap * duration:
            return False
    return True


def _opening_cues_before_reference(reference_points, target_points, offset):
    # Only remove a short, clearly displaced prefix. Cues crossing the first
    # reference cue can contain real dialogue and should be retained.
    if offset > -2500 or not reference_points or not target_points:
        return set()
    if target_points[0]['end'] + offset > 0:
        return set()
    first_reference_start = reference_points[0]['start']
    removed = set()
    for point in target_points:
        if (point['end'] + offset > first_reference_start or
                point['end'] - target_points[0]['start'] > 120000):
            break
        removed.add(point['id'])
    return removed if len(removed) >= 2 else set()


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


def _estimate_global_offset(reference_points, target_points, progress_callback=None, cancel_event=None):
    overlap_offset = _scan_best_global_offset(reference_points, target_points,
                                            progress_callback=progress_callback, cancel_event=cancel_event)
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


def _build_offset_knots(reference_points, target_points, global_offset, progress_callback=None, cancel_event=None):
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
    total_windows = (end_time - start_time) // WINDOW_STEP_MS + 1
    window_index = 0
    while center <= end_time:
        _report_progress(progress_callback, 'sections', window_index, total_windows, cancel_event)
        target_window_intervals = _window_intervals(target_points, center - WINDOW_HALF_MS, center + WINDOW_HALF_MS)
        count = len(target_window_intervals)
        if count >= WINDOW_MIN_POINTS:
            def window_progress(done, total):
                _report_progress(progress_callback, 'sections', window_index + float(done) / total,
                                 total_windows, cancel_event)
            best_offset, best_score = _best_offset_for_window(
                reference_intervals, target_window_intervals, previous_offset,
                progress_callback=window_progress, cancel_event=cancel_event)
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
        window_index += 1
    _report_progress(progress_callback, 'sections', total_windows, total_windows, cancel_event)

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
            if right.get('step'):
                return right['offset'] if timestamp == right['time'] else left['offset']
            span = right['time'] - left['time']
            if span <= 0:
                return right['offset']
            ratio = (timestamp - left['time']) / float(span)
            return left['offset'] + (right['offset'] - left['offset']) * ratio
    return knots[-1]['offset']


def _apply_knots(target_subs, knots, progress_callback=None, cancel_event=None, stage='adjust'):
    _report_progress(progress_callback, stage, 0, max(1, len(getattr(target_subs, 'events', []))), cancel_event)
    synced = copy.deepcopy(target_subs)
    previous_start = -1
    events = getattr(synced, 'events', [])
    for index, event in enumerate(events):
        if index % 64 == 0:
            _report_progress(progress_callback, stage, index, len(events), cancel_event)
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
    _report_progress(progress_callback, stage, len(events), len(events), cancel_event)
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


def _section_alignment(reference_points, target_points):
    """Measure ordered cue matches and dialogue overlap across the whole file."""
    starts = sorted(point['start'] for point in reference_points)
    intervals = sorted((point['start'], point['end']) for point in reference_points)
    target = sorted(target_points, key=lambda point: point['start'])
    if not starts or not target:
        return {'verified': False, 'score': 0.0, 'preview_ms': 0}
    reference_span = max(1, starts[-1] - starts[0])
    sections = 3 if len(target) >= 24 else 1
    scores = []
    next_reference = 0
    for index in range(sections):
        section = target[index * len(target) // sections:(index + 1) * len(target) // sections]
        matches = 0
        for point in section:
            start = point['start']
            candidate = bisect_left(starts, start - MATCH_OK_THRESHOLD_MS, lo=next_reference)
            if candidate < len(starts) and starts[candidate] <= start + MATCH_OK_THRESHOLD_MS:
                matches += 1
                next_reference = candidate + 1
        target_intervals = [(point['start'], point['end']) for point in section]
        duration = sum(end - start for start, end in target_intervals)
        overlap = _interval_overlap_score(intervals, target_intervals, 0) / max(1, duration)
        score = min(overlap, matches / len(section))
        scores.append((score, section[len(section) // 2]['start']))
    score, preview_ms = min(scores)
    shared_span = min(starts[-1], target[-1]['start']) - max(starts[0], target[0]['start'])
    return {
        'verified': len(target) >= 8 and score >= 0.72 and shared_span >= 0.75 * reference_span,
        'score': score,
        'preview_ms': preview_ms,
    }


def _find_cut_knots(reference_points, target_points, seed, progress_callback, cancel_event):
    """Use a step only when a single cut gives strong matches on both sides."""
    if len(target_points) < 36:
        return None
    reference = [(point['start'], point['end']) for point in reference_points]
    target = [(point['start'], point['end']) for point in target_points]
    third = len(target) // 3
    left, _ = _best_offset_for_window(reference, target[:third], seed, cancel_event=cancel_event)
    right, _ = _best_offset_for_window(reference, target[-third:], seed, cancel_event=cancel_event)
    if abs(left - right) < 2000:
        return None

    # Build cumulative overlap once per offset to score every candidate gap.
    prefixes = []
    starts = [start for start, _ in reference]
    longest_cue = max((end - start for start, end in reference), default=0)
    for offset in (left, right):
        cumulative = [0.0]
        for start, end in target:
            first = bisect_left(starts, start + offset - longest_cue)
            last = bisect_left(starts, end + offset)
            overlap = _interval_overlap_score(reference[first:last], [(start, end)], offset)
            cumulative.append(cumulative[-1] + overlap)
        prefixes.append(cumulative)
    duration = [0]
    for start, end in target:
        duration.append(duration[-1] + end - start)
    baseline = max(prefixes[0][-1], prefixes[1][-1], _interval_overlap_score(reference, target, seed))
    best = None
    best_score = baseline + 0.08 * duration[-1]
    for index in range(third // 2, len(target) - third // 2):
        _report_progress(progress_callback, 'sections', index, len(target), cancel_event)
        previous_end, next_start = target[index - 1][1], target[index][0]
        if previous_end >= next_start or previous_end + left >= next_start + right:
            continue
        before = prefixes[0][index]
        after = prefixes[1][-1] - prefixes[1][index]
        if (before + after > best_score and before >= 0.80 * duration[index] and
                after >= 0.80 * (duration[-1] - duration[index])):
            best = next_start
            best_score = before + after
    if best is None:
        return None
    return [{'time': target[0][0], 'offset': left, 'count': len(target)},
            {'time': best, 'offset': right, 'count': len(target), 'step': True}]


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


def sync_local(reference_subs, target_subs, enable_frame_rate_correction=True, progress_callback=None, cancel_event=None,
               prefer_simple_alignment=False):
    reference_points = _subtitle_points(reference_subs)
    raw_points = _subtitle_points(target_subs)
    raw_sections = _section_alignment(reference_points, raw_points)
    _report_progress(progress_callback, 'speed', 0, len(FRAME_RATE_RATIOS), cancel_event)
    detection_started_at = time.monotonic()
    initial_offset = None
    unchanged_alignment = None
    simple_alignment = False
    if prefer_simple_alignment and reference_points and raw_points:
        if (raw_sections['verified'] and raw_sections['score'] >= 0.78 and
                _evaluate_alignment(reference_points, raw_points)['p90_error_ms'] <= 180):
            initial_offset = 0
            simple_alignment = True
        elif enable_frame_rate_correction:
            def simple_progress(done, total):
                _report_progress(progress_callback, 'speed', float(done) / total, len(FRAME_RATE_RATIOS), cancel_event)
            unchanged_alignment = _scan_best_global_offset(
                reference_points, raw_points, fine_step=50, return_score=True,
                progress_callback=simple_progress, cancel_event=cancel_event
            )
            initial_offset = unchanged_alignment[0]
            opening = _opening_cues_before_reference(reference_points, raw_points, initial_offset)
            shifted = [dict(point, start=point['start'] + initial_offset, end=point['end'] + initial_offset)
                       for point in raw_points if point['id'] not in opening]
            shifted_sections = _section_alignment(reference_points, shifted)
            simple_alignment = (shifted_sections['verified'] and shifted_sections['score'] >= 0.85 and
                                _evaluate_alignment(reference_points, shifted)['p90_error_ms'] <= 250)
    if enable_frame_rate_correction and not simple_alignment:
        fps_detection = detect_frame_rate_ratio(
            reference_subs, target_subs, progress_callback, cancel_event, unchanged_alignment=unchanged_alignment
        )
    else:
        fps_detection = {
            'ratio': 1.0, 'name': '1.0', 'offset_ms': 0, 'score': 0.0,
            'runner_up_score': 0.0, 'margin': 0.0, 'applied': False,
        }
    fps_detection_ms = int(round((time.monotonic() - detection_started_at) * 1000.0))
    working_target_subs = target_subs
    if fps_detection['applied']:
        working_target_subs = _scale_subtitle_timings(target_subs, 1.0 / fps_detection['ratio'])

    target_points = _subtitle_points(working_target_subs) if fps_detection['applied'] else raw_points

    _report_progress(progress_callback, 'shift', 0, 1, cancel_event)
    def shift_progress(done, total):
        _report_progress(progress_callback, 'shift', done, total, cancel_event)
    if initial_offset is not None and not fps_detection['applied']:
        global_offset = initial_offset
        shift_progress(1, 1)
    else:
        global_offset = _scan_best_global_offset(reference_points, target_points, fine_step=50,
                                                progress_callback=shift_progress, cancel_event=cancel_event)
    def section_progress(done, total):
        _report_progress(progress_callback, 'sections', done, total, cancel_event)
    stable = simple_alignment or _stable_timeline(reference_points, target_points, global_offset,
                              progress_callback=section_progress)
    removed_cues = set()
    if stable:
        # Section searches can jump to unrelated dialogue in dense scenes.
        # Keep a single offset when it fits the full episode.
        knots = [{'time': 0, 'offset': global_offset, 'count': len(target_points)}]
        removed_cues = _opening_cues_before_reference(reference_points, target_points, global_offset)
        section_progress(3, 3)
    else:
        knots = _find_cut_knots(reference_points, target_points, global_offset, progress_callback, cancel_event)
        if knots is None:
            knots = _build_offset_knots(reference_points, target_points, global_offset, progress_callback, cancel_event)
    synced_subs = _apply_knots(working_target_subs, knots, progress_callback, cancel_event)
    if removed_cues:
        synced_subs.events = [event for index, event in enumerate(synced_subs.events)
                              if index not in removed_cues]
    _report_progress(progress_callback, 'check', 0, 1, cancel_event)
    synced_points = _subtitle_points(synced_subs)
    metrics = _evaluate_alignment(reference_points, synced_points)
    reference_dialogue = {point['text'] for point in reference_points if len(point['text']) >= 20}
    target_dialogue = {point['text'] for point in raw_points if len(point['text']) >= 20}
    knot_quality = _knot_instability(knots)
    _report_progress(progress_callback, 'check', 1, 1, cancel_event)
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
        'simple_alignment': simple_alignment,
        'trimmed_opening_cues': len(removed_cues),
        'edit_cut_ms': next((int(k['time']) for k in knots if k.get('step')), None),
        'same_dialogue': len(target_dialogue) >= 20 and len(reference_dialogue & target_dialogue) >= 0.65 * len(target_dialogue),
        'raw_sections': raw_sections,
        'synced_sections': _section_alignment(reference_points, synced_points),
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


def sync_from_anchor_pairs(reference_subs, target_subs, anchor_pairs, progress_callback=None, cancel_event=None):
    _report_progress(progress_callback, 'ai_adjust', 0, 1, cancel_event)
    reference_points = _subtitle_points(reference_subs)
    target_points = _subtitle_points(target_subs)
    reference_lookup, _, _ = _point_lookup(reference_points)
    target_lookup, _, _ = _point_lookup(target_points)

    anchor_knots = []
    used_reference_ids = set()
    used_target_ids = set()
    previous_reference_start = None
    previous_target_start = None
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

        if reference_id in used_reference_ids or target_id in used_target_ids:
            raise RuntimeError('AI alignment reused a subtitle cue.')
        if (previous_reference_start is not None and
                (reference_point['start'] <= previous_reference_start or
                 target_point['start'] <= previous_target_start)):
            raise RuntimeError('AI alignment anchors are out of timeline order.')
        used_reference_ids.add(reference_id)
        used_target_ids.add(target_id)
        previous_reference_start = reference_point['start']
        previous_target_start = target_point['start']

        anchor_knots.append({
            'time': float(target_point['start']),
            'offset': float(reference_point['start'] - target_point['start']),
            'count': 1,
        })

    if len(anchor_knots) < 3:
        raise RuntimeError('AI alignment needs at least three valid anchor pairs.')

    anchor_knots.sort(key=lambda knot: knot['time'])

    deduped = []
    for knot in anchor_knots:
        if not deduped or int(deduped[-1]['time']) != int(knot['time']):
            deduped.append(knot)
        else:
            merged_offset = _median([deduped[-1]['offset'], knot['offset']])
            deduped[-1]['offset'] = merged_offset
            deduped[-1]['count'] += 1

    synced_subs = _apply_knots(target_subs, deduped, progress_callback, cancel_event, stage='ai_adjust')
    _report_progress(progress_callback, 'ai_check', 0, 1, cancel_event)
    synced_points = _subtitle_points(synced_subs)
    metrics = _evaluate_alignment(reference_points, synced_points)
    knot_quality = _knot_instability(deduped)
    _report_progress(progress_callback, 'ai_check', 1, 1, cancel_event)
    metrics.update({
        'method': 'ai_anchor',
        'estimated_global_offset_ms': int(round(_median([k['offset'] for k in deduped]))),
        'knots': [{'time': int(round(k['time'])), 'offset': int(round(k['offset'])), 'count': int(k['count'])} for k in deduped],
        'knot_max_jump_ms': knot_quality['max_jump_ms'],
        'knot_span_ms': knot_quality['span_ms'],
        'synced_subs': synced_subs,
        'low_confidence': (metrics['confidence'] < LOW_CONFIDENCE_THRESHOLD or
                           metrics['p90_error_ms'] >= LOCAL_SYNC_P90_LOW_CONFIDENCE_MS or
                           knot_quality['unstable']),
    })
    return metrics
