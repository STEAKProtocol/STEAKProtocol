"""
Script specifically to generate the upgrade proposal from version 0 to version 1 of the stake chain contract.

- Changes the stake chain contract from version 0 to version 1.
- Changes the stake chain upgrade contract from version 0 to version 1.
- Introduces slot leader interval parameter to the stake chain contract at 30 (minutes).
"""

from fractions import Fraction

import fire
from opshin.ledger.api_v2 import (
    ScriptCredential,
    SomeOutputDatumHash,
)
from opshin.prelude import Nothing
from pycardano import (
    DeserializeException,
    plutus_script_hash,
    datum_hash,
)

from steak_protocol.offchain.util import (
    STAKE_CHAIN_AUTH_NFT,
    amount_of_token_in_value,
    token_from_string,
    VERSION_0,
    VERSION_1,
)
from steak_protocol.onchain.stakechain.stakechain_upgrade_v0a import (
    ChainUpgradeProposal,
)
from steak_protocol.onchain.types import (
    StakeChainV0State,
    StakeChainV1Params,
)
from steak_protocol.utils import context
from steak_protocol.utils.contracts import get_contract
from steak_protocol.utils.to_script_context import (
    to_address,
    to_fraction,
)

from opshin.builder import apply_parameters


def main(
    stakechain_auth_nft: str = STAKE_CHAIN_AUTH_NFT,
    upgrade_length: int = 7,
    slot_leader_interval: int = 30,
    register_fee: int = 50_000_000_000,
    fraction_per_block: int = "8/500000",
):
    _, _, stakechain_v0_address = get_contract(
        "stakechain_" + VERSION_0
    )
    _, _, stakechain_v1_address = get_contract(
        "stakechain_" + VERSION_1
    )
    stakechain_auth_nft = token_from_string(stakechain_auth_nft)

    stakechain_utxo = None
    stakechain_state = None
    for u in context.utxos(stakechain_v0_address):
        if amount_of_token_in_value(stakechain_auth_nft, u.output.amount) == 0:
            continue
        try:
            stakechain_state = StakeChainV0State.from_cbor(u.output.datum.cbor)
        except DeserializeException as e:
            continue
        stakechain_utxo = u
        break
    assert stakechain_utxo is not None, "No stake chain state found"

    stakechain_upgrade_script_raw, _, _ = get_contract(
        "stakechain_upgrade_" + VERSION_1, compressed=True
    )
    stakechain_upgrade_script = apply_parameters(
        stakechain_upgrade_script_raw,
        upgrade_length,
        stakechain_auth_nft,
    )
    stakechain_upgrade_script_hash = plutus_script_hash(stakechain_upgrade_script)

    prev_params = stakechain_state.params
    upgrade_proposal = ChainUpgradeProposal(
        upgrade_address=to_address(stakechain_v1_address),
        upgrade_params=StakeChainV1Params(
            # changed parameters
            fraction_per_block=to_fraction(Fraction(fraction_per_block)),
            register_fee=register_fee,
            upgrade_approval=ScriptCredential(stakechain_upgrade_script_hash.payload),
            slot_leader_interval=slot_leader_interval,
            # unchanged parameters
            stakeholder_address=prev_params.stakeholder_address,
            stakeholder_auth_nft=prev_params.stakeholder_auth_nft,
            slot_length=prev_params.slot_length,
            stake_coin=prev_params.stake_coin,
            auth_nft=prev_params.auth_nft,
            genesis_time=prev_params.genesis_time,
            num_slot_leaders=prev_params.num_slot_leaders,
            max_holders=prev_params.max_holders,
        ),
        payout_txout=Nothing(),
        take_treasury=Nothing(),
    )
    print(
        "Raw proposal (to be submitted in upgrade redeemer):",
        upgrade_proposal.to_cbor().hex(),
    )
    print("Proposal Datum hash:", datum_hash(upgrade_proposal).payload.hex())
    print(
        "Output Datum hash cbor (to be included in pool aux):",
        SomeOutputDatumHash(datum_hash(upgrade_proposal).payload).to_cbor().hex(),
    )


if __name__ == "__main__":
    fire.Fire(main)
