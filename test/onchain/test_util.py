from copy import copy

from hypothesis import given
from hypothesis import strategies as st

from steak_protocol.onchain.util import remove_bytes_at_index, remove_int_at_index


@given(st.lists(st.integers()), st.integers())
def test_remove_pool_at_index(pools: list, index):
    try:
        assert 0 <= index < len(pools)
        exp_parts = copy(pools)
        exp_parts.pop(index)
    except AssertionError:
        exp_parts = None
    try:
        res_parts = remove_int_at_index(pools, index)
    except AssertionError:
        res_parts = None
    assert res_parts == exp_parts


@given(st.lists(st.binary()), st.integers())
def test_remove_pool_at_index(pools: list, index):
    try:
        assert 0 <= index < len(pools)
        exp_parts = copy(pools)
        exp_parts.pop(index)
    except AssertionError:
        exp_parts = None
    try:
        res_parts = remove_bytes_at_index(pools, index)
    except AssertionError:
        res_parts = None
    assert res_parts == exp_parts
