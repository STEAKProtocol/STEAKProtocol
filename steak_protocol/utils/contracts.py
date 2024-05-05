from pathlib import Path
from typing import Union

from pycardano import (
    PaymentVerificationKey,
    PaymentSigningKey,
    Address,
    Network,
    PlutusV2Script,
    plutus_script_hash,
    ChainContext,
    UTxO,
)

from .keys import get_address
from .network import network, context

build_dir = Path(__file__).parent.parent.parent.joinpath("build")


def module_name(module):
    return Path(module.__file__).stem


def get_contract(name, compressed=True, context=context):
    with open(
        build_dir.joinpath(f"{name}{'_compressed' if compressed else ''}/script.cbor")
    ) as f:
        contract_cbor_hex = f.read().strip()
    contract_cbor = bytes.fromhex(contract_cbor_hex)

    contract_plutus_script = PlutusV2Script(contract_cbor)
    contract_script_hash = plutus_script_hash(contract_plutus_script)
    contract_script_address = Address(contract_script_hash, network=network)
    if context is not None:
        contract_plutus_script_ref = get_ref_utxo(contract_plutus_script, context)
        if contract_plutus_script_ref is not None:
            contract_plutus_script = contract_plutus_script_ref
    return contract_plutus_script, contract_script_hash, contract_script_address


def get_ref_utxo(contract: Union[PlutusV2Script, UTxO], context: ChainContext):
    if isinstance(contract, UTxO):
        return contract
    script_address = Address(payment_part=plutus_script_hash(contract), network=network)
    for utxo in context.utxos(script_address):
        if utxo.output.script == contract:
            return utxo
    return contract
