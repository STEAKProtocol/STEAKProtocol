import functools
import random
import re
from time import sleep

import fire
import pycardano
from opshin.ledger.api_v2 import SomeOutputDatum
from opshin.std.builtins import sha2_256
from opshin.prelude import Token
from pycardano import (
    TransactionBuilder,
    script_hash,
    TransactionOutput,
    Value,
    Redeemer,
    DeserializeException,
    Withdrawals,
    Address,
    plutus_script_hash,
    PlutusData,
    Unit,
    OgmiosChainContext,
)
from steak_protocol.onchain.stakepool.stakepool_request import (
    AddStakeRequest,
    RemoveStakeRequest,
    FillRequest,
)
import steak_protocol.onchain.stakeholder.stakeholder as stakeholder
import steak_protocol.onchain.stakechain.stakechain as stakechain
from steak_protocol.onchain.stakepool.stakepool import AddStake, RemoveStake, PoolState
from steak_protocol.offchain.util import (
    sorted_utxos,
    with_min_lovelace,
    asset_from_token,
    STAKE_CHAIN_AUTH_NFT,
    amount_of_token_in_value,
    token_from_string,
    adjust_for_wrong_fee,
)
from opshin.prelude import Token
from steak_protocol.onchain.types import (
    StakeChainState,
    StakeHolderRegistrations,
    StakeHolderState,
)
from steak_protocol.utils import get_signing_info, network, context
from steak_protocol.utils.contracts import get_contract, get_ref_utxo
from steak_protocol.utils.network import show_tx, ogmios_url, kupo_url
from steak_protocol.utils.to_script_context import (
    to_address,
    to_tx_out_ref,
)
from steak_protocol.utils.from_script_context import from_address
from pycardano.crypto.bech32 import encode

from opshin.builder import apply_parameters


def main(
    name: str = "bob",
    stakechain_auth_nft: str = STAKE_CHAIN_AUTH_NFT,
    stake_key: str = "*",
    no_stake_key: bool = False,
):
    while True:
        try:
            fill_request(
                name=name,
                stakechain_auth_nft=stakechain_auth_nft,
                stake_key=stake_key,
                no_stake_key=no_stake_key,
            )
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(e)
            print("Press Ctrl+C to stop. Trying again in 5 seconds...")
        sleep(5)


