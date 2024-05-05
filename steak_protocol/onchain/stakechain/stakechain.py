"""
The main protocol implementation. It controls the addition of new blocks
and the distribution of miner rewards.
"""

from opshin.std.integrity import check_integrity

from steak_protocol.onchain.types import *
from steak_protocol.onchain.util import *
from steak_protocol.onchain.utils.random import *
from steak_protocol.onchain.utils.value import *


@dataclass
class RegisterStake(PlutusData):
    CONSTR_ID = 2
    old_state_index: int
    new_state_index: int
    new_stake_index: int


@dataclass
class DeregisterStake(PlutusData):
    CONSTR_ID = 3
    old_state_index: int
    new_state_index: int
    old_stake_index: int
    stake_index_in_holder_list: int


@dataclass
class UpdateStake(PlutusData):
    CONSTR_ID = 4
    old_state_index: int
    new_state_index: int
    old_stake_index: int
    new_stake_index: int
    stake_index_in_holder_list: int


@dataclass
class MineBlockUpdateStake(PlutusData):
    CONSTR_ID = 5
    old_state_index: int
    new_state_index: int
    producing_holder_ref_utxo_index: int
    elected_slot_leader: int
    slot_leader_secret: bytes
    slot_leader_sig: bytes
    aux: OutputDatum
    old_stake_index: int
    new_stake_index: int
    stake_index_in_holder_list: int


@dataclass
class UpgradeProtocol(PlutusData):
    CONSTR_ID = 6


StateRedeemer = Union[
    RegisterStake,
    DeregisterStake,
    UpdateStake,
    MineBlockUpdateStake,
    UpgradeProtocol,
]


def check_slot_of_tx(
    suggested_slot: int,
    genesis_time: POSIXTime,
    slot_length: POSIXTime,
    tx_info: TxInfo,
) -> None:
    """
    Computes the slot of the current transaction
    and makes sure that the validity interval is entirely within
    the current slot.
    """
    valid_range = tx_info.valid_range
    min_acceptable_lower_bound = genesis_time + slot_length * suggested_slot
    max_acceptable_upper_bound = min_acceptable_lower_bound + slot_length
    assert contains(
        make_range(min_acceptable_lower_bound, max_acceptable_upper_bound), valid_range
    ), "Transaction not in current slot"


def check_valid_stake_holder(
    stake_holder_state: StakeHolderState,
    stake_output: TxOut,
    own_prev_state: StakeChainState,
    tx_info: TxInfo,
):
    """
    Check that the stake holder state is valid
    """
    check_owner_signed_tx(stake_holder_state.params.owner, tx_info)
    assert (
        amount_of_token_in_output(
            own_prev_state.params.stakeholder_auth_nft, stake_output
        )
        == 1
    ), "Auth NFT not present in referenced holder"
    assert (
        stake_holder_state.params.chain_auth_nft == own_prev_state.params.auth_nft
    ), "Auth NFT not matching"
    assert (
        stake_output.address == own_prev_state.params.stakeholder_address
    ), "Stake holder address not matching"


def new_chain_state(
    own_next_state: StakeChainState,
    own_prev_state: StakeChainState,
    tx_info: TxInfo,
    elected_slot_leader: int,
) -> CoreChainState:
    # check that the chain state is correct
    new_slot_number = own_next_state.chain_state.slot_number
    params = own_prev_state.params
    # check that the slot number looks correct
    check_slot_of_tx(
        new_slot_number,
        params.genesis_time,
        params.slot_length,
        tx_info,
    )
    block_number = own_prev_state.chain_state.block_number + 1
    return CoreChainState(
        block_number,
        # we generate the block hash based on preceding block
        # and preceding block producer sig and slot leader that produced the block
        sha2_256(
            bytes_big_from_unsigned_int(elected_slot_leader)
            + own_prev_state.chain_state.to_cbor()
            + own_prev_state.producer_state.producer_signature
        ),
        new_slot_number,
    )


