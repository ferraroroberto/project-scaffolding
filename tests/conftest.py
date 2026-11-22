"""Collection guard and shared fixtures for the whole `tests/` tree.

`tests/fixtures/` holds fixture *repos* (synthetic adopters for generator tests);
the `test_*.py` files inside are data the generator parses, never tests to run.

`synthetic_host` (from the vendored `tests/host/_synthetic_host.py`) is the one way a
test reads an account name or home folder; the conventions ratchet's
`host-identity` rule flags direct reads.
"""

from tests.host._synthetic_host import synthetic_host  # noqa: F401 -- registers the fixture

collect_ignore = ["fixtures"]
