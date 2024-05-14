import functools
import os
from typing import List

import blockfrost
import ogmios

import pycardano
from pycardano import Network, OgmiosChainContext, BlockFrostChainContext

ogmios_host = os.getenv("OGMIOS_API_HOST", "localhost")
ogmios_port = os.getenv("OGMIOS_API_PORT", "1337")
ogmios_protocol = os.getenv("OGMIOS_API_PROTOCOL", "ws")
ogmios_url = f"{ogmios_protocol}://{ogmios_host}:{ogmios_port}"

kupo_host = os.getenv("KUPO_API_HOST", None)
kupo_port = os.getenv("KUPO_API_PORT", "80")
kupo_protocol = os.getenv("KUPO_API_PROTOCOL", "http")
kupo_url = (f"{kupo_protocol}://{kupo_host}:{kupo_port}") if kupo_host else None

blockfrost_project_id = os.getenv("BLOCKFROST_PROJECT_ID", None)

network = Network.MAINNET

# Load chain context
if blockfrost_project_id is not None:
    context = BlockFrostChainContext(
        blockfrost_project_id,
        base_url=(
            blockfrost.ApiUrls.mainnet.value
            if network == Network.MAINNET
            else blockfrost.ApiUrls.preview.value
        ),
    )
else:
    try:
        context = OgmiosChainContext(ogmios_url, network=network, kupo_url=kupo_url)
    except Exception:
        try:
            context = ogmios.OgmiosChainContext(
                host=ogmios_host,
                port=int(ogmios_port),
                secure=ogmios_protocol == "wss",
                network=network,
            )
        except Exception as e:
            print("No ogmios available")
            context = None

_datum_cache = {}

if kupo_url and (
    isinstance(context, ogmios.OgmiosChainContext)
    or isinstance(context, BlockFrostChainContext)
):
    # ugly hack
    context._datum_cache = _datum_cache
    context._kupo_url = kupo_url
    context._get_datum_from_kupo = functools.partial(
        OgmiosChainContext._get_datum_from_kupo, context
    )
    context._extract_asset_info = functools.partial(
        OgmiosChainContext._extract_asset_info, context
    )
    context._utxos = functools.partial(OgmiosChainContext._utxos_kupo, context)
    # end of ugly hack


def show_tx(signed_tx: pycardano.Transaction):
    tx_hash = signed_tx.id.payload.hex()
    print(f"transaction id: {tx_hash}")
    if network == Network.MAINNET:
        print(f"Cexplorer: https://cexplorer.io/tx/{tx_hash}")
        print(f"Cardanoscan: https://cardanoscan.io/transaction/{tx_hash}")
    else:
        print(f"Cexplorer: https://preview.cexplorer.io/tx/{tx_hash}")
        print(f"Cexplorer: https://preprod.cexplorer.io/tx/{tx_hash}")
        print(f"Yaci: http://localhost:5173/transactions/{tx_hash}")
