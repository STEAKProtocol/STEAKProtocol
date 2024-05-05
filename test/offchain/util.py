import dataclasses
import time
from typing import Union

import pycardano

from steak_protocol.utils.network import context


@dataclasses.dataclass()
class StakeChainConfig:
    name: str = "admin"
    stake_coin_total_supply: int = 77_777_777_000_000
    slot_length: int = 1 * 60 * 1000
    stakecoin_name: str = "stakecoin"
    fraction_per_block: int = f"3/{int(10_000_000)}"
    register_fee: int = 7_000_000
    num_slot_leaders: int = 1
    max_holders: int = 20
    cip67_wallet: str = "cip67"
    fraction_ico: str = "20/100"
    image: str = (
        "ipfs://QmcLT4S5SHqQUAHzD1MDLSG1hfggLERh9NPVwUfaNbueht/logo_cropped.png"
    )
    image_type: str = "image/png"
    description: str = (
        "The native token of the STEAK Chain protocol powering sustainable random number oracles on Cardano."
    )
    ticker: str = "STK"
    decimals: int = 6
    website: str = "https://steakprotocol.com"
    upgrade_length: int = 7


DEFAULT_CONFIG = StakeChainConfig()


def wait_for_tx(
    tx: Union[pycardano.Transaction, pycardano.TransactionInput],
    context: pycardano.OgmiosChainContext = context,
):
    while not context.utxo_by_tx_id(
        (
            tx.id.payload
            if isinstance(tx, pycardano.Transaction)
            else tx.transaction_id.payload
        ).hex(),
        0,
    ):
        time.sleep(1)
        print("Waiting for transaction to be included in the blockchain")
