import datetime
import subprocess
import sys
from pathlib import Path
from typing import Union

import fire

from opshin.prelude import Token

from steak_protocol.onchain import (
    stakecoin,
    airdrop,
)
from steak_protocol.onchain.stakeholder import (
    stakeholder_auth_nft,
    stakeholder,
)
from steak_protocol.onchain.stakechain import (
    stakechain,
    stakechain_auth_nft,
    stakechain_upgrade,
)
from steak_protocol.onchain.stakepool import stakepool_request, stakepool
from steak_protocol.utils import network, get_signing_info, get_address
from steak_protocol.utils.to_script_context import to_address


def build_compressed(
    type: str, script: Union[Path, str], cli_options=("--cf",), args=()
):
    script = Path(script)
    command = [
        sys.executable,
        "-m",
        "opshin",
        *cli_options,
        "build",
        type,
        script,
        *args,
        "--recursion-limit",
        "3000",
        "-O3",
    ]
    subprocess.run(command, check=True)

    built_contract = Path(f"build/{script.stem}/script.cbor")
    built_contract_compressed_cbor = Path(f"build/tmp.cbor")

    try:
        with built_contract_compressed_cbor.open("wb") as fp:
            subprocess.run(
                ["aiken", "uplc", "shrink", built_contract, "--cbor", "--hex"],
                stdout=fp,
                check=True,
            )
    except subprocess.CalledProcessError:
        print(f"Failed to compress contract, did you install aiken?")
        exit(42)

    subprocess.run(
        [
            sys.executable,
            "-m",
            "uplc",
            "build",
            "--from-cbor",
            built_contract_compressed_cbor,
            "-o",
            f"build/{script.stem}_compressed",
            "--recursion-limit",
            "2000",
        ]
    )


def token_from_token_string(token: str) -> Token:
    policy_id, token_name = token.split(".")
    return Token(bytes.fromhex(policy_id), bytes.fromhex(token_name))


def main(
    airdrop_admin: str = "admin",
    airdrop_expiration: int = int(
        datetime.datetime(
            2024, 9, 1, tzinfo=datetime.timezone(datetime.timedelta())
        ).timestamp()
        * 1000
    ),
    airdrop_minutxo_receiver: str = "admin",
):
    admin_payment_vkey, admin_payment_skey, admin_payment_address = get_signing_info(
        airdrop_admin, network=network
    )
    airdrop_minutxo_receiver = get_address(airdrop_minutxo_receiver, network=network)
    build_compressed(
        "spending",
        airdrop.__file__,
        args=(
            to_address(airdrop_minutxo_receiver).to_json(),
            f'{{"bytes": "{admin_payment_vkey.hash().payload.hex()}"}}',
            f'{{"int": {airdrop_expiration}}}',
        ),
    )

    for script in (
        stakecoin,
        stakeholder_auth_nft,
    ):
        build_compressed("minting", script.__file__)
    for script in (
        stakechain,
        stakeholder,
        stakepool_request,
    ):
        build_compressed("spending", script.__file__)
    for script in (stakepool,):
        build_compressed("any", script.__file__)
    unique_stake_chain_nft_arg = b"stakechain"
    build_compressed(
        "minting",
        stakechain_auth_nft.__file__,
        args=(f'{{"bytes": "{unique_stake_chain_nft_arg.hex()}"}}',),
    )
    build_compressed(
        "rewarding",
        stakechain_upgrade.__file__,
    )


if __name__ == "__main__":
    fire.Fire(main)
