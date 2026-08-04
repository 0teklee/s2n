import importlib
import pkgutil
from typing import Any, Dict, List

from s2n.s2nscanner.logger import get_logger

PLUGIN_PACKAGE = "s2n.s2nscanner.plugins"
logger = get_logger("plugin_discovery")

def discover_plugins(include_instances: bool = False) -> List[Dict[str, Any]]:
    """
    Discover all available plugins and return their metadata.
    """
    try:
        package = importlib.import_module(PLUGIN_PACKAGE)
    except ImportError:
        logger.exception("Unable to import plugin package %s", PLUGIN_PACKAGE)
        return []

    discovered = []
    excluded_modules = {"helper", "discovery", "registry", "base"}
    
    # pkgutil expects the filesystem path of the package
    if not hasattr(package, "__path__"):
        return []

    for _, modname, _ in pkgutil.iter_modules(package.__path__):
        if modname in excluded_modules or modname.startswith("__"):
            continue
            
        module_name = f"{PLUGIN_PACKAGE}.{modname}"
        try:
            module = importlib.import_module(module_name)
            factory = getattr(module, "Plugin", None)
            
            instance = None
            if factory and callable(factory):
                instance = factory()
            else:
                # Fallback: check if there's a class named *Scanner
                scanner_class = None
                for attr_name in dir(module):
                    if attr_name.endswith("Scanner") and attr_name != "Scanner":
                        scanner_class = getattr(module, attr_name)
                        break
                
                if scanner_class:
                    instance = scanner_class()
            
            if instance:
                meta = {
                    "id": modname,
                    "name": getattr(instance, "name", modname),
                    "description": getattr(instance, "description", ""),
                    "version": getattr(instance, "version", "0.1.0"),
                }
                if include_instances:
                    setattr(instance, "_s2n_module_name", modname)
                    meta["instance"] = instance
                discovered.append(meta)
        except Exception:
            logger.exception("Failed to load plugin module %s", module_name)
            continue
            
    return discovered