def compute_slot_leader(
    state: StakeChainState,
    current_slot_number: int,
    slot_leader_number: int,
) -> int:
    """
    The slot leader is determined by a weighted sample from the list
    of registered stake holders.
    The randomness of the coin toss stems from the previous state hash
    and the current slot number and the slot leader that produced the block.

    Note that the previous hash depends only on the chain state of the before-previous block
    hence the slot leader of block t can not be influenced by producer t-1 but only t-2,
    decreasing the predictibility and manipulatibility of follow up block producers.
    The current slot number can not be influenced at all but is also not predictable.
    The elected slot leader number is only marginally influencable (should be between 0 and 5-10).
    """
    rng_seed = (
        bytes_big_from_unsigned_int(slot_leader_number)
        + state.chain_state.block_hash
        + bytes_big_from_unsigned_int(current_slot_number)
    )
    skip_holders = state.skip_holders
    slot_leader_index = weighted_sample(
        state.holder_state.stake_holder_weights[skip_holders:], rng_seed
    )
    return max([0, slot_leader_index + skip_holders])


def check_correct_producer(
    prev_state: StakeChainState,
    slot_number: int,
    redeemer: MineBlockUpdateStake,
    tx_info: TxInfo,
    new_chain_state: CoreChainState,
) -> None:
    """
    Checks that
    1. the producer is a valid producer and correctly signed the transaction
    2. the producer is the correct producer as selected by the slot protocol
    3. the producer signed the block with the correct slot leader signature
    Note: the correctness of the slot number and validity is checked in check_correct_new_state
    """
    producing_holder_info = tx_info.reference_inputs[
        redeemer.producing_holder_ref_utxo_index
    ]
    producing_holder_ref_input = producing_holder_info.resolved
    producing_holder_state: StakeHolderState = resolve_datum_unsafe(
        producing_holder_ref_input, tx_info
    )

    # 1
    check_valid_stake_holder(
        producing_holder_state, producing_holder_ref_input, prev_state, tx_info
    )

    # 2
    slot_leader = compute_slot_leader(
        prev_state,
        slot_number,
        redeemer.elected_slot_leader,
    )
    assert (
        producing_holder_state.params.stakechain_id
        == prev_state.holder_state.stake_holder_ids[slot_leader]
    ), "Stake holder is not current slot leader"
    assert (
        redeemer.elected_slot_leader <= prev_state.params.num_slot_leaders
    ), "Stake holder is not allowed to mint slot"

    # 3
    verify_commited_signature(
        redeemer.slot_leader_secret,
        producing_holder_state.committed_hashes[0],
        # the block contains slot number and block number and block hash
        # it does not include the previous input hash to reduce influence
        new_chain_state.to_cbor(),
        redeemer.slot_leader_sig,
    )


def check_correct_mine_value_update(
    own_prev_state: StakeChainState,
    own_prev_input: TxOut,
    own_next_output: TxOut,
):
    params = own_prev_state.params
    stake_coin = params.stake_coin
    prev_reserve_amount = amount_of_token_in_output(stake_coin, own_prev_input)
    amount_to_be_distributed = floor_fraction(
        scale_fraction(prev_reserve_amount, params.fraction_per_block)
    )

    prev_value = own_prev_input.value
    prev_value_without_amount = subtract_value(
        prev_value,
        {stake_coin.policy_id: {stake_coin.token_name: amount_to_be_distributed}},
    )
    next_value = own_next_output.value
    check_equal_except_ada_increase(next_value, prev_value_without_amount)


def check_correct_register_value_update(
    own_prev_state: StakeChainState,
    own_prev_input: TxOut,
    own_next_output: TxOut,
):
    params = own_prev_state.params
    stake_coin = params.stake_coin
    fee_amount = params.register_fee

    prev_value = own_prev_input.value
    prev_value_with_fee = add_value(
        prev_value,
        {stake_coin.policy_id: {stake_coin.token_name: fee_amount}},
    )
    next_value = own_next_output.value
    check_equal_except_ada_increase(next_value, prev_value_with_fee)


