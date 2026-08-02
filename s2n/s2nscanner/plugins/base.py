"""
S2N Plugin contract (IFACE-05)
==============================

Every plugin discovered by `discovery.py` must satisfy this structural contract:
a `name`/`description`, a constructor accepting an optional `PluginConfig`, and
a `run(plugin_context) -> PluginResult` entry point.

`pre_scan` / `post_scan` / `cleanup` are intentionally NOT part of this
contract — they are optional lifecycle hooks that only some plugins (e.g. an
AI-driven plugin agent) implement; `scan_engine.py` probes for them with
`hasattr` and must keep doing so.

`BasePlugin` is a `Protocol`, not a base class plugins must inherit from —
plugins already satisfy it structurally, so this is a static-typing aid
(`isinstance(plugin, BasePlugin)` also works because it is `@runtime_checkable`)
rather than a required subclass relationship.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from s2n.s2nscanner.interfaces import PluginConfig, PluginContext, PluginResult


@runtime_checkable
class BasePlugin(Protocol):
    name: str
    description: str

    def __init__(self, config: Optional[PluginConfig] = None) -> None: ...

    def run(self, plugin_context: PluginContext) -> PluginResult: ...


__all__ = ["BasePlugin"]
