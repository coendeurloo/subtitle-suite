import threading
import unittest

from resources.lib.background_jobs import CancellableJob, JobCancelled


class BackgroundJobTests(unittest.TestCase):
    def test_returns_worker_result(self):
        job = CancellableJob(lambda cancelled: 'done').start()
        self.assertTrue(job.wait(1.0))
        self.assertEqual('done', job.get_result())

    def test_cancel_discards_a_late_worker_result(self):
        started = threading.Event()
        release = threading.Event()

        def operation(cancelled):
            started.set()
            release.wait(1.0)
            return 'late result'

        job = CancellableJob(operation).start()
        self.assertTrue(started.wait(1.0))
        job.cancel()
        release.set()
        self.assertTrue(job.wait(1.0))
        with self.assertRaises(JobCancelled):
            job.get_result()
