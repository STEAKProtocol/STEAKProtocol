import fire
import pycardano
from pycardano import (
    TransactionBuilder,
    DeserializeException,
    plutus_script_hash,
)

from steak_protocol.offchain.util import (
    STAKE_CHAIN_AUTH_NFT,
    amount_of_token_in_value,
    token_from_string,
    asset_from_token,
    ContractVersion,
    VERSION_0,
    VERSION_0a,
    VERSION_1,
)
from steak_protocol.onchain.types import (
    StakeChainV0State,
)
from steak_protocol.utils import get_signing_info, network, context
from steak_protocol.utils.contracts import get_contract, get_ref_utxo
from steak_protocol.utils.network import show_tx

from opshin.builder import apply_parameters


def main(
    name: str = "admin",
    stakechain_auth_nft: str = STAKE_CHAIN_AUTH_NFT,
    upgrade_len: int = 7,
    return_tx: bool = True,
    stakechain_upgrade_version: ContractVersion = VERSION_0,
):
    _, payment_skey, payment_address = get_signing_info(
        name, network=network
    )
#    _, _, stakechain_v0_address = get_contract(
#        "stakechain_" + VERSION_0
#    )
#    stakechain_script = get_ref_utxo(stakechain_script, context)
    stakechain_auth_nft = token_from_string(stakechain_auth_nft)

#    stakechain_utxo = None
#    stakechain_state = None
#    for u in context.utxos(stakechain_v0_address):
#        if amount_of_token_in_value(stakechain_auth_nft, u.output.amount) == 0:
#            continue
#        try:
#            stakechain_state = StakeChainV0State.from_cbor(u.output.datum.cbor)
#        except DeserializeException as e:
#            continue
#        stakechain_utxo = u
#        break
#    assert stakechain_utxo is not None, "No stake chain state found"

    stakechain_upgrade_script_raw, _, _ = get_contract(
        "stakechain_upgrade_" + stakechain_upgrade_version, compressed=True
    )
    stakechain_upgrade_script = apply_parameters(
        stakechain_upgrade_script_raw,
        upgrade_len,
        stakechain_auth_nft,
    )
    stakechain_upgrade_script_hash = plutus_script_hash(stakechain_upgrade_script)
#    assert (
#        stakechain_upgrade_script_hash.payload
#        == stakechain_state.params.upgrade_approval.credential_hash
#    ), "Invalid script parameterization"

    stakechain_upgrade_registration_cert = pycardano.StakeRegistration(
        pycardano.StakeCredential(stakechain_upgrade_script_hash)
    )

    # Build the transaction
    builder = TransactionBuilder(context)
    builder.add_input_address(payment_address)
    builder.certificates = [stakechain_upgrade_registration_cert]

    # Sign the transaction
    tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    context.submit_tx(tx)
    show_tx(tx)
    if return_tx:
        return tx


if __name__ == "__main__":
    fire.Fire(main)
