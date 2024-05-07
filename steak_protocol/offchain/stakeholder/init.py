import random
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
)
from steak_protocol.onchain.stakechain.stakechain import RegisterStake
from steak_protocol.onchain.stakeholder.stakeholder_auth_nft import Mint
from steak_protocol.onchain.types import (
    StakeChainState,
    StakeHolderRegistrations,
    StakeHolderState,
    StakePoolParams,
)
from steak_protocol.utils import get_signing_info, network, context
from steak_protocol.utils.contracts import get_contract, get_ref_utxo
from steak_protocol.utils.network import show_tx
from steak_protocol.utils.to_script_context import (
    to_address,
    to_tx_out_ref,
)

from opshin.builder import apply_parameters


def main(
    name: str = "admin",
    stakechain_auth_nft: str = STAKE_CHAIN_AUTH_NFT,
    stake_amount: int = 1_000_000,
    stakeholder_id: str = "1番",
    skip_warning: bool = False,
):
    print(
        "Warning: if you previously ran this script with the same name, the secrets will be overwritten. Press enter to continue."
    )
    if not skip_warning:
        input()
    payment_vkey, payment_skey, payment_address = get_signing_info(
        name, network=network
    )

    stakechain_script, _, stakechain_address = get_contract("stakechain")
    stakeholder_script, _, stakeholder_address = get_contract("stakeholder")
    stakechain_auth_nft = token_from_string(stakechain_auth_nft)

    stakechain_utxo = None
    stakechain_state = None
    for u in context.utxos(stakechain_address):
        if amount_of_token_in_value(stakechain_auth_nft, u.output.amount) == 0:
            continue
        try:
            stakechain_state = StakeChainState.from_cbor(u.output.datum.cbor)
        except DeserializeException as e:
            continue
        stakechain_utxo = u
        break
    assert stakechain_utxo is not None, "No stake chain state found"

    stakecoin = stakechain_state.params.stake_coin
    assert stakechain_state.params.stakeholder_address == to_address(
        stakeholder_address
    ), "Wrong stakeholder address"

    new_stakechain_state = StakeChainState(
        params=stakechain_state.params,
        chain_state=stakechain_state.chain_state,
        holder_state=StakeHolderRegistrations(
            stake_holder_weights=[stake_amount]
            + stakechain_state.holder_state.stake_holder_weights,
            stake_holder_ids=[stakeholder_id.encode()]
            + stakechain_state.holder_state.stake_holder_ids,
        ),
        producer_state=stakechain_state.producer_state,
        skip_holders=stakechain_state.skip_holders + 1,
        spent_for=to_tx_out_ref(stakechain_utxo.input),
    )

    payment_utxos = context.utxos(payment_address)
    all_input_utxos = sorted_utxos(payment_utxos + [stakechain_utxo])
    stakechain_utxo_index = all_input_utxos.index(stakechain_utxo)

    stakeholder_auth_nft_script_raw, _, _ = get_contract(
        "stakeholder_auth_nft", compressed=True
    )
    stakeholder_auth_nft_script = apply_parameters(
        stakeholder_auth_nft_script_raw, stakechain_auth_nft
    )
    stakeholder_auth_nft_policy_id = script_hash(stakeholder_auth_nft_script)

    mint_redeemer = Mint(
        chain_input_index=stakechain_utxo_index,
    )
    stakeholder_auth_nft_token_name = stakechain_auth_nft.token_name
    stakeholder_auth_nft = Token(
        stakeholder_auth_nft_policy_id.payload,
        stakeholder_auth_nft_token_name,
    )
    minted_asset = asset_from_token(stakeholder_auth_nft, 1)

    hash_secrets = [random.randbytes(32) for _ in range(5)]

    new_stakeholder_state = StakeHolderState(
        StakePoolParams(
            owner=PubKeyCredential(payment_vkey.hash().payload),
            stakechain_id=stakeholder_id.encode(),
            chain_auth_nft=stakechain_auth_nft,
            stakeholder_auth_nft=stakeholder_auth_nft,
        ),
        committed_hashes=[sha256(x).digest() for x in hash_secrets],
        aux=NoOutputDatum(),
    )

    txbuilder = TransactionBuilder(context)
    for u in payment_utxos:
        txbuilder.add_input(u)
    txbuilder.add_script_input(
        stakechain_utxo,
        get_ref_utxo(stakechain_script, context),
        None,
        Redeemer(
            RegisterStake(
                stakechain_utxo_index,
                0,
                1,
            )
        ),
    )
    txbuilder.add_output(
        with_min_lovelace(
            TransactionOutput(
                stakechain_address,
                amount=stakechain_utxo.output.amount
                + value_from_token(stakecoin, stakechain_state.params.register_fee),
                datum=new_stakechain_state,
            ),
            context,
        )
    )
    txbuilder.mint = minted_asset
    txbuilder.add_minting_script(
        stakeholder_auth_nft_script,
        Redeemer(mint_redeemer),
    )
    txbuilder.add_output(
        with_min_lovelace(
            TransactionOutput(
                stakeholder_address,
                amount=Value(
                    coin=0,
                    multi_asset=asset_from_token(stakecoin, stake_amount)
                    + asset_from_token(stakeholder_auth_nft, 1),
                ),
                datum=new_stakeholder_state,
            ),
            context,
        )
    )
    txbuilder.auxiliary_data = pycardano.AuxiliaryData(
        data=pycardano.AlonzoMetadata(
            metadata=pycardano.Metadata(
                {
                    674: {"msg": ["Register Stake Holder"]},
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
    commit_hash_secrets(name, hash_secrets)
    show_tx(tx)
    return tx


if __name__ == "__main__":
    fire.Fire(main)
