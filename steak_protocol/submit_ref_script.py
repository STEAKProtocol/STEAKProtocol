# create reference UTxOs
from time import sleep
from typing import List

import fire
import pycardano
from pycardano import (
    TransactionBuilder,
    TransactionOutput,
    min_lovelace,
    Value,
    PlutusV2Script,
    script_hash,
    UTxO,
)

from steak_protocol.onchain import one_shot_nft
from steak_protocol.onchain.stakechain import stakechain
from steak_protocol.onchain.stakeholder import stakeholder
from steak_protocol.onchain.stakepool import stakepool
from steak_protocol.utils import network, get_signing_info
from steak_protocol.utils.contracts import get_contract, get_ref_utxo, module_name
from steak_protocol.utils.network import context, show_tx


def submit_ref_script(contract_script: PlutusV2Script, name: str):
    owner = "scripts"
    payment_vkey, payment_skey, payment_address = get_signing_info(
        owner, network=network
    )

    while True:
        try:
            ref_utxo = get_ref_utxo(contract_script, context)
            if isinstance(ref_utxo, UTxO):
                print(f"reference script UTXO for {name} already exists")
                return ref_utxo.input
                break
            contract_address = pycardano.Address(
                payment_part=script_hash(contract_script), network=network
            )
            txbuilder = TransactionBuilder(context)
            output = TransactionOutput(
                contract_address, amount=1_000_000, script=contract_script
            )
            output.amount = Value(min_lovelace(context, output))
            txbuilder.add_output(output)
            txbuilder.add_input_address(payment_address)
            signed_tx = txbuilder.build_and_sign(
                signing_keys=[payment_skey], change_address=payment_address
            )
            context.submit_tx(signed_tx)
            print(
                f"creating {name} reference script UTXO; transaction id: {signed_tx.id}"
            )
            show_tx(signed_tx)
            return signed_tx
        except KeyboardInterrupt:
            exit()
        except Exception as e:
            print(f"Error: {e}")
            sleep(1)


def main(compress: bool = True):
    for contract in [
        stakechain,
        stakeholder,
        stakepool,
    ]:
        contract_script, _, _ = get_contract(module_name(contract), compressed=compress)
        tx = submit_ref_script(contract_script, module_name(contract))
    return tx


if __name__ == "__main__":
    fire.Fire(main)