def check_correct_update_value_update(
    own_prev_input: TxOut,
    own_next_output: TxOut,
):
    prev_value = own_prev_input.value
    next_value = own_next_output.value
    check_equal_except_ada_increase(next_value, prev_value)


def check_correct_new_registered_state(
    own_next_state: StakeChainState,
    own_prev_state: StakeChainState,
    own_pref_ref_input: TxOutRef,
    stake_holder_state: StakeHolderState,
    stake_holder_output: TxOut,
) -> None:
    stake_coin = own_prev_state.params.stake_coin
    added_holder_weight = amount_of_token_in_output(stake_coin, stake_holder_output)
    added_holder_id = stake_holder_state.params.stakechain_id
    prev_holder_state = own_prev_state.holder_state
    # check that the added holder is correctly added to the state
    assert (
        not added_holder_id in prev_holder_state.stake_holder_ids
    ), "Pool id already taken"
    assert len(added_holder_id) <= 5, "Pool id too long"
    new_desired_holder_state = StakeHolderRegistrations(
        [added_holder_weight] + prev_holder_state.stake_holder_weights,
        [added_holder_id] + prev_holder_state.stake_holder_ids,
    )
    # check that the overall state is correctly updated
    new_desired_state = StakeChainState(
        own_prev_state.params,
        new_desired_holder_state,
        own_prev_state.chain_state,
        own_prev_state.producer_state,
        own_prev_state.skip_holders + 1,
        own_pref_ref_input,
    )
    assert own_next_state == new_desired_state, "New state is incorrect"


def check_correct_new_deregistered_state(
    own_next_state: StakeChainState,
    own_prev_state: StakeChainState,
    own_prev_ref_input: TxOutRef,
    stake_holder_state: StakeHolderState,
    holder_index: int,
) -> None:
    removed_holder_id = stake_holder_state.params.stakechain_id
    prev_holder_state = own_prev_state.holder_state
    # two possibilities: either the holder was contained in the state before -> no change to list, negative index
    # or the holder was not contained in the state before -> change to list
    if holder_index >= 0:
        # check that the removed pool is correctly removed from the state
        assert (
            prev_holder_state.stake_holder_ids[holder_index] == removed_holder_id
        ), "Pool id incorrect"
        new_desired_holder_state = StakeHolderRegistrations(
            remove_int_at_index(prev_holder_state.stake_holder_weights, holder_index),
            remove_bytes_at_index(prev_holder_state.stake_holder_ids, holder_index),
        )
        # skip holders is decremented if the removed holder was to be skipped
        # ensures that deregistering a holder can not be used to manipulate the slot leader
        skip_holder_delta = int(holder_index < own_prev_state.skip_holders)
    else:
        assert (
            not removed_holder_id in prev_holder_state.stake_holder_ids
        ), "Pool id present in chain"
        new_desired_holder_state = prev_holder_state
        skip_holder_delta = 0
    # check that the overall state is correctly updated
    new_desired_state = StakeChainState(
        own_prev_state.params,
        new_desired_holder_state,
        own_prev_state.chain_state,
        own_prev_state.producer_state,
        own_prev_state.skip_holders - skip_holder_delta,
        own_prev_ref_input,
    )
    assert own_next_state == new_desired_state, "New state is incorrect"


