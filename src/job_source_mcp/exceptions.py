from __future__ import annotations


class RateLimitedError(RuntimeError):
    """Raised when a source keeps returning HTTP 429 after backing off.

    This exists so callers can tell "the remote throttled us" apart from "the
    search ran fine but matched nothing". Both used to collapse into an empty
    result list; now a rate-limited source surfaces explicitly instead.
    """

    def __init__(self, source: str, interval: float | None = None) -> None:
        self.source = source
        self.interval = interval
        msg = f"{source} rate-limited (HTTP 429) after back-off"
        if interval is not None:
            msg += f"; next request spaced ~{interval:.0f}s apart"
        super().__init__(msg)
