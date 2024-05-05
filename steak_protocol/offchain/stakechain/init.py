import datetime
import fractions

import fire
import pycardano
import uplc.ast
from opshin.ledger.api_v2 import PubKeyCredential, SomeOutputDatum, ScriptCredential
from opshin.prelude import Token, Nothing
from pycardano import (
    TransactionBuilder,
    script_hash,
    TransactionOutput,
    Value,
    Redeemer,
    RawCBOR,
    plutus_script_hash,
)

from steak_protocol.offchain.util import (
    sorted_utxos,
    with_min_lovelace,
    asset_from_token,
)
from steak_protocol.onchain import stakecoin
from steak_protocol.onchain.stakechain.stakechain_auth_nft import one_shot_nft_name
from steak_protocol.onchain.types import (
    StakeChainState,
    CoreChainState,
    StakeChainParams,
    StakeHolderRegistrations,
    ProducerState,
)
from steak_protocol.utils import get_signing_info, network, context
from steak_protocol.utils.contracts import get_contract
from steak_protocol.utils.network import show_tx
from steak_protocol.utils.to_script_context import (
    to_tx_out_ref,
    to_address,
    to_fraction,
)

from opshin.builder import apply_parameters


def split_if_too_large(metadata: str):
    if isinstance(metadata, str):
        metadata = metadata.encode("utf8")
    if len(metadata) < 64:
        return metadata
    metadata_split = []
    for i in range(0, len(metadata), 64):
        metadata_split.append(metadata[i : i + 64])
    return metadata_split


def wrap(x):
    if isinstance(x, dict):
        return uplc.ast.PlutusMap({wrap(k): wrap(v) for k, v in x.items()})
    if isinstance(x, list):
        return uplc.ast.PlutusList([wrap(y) for y in x])
    if isinstance(x, str):
        return uplc.ast.PlutusByteString(x.encode("utf8"))
    if isinstance(x, int):
        return uplc.ast.PlutusInteger(x)
    if isinstance(x, bytes):
        return uplc.ast.PlutusByteString(x)
    return x


