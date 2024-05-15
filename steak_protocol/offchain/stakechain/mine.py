import copy
import datetime
import secrets
import time
from typing import Optional

import fire
import pycardano
from opshin.ledger.api_v2 import (
    ScriptCredential,
    NoOutputDatum,
    SomeOutputDatum,
    SomeOutputDatumHash,
)
from opshin.std.builtins import sha2_256
from opshin.std.math import bytes_big_from_unsigned_int
from opshin.std.fractions import floor_fraction, ceil_fraction
from pycardano import (
    TransactionBuilder,
    TransactionOutput,
    Redeemer,
    DeserializeException,
    Value,
    Withdrawals,
    Address,
    plutus_script_hash,
    UTxO,
)
from steak_protocol.onchain.stakepool.stakepool import (
    InteractWithPool,
    PoolState,
    PoolParams,
)
from steak_protocol.offchain.util import (
    sorted_utxos,
    with_min_lovelace,
    STAKE_CHAIN_AUTH_NFT,
    amount_of_token_in_value,
    token_from_string,
    asset_from_token,
    committed_hash_secrets,
    custom_sign_message,
    commit_hash_secrets,
    write_ahead_hash_secrets,
    all_committed_hash_secrets,
)
from steak_protocol.onchain.stakechain.stakechain import MineBlockUpdateStake
from steak_protocol.onchain.stakeholder.stakeholder import UpdateStake
from steak_protocol.onchain.types import (
    StakeChainState,
    CoreChainState,
    StakeHolderState,
    ProducerState,
    StakeHolderRegistrations,
)
from steak_protocol.onchain.util import scale_fraction
from steak_protocol.utils import get_signing_info, network, context
from steak_protocol.utils.contracts import get_contract, get_ref_utxo
from steak_protocol.utils.network import show_tx
from steak_protocol.utils.to_script_context import (
    to_tx_out_ref,
    to_address,
)


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
    stakepool_id: str = "3番",
    producer_message_hash_hex: Optional[str] = None,
    # number of seconds of validity for the transaction
    # closer to 60 -> more likely to hit an invalid slot from stakechain view
    # closer to 0 -> harder to be included in the cardano chain
    tx_validity_width: int = 40,
    # how frequently to retry in case of failure (failure is the default)
    retry_interval: int = 5,
    # amount of time to wait before committing hash secrets
    # lower values may lead to more frequent necessecity to recover the pool
    # higher values may lead to more frequent missed blocks
    commit_interval: int = 120,
):
    while True:
        try:
            mine(
                name=name,
                stakechain_auth_nft=stakechain_auth_nft,
                pool_id=stakepool_id,
                producer_message_hash_hex=producer_message_hash_hex,
                tx_validity_width=tx_validity_width,
                commit_interval=commit_interval,
            )
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(e)
            print("Press Ctrl+C to stop. Trying again in 5 seconds...")
        else:
            print("Block mined! Trying again in 5 seconds...")
        time.sleep(retry_interval)


