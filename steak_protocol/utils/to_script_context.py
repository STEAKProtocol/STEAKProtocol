import fractions
from typing import Optional

import pycardano
from opshin.prelude import *
from opshin.std.fractions import Fraction


def to_staking_credential(
    sk: Union[
        pycardano.VerificationKeyHash,
        pycardano.ScriptHash,
        pycardano.PointerAddress,
        None,
    ]
):
    try:
        return SomeStakingCredential(to_staking_hash(sk))
    except NotImplementedError:
        return NoStakingCredential()


def to_staking_hash(
    sk: Union[
        pycardano.VerificationKeyHash, pycardano.ScriptHash, pycardano.PointerAddress
    ]
):
    if isinstance(sk, pycardano.PointerAddress):
        return StakingPtr(sk.slot, sk.tx_index, sk.cert_index)
    if isinstance(sk, pycardano.VerificationKeyHash):
        return StakingHash(PubKeyCredential(sk.payload))
    if isinstance(sk, pycardano.ScriptHash):
        return StakingHash(ScriptCredential(sk.payload))
    raise NotImplementedError(f"Unknown stake key type {type(sk)}")


def to_wdrl(wdrl: Optional[pycardano.Withdrawals]) -> Dict[StakingCredential, int]:
    if wdrl is None:
        return {}

    def m(k: bytes):
        sk = pycardano.Address.from_primitive(k).staking_part
        return to_staking_hash(sk)

    return {m(key): val for key, val in wdrl.to_primitive().items()}


def to_valid_range(validity_start: Optional[int], ttl: Optional[int]):
    if validity_start is None:
        lower_bound = LowerBoundPOSIXTime(NegInfPOSIXTime(), FalseData())
    else:
        # TODO converting slot number to POSIXTime
        lower_bound = LowerBoundPOSIXTime(FinitePOSIXTime(validity_start), TrueData())
    if ttl is None:
        upper_bound = UpperBoundPOSIXTime(PosInfPOSIXTime(), FalseData())
    else:
        # TODO converting slot number to POSIXTime
        upper_bound = UpperBoundPOSIXTime(FinitePOSIXTime(ttl), TrueData())
    return POSIXTimeRange(lower_bound, upper_bound)


def to_pubkeyhash(vkh: pycardano.VerificationKeyHash):
    return PubKeyHash(vkh.to_primitive())


def to_tx_id(tx_id: pycardano.TransactionId):
    return TxId(tx_id.to_primitive())


def to_dcert(c: pycardano.Certificate) -> DCert:
    raise NotImplementedError("Can not convert certificates yet")


def multiasset_to_value(ma: pycardano.MultiAsset) -> Value:
    return {
        PolicyId(policy_id): {
            TokenName(asset_name): quantity for asset_name, quantity in asset.items()
        }
        for policy_id, asset in ma.to_shallow_primitive().items()
    }


def value_to_value(v: pycardano.Value):
    ma = multiasset_to_value(v.multi_asset)
    ma[b""][b""] = v.coin
    return ma


def to_payment_credential(
    c: Union[pycardano.VerificationKeyHash, pycardano.ScriptHash]
):
    if isinstance(c, pycardano.VerificationKeyHash):
        return PubKeyCredential(PubKeyHash(c.payload))
    if isinstance(c, pycardano.ScriptHash):
        return ScriptCredential(ValidatorHash(c.payload))
    raise NotImplementedError(f"Unknown payment key type {type(c)}")


def to_address(a: pycardano.Address):
    return Address(
        to_payment_credential(a.payment_part),
        to_staking_credential(a.staking_part),
    )


def to_tx_out(o: pycardano.TransactionOutput):
    if o.datum is not None:
        output_datum = SomeOutputDatum(o.datum)
    elif o.datum_hash is not None:
        output_datum = SomeOutputDatumHash(o.datum_hash.to_primitive())
    else:
        output_datum = NoOutputDatum()
    if o.script is None:
        script = NoScriptHash()
    else:
        script = SomeScriptHash(o.script.hash().to_primitive())
    return TxOut(
        to_address(o.address),
        value_to_value(o.amount),
        output_datum,
        script,
    )


def to_tx_out_ref(i: pycardano.TransactionInput):
    return TxOutRef(
        TxId(i.transaction_id.to_primitive()),
        i.index,
    )


def to_tx_in_info(i: pycardano.TransactionInput, o: pycardano.TransactionOutput):
    return TxInInfo(
        to_tx_out_ref(i),
        to_tx_out(o),
    )


def to_tx_info(
    tx: pycardano.Transaction,
    resolved_inputs: List[pycardano.TransactionOutput],
    resolved_reference_inputs: List[pycardano.TransactionOutput],
):
    tx_body = tx.transaction_body
    return TxInfo(
        [to_tx_in_info(i, o) for i, o in zip(tx_body.inputs, resolved_inputs)],
        [
            to_tx_in_info(i, o)
            for i, o in zip(tx_body.reference_inputs, resolved_reference_inputs)
        ],
        [to_tx_out(o) for o in tx_body.outputs],
        value_to_value(pycardano.Value(tx_body.fee)),
        multiasset_to_value(tx_body.mint),
        [to_dcert(c) for c in tx_body.certificates],
        to_wdrl(tx_body.withdraws),
        to_valid_range(tx_body.validity_start, tx_body.ttl),
        [to_pubkeyhash(s) for s in tx_body.required_signers],
        {
            pycardano.datum_hash(d): d
            for d in [
                o.datum
                for o in tx_body.outputs + resolved_inputs + resolved_reference_inputs
                if o.datum is not None
            ]
            + tx.transaction_witness_set.plutus_data
        },
        {pycardano.datum_hash(r): r for r in tx.transaction_witness_set.redeemer},
        to_tx_id(tx_body.id),
    )


def to_fraction(f: fractions.Fraction):
    return Fraction(f.numerator, f.denominator)
