from opshin.prelude import *
from opshin.ledger.interval import *


def validator(
    minutxo_addr: Address,
    admin: PubKeyHash,
    expiry_date: POSIXTime,
    recp: PubKeyHash,
    redeemer: int,
    context: ScriptContext,
) -> None:
    tx_info = context.tx_info
    if redeemer >= 0:
        assert recp in tx_info.signatories, "Owner must sign the transaction"
        assert (
            tx_info.outputs[redeemer].address == minutxo_addr
        ), "One Output must go to minutxo_addr"
    else:
        assert admin in tx_info.signatories, "Owner must sign the transaction"
        lower_bound: FinitePOSIXTime = tx_info.valid_range.lower_bound.limit
        assert lower_bound.time >= expiry_date, "Contract has not yet expired"
