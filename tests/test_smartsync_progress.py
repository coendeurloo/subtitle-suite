import threading
import unittest
from unittest.mock import Mock, patch

from resources.lib import smartsync
from resources.lib.background_jobs import JobCancelled
from resources.lib.smartsync_progress import SmartSyncProgress
from test_smartsync_framerate import _reference_subs, _target_from_reference
from test_service_translation import service


class SmartSyncWorkProgressTests(unittest.TestCase):
    def test_progress_follows_work_and_does_not_change_timing(self):
        reference = _reference_subs(90)
        target = _target_from_reference(reference, offset=5000)
        expected = smartsync.sync_local(reference, target)
        state = SmartSyncProgress()
        snapshots = []
        def record(stage, completed, total):
            state.report(stage, completed, total)
            snapshots.append(state.snapshot())
        actual = smartsync.sync_local(reference, target, progress_callback=record)
        self.assertEqual([(e.start, e.end) for e in expected['synced_subs'].events],
                         [(e.start, e.end) for e in actual['synced_subs'].events])
        self.assertEqual(expected['confidence'], actual['confidence'])
        self.assertEqual(expected['knots'], actual['knots'])
        percentages = [item[1] for item in snapshots]
        self.assertEqual(percentages, sorted(percentages))
        self.assertEqual(percentages[-1], 88)
        for stage in ['speed', 'shift', 'sections', 'adjust', 'check']:
            self.assertTrue(any(item[0] == stage for item in snapshots), stage)
        for stage in ['speed', 'shift', 'sections']:
            self.assertTrue(any(item[0] == stage and 0 < item[2] < item[3] for item in snapshots), stage)
        self.assertGreater(len(set(percentages)), 40)

    def test_cancellation_during_expensive_scans_does_not_change_input(self):
        reference = _reference_subs(90)
        target = _target_from_reference(reference, offset=5000)
        original = [(e.start, e.end) for e in target.events]
        for cancelled_stage in ['speed', 'shift', 'sections', 'adjust']:
            event = threading.Event()
            def cancel(stage, completed, total):
                if stage == cancelled_stage:
                    event.set()
            with self.assertRaises(JobCancelled):
                smartsync.sync_local(reference, target, progress_callback=cancel, cancel_event=event)
            self.assertEqual(original, [(e.start, e.end) for e in target.events])

    def test_scan_checks_cancellation_inside_one_comparison(self):
        event = threading.Event()
        points = smartsync._subtitle_points(_reference_subs(20))
        updates = []
        def report(completed, total):
            updates.append(completed)
            if completed >= 32:
                event.set()
        with self.assertRaises(JobCancelled):
            smartsync._scan_best_global_offset(points, points, progress_callback=report, cancel_event=event)
        self.assertLess(max(updates), 100)

    def test_ai_progress_is_reported_without_changing_anchor_validation(self):
        reference = _reference_subs(20)
        target = _target_from_reference(reference, offset=2000)
        snapshots = []
        pairs = [{'reference_id': i, 'target_id': i} for i in [0, 5, 10, 15, 19]]
        smartsync.sync_from_anchor_pairs(reference, target, pairs,
                                        progress_callback=lambda *args: snapshots.append(args))
        self.assertIn('ai_adjust', [s[0] for s in snapshots])
        self.assertEqual(snapshots[-1], ('ai_check', 1, 1))


class SmartSyncUIProgressTests(unittest.TestCase):
    def test_ui_updates_on_main_thread_while_worker_is_still_busy(self):
        busy = threading.Event()
        released = threading.Event()
        main_thread = threading.get_ident()
        calls = []
        worker_thread = []
        dialog = Mock()
        dialog.iscanceled.return_value = False
        def operation(report, cancel_event):
            worker_thread.append(threading.get_ident())
            report('sections', 2, 20)
            busy.set()
            self.assertTrue(released.wait(2))
            report('check', 1, 1)
            return {'done': True}
        def update(progress, percent, message, detail=''):
            calls.append((threading.get_ident(), percent, message, detail))
            if busy.is_set() and 'Comparing sections' in message:
                released.set()
        with patch.object(service, '_progress_update', side_effect=update), \
             patch.object(service, '_keep_translation_awake'):
            result = service._run_smart_sync_job(operation, dialog)
        self.assertTrue(result['done'])
        self.assertTrue(released.is_set())
        self.assertTrue(all(c[0] == main_thread for c in calls))
        self.assertNotEqual(worker_thread[0], main_thread)
        self.assertTrue(any('2/20' in c[3] for c in calls))
        self.assertEqual(calls[-1][1], 88)

    def test_cancel_interrupts_worker_and_pipeline_does_not_save(self):
        cancelled = threading.Event()
        dialog = Mock()
        dialog.iscanceled.return_value = True
        def operation(report, event):
            report('sections', 1, 20)
            if event.wait(2):
                cancelled.set()
                raise JobCancelled()
        with patch.object(service, '_keep_translation_awake'), \
             patch.object(service, '_progress_update'):
            with self.assertRaises(JobCancelled):
                service._run_smart_sync_job(operation, dialog)
        self.assertTrue(cancelled.wait(2))
        with patch.object(service, '_create_smart_sync_progress', return_value=dialog), \
             patch.object(service, '_run_smart_sync_local', side_effect=JobCancelled()), \
             patch.object(service, '_select_smart_sync_apply_mode') as choose, \
             patch.object(service, '_apply_synced_subtitle_to_target') as save:
            self.assertFalse(service._run_smart_sync_pipeline('reference.srt', 'target.srt')['applied'])
        dialog.close.assert_called_once()
        choose.assert_not_called()
        save.assert_not_called()

    def test_worker_failure_closes_dialog_and_does_not_save(self):
        dialog = Mock()
        with patch.object(service, '_create_smart_sync_progress', return_value=dialog), \
             patch.object(service, '_run_smart_sync_local', side_effect=OSError('bad file')), \
             patch.object(service, '_apply_synced_subtitle_to_target') as save:
            self.assertFalse(service._run_smart_sync_pipeline('reference.srt', 'target.srt')['applied'])
        dialog.close.assert_called_once()
        save.assert_not_called()

    def test_save_failure_still_closes_progress(self):
        analyzing, saving = Mock(), Mock()
        with patch.object(service, '_create_smart_sync_progress', side_effect=[analyzing, saving]), \
             patch.object(service, '_run_smart_sync_local', return_value={'confidence':1,'median_error_ms':0,'low_confidence':False,'synced_subs':object()}), \
             patch.object(service, '_notify'), \
             patch.object(service, '__language__', return_value='%s %s'), \
             patch.object(service, '_select_smart_sync_apply_mode', return_value='replace'), \
             patch.object(service, '_apply_synced_subtitle_to_target', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                service._run_smart_sync_pipeline('reference.srt', 'target.srt')
        analyzing.close.assert_called_once()
        saving.close.assert_called_once()

    def test_cached_old_labels_use_fallback_text(self):
        with patch.object(service, '__language__', return_value=''):
            self.assertEqual(service._smart_sync_status(33324, 2, 20, 5), '2/20 checks completed (5s elapsed)')


if __name__ == '__main__':
    unittest.main()
