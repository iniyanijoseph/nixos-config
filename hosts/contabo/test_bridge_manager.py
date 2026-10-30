"""Local launcher checks; never connect to the VPS or authenticate accounts."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('bridge-manager.sh')


class LauncherTests(unittest.TestCase):
    def fixture(self, directory, hostname='laptop'):
        directory = Path(directory)
        programs = {
            'uname': '#!/bin/sh\necho ' + hostname + '\n',
            'ssh': '#!/bin/sh\nprintf "%s\\n" "$@" > "$FIXTURE/ssh-args"\necho $$ > "$FIXTURE/tunnel-pid"\nexec sleep 30\n',
            'curl': '#!/bin/sh\necho "{\\"errcode\\":\\"M_MISSING_TOKEN\\"}"\n',
            'mautrix-manager': '#!/bin/sh\necho opened > "$FIXTURE/opened"\n',
        }
        for name, text in programs.items():
            file = directory / name
            file.write_text(text)
            file.chmod(0o755)
        return dict(os.environ, PATH=str(directory) + ':' + os.environ['PATH'],
                    DISPLAY=':fixture', FIXTURE=str(directory))

    def test_loopback_tunnel_is_closed_when_application_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            env = self.fixture(directory)
            subprocess.run(['bash', str(SCRIPT)], env=env, check=True,
                           capture_output=True, text=True, timeout=10)
            directory = Path(directory)
            self.assertTrue((directory / 'opened').exists())
            args = (directory / 'ssh-args').read_text()
            self.assertIn('127.0.0.1:29321:127.0.0.1:29321', args)
            self.assertIn('127.0.0.1:29320:127.0.0.1:29320', args)
            self.assertIn('ExitOnForwardFailure=yes', args)
            pid = int((directory / 'tunnel-pid').read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_server_and_headless_sessions_are_rejected_before_ssh(self):
        for hostname, display in [('contabo', ':fixture'), ('laptop', '')]:
            with self.subTest(hostname=hostname), tempfile.TemporaryDirectory() as directory:
                env = self.fixture(directory, hostname)
                env.update(DISPLAY=display, WAYLAND_DISPLAY='')
                result = subprocess.run(['bash', str(SCRIPT)], env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertFalse((Path(directory) / 'ssh-args').exists())


if __name__ == '__main__':
    unittest.main()
