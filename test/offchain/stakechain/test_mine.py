from dataclasses import asdict
from time import sleep

from steak_protocol.offchain.stakechain.init import main as init_stakechain
from steak_protocol.offchain.stakeholder.init import main as init_stakeholder
from steak_protocol.offchain.stakechain.mine import main as mine_stakechain
from steak_protocol.submit_ref_script import main as submit_ref_script

from test.offchain.util import DEFAULT_CONFIG, wait_for_tx


def test_mine():
    wait_for_tx(submit_ref_script())
    stakechain_tx, stakechain_nft = init_stakechain(
        **asdict(DEFAULT_CONFIG),
    )
    wait_for_tx(
        stakechain_tx,
    )
    wait_for_tx(
        init_stakeholder(
            name=DEFAULT_CONFIG.name,
            stakechain_auth_nft=stakechain_nft,
            stake_amount=10000,
            stakeholder_id="0",
            skip_warning=True,
        )
    )
    sleep(DEFAULT_CONFIG.slot_length / 1000 + 1)
    wait_for_tx(
        mine_stakechain(
            name=DEFAULT_CONFIG.name,
            stakechain_auth_nft=stakechain_nft,
        )[0]
    )
