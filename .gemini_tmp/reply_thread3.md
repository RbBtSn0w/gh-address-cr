Fixed in d753b03.

Extracted the duplicated `parse_dispatch()` function (along with `VALID_MODES` and `VALID_PRODUCERS` constants) into `python_common.py` as a single shared implementation. Both `cr_loop.py` and `control_plane.py` now import from the shared module.

**Changes:**
- `python_common.py`: added `parse_dispatch()`, `VALID_MODES`, `VALID_PRODUCERS`
- `cr_loop.py`: removed local `parse_dispatch()` and constants, imports from `python_common`
- `control_plane.py`: removed local `parse_dispatch()` and constants, imports from `python_common`

**Validation:**
- All 88 tests pass with `pytest tests/ -v`
- Both dispatchers now use identical parsing logic from a single source
