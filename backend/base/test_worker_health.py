from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from base.worker_health import heartbeat_key, write_worker_heartbeat


class WorkerHealthTests(SimpleTestCase):
    def test_heartbeat_key_rejects_unsafe_names(self):
        self.assertEqual(
            heartbeat_key("hr18-submission"),
            "renshi:worker:hr18-submission:heartbeat",
        )
        with self.assertRaises(ValueError):
            heartbeat_key("../../unsafe")

    @patch.dict("os.environ", {"REDIS_URL": "redis://redis:6379/0"})
    @patch("base.worker_health.redis.Redis.from_url")
    def test_heartbeat_has_bounded_ttl(self, from_url):
        client = MagicMock()
        from_url.return_value = client
        self.assertTrue(write_worker_heartbeat("legacy-scheduler"))
        key, value = client.set.call_args.args
        self.assertEqual(key, "renshi:worker:legacy-scheduler:heartbeat")
        self.assertGreater(float(value), 0)
        self.assertEqual(client.set.call_args.kwargs["ex"], 300)
