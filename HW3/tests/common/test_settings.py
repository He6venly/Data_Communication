# 공통 설정값을 테스트한다.

import unittest

from hw3.common import settings


class SettingsTests(unittest.TestCase):
    def test_fixed_contract_values(self) -> None:
        self.assertEqual(1, settings.CONTRACT_VERSION)
        self.assertEqual(10, settings.WORKER_COUNT)
        self.assertEqual(6, settings.DISPATCHER_COUNT)
        self.assertEqual(4575, settings.COORDINATOR_PORT)
        self.assertEqual((1000, 100000, 10, 10000), (
            settings.TASK_COUNT,
            settings.TASK_SIZE,
            settings.STEPS_PER_TASK,
            settings.STEP_SIZE,
        ))
        self.assertEqual(7000, settings.PEER_BASE_PORT)
        self.assertEqual((1.0, 1.0, 5.0), (
            settings.HEARTBEAT_INTERVAL_SECONDS,
            settings.FAILURE_DETECTOR_INTERVAL_SECONDS,
            settings.POOL_LOG_INTERVAL_SECONDS,
        ))
        self.assertEqual((3.0, 5.0), (
            settings.SUSPECT_TIMEOUT_SECONDS,
            settings.DEAD_TIMEOUT_SECONDS,
        ))
        self.assertEqual((10.0, 20.0), settings.INITIAL_CRASH_INTERVAL_SECONDS)
        self.assertEqual((5.0, 15.0), settings.CRASH_INTERVAL_SECONDS)
        self.assertEqual((10.0, 15.0), settings.DOWNTIME_SECONDS)
        self.assertEqual(80.0, settings.CRASH_CUTOFF_SECONDS)
        self.assertEqual((0.5, 2.0, 100), (
            settings.CONNECT_RETRY_SECONDS,
            settings.REJOIN_RETRY_SECONDS,
            settings.DEFAULT_STEP_DELAY_MS,
        ))
        self.assertEqual(5_761_455, settings.EXPECTED_PRIME_COUNT)


if __name__ == "__main__":
    unittest.main()
