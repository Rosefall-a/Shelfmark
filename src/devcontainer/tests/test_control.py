import unittest
from unittest.mock import patch

import control


class ControlCommandTests(unittest.TestCase):
    def test_dev_start_builds_current_checkout(self):
        args = control.compose_args(control.DEFAULT_INSTANCES[0], "start")
        self.assertEqual(args[-3:], ["up", "-d", "--build"])
        self.assertIn("--env-file", args)
        self.assertIn("uta-debug-dev", args)

    def test_image_mode_uses_tag_without_building(self):
        instance = {**control.DEFAULT_INSTANCES[1], "build_mode": "image", "image": "ghcr.io/example/app:v1"}
        args = control.compose_args(instance, "start")
        self.assertEqual(args[-5:], ["up", "-d", "--no-build", "--pull", "always"])

    def test_instances_are_isolated_by_project_and_port(self):
        instances = [
            {**control.DEFAULT_INSTANCES[0], "id": "dev-a", "project": "dev-a", "port": 5173},
            {**control.DEFAULT_INSTANCES[0], "id": "dev-b", "project": "dev-b", "port": 5174},
            {**control.DEFAULT_INSTANCES[1], "id": "prod-a", "project": "prod-a", "port": 8180},
        ]
        self.assertEqual(len(control.validate_instances(instances)), 3)

    def test_duplicate_ports_are_rejected(self):
        instances = [
            {**control.DEFAULT_INSTANCES[0], "id": "a", "project": "a", "port": 5173},
            {**control.DEFAULT_INSTANCES[0], "id": "b", "project": "b", "port": 5173},
        ]
        with self.assertRaises(ValueError):
            control.validate_instances(instances)

    def test_reset_is_scoped_and_removes_volumes(self):
        args = control.compose_args(control.DEFAULT_INSTANCES[0], "reset")
        self.assertEqual(args[-3:], ["down", "--volumes", "--remove-orphans"])
        self.assertIn("uta-debug-dev", args)

    def test_invalid_action_is_rejected(self):
        with self.assertRaises(ValueError):
            control.compose_args(control.DEFAULT_INSTANCES[0], "exec")

    @patch("control.subprocess.run")
    def test_run_command_does_not_use_a_shell(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        run.return_value.stderr = ""
        control.run_command(["docker", "info"])
        self.assertNotIn("shell", run.call_args.kwargs)
