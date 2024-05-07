import datetime
import fire
import pycardano
from opshin import apply_parameters
from opshin.ledger.api_v2 import ScriptCredential
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

from steak_protocol.onchain.stakeholder import stakeholder, stakeholder_auth_nft
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
    value_from_token,
)
from steak_protocol.onchain.stakechain.stakechain import (
    DeregisterStake,
)
from steak_protocol.onchain.types import (
    StakeChainState,
    StakeHolderState,
    StakeHolderRegistrations,
)
from steak_protocol.onchain.util import (
    remove_int_at_index,
    remove_bytes_at_index,
)
from steak_protocol.utils import get_signing_info, network, context
from steak_protocol.utils.contracts import get_contract, get_ref_utxo
from steak_protocol.utils.network import show_tx
from steak_protocol.utils.to_script_context import (
    to_tx_out_ref,
    to_address,
)


def main(
    name: str = "admin",
    stakechain_auth_nft: str = STAKE_CHAIN_AUTH_NFT,
    pool_id: str = "2番",
):
    payment_vkey, payment_skey, payment_address = get_signing_info(
        name, network=network
    )

    stakechain_script, _, stakechain_address = get_contract("stakechain")
    stakeholder_script, _, stakeholder_address = get_contract("stakeholder")
    stakechain_auth_nft = token_from_string(stakechain_auth_nft)
    stakepool_script, _, _ = get_contract("stakepool")

    stakeholder_auth_nft_script_raw, _, _ = get_contract(
        "stakeholder_auth_nft", compressed=True
    )
    stakeholder_auth_nft_script = apply_parameters(
        stakeholder_auth_nft_script_raw, stakechain_auth_nft
    )

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

    # prepare stake holder utxo
    stakeholder_utxo = None
    stakeholder_state = None
    for u in context.utxos(stakeholder_address):
        try:
            stakeholder_state = StakeHolderState.from_cbor(u.output.datum.cbor)
            if stakeholder_state.params.stakechain_id == pool_id:
                continue
            if (
                stakeholder_state.params.block_pubkey == payment_vkey.payload
                and stakeholder_state.params.chain_auth_nft == stakechain_auth_nft
            ):
                stakeholder_utxo = u
                break
        except DeserializeException:
            continue
        except AttributeError:
            continue
    assert stakeholder_utxo is not None, "No stake holder state found"

    own_index_in_stakeholder_list = (
        stakechain_state.holder_state.stake_holder_ids.index(
            stakeholder_state.params.stakechain_id
        )
    )

    new_holder_registrations = StakeHolderRegistrations(
        stake_holder_ids=remove_int_at_index(
            stakechain_state.holder_state.stake_holder_ids,
            own_index_in_stakeholder_list,
        ),
        stake_holder_weights=remove_bytes_at_index(
            stakechain_state.holder_state.stake_holder_weights,
            own_index_in_stakeholder_list,
        ),
    )

    new_stakechain_state = StakeChainState(
        params=stakechain_state.params,
        holder_state=new_holder_registrations,
        chain_state=stakechain_state.chain_state,
        producer_state=stakechain_state.producer_state,
        skip_holders=stakechain_state.skip_holders
        - int(own_index_in_stakeholder_list < stakechain_state.skip_holders),
        spent_for=to_tx_out_ref(stakechain_utxo.input),
    )

    stakeholder_is_pool = isinstance(stakeholder_state.params.owner, ScriptCredential)

    payment_utxos = context.utxos(payment_address)
    all_input_utxos = sorted_utxos(payment_utxos + [stakechain_utxo, stakeholder_utxo])
    stakeholder_utxo_index = all_input_utxos.index(stakeholder_utxo)
    stakechain_utxo_index = all_input_utxos.index(stakechain_utxo)

    stakechain_script = get_ref_utxo(stakechain_script, context)
    stakeholder_script = get_ref_utxo(stakeholder_script, context)

    deregister_chain_redeemer = Redeemer(
        DeregisterStake(
            old_state_index=stakechain_utxo_index,
            new_state_index=0,
            old_stake_index=stakeholder_utxo_index,
            stake_index_in_holder_list=own_index_in_stakeholder_list,
        )
    )

    deregister_fee = value_from_token(stakecoin, stakechain_state.params.register_fee)

    txbuilder = TransactionBuilder(context)
    for u in payment_utxos:
        txbuilder.add_input(u)
    txbuilder.reference_inputs.add(stakeholder_utxo)
    txbuilder.add_script_input(
        stakechain_utxo,
        stakechain_script,
        None,
        deregister_chain_redeemer,
    )
    txbuilder.add_script_input(
        stakeholder_utxo,
        stakeholder_script,
        None,
        Redeemer(
            stakeholder.DeregisterStake(
                own_input_index=stakeholder_utxo_index,
                chain_input_index=stakechain_utxo_index,
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

    txbuilder.add_output(
        with_min_lovelace(
            TransactionOutput(
                stakechain_address,
                amount=stakechain_utxo.output.amount + deregister_fee,
                datum=new_stakechain_state,
            ),
            context,
        )
    )
    txbuilder.mint = asset_from_token(stakeholder_state.params.stakeholder_auth_nft, -1)
    txbuilder.add_minting_script(
        stakeholder_auth_nft_script,
        Redeemer(stakeholder_auth_nft.Burn()),
    )
    txbuilder.validity_start = context.last_block_slot
    txbuilder.ttl = context.last_block_slot + 20
    txbuilder.auxiliary_data = pycardano.AuxiliaryData(
        data=pycardano.AlonzoMetadata(
            metadata=pycardano.Metadata({674: {"msg": ["Deregister Stakeholder"]}})
        )
    )
    tx = txbuilder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    context.submit_tx(tx)
    show_tx(tx)


if __name__ == "__main__":
    fire.Fire(main)
