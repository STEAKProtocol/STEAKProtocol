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
        target_output = tx_info.outputs[redeemer]
        assert (
            target_output.address == minutxo_addr
        ), "One Output must go to minutxo_addr"
        purpose: Spending = context.purpose
        assert (
            resolve_datum_unsafe(target_output, tx_info) == purpose.tx_out_ref
        ), "Datum must be the tx_out_ref"
        assert (
            target_output.value[b""][b""] >= 2_500_000
        ), "Output must have value of 2_500_000 lovelace"
    else:
        assert admin in tx_info.signatories, "Owner must sign the transaction"
        lower_bound: FinitePOSIXTime = tx_info.valid_range.lower_bound.limit
        assert lower_bound.time >= expiry_date, "Contract has not yet expired"
