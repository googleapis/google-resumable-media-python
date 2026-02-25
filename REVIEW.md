# Review of PR #495

**Verdict: LGTM**

## Summary
The PR adds `max_length` parameter to `decompress` method in `_GzipDecoder` and `_BrotliDecoder` wrappers, enabling streaming decompression support. This aligns with `urllib3` interface and is implemented correctly with backward compatibility for older dependency versions.

## Detailed Findings

1.  **Conflict & Relevance Check**:
    - The PR applies cleanly and does not conflict with the `main` branch.
    - The changes are logically relevant to enabling streaming decompression support, consistent across synchronous and asynchronous modules.

2.  **Functional Correctness**:
    - The implementation correctly adds the `max_length` parameter to the `decompress` method in `_GzipDecoder` and `_BrotliDecoder` wrappers.
    - The implementation robustly handles older `urllib3` versions (or custom environments) via a `try-except TypeError` fallback mechanism. This ensures backward compatibility.
    - The default value `max_length=-1` aligns with `urllib3`'s convention for "unlimited" (verified against `urllib3==2.6.3`).
    - The `_BrotliDecoder` wrapper correctly exposes `has_unconsumed_tail` property, delegating to the underlying decoder and handling `AttributeError` gracefully.
    - The `_GzipDecoder` correctly inherits `has_unconsumed_tail` from `urllib3.response.GzipDecoder` (if available).

3.  **Google Python Standards**:
    - **Type Hinting (PEP 484)**: The new code relies on docstrings for type information (`Args: ... max_length (int): ...`). This is consistent with the existing codebase style in `download.py`, though modern Google style encourages inline type hints. I consider this acceptable given the file's current state.
    - **Docstring Quality**: The docstrings follow the Google Python Style Guide, clearly documenting the new parameter and its behavior.
    - **Logging vs Print**: No new logging or print statements were introduced.
    - **Formatting**: The code appears to be formatted correctly (likely `black` compliant).

4.  **Technical Merit & Architecture**:
    - The solution is idiomatic for a wrapper library. It extends functionality while delegating the heavy lifting to `urllib3`.
    - The use of inheritance for `_GzipDecoder` and composition for `_BrotliDecoder` mirrors the existing architecture and is appropriate.
    - The fallback mechanism is a pragmatic way to support diverse dependency versions without complex version checking logic.

5.  **Testing**:
    - The PR includes unit tests in `tests/unit/requests/test_download.py` and `tests_async/unit/requests/test_download.py`.
    - The tests cover both the success path (passing `max_length`) and the fallback path (simulating `TypeError`).
    - I ran the relevant tests locally and they passed (119 tests passed).
    - The tests verify that arguments are forwarded correctly.

6.  **Critical Issues**: None found.

7.  **Suggested Refactors**: None required. The implementation is clean and minimal.
