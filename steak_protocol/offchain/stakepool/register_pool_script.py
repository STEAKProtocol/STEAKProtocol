import fire
import pycardano

from opshin.prelude import Token, TxOutRef, TxId
from opshin.ledger.api_v2 import (
    PubKeyCredential,
)
from steak_protocol.utils import context
from steak_protocol.utils.network import show_tx
from steak_protocol.utils.to_script_context import to_address
from opshin.prelude import Token
from pycardano import (
    TransactionBuilder,
    DeserializeException,
    StakeRegistration,
    StakeCredential,
    script_hash,
    plutus_script_hash,
)
from steak_protocol.onchain.types import (
    StakeChainV0State,
)
from steak_protocol.offchain.util import (
    token_from_string,
    STAKE_CHAIN_AUTH_NFT,
    amount_of_token_in_value,
    ContractVersion,
    VERSION_0,
)
from steak_protocol.utils import get_signing_info, network, context
from steak_protocol.utils.contracts import get_contract

from opshin.builder import apply_parameters


def main(
    name: str = "admin",
    stakechain_auth_nft: str = STAKE_CHAIN_AUTH_NFT,
    return_tx: bool = False,
    stakechain_version: ContractVersion = VERSION_0,
):
    payment_vkey, payment_skey, payment_address = get_signing_info(
        name, network=network
    )
    _, _, stakechain_address = get_contract("stakechain_" + stakechain_version)
    _, _, stakeholder_address = get_contract("stakeholder")
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

    assert stakechain_state.params.stakeholder_address == to_address(
        stakeholder_address
    ), "Wrong stakeholder address"

    stakeholder_auth_nft_script_raw, _, _ = get_contract(
        "stakeholder_auth_nft", compressed=True
    )
    stakeholder_auth_nft_script = apply_parameters(
        stakeholder_auth_nft_script_raw, stakechain_auth_nft
    )
    stakepool_script, _, stakepool_address = get_contract("stakepool")

    stakepool_registration_cert = StakeRegistration(
        StakeCredential(plutus_script_hash(stakepool_script))
    )

    builder = TransactionBuilder(context)
    builder.add_input_address(payment_address)
    builder.certificates = [stakepool_registration_cert]

    signed_tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    context.submit_tx(signed_tx)
    show_tx(signed_tx)
    if return_tx:
        return signed_tx


if __name__ == "__main__":
    fire.Fire(main)
