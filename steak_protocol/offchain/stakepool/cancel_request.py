import fire
import pycardano
from opshin.prelude import Token
from pycardano import (
    TransactionBuilder,
    TransactionOutput,
    Value,
    DeserializeException,
    Redeemer,
)
from steak_protocol.onchain.stakepool.stakepool_request import (
    AddStakeRequest,
    RemoveStakeRequest,
    CancelRequest,
)
from steak_protocol.onchain.types import StakeChainState
from steak_protocol.offchain.util import (
    with_min_lovelace,
    asset_from_token,
    STAKE_CHAIN_AUTH_NFT,
    token_from_string,
    amount_of_token_in_value,
)
from steak_protocol.utils import get_signing_info, network, context
from steak_protocol.utils.contracts import get_contract
from steak_protocol.utils.network import show_tx
from steak_protocol.utils.to_script_context import (
    to_address,
)


def main(
    name: str = "admin",
    stakechain_auth_nft: str = STAKE_CHAIN_AUTH_NFT,
    return_tx: bool = False,
):
    payment_vkey, payment_skey, payment_address = get_signing_info(
        name, network=network
    )

    stakepool_request_script, _, stakepool_request_address = get_contract(
        "stakepool_request"
    )
    _, _, stakeholder_address = get_contract("stakeholder")
    _, _, stakechain_address = get_contract("stakechain")
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

    request_utxo = None
    request_state = None
    for u in context.utxos(stakepool_request_address):
        try:
            request_state = AddStakeRequest.from_cbor(u.output.datum.cbor)
        except DeserializeException as e:
            try:
                request_state = RemoveStakeRequest.from_cbor(u.output.datum.cbor)
            except DeserializeException as e:
                continue
        owner = request_state.owner
        if owner == to_address(payment_address).payment_credential.credential_hash:
            request_utxo = u
            break
    assert request_utxo is not None, "No open request with this owner found"

    txbuilder = TransactionBuilder(context)
    txbuilder.add_input_address(payment_address)
    txbuilder.add_script_input(
        request_utxo,
        stakepool_request_script,
        None,
        Redeemer(
            CancelRequest(),
        ),
    )
    txbuilder.auxiliary_data = pycardano.AuxiliaryData(
        data=pycardano.AlonzoMetadata(
            metadata=pycardano.Metadata(
                {
                    674: {"msg": ["Cancel Stake Request"]},
                }
            )
        )
    )
    txbuilder.required_signers = [payment_vkey.hash()]
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
