from opshin.std.math import *
from opshin.std.builtins import *


def random_number(rng_seed: bytes) -> int:
    """
    Compute a random number between 0 and 2^64 based on rng_seed
    """
    return unsigned_int_from_bytes_big(sha2_256(rng_seed)[:8])


def random_uniform(ex_upper_bound: int, rng_seed: bytes) -> int:
    """
    Compute a pseudo random number between 0 and ex_upper_bound (exclusive)
    This only produces a uniform result for ex_upper_bound < 2^64
    Deterministic based on rng_seed
    """
    return random_number(rng_seed) % ex_upper_bound


def weighted_sample(choices: List[int], rng_seed: bytes) -> int:
    total = sum(choices)
    r = random_uniform(total, rng_seed)
    upto = 0
    i = 0
    for w in choices:
        upto += w
        if upto >= r:
            return i
        i += 1
    assert False, "Shouldn't get here"
    return -1
