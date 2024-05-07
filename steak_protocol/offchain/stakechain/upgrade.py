import datetime
from typing import List

import fire
import pycardano
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
)
from steak_protocol.onchain.stakechain.stakechain import MineBlock, UpgradeProtocol
from steak_protocol.onchain.stakechain.stakechain_upgrade import (
    ChainUpgradeProposal,
    ChainUpgrade,
)
from steak_protocol.onchain.types import (
    StakeChainState,
    CoreChainState,
    StakeHolderState,
    ProducerState,
)
from steak_protocol.onchain.util import scale_fraction
from steak_protocol.utils import get_signing_info, network, context
from steak_protocol.utils.contracts import get_contract, get_ref_utxo
from steak_protocol.utils.from_script_context import from_address
from steak_protocol.utils.network import show_tx
from steak_protocol.utils.to_script_context import (
    to_tx_out_ref,
    to_address,
)

from opshin.builder import apply_parameters


def compute_current_slot(genesis_time: int, slot_length: int) -> int:
    current_time = int(datetime.datetime.now().timestamp() * 1000)
    return (current_time - genesis_time) // slot_length


def compute_validity_interval(genesis_time: int, slot_length: int) -> tuple[int, int]:
    suggested_slot = compute_current_slot(genesis_time, slot_length)
    min_acceptable_lower_bound = genesis_time + slot_length * suggested_slot
    max_acceptable_upper_bound = min_acceptable_lower_bound + slot_length
    return min_acceptable_lower_bound, max_acceptable_upper_bound


def main(
    name: str = "admin",
    stakechain_auth_nft: str = STAKE_CHAIN_AUTH_NFT,
    previous_producer_states_cbor: List[str] = None,
    proposal_cbor: str = None,
    return_tx: bool = False,
):
    payment_vkey, payment_skey, payment_address = get_signing_info(
        name, network=network
    )

    stakechain_script, _, stakechain_address = get_contract("stakechain")
    stakechain_script = get_ref_utxo(stakechain_script, context)
    stakechain_auth_nft = token_from_string(stakechain_auth_nft)

    stakechain_upgrade_script_raw, _, _ = get_contract(
        "stakechain_upgrade", compressed=True
    )
    stakechain_upgrade_script = apply_parameters(
        stakechain_upgrade_script_raw,
        len(previous_producer_states_cbor) + 1,
        stakechain_auth_nft,
    )
    stakechain_upgrade_script_hash = plutus_script_hash(stakechain_upgrade_script)

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

    new_stakechain_state = StakeChainState(
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
                previous_states=[
                    ProducerState.from_cbor(cbor)
                    for cbor in previous_producer_states_cbor
                ],
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
    txbuilder.validity_start = context.last_block_slot
    txbuilder.ttl = context.last_block_slot + 20
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
