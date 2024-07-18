import datetime
from typing import List

import fire
import pycardano
import requests
from opshin.ledger.api_v2 import PubKeyCredential, NoOutputDatum, SomeOutputDatum
from opshin.prelude import Nothing
from pycardano import (
    TransactionBuilder,
    TransactionOutput,
    Redeemer,
    DeserializeException,
    Value,
    plutus_script_hash,
    datum_hash,
)

from steak_protocol.offchain.util import (
    sorted_utxos,
    with_min_lovelace,
    STAKE_CHAIN_AUTH_NFT,
    amount_of_token_in_value,
    token_from_string,
    asset_from_token,
    ContractVersion,
    VERSION_0,
    VERSION_0a,
)
from steak_protocol.onchain.stakechain.stakechain_v0 import UpgradeProtocol
from steak_protocol.onchain.stakechain.stakechain_upgrade_v0a import (
    ChainUpgradeProposal,
    ChainUpgrade,
)
from steak_protocol.onchain.types import (
    StakeChainV0State,
    StakeChainV1State,
    ProducerState,
)
from steak_protocol.onchain.util import scale_fraction
from steak_protocol.utils import get_signing_info, network, context
from steak_protocol.utils.contracts import get_contract, get_ref_utxo
from steak_protocol.utils.from_script_context import from_address
from steak_protocol.utils.network import show_tx
from steak_protocol.utils.to_script_context import (
    to_tx_out_ref,
)

from opshin.builder import apply_parameters


def previous_producer_states_from_kupo(
    kupo_url: str,
    stakechain_addr: str,
    context: pycardano.ChainContext,
):
    """
    Assuming that a kupo instance is running at the given url with the match pattern matching the stakechain address
    and no pruning, we can obtain the previous producer states from the kupo instance.

    Returns preceding producer states in the order of most recent first.
    Returns only those states that resolve to the same message
    """
    utxo_url = "{}/matches/{}?order=most_recent_first".format(kupo_url, stakechain_addr)
    matches = requests.get(utxo_url).json()
    initial_producer_message_hash = None
    producer_states = []
    for match in matches:
        dtm_hash = match["datum_hash"]
        if dtm_hash is None:
            break
        datum_cbor = requests.get("{}/datums/{}".format(kupo_url, dtm_hash)).json()[
            "datum"
        ]
        chain_state = StakeChainV0State.from_cbor(datum_cbor)
        producer_state = chain_state.producer_state
        if isinstance(producer_state.auxiliary, NoOutputDatum):
            break
        if isinstance(producer_state.auxiliary, SomeOutputDatum):
            producer_message_hash = datum_hash(producer_state.auxiliary.datum).payload
        else:
            producer_message_hash = producer_state.auxiliary.datum_hash
        if (
            initial_producer_message_hash is None
            or initial_producer_message_hash == producer_message_hash
        ):
            initial_producer_message_hash = producer_message_hash
            producer_states.append(producer_state)
    return producer_states


