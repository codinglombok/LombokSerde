"""Shared cross-language vector runner (mirrors rust/tests/vectors.rs)."""

from vectors_common import check_case, load_cases

import lombokserde  # noqa: F401  (version marker)


def test_vector_file_has_at_least_100_cases():
    cases = load_cases()
    assert len(cases) >= 100, f"expected >= 100 vector cases, got {len(cases)}"


def test_shared_vectors_bit_identical():
    cases = load_cases()
    failures = [msg for c in cases if (msg := check_case(c))]
    assert not failures, f"{len(failures)} of {len(cases)} vector cases failed:\n" + "\n".join(
        failures
    )
