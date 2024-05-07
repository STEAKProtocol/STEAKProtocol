from dataclasses import asdict
from time import sleep

from opshin.prelude import Nothing
from pycardano import datum_hash

from steak_protocol.offchain.stakechain.init import main as init_stakechain
from steak_protocol.offchain.stakeholder.init import main as init_stakeholder
from steak_protocol.offchain.stakechain.mine import mine as mine_stakechain
from steak_protocol.onchain.stakechain.stakechain_upgrade import ChainUpgradeProposal
from steak_protocol.submit_ref_script import main as submit_ref_script
from steak_protocol.offchain.stakechain.upgrade import main as upgrade_stakechain
from steak_protocol.offchain.stakechain.register_upgrade import main as register_upgrade
from steak_protocol.utils import get_address
from steak_protocol.utils.to_script_context import to_address

from test.offchain.util import DEFAULT_CONFIG, wait_for_tx


def test_upgrade():
    wait_for_tx(submit_ref_script())
    stakechain_tx, stakechain_nft = init_stakechain(
        **asdict(DEFAULT_CONFIG),
        return_tx=True,
    )
    wait_for_tx(
        stakechain_tx,
    )
    try:
        wait_for_tx(
            register_upgrade(
                DEFAULT_CONFIG.name,
                stakechain_nft,
                DEFAULT_CONFIG.upgrade_length,
                return_tx=True,
            )
        )
    except Exception as e:
        print("already registered")

    wait_for_tx(
        init_stakeholder(
            name=DEFAULT_CONFIG.name,
            stakechain_auth_nft=stakechain_nft,
            stake_amount=10000,
            stakeholder_id="0",
            skip_warning=True,
            return_tx=True,
        )
    )
    upgrade_proposal = ChainUpgradeProposal(
        upgrade_address=to_address(get_address(DEFAULT_CONFIG.name)),
        upgrade_params=Nothing(),
        payout_txout=Nothing(),
        take_treasury=Nothing(),
    )
    upgrade_proposal_hash = datum_hash(upgrade_proposal)
    stakechain_states = []
    for i in range(DEFAULT_CONFIG.upgrade_length):
        successful = False
        retries = 0
        while not successful:
            try:
                sleep(DEFAULT_CONFIG.slot_length / 1000 + 1)
                tx, state = mine_stakechain(
                    name=DEFAULT_CONFIG.name,
                    stakechain_auth_nft=stakechain_nft,
                    producer_message_hash_hex=upgrade_proposal_hash.payload.hex(),
                )
                wait_for_tx(tx)
                stakechain_states.append(state)
                successful = True
            except Exception as e:
                print(f"Exception mining block {i}, retrying", e)
                if retries > 3:
                    print(e)
                    assert False
                continue
    wait_for_tx(
        upgrade_stakechain(
            name=DEFAULT_CONFIG.name,
            stakechain_auth_nft=stakechain_nft,
            previous_producer_states_cbor=list(
                reversed(
                    [
                        state.producer_state.to_cbor().hex()
                        for state in stakechain_states[:-1]
                    ]
                )
            ),
            proposal_cbor=upgrade_proposal.to_cbor().hex(),
            return_tx=True,
        )
    )
