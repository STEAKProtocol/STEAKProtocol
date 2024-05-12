import json
from hashlib import sha256
from typing import List, Union

import pycardano

from opshin.prelude import Token
from pycardano import (
    MultiAsset,
    ScriptHash,
    Asset,
    AssetName,
    Value,
    Transaction,
    VerificationKeyWitness,
    SigningKey,
    ExtendedSigningKey,
)

from steak_protocol.utils.keys import keys_dir

STAKE_CHAIN_AUTH_NFT = "dfc450815c964e21bc9dd8e4ed1029c3407408c9fa95c48e1484f368.221c348f186c3e43ac9863a52d619d8183a274e7e15b40fa733b57fc76fd27f4"
INITIAL_STAKE_POOL_LIQUIDITY = 1_000


def token_from_string(token: str) -> Token:
    if token == "lovelace":
        return Token(b"", b"")
    policy_id, token_name = token.split(".")
    return Token(
        policy_id=bytes.fromhex(policy_id),
        token_name=bytes.fromhex(token_name),
    )


def value_from_token(token: Token, amount: int) -> Value:
    if token.policy_id == b"" and token.token_name == b"":
        return pycardano.Value(coin=amount)
    return pycardano.Value(multi_asset=asset_from_token(token, amount))


def asset_from_token(token: Token, amount: int) -> MultiAsset:
    return MultiAsset(
        {ScriptHash(token.policy_id): Asset({AssetName(token.token_name): amount})}
    )


def with_min_lovelace(
    output: pycardano.TransactionOutput, context: pycardano.ChainContext
):
    min_lvl = pycardano.min_lovelace(context, output)
    output.amount.coin = max(output.amount.coin, min_lvl + 500000)
    return output


def sorted_utxos(txs: List[pycardano.UTxO]):
    return sorted(
        txs,
        key=lambda u: (u.input.transaction_id.payload, u.input.index),
    )


def amount_of_token_in_value(
    token: Token,
    value: Value,
) -> int:
    return value.multi_asset.get(ScriptHash(token.policy_id), {}).get(
        AssetName(token.token_name), 0
    )


def adjust_for_wrong_fee(
    tx_signed: Transaction,
    signing_keys: List[Union[SigningKey, ExtendedSigningKey]],
    output_offset: int = 0,
    fee_offset: int = 0,
) -> Transaction:
    new_value = pycardano.transaction.Value(
        coin=tx_signed.transaction_body.outputs[-1].amount.coin
        - output_offset
        - fee_offset,
        multi_asset=tx_signed.transaction_body.outputs[-1].amount.multi_asset,
    )
    tx_signed.transaction_body.outputs[-1].amount = new_value
    tx_signed.transaction_body.fee += fee_offset

    witness_set = tx_signed.transaction_witness_set
    witness_set.vkey_witnesses = []
    for signing_key in set(signing_keys):
        signature = signing_key.sign(tx_signed.transaction_body.hash())
        witness_set.vkey_witnesses.append(
            VerificationKeyWitness(signing_key.to_verification_key(), signature)
        )
    return Transaction(
        tx_signed.transaction_body, witness_set, auxiliary_data=tx_signed.auxiliary_data
    )


def committed_hash_secrets(name: str):
    with open(keys_dir / f"{name}.hash_secret") as f:
        return [bytes.fromhex(x) for x in json.load(f)]


def commit_hash_secrets(name: str, secrets: List[bytes]):
    with open(keys_dir / f"{name}.hash_secret", "w") as f:
        json.dump([x.hex() for x in secrets], f)


def custom_sign_message(secret: bytes, message: bytes) -> bytes:
    return sha256(message + secret).digest()