def main(
    name: str = "admin",
    stake_coin_total_supply: int = 77_777_777_000_000,
    slot_length: int = 1 * 60 * 1000,
    stakecoin_name: str = "stakecoin",
    fraction_per_block: int = f"3/{int(10_000_000)}",
    register_fee: int = 7_000_000,
    num_slot_leaders: int = 1,
    max_holders: int = 20,
    cip67_wallet: str = "cip67",
    fraction_ico: str = "20/100",
    image: str = "ipfs://QmcLT4S5SHqQUAHzD1MDLSG1hfggLERh9NPVwUfaNbueht/logo_cropped.png",
    image_type: str = "image/png",
    description: str = "The native token of the STEAK Chain protocol, powering sustainable random number oracles on Cardano.",
    ticker: str = "STK",
    decimals: int = 6,
    website: str = "https://steakprotocol.com",
    upgrade_length: int = 7,
):
    payment_vkey, payment_skey, payment_address = get_signing_info(
        name, network=network
    )

    # generate coin
    utxos = context.utxos(payment_address)
    assert len(utxos) > 0, f"No UTxOs found at {payment_address}"
    utxo_to_spend = utxos[0]
    utxo_plutus_ref = to_tx_out_ref(utxo_to_spend.input)
    stakecoin_raw_script, _, _ = get_contract("stakecoin", context=None)
    stake_coin_script = apply_parameters(stakecoin_raw_script, utxo_plutus_ref)
    stake_coin_policy_id = script_hash(stake_coin_script)
    _, _, stakeholder_address = get_contract("stakeholder")
    # we want a unicode token name
    # but CIP 67/68 break this so whatever
    token_name = bytes.fromhex("0014df10") + stakecoin_name.encode("utf8")
    ref_token_name = bytes.fromhex("000643b0") + stakecoin_name.encode("utf8")
    stake_coin = Token(
        policy_id=stake_coin_policy_id.payload,
        token_name=token_name,
    )
    ref_stake_coin = Token(
        policy_id=stake_coin_policy_id.payload,
        token_name=ref_token_name,
    )
    stakechain_auth_nft_script, stakechain_auth_nft_policyid, _ = get_contract(
        "stakechain_auth_nft"
    )
    stakechain_auth_nft_tokenname = one_shot_nft_name(utxo_plutus_ref)
    stakechain_auth_nft = Token(
        policy_id=stakechain_auth_nft_policyid.payload,
        token_name=stakechain_auth_nft_tokenname,
    )
    stakeholder_auth_nft_script_raw, _, _ = get_contract("stakeholder_auth_nft")
    stakeholder_auth_nft_script = apply_parameters(
        stakeholder_auth_nft_script_raw, stakechain_auth_nft
    )
    stakeholder_auth_nft_policy_id = script_hash(stakeholder_auth_nft_script)
    _, _, stakechain_address = get_contract("stakechain")

    # rebuild script with parameters
    stakechain_upgrade_script_raw, _, _ = get_contract(
        "stakechain_upgrade", compressed=True
    )
    stakechain_upgrade_script = apply_parameters(
        stakechain_upgrade_script_raw,
        upgrade_length,
        stakechain_auth_nft,
    )
    stakechain_upgrade_script_hash = plutus_script_hash(stakechain_upgrade_script)

    stake_chain_initial_state = StakeChainState(
        params=StakeChainParams(
            stakeholder_address=to_address(stakeholder_address),
            stakeholder_auth_nft=Token(
                stakeholder_auth_nft_policy_id.payload,
                stakechain_auth_nft_tokenname,
            ),
            slot_length=slot_length,
            stake_coin=stake_coin,
            fraction_per_block=to_fraction(fractions.Fraction(fraction_per_block)),
            auth_nft=stakechain_auth_nft,
            genesis_time=int(datetime.datetime.now().timestamp() * 1000),
            register_fee=register_fee,
            upgrade_approval=ScriptCredential(stakechain_upgrade_script_hash.payload),
            num_slot_leaders=num_slot_leaders,
            max_holders=max_holders,
        ),
        holder_state=StakeHolderRegistrations(
            stake_holder_weights=[],
            stake_holder_ids=[],
        ),
        chain_state=CoreChainState(
            block_number=0,
            block_hash=b"",
            slot_number=0,
        ),
        producer_state=ProducerState(
            producer_signature=b"",
            auxiliary=SomeOutputDatum(0),
            prev_producer_state_hash=b"",
        ),
        skip_holders=-1000,
        spent_for=Nothing(),
    )
    all_input_utxos = sorted_utxos(utxos)
    ref_utxo_index = all_input_utxos.index(utxo_to_spend)

    fraction_ico = fractions.Fraction(fraction_ico)
    minted_asset = (
        asset_from_token(stakechain_auth_nft, 1)
        + asset_from_token(
            stake_coin,
            stake_coin_total_supply,
        )
        + asset_from_token(ref_stake_coin, 1)
    )

    txbuilder = TransactionBuilder(context)
    for u in all_input_utxos:
        txbuilder.add_input(u)
    txbuilder.add_output(
        with_min_lovelace(
            TransactionOutput(
                stakechain_address,
                amount=Value(
                    coin=1_000_000,
                    multi_asset=minted_asset
                    - asset_from_token(
                        stake_coin, int(fraction_ico * stake_coin_total_supply)
                    )
                    - asset_from_token(ref_stake_coin, 1),
                ),
                datum=stake_chain_initial_state,
            ),
            context,
        )
    )
    txbuilder.mint = minted_asset
    txbuilder.add_minting_script(
        stakechain_auth_nft_script,
        Redeemer(ref_utxo_index),
    )
    txbuilder.add_minting_script(
        stake_coin_script,
        Redeemer(stakecoin.Mint(ref_utxo_index)),
    )
    # set metadata according to CIP 25
    txbuilder.auxiliary_data = pycardano.AuxiliaryData(
        data=pycardano.AlonzoMetadata(
            metadata=pycardano.Metadata(
                {
                    674: {"msg": ["Stake Chain Init"]},
                    721: {
                        stake_coin.policy_id: {
                            token_name: {
                                "name": stakecoin_name,
                                "image": split_if_too_large(image),
                                "mediaType": split_if_too_large(image_type),
                                "description": split_if_too_large(description),
                                "website": split_if_too_large(website),
                                "ticker": ticker,
                                "decimalPlaces": decimals,
                                "decimals": decimals,
                            },
                        },
                        "version": 2,
                    },
                }
            )
        )
    )
    _, _, cip67_wallet_address = get_signing_info(cip67_wallet, network=network)
    txbuilder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=cip67_wallet_address,
                amount=Value(
                    coin=1,
                    multi_asset=asset_from_token(ref_stake_coin, 1),
                ),
                datum=RawCBOR(
                    uplc.ast.plutus_cbor_dumps(
                        uplc.ast.PlutusConstr(
                            0,
                            [
                                wrap(
                                    {
                                        b"name": stakecoin_name.encode("utf8"),
                                        b"image": image.encode("utf8"),
                                        b"mediaType": image_type.encode("utf8"),
                                        b"description": (description).encode("utf8"),
                                        b"website": website.encode("utf8"),
                                        b"ticker": ticker.encode("utf8"),
                                        b"decimals": decimals,
                                    }
                                ),
                                uplc.ast.PlutusInteger(1),
                                uplc.ast.PlutusConstr(0, []),
                            ],
                        )
                    )
                ),
            ),
            context,
        )
    )
    txbuilder.fee_buffer = 1000
    txbuilder.collaterals = sorted(utxos, key=lambda u: u.output.amount.coin)[:3]
    tx = txbuilder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    context.submit_tx(tx)
    show_tx(tx)
    print("Stake Chain Init complete")
    print(
        "Stake Chain Auth NFT:",
        stakechain_auth_nft.policy_id.hex(),
        stakechain_auth_nft.token_name.hex(),
    )
    return (
        tx,
        f"{stakechain_auth_nft.policy_id.hex()}.{stakechain_auth_nft_tokenname.hex()}",
    )


if __name__ == "__main__":
    fire.Fire(main)
