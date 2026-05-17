"""Signal direction type — re-exported from aqcs.utils.events for convenience.

Using the canonical SignalDirection from the Event Schema avoids duplication
and ensures that signal values in research code and in emitted events are
the same type.
"""

from aqcs.utils.events import SignalDirection

__all__ = ["SignalDirection"]
