"""
A stake holder participating in the stake coin protocol.
It can be registered by interacting with the stake chain and minting a registration token (stakeholder_auth_nft).
The stake is locked until a user-specified deadline and will be automatically deregistered after that.
The owner can withdraw the stake after the deregistration deadline.
It can be controlled (owned) by a pubkey or script credential.
If a script credential is specified, a corresponding withdrawal has to be present in the transaction.

Registration is performed by sending a RegisterStake transaction to the stake chain contract
and minting a corresponding registration token (which depends on approval by the stake chain contract).
"""

from steak_protocol.onchain.util import *


@dataclass
class DeregisterStake(PlutusData):
    CONSTR_ID = 2
    own_input_index: int
    chain_input_index: int


@dataclass
class UpdateStake(PlutusData):
    CONSTR_ID = 3
    own_input_index: int
    chain_input_index: int
    own_output_index: int


StakeHolderRedeemer = Union[DeregisterStake, UpdateStake]


def validator(
    holder_state: StakeHolderState,
    redeemer: StakeHolderRedeemer,
    context: ScriptContext,
) -> None:
    tx_info = context.tx_info
    purpose = get_spending_purpose(context)
    own_input = tx_info.inputs[redeemer.own_input_index]
    assert purpose.tx_out_ref == own_input.out_ref, "Referenced wrong input"
    holder_params = holder_state.params

    # require that the chain witnesses the transaction
    holder_input = tx_info.inputs[redeemer.chain_input_index]
    assert (
        amount_of_token_in_output(holder_params.chain_auth_nft, holder_input.resolved)
        == 1
    ), "Chain must have exactly one auth NFT"

    # Check that the auth nft is correctly handled and not removed
    stakeholder_auth_nft = holder_params.stakeholder_auth_nft
    if isinstance(redeemer, DeregisterStake):
        check_mint_exactly_n_with_name(
            tx_info.mint,
            -1,
            stakeholder_auth_nft.policy_id,
            stakeholder_auth_nft.token_name,
        ), "Must burn the auth NFT"
    elif isinstance(redeemer, UpdateStake):
        own_output = tx_info.outputs[redeemer.own_output_index]
        assert token_present_in_output(
            holder_params.stakeholder_auth_nft, own_output
        ), "Must preserve the auth NFT"
        assert (
            not stakeholder_auth_nft.policy_id in tx_info.mint.keys()
        ), "Must not mint the auth NFT"
    else:
        assert False, "Invalid redeemer"

    # only allow linear inputs
    stakeholder_inputs = sum(
        [
            amount_of_token_in_output(stakeholder_auth_nft, i.resolved)
            for i in tx_info.inputs
        ]
    )
    assert stakeholder_inputs == 1, "Must have exactly one input from stake holder"

    # require signature of owner
    check_owner_signed_tx(holder_params.owner, tx_info)
