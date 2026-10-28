"""Finite control-plane commands; timeout is failure, never successful capture."""
import os
import re
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


CAPTURE_COMPLETE = 'PQC_CAPTURE_COMMAND_COMPLETE'


def capture_command(target, script, seconds):
    """Bound the script and its cleanup; acknowledge completion after its shell exits.

    GNU timeout propagates a child's 124 unchanged. The outer shell therefore
    records the completed child's status, after EXIT traps, inside the deadline.
    Killing the timed process group cannot produce this acknowledgement.
    """
    wrapped = (f'sh -c {shlex.quote(script)}; capture_status=$?; '
               f'printf "\\n{CAPTURE_COMPLETE} rc=%s\\n" "$capture_status" >&2; '
               'exit "$capture_status"')
    return ['ssh', target, f'timeout --kill-after=20s {seconds:g}s sh -c {shlex.quote(wrapped)}']


def capture_result(completed, *, remote_deadline, capture_limit):
    """Return the capture status and any unresolved control-plane safety reason."""
    reason = None
    code = completed.returncode
    stderr = completed.stderr
    # Require a single, matching terminal acknowledgement; partial/mismatched
    # evidence must not turn a real control-plane timeout into a normal capture.
    acknowledgements = re.findall(rf'^{CAPTURE_COMPLETE} rc=([0-9]+)$', stderr, re.MULTILINE)
    finished = (acknowledgements == [str(code)] and
                stderr.rstrip().endswith(f'{CAPTURE_COMPLETE} rc={code}'))
    if code == 124 and finished:
        stderr += (f'\nCapture acquisition time limit reached ({capture_limit}s); '
                   'remote capture script completed with status 124.\n')
    elif code == 124:
        reason = 'Capture operation deadline expired; remote completion unverified'
        code = 125
        stderr += f'\nCapture operation deadline exceeded ({remote_deadline}s); remote completion unverified.\n'
    elif code == 137:
        reason = 'Capture command was killed; remote completion unverified'
        code = 125
        stderr += '\nCapture command terminated with status 137; remote completion unverified.\n'
    elif code == 125:
        reason = 'Capture control command failed or timed out; remote completion unverified'
    elif code == 255:
        reason = 'Capture SSH transport failed; remote completion unverified'
    return subprocess.CompletedProcess(completed.args, code, completed.stdout, stderr), reason
