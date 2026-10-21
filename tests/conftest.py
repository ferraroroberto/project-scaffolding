"""Collection guard for the whole `tests/` tree.

`tests/_fixtures/` holds fixture *repos* (synthetic adopters for generator tests);
the `test_*.py` files inside are data the generator parses, never tests to run.
"""

collect_ignore = ["_fixtures"]
