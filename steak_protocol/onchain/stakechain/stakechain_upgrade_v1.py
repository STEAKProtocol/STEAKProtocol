"""
A withdrawal script that certifies correct upgrades of the stakechain based on consensus among stakeholders.
"""

from opshin.std.integrity import check_integrity

from steak_protocol.onchain.util import *
from steak_protocol.onchain.utils.value import *


@dataclass
class SomeValue(PlutusData):
    CONSTR_ID = 0
    value: Value


@dataclass
class ChainUpgradeProposal(PlutusData):
    CONSTR_ID = 120
    # the new address of the protocol
    upgrade_address: Union[Address, Nothing]
    # the new parameters of the protocol
    upgrade_params: Union[StakeChainV1Params, Nothing]
    # payout of funds governed by the protocol
    payout_txout: Union[TxOut, Nothing]
    # taking in treasury funds
    take_treasury: Union[SomeValue, Nothing]


@dataclass
class ChainUpgrade(PlutusData):
    CONSTR_ID = 0
    previous_states: List[ProducerState]
    upgrade_proposal: ChainUpgradeProposal
    prev_chain_state_index: int
    next_chain_state_index: int
    # ignored if no payout specified
    payout_index: int


def validator(
    agreement_length: int,
    stakechain_auth_nft: Token,
    redeemer: ChainUpgrade,
    context: ScriptContext,
) -> None:
    purpose = context.purpose
    assert isinstance(purpose, Rewarding), "wrong script purpose"
    # obtain the current staking state
    tx_info = context.tx_info
    prev_chain_state_output_info = tx_info.inputs[redeemer.prev_chain_state_index]
    prev_chain_state_output = prev_chain_state_output_info.resolved
    assert (
        amount_of_token_in_output(stakechain_auth_nft, prev_chain_state_output) == 1
    ), "Wrong stake chain output referenced"
    prev_chain_state: StakeChainV1State = resolve_datum_unsafe(
        prev_chain_state_output, tx_info
    )

    # check that the proposal was agreed by all n preceding blocks
    proposal = redeemer.upgrade_proposal
    proposal_hash = SomeOutputDatumHash(blake2b_256(proposal.to_cbor()))
    chain_state = prev_chain_state.producer_state
    assert (
        chain_state.auxiliary == proposal_hash
        or chain_state.auxiliary == SomeOutputDatum(proposal)
    ), "Block did not agree to upgrade"

    assert (
        len(redeemer.previous_states) == agreement_length - 1
    ), "Not enough blocks provided"
    for prev_state in redeemer.previous_states:
        assert chain_state.prev_producer_state_hash == sha2_256(
            prev_state.to_cbor()
        ), "Incorrect previous producer state hash"
        chain_state = prev_state

        assert (
            prev_state.auxiliary == proposal_hash
            or prev_state.auxiliary == SomeOutputDatum(proposal)
        ), "Block did not agree to upgrade"

    # no other scripts involved
    assert len(tx_info.redeemers) == 2, "Only upgrade and holder script must be invoked"

    # check that the new output agrees with the upgrade
    new_chain_state_output = tx_info.outputs[redeemer.next_chain_state_index]
    assert (
        amount_of_token_in_output(stakechain_auth_nft, new_chain_state_output) == 1
    ), "auth nft must be present"
    new_chain_state: StakeChainV1State = resolve_datum_unsafe(
        new_chain_state_output, tx_info
    )

    # check state upgrade or preservation
    upgrade_params = proposal.upgrade_params
    if isinstance(upgrade_params, StakeChainV1Params):
        new_params = upgrade_params
    else:
        new_params = prev_chain_state.params

    new_desired_chain_state = StakeChainV1State(
        new_params,
        prev_chain_state.holder_state,
        prev_chain_state.chain_state,
        prev_chain_state.producer_state,
        prev_chain_state.skip_holders,
        prev_chain_state_output_info.out_ref,
    )
    assert new_desired_chain_state == new_chain_state, "Incorrect state upgrade"

    # check address upgrade or preservation
    upgrade_address = proposal.upgrade_address
    if isinstance(upgrade_address, Address):
        new_address = upgrade_address
    else:
        new_address = prev_chain_state_output.address
    assert new_address == new_chain_state_output.address, "Incorrect address upgrade"

    # check value preservation and payout
    expected_value_after_upgrade = prev_chain_state_output.value

    take_treasury = proposal.take_treasury
    if isinstance(take_treasury, SomeValue):
        expected_value_after_upgrade = add_value(
            take_treasury.value, expected_value_after_upgrade
        )
    upgrade_payout = proposal.payout_txout
    if isinstance(upgrade_payout, TxOut):
        payout_output = tx_info.outputs[redeemer.payout_index]
        # do modular comparison to allow for ada increase
        check_equal_except_ada_increase(payout_output.value, upgrade_payout.value)
        assert payout_output.address == upgrade_payout.address, "Payout address wrong"
        assert payout_output.datum == upgrade_payout.datum, "Payout datum wrong"
        assert (
            payout_output.reference_script == upgrade_payout.reference_script
        ), "Reference script wrong"

        expected_value_after_upgrade = subtract_value(
            expected_value_after_upgrade, upgrade_payout.value
        )
    check_equal_except_ada_increase(
        expected_value_after_upgrade, new_chain_state_output.value
    )
