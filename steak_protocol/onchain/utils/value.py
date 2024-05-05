from opshin.prelude import *

EMPTY_VALUE_DICT: Value = {}
EMTPY_TOKENNAME_DICT: Dict[TokenName, int] = {}


def merge_without_duplicates(a: List[bytes], b: List[bytes]) -> List[bytes]:
    """
    Merge two lists without duplicates
    Note: The cost of this is O(n^2), can we assume that the lists are small?
    Rough estimate allows 1000 bytes / 32 bytes per policy id ~ 31 policy ids
    However for token names no lower bound on the length is given, so we assume 1000 bytes / 1 byte per token name ~ 1000 token names
    """
    return [x for x in a if not x in b] + b


def _subtract_token_names(
    a: Dict[TokenName, int], b: Dict[TokenName, int]
) -> Dict[TokenName, int]:
    """
    Subtract b from a, return a - b
    """
    if not b:
        return a
    elif not a:
        return {tn_amount[0]: -tn_amount[1] for tn_amount in b.items()}
    return {
        tn: a.get(tn, 0) - b.get(tn, 0)
        for tn in merge_without_duplicates(a.keys(), b.keys())
    }


def subtract_value(a: Value, b: Value) -> Value:
    """
    Subtract b from a, return a - b
    """
    if not b:
        return a
    elif not a:
        return {
            pid_tokens[0]: {
                tn_amount[0]: -tn_amount[1] for tn_amount in pid_tokens[1].items()
            }
            for pid_tokens in b.items()
        }
    return {
        pid: _subtract_token_names(
            a.get(pid, EMTPY_TOKENNAME_DICT), b.get(pid, EMTPY_TOKENNAME_DICT)
        )
        for pid in merge_without_duplicates(a.keys(), b.keys())
    }


def _add_token_names(
    a: Dict[TokenName, int], b: Dict[TokenName, int]
) -> Dict[TokenName, int]:
    """
    Add b to a, return a + b
    """
    if not a:
        return b
    if not b:
        return a
    return {
        tn: a.get(tn, 0) + b.get(tn, 0)
        for tn in merge_without_duplicates(a.keys(), b.keys())
    }


def add_value(a: Value, b: Value) -> Value:
    """
    Add b to a, return a + b
    """
    if not a:
        return b
    if not b:
        return a
    return {
        pid: _add_token_names(
            a.get(pid, EMTPY_TOKENNAME_DICT), b.get(pid, EMTPY_TOKENNAME_DICT)
        )
        for pid in merge_without_duplicates(a.keys(), b.keys())
    }


def total_value(value_store_inputs: List[TxOut]) -> Value:
    """
    Calculate the total value of all inputs
    """
    total_value = EMPTY_VALUE_DICT
    for txo in value_store_inputs:
        total_value = add_value(total_value, txo.value)
    return total_value


def amount_of_token_in_value(
    token: Token,
    value: Value,
) -> int:
    return value.get(token.policy_id, {b"": 0}).get(token.token_name, 0)


def check_equal_except_ada_increase(a: Value, b: Value) -> None:
    """
    Check that the value of a is equal to the value of b, i.e. a == b
    except for the ada amount which can increase, i.e. a["ada"] >= b["ada"]
    """
    pids = merge_without_duplicates(a.keys(), b.keys())
    for policy_id in pids:
        if policy_id == b"":
            assert a.get(policy_id, EMTPY_TOKENNAME_DICT).get(b"", 0) >= b.get(
                policy_id, EMTPY_TOKENNAME_DICT
            ).get(b"", 0), f"Value of lovelace too low"
        else:
            a_tnd = a.get(policy_id, EMTPY_TOKENNAME_DICT)
            b_tnd = b.get(policy_id, EMTPY_TOKENNAME_DICT)
            tns = merge_without_duplicates(a_tnd.keys(), b_tnd.keys())
            for token_name in tns:
                assert a.get(policy_id, EMTPY_TOKENNAME_DICT).get(
                    token_name, 0
                ) == b.get(policy_id, EMTPY_TOKENNAME_DICT).get(
                    token_name, 0
                ), f"Value of additional token is not equal"


def check_preserves_value(
    previous_state_input: TxOut, next_state_output: TxOut
) -> None:
    """
    Check that the value of the previous state input is equal to the value of the next state output
    No additional tokens are to be added (except for ada) and no tokens are to be removed
    """
    previous_state_value = previous_state_input.value
    next_state_value = next_state_output.value
    check_equal_except_ada_increase(next_state_value, previous_state_value)
