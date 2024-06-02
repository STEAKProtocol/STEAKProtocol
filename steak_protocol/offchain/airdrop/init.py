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
from steak_protocol.onchain.stakechain.stakechain_v0 import RegisterStake
from steak_protocol.onchain.stakeholder.stakeholder_auth_nft import Mint
from steak_protocol.onchain.types import (
    StakeChainV0State,
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
    name: str = "airdrop",
    stakechain_auth_nft: str = STAKE_CHAIN_AUTH_NFT,
    airdrop_amount: int = 1200_000_000,
    recipients_file: str = "addresses.txt",
    return_tx: bool = False,
    change_address: str = None,
):
    payment_vkey, payment_skey, payment_address = get_signing_info(
        name, network=network
    )

    stakechain_script, _, stakechain_address = get_contract("stakechain")
    stakechain_auth_nft = token_from_string(stakechain_auth_nft)
    airdrop_script, _, airdrop_address = get_contract("airdrop")

    stakechain_utxo = None
    stakechain_state = None
    for u in context.utxos(stakechain_address):
        if amount_of_token_in_value(stakechain_auth_nft, u.output.amount) == 0:
            continue
        try:
            stakechain_state = StakeChainV0State.from_cbor(u.output.datum.cbor)
        except DeserializeException as e:
            continue
        stakechain_utxo = u
        break
    assert stakechain_utxo is not None, "No stake chain state found"

    stakecoin = stakechain_state.params.stake_coin

    txbuilder = TransactionBuilder(context)
    txbuilder.add_input_address(payment_address)

    with open(recipients_file) as f:
        recipients = set(f.readlines())
    for recipient_addr in recipients:
        recipient = pycardano.Address.from_primitive(recipient_addr.strip())
        recipient_airdrop_addr = pycardano.Address(
            payment_part=airdrop_address.payment_part,
            staking_part=recipient.staking_part,
            network=network,
        )
        txbuilder.add_output(
            with_min_lovelace(
                TransactionOutput(
                    recipient_airdrop_addr,
                    amount=value_from_token(stakecoin, airdrop_amount),
                    datum=recipient.payment_part.payload,
                ),
                context,
            )
        )
    txbuilder.auxiliary_data = pycardano.AuxiliaryData(
        data=pycardano.AlonzoMetadata(
            metadata=pycardano.Metadata(
                {
                    674: {"msg": ["Initialize Airdrop"]},
                }
            )
        )
    )
    tx = txbuilder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=(
            payment_address
            if change_address is None
            else pycardano.Address.from_primitive(change_address)
        ),
    )

    context.submit_tx(tx)
    show_tx(tx)
    if return_tx:
        return tx


if __name__ == "__main__":
    fire.Fire(main)
