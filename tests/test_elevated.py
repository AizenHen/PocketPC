import os
from pathlib import Path
import subprocess
import sys
import unittest

from backend.elevated import ElevatedInputBroker


class ElevatedBrokerTests(unittest.TestCase):
    def test_authenticated_pipe_helper_starts_and_stops_without_permissions(self):
        broker = ElevatedInputBroker({"left": 0, "top": 0, "width": 100, "height": 100})
        packaged_helper = os.environ.get("POCKETPC_TEST_HELPER")
        helper = Path(__file__).resolve().parents[1] / "pocketpc_input_helper.py"
        command = [*([] if packaged_helper else [sys.executable]), packaged_helper or str(helper),
            "--pipe", broker.pipe, "--key", broker.key.hex(),
            "--left", "0", "--top", "0", "--width", "100", "--height", "100",
            "--parent", str(os.getpid()),
        ]
        process = subprocess.Popen(command)
        try:
            self.assertIs(broker.accept(), broker)
            broker.close()
            self.assertEqual(process.wait(timeout=5), 0)
        finally:
            broker.close()
            if process.poll() is None:
                process.kill()


if __name__ == "__main__":
    unittest.main()