def check_correct_new_updated_state(
    own_next_state: StakeChainState,
    own_prev_state: StakeChainState,
    own_prev_ref_input: TxOutRef,
    prev_stake_holder_state: StakeHolderState,
    stake_holder_output: TxOut,
    holder_index: int,
    stake_coin: Token,
) -> None:
    updated_holder_id = prev_stake_holder_state.params.stakechain_id
    prev_holder_state = own_prev_state.holder_state
    new_holder_weight = amount_of_token_in_output(stake_coin, stake_holder_output)
    # check that the added holder is correctly added to the state
    assert (
        0 <= holder_index < len(prev_holder_state.stake_holder_ids)
    ), "Pool index out of bounds"
    assert (
        prev_holder_state.stake_holder_ids[holder_index] == updated_holder_id
    ), "Pool id incorrect"
    new_desired_holder_state = StakeHolderRegistrations(
        prev_holder_state.stake_holder_weights[:holder_index]
        + [new_holder_weight]
        + prev_holder_state.stake_holder_weights[holder_index + 1 :],
        prev_holder_state.stake_holder_ids,
    )
    # check that the overall state is correctly updated
    new_desired_state = StakeChainState(
        own_prev_state.params,
        new_desired_holder_state,
        own_prev_state.chain_state,
        own_prev_state.producer_state,
        own_prev_state.skip_holders,
        own_prev_ref_input,
    )
    assert own_next_state == new_desired_state, "New state is incorrect"


def check_correct_new_updated_mined_state(
    own_next_state: StakeChainState,
    own_prev_state: StakeChainState,
    own_prev_input_ref: TxOutRef,
    tx_info: TxInfo,
    redeemer: MineBlockUpdateStake,
    prev_stake_holder_state: StakeHolderState,
    stake_holder_output: TxOut,
    holder_index: int,
    stake_coin: Token,
) -> CoreChainState:
    params = own_prev_state.params
    # check that the added holder is correctly added to the state
    updated_holder_id = prev_stake_holder_state.params.stakechain_id
    prev_holder_state = own_prev_state.holder_state
    new_holder_weight = amount_of_token_in_output(stake_coin, stake_holder_output)
    # check that the added holder is correctly added to the state
    assert (
        0 <= holder_index < len(prev_holder_state.stake_holder_ids)
    ), "Pool index out of bounds"
    assert (
        prev_holder_state.stake_holder_ids[holder_index] == updated_holder_id
    ), "Pool id incorrect"
    new_desired_holder_state = StakeHolderRegistrations(
        prev_holder_state.stake_holder_weights[:holder_index]
        + [new_holder_weight]
        + prev_holder_state.stake_holder_weights[holder_index + 1 :],
        prev_holder_state.stake_holder_ids,
    )
    # check that the state overall looks correct
    # this includes a check for integrity
    aux = redeemer.aux
    assert len(aux.to_cbor()) < 100, "Attached too long aux data"
    generated_new_chain_state = new_chain_state(
        own_next_state,
        own_prev_state,
        tx_info,
        redeemer.elected_slot_leader,
    )
    # check that slot number is strictly increasing
    assert (
        generated_new_chain_state.slot_number > own_prev_state.chain_state.slot_number
    ), "Slot number not strictly increasing"
    desired_new_producer_state = ProducerState(
        redeemer.slot_leader_sig,
        aux,
        sha2_256(own_prev_state.producer_state.to_cbor()),
    )
    desired_new_state = StakeChainState(
        params,
        new_desired_holder_state,
        generated_new_chain_state,
        desired_new_producer_state,
        # reset skip holders
        0,
        own_prev_input_ref,
    )
    assert own_next_state == desired_new_state, "New state is incorrect"
    return generated_new_chain_state


def number_stake_holders_spent(own_prev_state: StakeChainState, tx_info: TxInfo) -> int:
    stakeholder_auth_nft = own_prev_state.params.stakeholder_auth_nft
    # check that no other auth nft is spent
    return sum(
        [
            amount_of_token_in_output(stakeholder_auth_nft, o.resolved)
            for o in tx_info.inputs
        ]
    )


def check_no_stake_holder_spent(own_prev_state: StakeChainState, tx_info: TxInfo):
    assert (
        number_stake_holders_spent(own_prev_state, tx_info) == 0
    ), "Tried to unlock tokens from registered holder"


def check_one_stake_holder_spent(own_prev_state: StakeChainState, tx_info: TxInfo):
    assert (
        number_stake_holders_spent(own_prev_state, tx_info) == 1
    ), "Tried to unlock more tokens from registered holder"