def main(
    name: str = "admin",
    stakechain_auth_nft: str = STAKE_CHAIN_AUTH_NFT,
    previous_producer_states_cbor: List[str] = None,
    proposal_cbor: str = "d905719fd8799fd87a9f581cbd6ffb813b1d5c536a7c49c6210bbe7202dff6bfbd9c3271a8f44ee5ffd87a80ffd8799fd8799fd87a9f581cf3e9624782fcc2d467f58c74f3dc005abac17a27ac20cc315981ebc6ffd87a80ffd8799f581cb5a23ff2e966434d32248c5ef06786248b48932ff4cd2d9d456e839d5820221c348f186c3e43ac9863a52d619d8183a274e7e15b40fa733b57fc76fd27f4ff19ea60d8799f581c2a80c713e0d518f84e0553957e3d581c9326cfc5931ea1f4dd0fb2924d0014df107374616b65636f696effd87a9f0119f424ffd8799f581cdfc450815c964e21bc9dd8e4ed1029c3407408c9fa95c48e1484f3685820221c348f186c3e43ac9863a52d619d8183a274e7e15b40fa733b57fc76fd27f4ff1b0000018f6d8e5e101b0000000ba43b7400d87a9f581c946566aa6e975de4dbfd43ac3990cd08bbf6f700c1d28623ec5793c1ff0114181effd87f80d87f80ff",
    return_tx: bool = True,
    stakechain_version: ContractVersion = VERSION_0,
    stakechain_upgrade_version: ContractVersion = VERSION_0a,
):
    payment_vkey, payment_skey, payment_address = get_signing_info(
        name, network=network
    )

    stakechain_script, _, stakechain_address = get_contract(
        "stakechain_" + stakechain_version
    )
    stakechain_script = get_ref_utxo(stakechain_script, context)
    stakechain_auth_nft = token_from_string(stakechain_auth_nft)

    if previous_producer_states_cbor is None:
        previous_producer_states = previous_producer_states_from_kupo(
            kupo_url="http://localhost:1991",
            stakechain_addr=stakechain_address,
            context=context,
        )[1:]
    else:
        previous_producer_states = [
            ProducerState.from_cbor(cbor) for cbor in previous_producer_states_cbor
        ]
    assert len(previous_producer_states) + 1 == 7, "Want 7 previous producer states"

    stakechain_upgrade_script_raw, _, _ = get_contract(
        "stakechain_upgrade_" + stakechain_upgrade_version, compressed=True
    )
    stakechain_upgrade_script = apply_parameters(
        stakechain_upgrade_script_raw,
        len(previous_producer_states) + 1,
        stakechain_auth_nft,
    )
    stakechain_upgrade_script_hash = plutus_script_hash(stakechain_upgrade_script)

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

    producer_state = stakechain_state.producer_state
    if isinstance(producer_state.auxiliary, NoOutputDatum):
        raise ValueError("No proposal found")
    elif isinstance(producer_state.auxiliary, SomeOutputDatum):
        upgrade_proposal: ChainUpgradeProposal = producer_state.auxiliary.datum
    else:
        upgrade_proposal: ChainUpgradeProposal = ChainUpgradeProposal.from_cbor(
            proposal_cbor
        )
        assert (
            datum_hash(upgrade_proposal).payload == producer_state.auxiliary.datum_hash
        )
    if isinstance(upgrade_proposal.upgrade_address, Nothing):
        new_address = stakechain_utxo.output.address
    else:
        new_address = from_address(upgrade_proposal.upgrade_address)

    if isinstance(upgrade_proposal.upgrade_params, Nothing):
        new_params = stakechain_state.params
    else:
        new_params = upgrade_proposal.upgrade_params

    new_stakechain_state = StakeChainV1State(
        params=new_params,
        holder_state=stakechain_state.holder_state,
        chain_state=stakechain_state.chain_state,
        producer_state=stakechain_state.producer_state,
        skip_holders=stakechain_state.skip_holders,
        spent_for=to_tx_out_ref(stakechain_utxo.input),
    )

    payment_utxos = context.utxos(payment_address)
    all_input_utxos = sorted_utxos(payment_utxos + [stakechain_utxo])
    stakechain_utxo_index = all_input_utxos.index(stakechain_utxo)

    txbuilder = TransactionBuilder(context)
    for u in payment_utxos:
        txbuilder.add_input(u)
    txbuilder.add_script_input(
        stakechain_utxo,
        stakechain_script,
        None,
        Redeemer(UpgradeProtocol()),
    )
    txbuilder.add_withdrawal_script(
        stakechain_upgrade_script,
        Redeemer(
            ChainUpgrade(
                previous_states=previous_producer_states,
                upgrade_proposal=upgrade_proposal,
                prev_chain_state_index=stakechain_utxo_index,
                next_chain_state_index=0,
                payout_index=-1,
            )
        ),
    )
    txbuilder.withdrawals = pycardano.Withdrawals(
        {
            bytes(
                pycardano.Address(
                    staking_part=stakechain_upgrade_script_hash, network=network
                )
            ): 0
        }
    )

    # TODO add payouts or treasury additions

    txbuilder.add_output(
        with_min_lovelace(
            TransactionOutput(
                new_address,
                amount=stakechain_utxo.output.amount,
                datum=new_stakechain_state,
            ),
            context,
        )
    )
    txbuilder.collaterals = sorted(payment_utxos, key=lambda u: u.output.amount.coin, reverse=True)[:3]
    txbuilder.validity_start = context.last_block_slot
    txbuilder.ttl = context.last_block_slot + 60
    txbuilder.auxiliary_data = pycardano.AuxiliaryData(
        data=pycardano.AlonzoMetadata(
            metadata=pycardano.Metadata(
                {
                    674: {"msg": ["Upgrade Protocol"]},
                }
            )
        )
    )
    txbuilder.fee_buffer = 1000
    tx = txbuilder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    context.submit_tx(tx)
    show_tx(tx)
    if return_tx:
        return tx


if __name__ == "__main__":
    fire.Fire(main)
