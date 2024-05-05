"""
The STK token is the reward token for the StakeChain. Its total supply is minted once and distributed to the stakers
during the progressing of the protocol.
"""

from steak_protocol.onchain.util import *


@dataclass
class Mint(PlutusData):
    CONSTR_ID = 0
    input_index: int


@dataclass
class Burn(PlutusData):
    CONSTR_ID = 1


def validator(
    input_txo: TxOutRef, redeemer: Union[Mint, Burn], context: ScriptContext
) -> None:
    if isinstance(redeemer, Mint):
        assert (
            context.tx_info.inputs[redeemer.input_index].out_ref == input_txo
        ), "Does not spend relevant txout"
    else:
        purpose = get_minting_purpose(context)
        own_mint = context.tx_info.mint[purpose.policy_id]
        assert all([x < 0 for x in own_mint.values()]), "Does not burn all tokens"
