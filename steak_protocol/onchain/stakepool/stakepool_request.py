"""
A request to add or remove stake for a stake pool that pools liquidity from multiple users and stakes it in the chain.
"""

from steak_protocol.onchain.util import *


@dataclass
class AddStakeRequest(PlutusData):
    CONSTR_ID = 2
    owner: PubKeyHash
    beneficiary: Address
    req_token: Token
    req_min_amount: int


@dataclass
class RemoveStakeRequest(PlutusData):
    CONSTR_ID = 3
    owner: PubKeyHash
    beneficiary: Address
    req_token: Token
    req_min_amount: int


@dataclass
class FillRequest(PlutusData):
    own_output_index: int
    CONSTR_ID = 4


@dataclass
class CancelRequest(PlutusData):
    CONSTR_ID = 5


StakeRequestRedeemer = Union[FillRequest, CancelRequest]


def validator(
    datum: Union[AddStakeRequest, RemoveStakeRequest],
    redeemer: StakeRequestRedeemer,
    context: ScriptContext,
) -> None:
    tx_info = context.tx_info
    purpose = get_spending_purpose(context)

    if isinstance(redeemer, CancelRequest):
        assert datum.owner in tx_info.signatories, "Owner must sign the transaction"
    elif isinstance(redeemer, FillRequest):
        own_output = tx_info.outputs[redeemer.own_output_index]
        assert (
            resolve_datum_unsafe(own_output, tx_info) == purpose.tx_out_ref
        ), "Output does not reference input"
        assert (
            amount_of_token_in_output(datum.req_token, own_output)
            >= datum.req_min_amount
        ), "Not enough tokens in output"
        assert own_output.address == datum.beneficiary, "Output must go to beneficiary"
    else:
        assert False, "Invalid redeemer"
