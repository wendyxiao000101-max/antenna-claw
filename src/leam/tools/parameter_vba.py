"""Utilities for adapting parameters VBA to the optimizer flow.

The generated ``<output>_parameters.bas`` ends with a call like::

    StoreParameters names, values

When that file is replayed as CST history *during an optimizer run*, it
overwrites the optimizer's trial values on every iteration. To enforce
the "Python initializes ParameterList; VBA history only references
names" principle, we strip that final assignment out before handing the
macro to the history builder.

The stripped VBA still carries the ``names(i)`` / ``values(i)`` arrays;
they act as documentation and as raw input that Python can parse via
:class:`leam.services.ParameterService.parse_bas`.
"""

from __future__ import annotations

import re


_STORE_CALL_RE = re.compile(
    r"^\s*StoreParameters\s+names\s*,\s*values\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def strip_parameters_store_call(vba_text: str) -> str:
    """Return ``vba_text`` with any final ``StoreParameters names, values``
    call commented out.

    Single-parameter ``StoreParameter "name", "value"`` lines are
    preserved (they're what OpenClaw uses to snapshot a specific
    optimizer iteration), since those are exactly the per-parameter
    direct writes that the optimizer accepts.
    """
    return _STORE_CALL_RE.sub(
        lambda m: "' [LEAM] removed for optimizer: " + m.group(0).strip(),
        vba_text,
    )


__all__ = ["strip_parameters_store_call"]
