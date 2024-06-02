import fire
import pycardano
from opshin.prelude import Token
from opshin.std.builtins import sha2_256
from pycardano import (
    TransactionBuilder,
    TransactionOutput,
    Value,
    script_hash,
    DeserializeException,
    MultiAsset,
)
from steak_protocol.onchain.stakepool.stakepool import PoolState
from steak_protocol.onchain.stakepool.stakepool_request import (
    AddStakeRequest,
    RemoveStakeRequest,
)
from steak_protocol.offchain.util import (
    with_min_lovelace,
    asset_from_token,
    STAKE_CHAIN_AUTH_NFT,
    token_from_string,
    amount_of_token_in_value,
    ContractVersion,
    VERSION_0,
)
from steak_protocol.onchain.types import (
    StakeChainV0State,
    StakeHolderState,
)
from steak_protocol.utils import get_signing_info, network, context
from steak_protocol.utils.contracts import get_contract
from steak_protocol.utils.network import show_tx
from steak_protocol.utils.to_script_context import (
    to_address,
)
from opshin.builder import apply_parameters


def main(
    name: str = "admin",
    stakechain_auth_nft: str = STAKE_CHAIN_AUTH_NFT,
    stakecoin_amount: int = 42_000_000,  # negative amount means remove stake request
    stakepool_id: str = "1番",
    return_tx: bool = False,
    stakechain_version: ContractVersion = VERSION_0,
):
    stakepool_id = stakepool_id.encode()
    _, payment_skey, payment_address = get_signing_info(name, network=network)

    _, _, stakepool_request_address = get_contract("stakepool_request")
    _, _, stakeholder_address = get_contract("stakeholder")
    _, _, stakechain_address = get_contract("stakechain_" + stakechain_version)
    _, stakepool_policy_id, _ = get_contract("stakepool")
    stakechain_auth_nft = token_from_string(stakechain_auth_nft)

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

    stakeholder_utxo = None
    stakeholder_state = None
    for u in context.utxos(stakeholder_address):
        if amount_of_token_in_value(stakeholder_auth_nft, u.output.amount) == 0:
            continue
        try:
            stakeholder_state = StakeHolderState.from_cbor(u.output.datum.cbor)
        except DeserializeException as e:
            continue
        if stakeholder_state.params.stakechain_id != stakepool_id:
            continue
        stakeholder_utxo = u
        break
    assert stakeholder_utxo is not None, "No stake holder state found"

    pool_state = PoolState.from_cbor(stakeholder_state.aux.datum.to_cbor())
    lp_token = Token(
        stakepool_policy_id.payload, sha2_256(pool_state.params.initial_utxo.to_cbor())
    )

    if stakecoin_amount > 0:
        stake_request_datum = AddStakeRequest(
            owner=to_address(payment_address).payment_credential.credential_hash,
            beneficiary=to_address(payment_address),
            req_token=lp_token,
            req_min_amount=stakecoin_amount,  # TODO: properly compute this
        )
    elif stakecoin_amount < 0:
        stake_request_datum = RemoveStakeRequest(
            owner=to_address(payment_address).payment_credential.credential_hash,
            beneficiary=to_address(payment_address),
            req_token=stakecoin,
            req_min_amount=-stakecoin_amount,
        )
    else:
        raise ValueError("stakecoin amount must be non-zero")

    txbuilder = TransactionBuilder(context)
    txbuilder.add_input_address(payment_address)
    txbuilder.add_output(
        with_min_lovelace(
            TransactionOutput(
                stakepool_request_address,
                amount=Value(
                    coin=3_500_000,
                    multi_asset=(
                        asset_from_token(stakecoin, stakecoin_amount)
                        if stakecoin_amount > 0
                        else asset_from_token(lp_token, -stakecoin_amount)
                    ),
                ),
                datum=stake_request_datum,
            ),
            context,
        )
    )
    txbuilder.auxiliary_data = pycardano.AuxiliaryData(
        data=pycardano.AlonzoMetadata(
            metadata=pycardano.Metadata(
                {
                    674: {
                        "msg": [
                            ("Add" if stakecoin_amount > 0 else "Remove")
                            + " Stake Request"
                        ]
                    },
                }
            )
        )
    )
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
