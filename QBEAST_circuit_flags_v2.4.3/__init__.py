"""
QBEAST AI - circuit & liquidity flags, v2.4.3, usable as a package (e.g. inside the qbeast_exec wheel):

    from <package> import circuit_liquidity_flags as C, flags_config as F, flags_io as IO
    cfg = F.load_config()

The bundle still works as plain files (python run_four_flags.py ..., python -m pytest ...): this file is only used
when the folder is imported as a package. Added in v2.4.3; nothing else changes.
"""
try:
    from . import circuit_liquidity_flags, flags_config, flags_io  # noqa: F401
    from .circuit_liquidity_flags import __version__  # noqa: F401
except ImportError:          # loaded outside a package (e.g. pytest collecting the plain bundle folder): nothing to do
    pass
