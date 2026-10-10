"""Bounded stdout and lifetime for an exact owned native-client process group."""
import os
import select
import signal
import subprocess
import time


def bounded_run(argv, *, cwd=None, timeout=15, limit=1048576):
    child = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    deadline = time.monotonic() + timeout
    output = bytearray()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv[0], timeout)
            ready, _, _ = select.select([child.stdout], [], [], remaining)
            if not ready:
                raise subprocess.TimeoutExpired(argv[0], timeout)
            chunk = os.read(child.stdout.fileno(), min(65536, limit + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > limit:
                raise ValueError('native output exceeds limit')
        returncode = child.wait(timeout=max(0.001, deadline - time.monotonic()))
        return subprocess.CompletedProcess(argv, returncode, bytes(output))
    finally:
        # The group belongs only to this invocation, including launcher helpers.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
        child.stdout.close()
