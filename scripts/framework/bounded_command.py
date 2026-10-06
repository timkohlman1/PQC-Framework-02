"""Finite control-plane commands; timeout is failure, never successful capture."""
import os
import shlex
import signal
import subprocess


def run(command, *, cwd, timeout=120):
    command = list(command)
    if command and command[0] in {'ssh', 'scp'}:
        command[1:1] = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                        '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2']
    process = subprocess.Popen(command, cwd=cwd, text=True, encoding='utf-8',
                               errors='replace', stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        # Kill the owned local group so a broker helper cannot leave an SSH child
        # or inherited output pipe behind. Remote completion is still unverified.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate(timeout=5)
        return subprocess.CompletedProcess(command, 125, stdout,
            stderr + f'\nFramework command timeout after {timeout:g}s; remote completion unverified.\n')
    except BaseException:
        # An operation watchdog may interrupt this runner during communicate.
        # Do not leave its separately owned local process group resident.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=5)
        raise


def capture_command(target, script, seconds):
    """Remote timeout owns the entire script's process group, including pipelines."""
    return ['ssh', target, f'timeout --kill-after=20s {seconds:g}s sh -c {shlex.quote(script)}']
