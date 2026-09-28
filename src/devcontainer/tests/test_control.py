import unittest
from unittest.mock import patch

import control


class ControlCommandTests(unittest.TestCase):
    def test_dev_start_builds_dev_stack(self):
        args = control.compose_args("dev", "start")
        self.assertEqual(args[-3:], ["up", "-d", "--build"])
        self.assertIn("uta-debug-dev", args)

    def test_prod_start_does_not_build(self):
        args = control.compose_args("prod", "start")
        self.assertEqual(args[-2:], ["up", "-d"])
        self.assertIn("uta-debug-prod", args)

    def test_reset_is_scoped_and_removes_volumes(self):
        args = control.compose_args("dev", "reset")
        self.assertEqual(args[-3:], ["down", "--volumes", "--remove-orphans"])
        self.assertIn("uta-debug-dev", args)

    def test_invalid_values_are_rejected(self):
        with self.assertRaises(ValueError):
            control.compose_args("prod", "exec")
        with self.assertRaises(ValueError):
            control.compose_args("unknown", "status")

    @patch("control.subprocess.run")
    def test_run_command_does_not_use_a_shell(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        run.return_value.stderr = ""
        control.run_command(["docker", "info"])
        self.assertNotIn("shell", run.call_args.kwargs)


    def test_compose_uses_shared_environment_file(self):
        args = control.compose_args("prod", "status")
        self.assertIn("--env-file", args)
        self.assertIn(str(control.CONFIG_PATH), args)
