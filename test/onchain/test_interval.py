from hypothesis import given, strategies as st

from steak_protocol.onchain.utils.ext_interval import *


@given(
    ext_time=st.integers(),
    lower_bound=st.integers(),
    upper_bound=st.integers(),
)
def test_before_ext(
    ext_time: int,
    lower_bound: int,
    upper_bound: int,
) -> None:
    assert before_ext(
        make_range(lower_bound, upper_bound), FinitePOSIXTime(ext_time)
    ) == (upper_bound < ext_time)


@given(
    lower_bound=st.integers(),
    upper_bound=st.integers(),
)
def test_ext_posinf_before(
    lower_bound: int,
    upper_bound: int,
) -> None:
    assert before_ext(make_range(lower_bound, upper_bound), PosInfPOSIXTime()) == True


@given(
    lower_bound=st.integers(),
    upper_bound=st.integers(),
)
def test_ext_posinf_before(
    lower_bound: int,
    upper_bound: int,
) -> None:
    assert before_ext(make_range(lower_bound, upper_bound), NegInfPOSIXTime()) == False


@given(
    lower_bound1=st.integers(),
    upper_bound1=st.integers(),
    lower_bound2=st.integers(),
    upper_bound2=st.integers(),
)
def test_entirely_after_time(
    lower_bound1: int,
    upper_bound1: int,
    lower_bound2: int,
    upper_bound2: int,
) -> None:
    assert entirely_after(
        make_range(lower_bound1, upper_bound1), make_range(lower_bound2, upper_bound2)
    ) == (lower_bound1 > upper_bound2)


@given(
    lower_bound1=st.integers(),
    upper_bound1=st.integers(),
    lower_bound2=st.integers(),
    upper_bound2=st.integers(),
)
def test_entirely_before_time(
    lower_bound1: int,
    upper_bound1: int,
    lower_bound2: int,
    upper_bound2: int,
) -> None:
    assert entirely_before(
        make_range(lower_bound1, upper_bound1), make_range(lower_bound2, upper_bound2)
    ) == (upper_bound1 < lower_bound2)


@given(
    ext_time=st.integers(),
    lower_bound=st.integers(),
    upper_bound=st.integers(),
)
def test_after_ext(
    ext_time: int,
    lower_bound: int,
    upper_bound: int,
) -> None:
    assert after_ext(
        make_range(lower_bound, upper_bound), FinitePOSIXTime(ext_time)
    ) == (ext_time < lower_bound)


@given(
    lower_bound=st.integers(),
    upper_bound=st.integers(),
)
def test_ext_posinf_after(
    lower_bound: int,
    upper_bound: int,
) -> None:
    assert after_ext(make_range(lower_bound, upper_bound), PosInfPOSIXTime()) == False


@given(
    lower_bound=st.integers(),
    upper_bound=st.integers(),
)
def test_ext_posinf_after(
    lower_bound: int,
    upper_bound: int,
) -> None:
    assert after_ext(make_range(lower_bound, upper_bound), NegInfPOSIXTime()) == True
