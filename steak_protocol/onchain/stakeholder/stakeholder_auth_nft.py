"""
Token to authenticate a stake holder position against the stake chain contract.
The NFT is unique and can only be minted when the stake chain contract approves the transaction.
"""

from steak_protocol.onchain.util import *


@dataclass
class Mint(PlutusData):
    CONSTR_ID = 0
    chain_input_index: int


@dataclass
class Burn(PlutusData):
    CONSTR_ID = 1


AuthNFTRedeemer = Union[Mint, Burn]


def validator(
    stakechain_auth_nft: Token,
    redeemer: AuthNFTRedeemer,
    context: ScriptContext,
) -> None:
    tx_info = context.tx_info
    purpose = get_minting_purpose(context)
    own_pid = purpose.policy_id
    own_auth_nft = Token(own_pid, stakechain_auth_nft.token_name)

    if isinstance(redeemer, Mint):
        chain_input_info = tx_info.inputs[redeemer.chain_input_index]
        chain_input = chain_input_info.resolved
        assert (
            amount_of_token_in_output(stakechain_auth_nft, chain_input) == 1
        ), "Chain must have exactly one auth NFT"
        stake_chain_state: StakeChainV0State = resolve_datum_unsafe(
            chain_input, tx_info
        )
        stakeholder_auth_nft = stake_chain_state.params.stakeholder_auth_nft
        stakeholder_outputs = [
            o
            for o in tx_info.outputs
            if amount_of_token_in_output(stakeholder_auth_nft, o) == 1
        ]
        assert (
            len(stakeholder_outputs) == 1
        ), "Must have exactly one output to stake holder"
        stakeholder_output = stakeholder_outputs[0]

        check_mint_exactly_one_to_output(tx_info.mint, own_auth_nft, stakeholder_output)

        stakeholder_datum: StakeHolderState = resolve_datum_unsafe(
            stakeholder_output, tx_info
        )
        assert (
            stakeholder_datum.params.stakeholder_auth_nft == own_auth_nft
        ), "Auth NFT must match own auth NFT"
    else:
        assert all(
            [x < 0 for x in tx_info.mint[own_pid].values()]
        ), "Must burn all tokens"