def fill_request(
    name: str = "admin",
    stakechain_auth_nft: str = STAKE_CHAIN_AUTH_NFT,
    stake_key: str = "*",
    no_stake_key: bool = False,
):
    _, payment_skey, payment_address = get_signing_info(name, network=network)

    stakechain_script, _, stakechain_address = get_contract("stakechain")
    stakeholder_script, _, stakeholder_address = get_contract("stakeholder")
    stakepool_script, stakepool_policy_id, stakepool_address = get_contract("stakepool")
    stakechain_auth_nft = token_from_string(stakechain_auth_nft)
    stakepool_request_script, _, stakepool_request_address = get_contract(
        "stakepool_request"
    )
    stakepool_request_credential_encoded = encode(
        "script", bytes.fromhex(str(stakepool_request_address.payment_part))
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

    stakeholder_auth_nft_script_raw, _, _ = get_contract("stakeholder_auth_nft")
    stakeholder_auth_nft_script = apply_parameters(
        stakeholder_auth_nft_script_raw, stakechain_auth_nft
    )
    stakeholder_auth_nft_policy_id = script_hash(stakeholder_auth_nft_script)

    stakeholder_auth_nft_token_name = stakechain_auth_nft.token_name
    stakeholder_auth_nft = Token(
        stakeholder_auth_nft_policy_id.payload,
        stakeholder_auth_nft_token_name,
    )

    # collect request (just one Add or Remove for now)
    # NOTE: "*" only works with ogmios + kupo
    if no_stake_key:
        stakepool_request_address_adjusted = stakepool_request_address
    elif stake_key == "*":
        stakepool_request_address_adjusted = (
            stakepool_request_address.payment_part.payload.hex() + "/*"
        )
    else:
        assert stake_key, "No stake key provided"
        stake_key = pycardano.Address.from_primitive(stake_key)
        stakepool_request_address_adjusted = pycardano.Address(
            payment_part=stakepool_request_address.payment_part,
            staking_part=stake_key.staking_part,
            network=stakepool_address.network,
        )
    request_utxos = context.utxos(stakepool_request_address_adjusted)
    request_state = None
    random.shuffle(request_utxos)
    for req_utxo in request_utxos:
        try:
            request_state = AddStakeRequest.from_cbor(req_utxo.output.datum.cbor)
            is_add_request = True
        except DeserializeException as e:
            try:
                request_state = RemoveStakeRequest.from_cbor(req_utxo.output.datum.cbor)
                is_add_request = False
            except DeserializeException as e:
                continue
        request_utxo = req_utxo

        stakeholder_utxo = None
        stakeholder_state = None
        for u in context.utxos(stakeholder_address):
            if amount_of_token_in_value(stakeholder_auth_nft, u.output.amount) == 0:
                continue
            try:
                stakeholder_state = StakeHolderState.from_cbor(u.output.datum.cbor)
            except DeserializeException as e:
                continue
            if not isinstance(stakeholder_state.aux, SomeOutputDatum):
                continue
            stakepool_state = PoolState.from_cbor(stakeholder_state.aux.datum.to_cbor())
            lp_token = Token(
                stakepool_policy_id.payload,
                sha2_256(stakepool_state.params.initial_utxo.to_cbor()),
            )
            if (
                isinstance(request_state, AddStakeRequest)
                and request_state.req_token != lp_token
            ):
                continue
            elif (
                isinstance(request_state, RemoveStakeRequest)
                and amount_of_token_in_value(lp_token, request_utxo.output.amount) == 0
            ):
                continue
            stakeholder_utxo = u
            break
        if stakeholder_utxo is None:
            print(
                f"No stake holder state found for {request_utxo.input.transaction_id.payload.hex()}"
            )
            continue

        # determine new stake amount
        holder_index = stakechain_state.holder_state.stake_holder_ids.index(
            stakeholder_state.params.stakechain_id
        )
        pool_state = PoolState.from_cbor(stakeholder_state.aux.datum.to_cbor())
        all_lp_tokens = pool_state.all_lp_tokens
        new_stake_holder_weights = stakechain_state.holder_state.stake_holder_weights
        prev_stake_amount = new_stake_holder_weights[holder_index]
        new_stake_amount = prev_stake_amount + (
            amount_of_token_in_value(stakecoin, request_utxo.output.amount)
            if is_add_request
            else (
                -prev_stake_amount
                * amount_of_token_in_value(lp_token, request_utxo.output.amount)
                // all_lp_tokens
            )
        )
        new_stake_holder_weights[holder_index] = new_stake_amount

        # determine lp amounts
        if is_add_request:
            lp_amount_to_mint = (
                all_lp_tokens
                * (new_stake_amount - prev_stake_amount)
                // prev_stake_amount
            )
        else:
            lp_amount_to_burn = -(
                all_lp_tokens
                * (new_stake_amount - prev_stake_amount)
                // prev_stake_amount
                + 1
            )

        # update weight according to new stake amount
        new_stakechain_state = StakeChainState(
            params=stakechain_state.params,
            holder_state=StakeHolderRegistrations(
                stake_holder_weights=new_stake_holder_weights,
                stake_holder_ids=stakechain_state.holder_state.stake_holder_ids,
            ),
            chain_state=stakechain_state.chain_state,
            producer_state=stakechain_state.producer_state,
            skip_holders=stakechain_state.skip_holders,
            spent_for=to_tx_out_ref(stakechain_utxo.input),
        )

        payment_utxos = context.utxos(payment_address)
        all_input_utxos = sorted_utxos(
            payment_utxos + [stakechain_utxo, stakeholder_utxo, request_utxo]
        )
        stakechain_utxo_index = all_input_utxos.index(stakechain_utxo)
        stakeholder_utxo_index = all_input_utxos.index(stakeholder_utxo)

        minted_lp_asset = asset_from_token(
            lp_token,
            lp_amount_to_mint if is_add_request else -lp_amount_to_burn,
        )

        new_stakeholder_state = StakeHolderState(
            params=stakeholder_state.params,
            committed_hashes=stakeholder_state.committed_hashes,
            aux=SomeOutputDatum(
                PoolState(
                    params=pool_state.params,
                    all_lp_tokens=all_lp_tokens
                    + (lp_amount_to_mint if is_add_request else -lp_amount_to_burn),
                )
            ),
        )

        txbuilder = TransactionBuilder(context)
        for u in payment_utxos:
            txbuilder.add_input(u)
        txbuilder.mint = minted_lp_asset
        txbuilder.add_minting_script(
            stakepool_script,
            Redeemer(Unit()),
        )
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
                AddStake(
                    own_input_index=stakeholder_utxo_index,
                    own_output_index=1,
                    chain_input_index=stakechain_utxo_index,
                    chain_output_index=0,
                )
                if is_add_request
                else RemoveStake(
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
                    amount=stakechain_utxo.output.amount,
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
                        multi_asset=asset_from_token(stakecoin, new_stake_amount)
                        + asset_from_token(stakeholder_auth_nft, 1),
                    ),
                    datum=new_stakeholder_state,
                ),
                context,
            )
        )
        txbuilder.add_output(
            with_min_lovelace(
                TransactionOutput(
                    from_address(request_state.beneficiary),
                    amount=Value(
                        multi_asset=(
                            asset_from_token(lp_token, lp_amount_to_mint)
                            if is_add_request
                            else asset_from_token(
                                stakecoin, prev_stake_amount - new_stake_amount
                            )
                        ),
                    ),
                    datum=to_tx_out_ref(request_utxo.input),
                ),
                context,
            )
        )
        txbuilder.add_script_input(
            stakechain_utxo,
            get_ref_utxo(stakechain_script, context),
            None,
            Redeemer(
                stakechain.UpdateStake(
                    old_state_index=stakechain_utxo_index,
                    new_state_index=0,
                    old_stake_index=stakeholder_utxo_index,
                    new_stake_index=1,
                    stake_index_in_holder_list=holder_index,
                )
            ),
        )
        txbuilder.add_script_input(
            stakeholder_utxo,
            get_ref_utxo(stakeholder_script, context),
            None,
            Redeemer(
                stakeholder.UpdateStake(
                    own_input_index=stakeholder_utxo_index,
                    chain_input_index=stakechain_utxo_index,
                    own_output_index=1,
                )
            ),
        )
        txbuilder.add_script_input(
            request_utxo,
            get_ref_utxo(stakepool_request_script, context),
            None,
            Redeemer(
                FillRequest(
                    own_output_index=2,
                )
            ),
        )
        txbuilder.auxiliary_data = pycardano.AuxiliaryData(
            data=pycardano.AlonzoMetadata(
                metadata=pycardano.Metadata(
                    {
                        674: {"msg": ["Fill Stake Request"]},
                    }
                )
            )
        )

        tx = txbuilder.build_and_sign(
            signing_keys=[payment_skey],
            change_address=payment_address,
        )

        try:
            context.submit_tx(tx)
        except Exception as e:
            coins = list(map(int, re.findall(r"'(?:lovelace|coins)': (\d+)", str(e))))
            if "valueNotConserved" in str(e) or "3123" in str(e) and len(coins) == 2:
                print(f"Coinsdiff: {coins[0]} vs {coins[1]}: {coins[1] - coins[0]}")
                print("Trying to adjust fee and output...")
                context.submit_tx(
                    adjust_for_wrong_fee(
                        tx,
                        [payment_skey],
                        output_offset=coins[1] - coins[0],
                    )
                )
            else:
                raise e
        show_tx(tx)


if __name__ == "__main__":
    fire.Fire(main)
