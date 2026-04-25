"""Tests for the optimizer-safe parameter VBA stripper."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from leam.tools import strip_parameters_store_call  # noqa: E402


def test_strips_store_parameters_call():
    text = (
        "Dim names(1 To 2) As String\n"
        "Dim values(1 To 2) As String\n"
        "\n"
        'names(1) = "L"\n'
        'values(1) = "20"\n'
        'names(2) = "W"\n'
        'values(2) = "10"\n'
        "\n"
        "StoreParameters names, values\n"
    )
    out = strip_parameters_store_call(text)
    assert "StoreParameters names, values" not in out.replace(
        "' [LEAM] removed for optimizer: StoreParameters names, values", ""
    )
    assert "' [LEAM] removed for optimizer" in out
    # individual StoreParameter "name", "value" calls must survive.
    assert 'names(1) = "L"' in out


def test_preserves_store_parameter_single_calls():
    text = (
        'StoreParameter "f0_GHz", "2.45"\n'
        "StoreParameters names, values\n"
        'StoreParameter "L", "20"\n'
    )
    out = strip_parameters_store_call(text)
    assert 'StoreParameter "f0_GHz", "2.45"' in out
    assert 'StoreParameter "L", "20"' in out
    assert "StoreParameters names, values" in out  # only in comment line
    assert out.count("StoreParameters names, values") == 1  # original replaced


def test_strip_is_idempotent():
    text = 'names(1) = "L"\nvalues(1) = "20"\nStoreParameters names, values\n'
    once = strip_parameters_store_call(text)
    twice = strip_parameters_store_call(once)
    assert once == twice