def mine(
    name: str = "admin",
    stakechain_auth_nft: str = STAKE_CHAIN_AUTH_NFT,
    pool_id: str = "1番",
    producer_message_hash_hex: Optional[str] = None,
    tx_validity_width: int = 40,
    commit_interval: int = 120,
):
    payment_vkey, payment_skey, payment_address = get_signing_info(
        name, network=network
    )

    stakechain_script, _, stakechain_address = get_contract("stakechain")
    stakeholder_script, _, stakeholder_address = get_contract("stakeholder")
    stakechain_auth_nft = token_from_string(stakechain_auth_nft)
    stakepool_script, _, _ = get_contract("stakepool")

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

    stakeholder_secretss = all_committed_hash_secrets(pool_id)
    all_stakeholder_secret_hashes = [
        [sha2_256(x) for x in stakeholder_secrets]
        for stakeholder_secrets in stakeholder_secretss
    ]
    # prepare stake holder utxo
    stakeholder_utxo = None
    stakeholder_state = None
    steakholder_secrets_match = None
    for u in context.utxos(stakeholder_address):
        try:
            stakeholder_state = StakeHolderState.from_cbor(u.output.datum.cbor)
            if (
                stakeholder_state.params.chain_auth_nft == stakechain_auth_nft
                and stakeholder_state.params.stakechain_id == pool_id.encode()
            ):
                for stakeholder_secret_hashes in all_stakeholder_secret_hashes:
                    if stakeholder_state.committed_hashes == stakeholder_secret_hashes:
                        steakholder_secrets_match = stakeholder_secret_hashes
                        break
            if steakholder_secrets_match is not None:
                stakeholder_utxo = u
                break
        except DeserializeException:
            continue
        except AttributeError:
            continue
    assert (
        stakeholder_utxo is not None
    ), "No stake holder state found. Correct secrets and pool name?"
    stakeholder_secrets = steakholder_secrets_match

    own_index_in_stakeholder_list = (
        stakechain_state.holder_state.stake_holder_ids.index(
            stakeholder_state.params.stakechain_id
        )
    )

    current_slot_number = compute_current_slot(
        stakechain_state.params.genesis_time, stakechain_state.params.slot_length
    )
    elected_slot_leader = 0  # just assume we are the leader and try to submit
    new_core_chain_state = CoreChainState(
        block_number=stakechain_state.chain_state.block_number + 1,
        block_hash=sha2_256(
            bytes_big_from_unsigned_int(elected_slot_leader)
            + stakechain_state.chain_state.to_cbor()
            + stakechain_state.producer_state.producer_signature
        ),
        slot_number=current_slot_number,
    )
    slot_leader_sig = custom_sign_message(
        stakeholder_secrets[0], new_core_chain_state.to_cbor()
    )

    producer_message = (
        NoOutputDatum()
        if producer_message_hash_hex is None
        else SomeOutputDatumHash(datum_hash=bytes.fromhex(producer_message_hash_hex))
    )
    new_stakechain_state = StakeChainState(
        params=stakechain_state.params,
        holder_state=stakechain_state.holder_state,
        chain_state=new_core_chain_state,
        producer_state=ProducerState(
            producer_signature=slot_leader_sig,
            auxiliary=producer_message,
            prev_producer_state_hash=sha2_256(
                stakechain_state.producer_state.to_cbor()
            ),
        ),
        skip_holders=0,
        spent_for=to_tx_out_ref(stakechain_utxo.input),
    )

    stakeholder_is_pool = isinstance(stakeholder_state.params.owner, ScriptCredential)
    if stakeholder_is_pool:
        pool_state = PoolState.from_cbor(stakeholder_state.aux.datum.to_cbor())
        guarantee_reward_fraction = pool_state.params.guaranteed_reward_fraction

    payment_utxos = context.utxos(payment_address)
    all_input_utxos = sorted_utxos(payment_utxos + [stakechain_utxo, stakeholder_utxo])
    stakeholder_utxo_index = all_input_utxos.index(stakeholder_utxo)
    stakechain_utxo_index = all_input_utxos.index(stakechain_utxo)

    stakechain_script = get_ref_utxo(stakechain_script, context)
    stakeholder_script = get_ref_utxo(stakeholder_script, context)
    all_ref_input_utxos = sorted_utxos(
        [stakeholder_utxo]
        + [u for u in [stakechain_script, stakeholder_script] if isinstance(u, UTxO)]
    )
    stakeholder_ref_utxo_index = all_ref_input_utxos.index(stakeholder_utxo)

    mining_redeemer = Redeemer(
        MineBlockUpdateStake(
            old_state_index=stakechain_utxo_index,
            new_state_index=0,
            producing_holder_ref_utxo_index=stakeholder_ref_utxo_index,
            elected_slot_leader=elected_slot_leader,
            aux=producer_message,
            slot_leader_secret=stakeholder_secrets[0],
            slot_leader_sig=slot_leader_sig,
            old_stake_index=stakeholder_utxo_index,
            new_stake_index=1,
            stake_index_in_holder_list=own_index_in_stakeholder_list,
        )
    )

    new_stakeholder_state = copy.deepcopy(stakeholder_state)
    new_stakeholder_secrets = stakeholder_secrets[1:] + [secrets.token_bytes(32)]
    new_stakeholder_state.committed_hashes = stakeholder_secret_hashes[1:] + [
        sha2_256(new_stakeholder_secrets[-1])
    ]

    txbuilder = TransactionBuilder(context)
    for u in payment_utxos:
        txbuilder.add_input(u)
    txbuilder.reference_inputs.add(stakeholder_utxo)
    txbuilder.add_script_input(
        stakechain_utxo,
        stakechain_script,
        None,
        mining_redeemer,
    )
    txbuilder.add_script_input(
        stakeholder_utxo,
        stakeholder_script,
        None,
        Redeemer(
            UpdateStake(
                own_input_index=stakeholder_utxo_index,
                chain_input_index=stakechain_utxo_index,
                own_output_index=1,
            )
        ),
    )

    if stakeholder_is_pool:
        txbuilder.withdrawals = Withdrawals(
            {
                bytes(
                    Address(
                        staking_part=plutus_script_hash(stakepool_script),
                        network=network,
                    )
                ): 0
            }
        )
        txbuilder.add_withdrawal_script(
            stakepool_script,
            Redeemer(
                InteractWithPool(
                    own_input_index=stakeholder_utxo_index,
                    own_output_index=1,
                    chain_input_index=stakechain_utxo_index,
                    chain_output_index=0,
                )
            ),
        )

    # determine new value
    prev_reserve_amount = amount_of_token_in_value(
        stakecoin, stakechain_utxo.output.amount
    )
    amount_to_be_distributed = floor_fraction(
        scale_fraction(prev_reserve_amount, stakechain_state.params.fraction_per_block)
    )
    desired_new_value = stakechain_utxo.output.amount.multi_asset - asset_from_token(
        stakecoin, amount_to_be_distributed
    )
    if stakeholder_is_pool:
        amount_to_pool = ceil_fraction(
            scale_fraction(amount_to_be_distributed, guarantee_reward_fraction)
        )
    else:
        amount_to_pool = amount_to_be_distributed

    # update holder weight in case of pool
    new_stakechain_state.holder_state.stake_holder_weights[
        own_index_in_stakeholder_list
    ] += amount_to_pool

    txbuilder.add_output(
        with_min_lovelace(
            TransactionOutput(
                stakechain_address,
                amount=Value(multi_asset=desired_new_value),
                datum=new_stakechain_state,
            ),
            context,
        )
    )
    txbuilder.add_output(
        with_min_lovelace(
            TransactionOutput(
                stakeholder_address,
                amount=Value(
                    multi_asset=stakeholder_utxo.output.amount.multi_asset
                    + asset_from_token(stakecoin, amount_to_pool),
                ),
                datum=new_stakeholder_state,
            ),
            context,
        )
    )
    txbuilder.validity_start = context.last_block_slot + 1
    txbuilder.ttl = txbuilder.validity_start + tx_validity_width
    txbuilder.auxiliary_data = pycardano.AuxiliaryData(
        data=pycardano.AlonzoMetadata(
            metadata=pycardano.Metadata(
                {
                    674: {"msg": ["Mine Block"]},
                }
            )
        )
    )
    tx = txbuilder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    # MODIFY THESE STEPS AT YOUR OWN RISK, may lead to need to recover the pool secrets
    write_ahead_hash_secrets(pool_id, new_stakeholder_secrets)
    context.submit_tx(tx)
    show_tx(tx)
    print("Checking if tx made it to the chain... DO NOT ABORT")
    time.sleep(commit_interval)
    assert (
        context.utxo_by_tx_id(tx.id.payload.hex(), 0) is not None
    ), "Transaction not found, aborting"
    # END OF DANGER ZONE
    commit_hash_secrets(pool_id, new_stakeholder_secrets)
    return tx, new_stakechain_state


if __name__ == "__main__":
    fire.Fire(main)
