"""IFACE-05: every discovered plugin must satisfy the BasePlugin structural contract."""

from s2n.s2nscanner.plugins.base import BasePlugin
from s2n.s2nscanner.plugins.discovery import discover_plugins


def test_every_discovered_plugin_satisfies_base_plugin_contract():
    plugins = discover_plugins(include_instances=True)
    assert plugins, "no plugins were discovered — check plugin package layout"

    for meta in plugins:
        instance = meta["instance"]
        assert isinstance(instance, BasePlugin), (
            f"{meta['id']} does not satisfy the BasePlugin contract "
            "(missing name/description/run)"
        )
        assert callable(instance.run)
        assert isinstance(instance.name, str) and instance.name
