#!/usr/bin/env python3
"""Run a command in a pseudo-terminal and answer a debconf yes/no question.

CI runners have no terminal, so debconf would fall back to its non-interactive
frontend and never show the question. This gives the command a pty, waits
until a "[yes/no]" prompt actually appears, then types the answer — so the
test doesn't depend on timing.

Usage: answer-debconf.py ANSWER COMMAND [ARGS...]
Use with DEBIAN_FRONTEND=teletype. Exits with the command's exit status;
exits 99 if the prompt never appeared.
"""
import os
import pty
import select
import sys
import time

answer = sys.argv[1].encode() + b"\n"
pid, fd = pty.fork()
if pid == 0:
    os.execvp(sys.argv[2], sys.argv[2:])

seen, answered, deadline = b"", False, time.time() + 600
while time.time() < deadline:
    ready, _, _ = select.select([fd], [], [], 1)
    if not ready:
        continue
    try:
        data = os.read(fd, 4096)
    except OSError:          # EIO: the command closed the terminal (it exited)
        break
    if not data:
        break
    sys.stdout.buffer.write(data)
    sys.stdout.flush()
    seen = (seen + data)[-4096:]
    if not answered and b"[yes/no]" in seen:
        os.write(fd, answer)
        answered = True
else:
    os.kill(pid, 9)
    sys.exit("answer-debconf: timed out")

status = os.waitpid(pid, 0)[1]
code = os.waitstatus_to_exitcode(status)
sys.exit(code if answered or code else 99)
