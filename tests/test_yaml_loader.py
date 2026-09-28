import pytest
from yaml.constructor import ConstructorError

from release_devkit.yaml_loader import load_yaml


def test_load_yaml_rejects_duplicate_keys():
    with pytest.raises(ConstructorError, match="duplicate key"):
        load_yaml("a: 1\na: 2\n")


def test_load_yaml_preserves_number_and_bool_scalars_as_strings():
    result = load_yaml("version: 0.1\nflag: true\ncount: 42\n")

    assert isinstance(result, dict)
    assert result == {"version": "0.1", "flag": "true", "count": "42"}


def test_load_yaml_preserves_null_as_none():
    result = load_yaml("key:\n")

    assert isinstance(result, dict)
    assert result == {"key": None}


def test_load_yaml_returns_none_for_empty_document():
    assert load_yaml("") is None
