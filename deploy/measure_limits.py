"""Measure the account's process/thread usage against what Chromium needs.

The browser dies with:

    pthread_create: Resource temporarily unavailable (11)
    Zygote could not fork: process_type gpu-process ... child_pid -1

Both are EAGAIN: the account cannot create another process or thread. On
CloudLinux this is the LVE NPROC cap, which `ulimit -u` does not show - it
reports "unlimited" while the cap is enforced elsewhere. So count what is
actually in use instead.

This only reads /proc. It creates nothing and stresses nothing, so it is
safe to run while the bot is serving.

    python deploy/measure_limits.py
"""

from __future__ import annotations

import os
import pwd

USER = pwd.getpwuid(os.getuid()).pw_name


def proc_entries():
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        path = f"/proc/{pid}"
        try:
            if os.stat(path).st_uid != os.getuid():
                continue
            with open(f"{path}/status") as fh:
                status = fh.read()
            name = ""
            threads = 1
            for line in status.splitlines():
                if line.startswith("Name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("Threads:"):
                    threads = int(line.split(":", 1)[1].strip())
            with open(f"{path}/cmdline", "rb") as fh:
                cmdline = fh.read().replace(b"\0", b" ").decode(errors="replace")
            yield int(pid), name, threads, cmdline
        except (OSError, ValueError):
            continue


def main() -> int:
    entries = list(proc_entries())
    procs = len(entries)
    threads = sum(t for _, _, t, _ in entries)

    # Match the browser itself, not a shell whose command line mentions it.
    chrome = [
        e for e in entries
        if "chrome" in e[1].lower()
        or any(marker in e[3] for marker in
               ("chrome-headless-shell", "chrome-linux", "/chrome "))
    ]
    chrome_threads = sum(t for _, _, t, _ in chrome)

    print(f"account: {USER}")
    print(f"processes in use : {procs}")
    print(f"threads in use   : {threads}")
    ulimit_u = os.popen("bash -c 'ulimit -u' 2>/dev/null").read().strip() or "?"
    print(f"ulimit -u says   : {ulimit_u}  (LVE caps are not shown here)")

    print(f"\nChromium right now: {len(chrome)} process(es), "
          f"{chrome_threads} thread(s)")
    for pid, name, t, cmd in sorted(chrome, key=lambda e: -e[2])[:8]:
        print(f"    pid {pid:>8}  {t:>3} threads  {name}  {cmd[:70]}")

    print("\nTop thread users overall:")
    for pid, name, t, cmd in sorted(entries, key=lambda e: -e[2])[:8]:
        print(f"    pid {pid:>8}  {t:>3} threads  {name}  {cmd[:70]}")

    headroom_needed = max(60, chrome_threads or 60)
    print(f"""
{'=' * 62}
WHAT THIS MEANS
{'=' * 62}
A second Chromium needs roughly as many threads as the first one
({headroom_needed} here). If the account's cap is close to the {threads} threads
already in use, that second browser cannot start - which is exactly the
pthread_create EAGAIN in the probe.

Two ways out, and they combine:

1. Do not start a second browser. Attach to the one already running:
       VINPRO_CDP_URL=http://127.0.0.1:<CDP_PORT>
   in .env.vinpro. Find the port with:
       grep -n "CDP_PORT" bot.py carfax_web_api.py | head

2. Ask the host to raise the account's process limit. Message to send:

   "Hello - our account {USER} on {os.uname().nodename} hits the LVE NPROC
    limit. A headless Chromium (Playwright) needs roughly {headroom_needed}
    threads and fails with 'pthread_create: Resource temporarily
    unavailable'. We currently use {procs} processes / {threads} threads.
    Could you raise NPROC for this account, or tell us the current value?"
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