def check_burn_one_auth_nft(own_prev_state: StakeChainState, tx_info: TxInfo):
    stakeholder_auth_nft = own_prev_state.params.stakeholder_auth_nft
    # check that the stake holder auth nft is burned
    check_mint_exactly_n_with_name(
        tx_info.mint,
        -1,
        stakeholder_auth_nft.policy_id,
        stakeholder_auth_nft.token_name,
    )


def check_mint_one_auth_nft(own_prev_state: StakeChainState, tx_info: TxInfo):
    stakeholder_auth_nft = own_prev_state.params.stakeholder_auth_nft
    # check that the stake holder auth nft is minted
    check_mint_exactly_n_with_name(
        tx_info.mint,
        1,
        stakeholder_auth_nft.policy_id,
        stakeholder_auth_nft.token_name,
    )


def check_no_auth_nft_mint(own_prev_state: StakeChainState, tx_info: TxInfo):
    stakeholder_auth_nft = own_prev_state.params.stakeholder_auth_nft
    assert not stakeholder_auth_nft.policy_id in tx_info.mint.keys(), "Auth NFT minted"


def validator(
    state: StakeChainState, redeemer: StateRedeemer, context: ScriptContext
) -> None:
    tx_info = context.tx_info

    if isinstance(redeemer, UpgradeProtocol):
        # Check that the upgrade approval contract signed the transaction
        # No other check required
        check_owner_signed_tx(state.params.upgrade_approval, tx_info)
    else:
        purpose = get_spending_purpose(context)

        own_prev_input_ref = purpose.tx_out_ref
        own_prev_input = resolve_linear_input(
            context.tx_info, redeemer.old_state_index, purpose
        )
        own_prev_state = state

        own_next_output = resolve_linear_output(
            own_prev_input, tx_info, redeemer.new_state_index
        )
        own_next_state: StakeChainState = resolve_datum_unsafe(own_next_output, tx_info)
        # Always check that the output is reasonably sized
        check_output_reasonably_sized(own_next_output, own_next_state, 15000)

        if isinstance(redeemer, RegisterStake):
            # A new stake holder is created
            # Check that the changes to the stakechain datum are correct
            # and match the created holder
            stake_output = tx_info.outputs[redeemer.new_stake_index]
            stake_holder_state: StakeHolderState = resolve_datum_unsafe(
                stake_output, tx_info
            )

            # check that max holder number not exceeded
            assert (
                len(own_next_state.holder_state.stake_holder_ids)
                <= state.params.max_holders
            ), "Max number of holders exceeded"

            # check that the new state is valid
            check_correct_new_registered_state(
                own_next_state,
                own_prev_state,
                own_prev_input_ref,
                stake_holder_state,
                stake_output,
            )

            # check that the stake holder owner signed the transaction
            check_valid_stake_holder(
                stake_holder_state, stake_output, own_prev_state, tx_info
            )
            # check that the block producer pubkey is valid
            assert (
                len(stake_holder_state.committed_hashes) >= 5
            ), "Not enough hashes commited"
            # NOTE: we can not further prove that the hashes are correct
            assert all(
                [len(h) == 32 for h in stake_holder_state.committed_hashes]
            ), "Invalid hash length"

            # Check that the registration fee is paid
            check_correct_register_value_update(
                own_prev_state, own_prev_input, own_next_output
            )
            # Check that no stake holder is spent and one auth nft is minted
            check_no_stake_holder_spent(own_prev_state, tx_info)
            check_mint_one_auth_nft(own_prev_state, tx_info)
        elif isinstance(redeemer, DeregisterStake):
            # An existing stake holder is dropped
            stake_output_info = tx_info.inputs[redeemer.old_stake_index]
            stake_output = stake_output_info.resolved
            stake_holder_state: StakeHolderState = resolve_datum_unsafe(
                stake_output, tx_info
            )

            # check that the new state is valid
            check_correct_new_deregistered_state(
                own_next_state,
                own_prev_state,
                own_prev_input_ref,
                stake_holder_state,
                redeemer.stake_index_in_holder_list,
            )

            # check that the old stake holder was a valid holder and approved the transaction
            check_valid_stake_holder(
                stake_holder_state, stake_output, own_prev_state, tx_info
            )

            # Check that the registration fee is paid
            check_correct_register_value_update(
                own_prev_state, own_prev_input, own_next_output
            )
            check_one_stake_holder_spent(own_prev_state, tx_info)
            check_burn_one_auth_nft(own_prev_state, tx_info)
        elif isinstance(redeemer, UpdateStake):
            # Update the registered stake of a specific holder
            stake_input_info = tx_info.inputs[redeemer.old_stake_index]
            stake_input = stake_input_info.resolved
            prev_stake_holder_state: StakeHolderState = resolve_datum_unsafe(
                stake_input, tx_info
            )
            stake_output = tx_info.outputs[redeemer.new_stake_index]
            next_stake_holder_state: StakeHolderState = resolve_datum_unsafe(
                stake_output, tx_info
            )

            # check that the new state is valid
            check_correct_new_updated_state(
                own_next_state,
                own_prev_state,
                own_prev_input_ref,
                prev_stake_holder_state,
                stake_output,
                redeemer.stake_index_in_holder_list,
                own_prev_state.params.stake_coin,
            )

            # check that the stake holders are valid
            check_valid_stake_holder(
                prev_stake_holder_state, stake_input, own_prev_state, tx_info
            )
            check_valid_stake_holder(
                next_stake_holder_state, stake_output, own_prev_state, tx_info
            )
            assert (
                prev_stake_holder_state.params == next_stake_holder_state.params
            ), "Stake holder state params changed"

            # Check that the value is preserved
            check_correct_update_value_update(own_prev_input, own_next_output)
            check_one_stake_holder_spent(own_prev_state, tx_info)
            check_no_auth_nft_mint(own_prev_state, tx_info)
        elif isinstance(redeemer, MineBlockUpdateStake):
            # Update the registered stake of a specific holder with the rewards of a new block
            stake_input_info = tx_info.inputs[redeemer.old_stake_index]
            stake_input = stake_input_info.resolved
            prev_stake_holder_state: StakeHolderState = resolve_datum_unsafe(
                stake_input, tx_info
            )
            stake_output = tx_info.outputs[redeemer.new_stake_index]
            next_stake_holder_state: StakeHolderState = resolve_datum_unsafe(
                stake_output, tx_info
            )

            # check that the new state is valid
            generated_new_chain_state = check_correct_new_updated_mined_state(
                own_next_state,
                own_prev_state,
                own_prev_input_ref,
                tx_info,
                redeemer,
                prev_stake_holder_state,
                stake_output,
                redeemer.stake_index_in_holder_list,
                own_prev_state.params.stake_coin,
            )
            # Check that the producer is allowed to add this state
            check_correct_producer(
                own_prev_state,
                own_next_state.chain_state.slot_number,
                redeemer,
                tx_info,
                generated_new_chain_state,
            )

            # check that the stake holders are valid
            check_valid_stake_holder(
                prev_stake_holder_state, stake_input, own_prev_state, tx_info
            )
            check_valid_stake_holder(
                next_stake_holder_state, stake_output, own_prev_state, tx_info
            )
            assert (
                prev_stake_holder_state.params == next_stake_holder_state.params
            ), "Stake holder state params changed"
            assert serialise_data(
                prev_stake_holder_state.committed_hashes[1:]
            ) == serialise_data(
                next_stake_holder_state.committed_hashes[:-1]
            ), "Did not correctly update commited hashes"
            assert (
                len(next_stake_holder_state.committed_hashes[-1]) == 32
            ), "Invalid hash length"

            # Check that the rewards are distributed correctly
            # And the auth nft is preserved
            check_correct_mine_value_update(
                own_prev_state, own_prev_input, own_next_output
            )
            check_no_auth_nft_mint(own_prev_state, tx_info)
            check_one_stake_holder_spent(own_prev_state, tx_info)
        else:
            assert False, "Invalid redeemer"
