"""Best-effort process RSS telemetry; no external dependency or user data."""


def memory_mb():
    """Return (current RSS MB, process high-water RSS MB), or (None, None).

    Linux /proc/self/status is used on Render. Values are process-wide, not
    per-thread or per-job. Both fields are in kB as reported by the kernel.
    """
    rss = peak = None
    try:
        with open('/proc/self/status', encoding='ascii') as stream:
            for line in stream:
                if line.startswith('VmRSS:'):
                    rss = round(int(line.split()[1]) / 1024, 1)
                elif line.startswith('VmHWM:'):
                    peak = round(int(line.split()[1]) / 1024, 1)
                if rss is not None and peak is not None:
                    break
    except (OSError, ValueError, IndexError):
        pass
    return rss, peak
