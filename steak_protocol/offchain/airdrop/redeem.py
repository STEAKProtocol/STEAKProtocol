import secrets
from hashlib import sha256

import fire
import pycardano
from opshin.ledger.api_v2 import PubKeyCredential, NoOutputDatum
from opshin.prelude import Token
from pycardano import (
    TransactionBuilder,
    script_hash,
    TransactionOutput,
    Value,
    Redeemer,
    DeserializeException,
    RawPlutusData,
)

from steak_protocol.offchain.util import (
    sorted_utxos,
    with_min_lovelace,
    asset_from_token,
    STAKE_CHAIN_AUTH_NFT,
    amount_of_token_in_value,
    token_from_string,
    value_from_token,
    commit_hash_secrets,
    write_ahead_hash_secrets,
)
from steak_protocol.onchain.stakechain.stakechain import RegisterStake
from steak_protocol.onchain.stakeholder.stakeholder_auth_nft import Mint
from steak_protocol.onchain.types import (
    StakeChainState,
    StakeHolderRegistrations,
    StakeHolderState,
    StakePoolParams,
)
from steak_protocol.utils import get_signing_info, network, context, get_address
from steak_protocol.utils.contracts import get_contract, get_ref_utxo
from steak_protocol.utils.network import show_tx
from steak_protocol.utils.to_script_context import (
    to_address,
    to_tx_out_ref,
)

from opshin.builder import apply_parameters


def main(
    name: str = "creator",
    minutxo_address: str = "recipient",
    return_tx: bool = False,
):
    payment_vkey, payment_skey, payment_address = get_signing_info(
        name, network=network
    )
    own_pkhash = payment_vkey.hash().payload
    minutxo_address = get_address(minutxo_address, network=network)

    airdrop_script, _, airdrop_address = get_contract("airdrop")

    airdrop_utxo = None
    for u in context.utxos(airdrop_address):
        try:
            airdrop_receiver = RawPlutusData.from_cbor(u.output.datum.cbor).data
        except Exception as e:
            continue
        if airdrop_receiver == own_pkhash:
            airdrop_utxo = u
            break
        airdrop_utxo = u
        break
    assert airdrop_utxo is not None, "No airdrop found"

    unlock_redeemer = Redeemer(0)

    minutxo_output_state = to_tx_out_ref(airdrop_utxo.input)

    txbuilder = TransactionBuilder(context)
    txbuilder.add_input_address(payment_address)
    txbuilder.add_script_input(
        airdrop_utxo,
        airdrop_script,
        None,
        unlock_redeemer,
    )
    txbuilder.add_output(
        with_min_lovelace(
            TransactionOutput(
                minutxo_address,
                amount=pycardano.Value(coin=2500000),
                datum=minutxo_output_state,
            ),
            context,
        )
    )
    txbuilder.required_signers = [payment_vkey.hash()]
    txbuilder.auxiliary_data = pycardano.AuxiliaryData(
        data=pycardano.AlonzoMetadata(
            metadata=pycardano.Metadata(
                {
                    674: {"msg": ["Claim Airdrop"]},
                }
            )
        )
    )
    tx = txbuilder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    context.submit_tx(tx)
    # only commit / overwrite the secrets if the transaction was successful
    show_tx(tx)
    if return_tx:
        return tx


if __name__ == "__main__":
    fire.Fire(main)
