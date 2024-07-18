import datetime
import subprocess
import sys
from pathlib import Path
from typing import Union

import fire
import pycardano

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
    stakechain_v0,
    stakechain_upgrade_v0,
    stakechain_upgrade_v0a,
    stakechain_v1,
    stakechain_auth_nft,
    stakechain_upgrade_v1,
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
    airdrop_admin_address: str = "addr1v9w2fjjd3zza2kk0r5qezakqckpuyyhays00g5393ksrn9q0fkekw",
    airdrop_expiration: int = int(
        datetime.datetime(
            2025, 1, 1, tzinfo=datetime.timezone(datetime.timedelta())
        ).timestamp()
        * 1000
    ),
    airdrop_minutxo_receiver_address: str = "addr1qxure479tsn845ljg706qnj8w92ge4765e4pakxumnq6n2sg23qataexxxye75kx8jjd9cx50jh3h3f7amv2f6d65j8quk4z45",
):
    airdrop_admin_address = pycardano.Address.from_primitive(airdrop_admin_address)
    airdrop_minutxo_receiver = pycardano.Address.from_primitive(
        airdrop_minutxo_receiver_address
    )
    build_compressed(
        "spending",
        airdrop.__file__,
        args=(
            to_address(airdrop_minutxo_receiver).to_json(),
            f'{{"bytes": "{airdrop_admin_address.payment_part.payload.hex()}"}}',
            f'{{"int": {airdrop_expiration}}}',
        ),
    )

    for script in (
        stakecoin,
        stakeholder_auth_nft,
    ):
        build_compressed("minting", script.__file__)
    for script in (
        stakechain_v0,
        stakechain_v1,
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
    for script in (
        stakechain_upgrade_v0,
        stakechain_upgrade_v0a,
        stakechain_upgrade_v1,
    ):
        build_compressed("rewarding", script.__file__)


if __name__ == "__main__":
    fire.Fire(main)
