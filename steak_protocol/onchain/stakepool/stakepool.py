"""
A stake pool that pools liquidity from multiple users and stakes it in the chain.
"""

from steak_protocol.onchain.util import *


@dataclass
class PoolParams(PlutusData):
    initial_utxo: TxOutRef
    admin: Owner
    guaranteed_reward_fraction: Fraction
    stake_auth_nft: Token
    chain_auth_nft: Token


@dataclass
class PoolState(PlutusData):
    params: PoolParams
    all_lp_tokens: int


@dataclass
class AddStake(PlutusData):
    CONSTR_ID = 2
    own_input_index: int
    own_output_index: int
    chain_input_index: int
    chain_output_index: int


@dataclass
class RemoveStake(PlutusData):
    CONSTR_ID = 3
    own_input_index: int
    own_output_index: int
    chain_input_index: int
    chain_output_index: int


@dataclass
class InteractWithPool(PlutusData):
    CONSTR_ID = 4
    own_input_index: int
    own_output_index: int
    chain_input_index: int
    chain_output_index: int


@dataclass
class RegisterPool(PlutusData):
    CONSTR_ID = 5
    own_input_index: int  # this value is ignored
    own_output_index: int
    ref_input_index: int


StakePoolRedeemer = Union[AddStake, RemoveStake, InteractWithPool, RegisterPool]


def validator(
    redeemer: StakePoolRedeemer,
    context: ScriptContext,
) -> None:
    tx_info = context.tx_info
    purpose = context.purpose

    if isinstance(purpose, Minting):
        assert (
            StakingHash(ScriptCredential(purpose.policy_id)) in tx_info.wdrl.keys()
        ), "Policy must be in the withdrawal map"
        return None
    assert isinstance(purpose, Rewarding), "Purpose must be Rewarding or Minting"
    own_staking_hash = purpose.staking_credential
    assert isinstance(own_staking_hash, StakingHash), "Invalid staking hash"
    own_script_credential = own_staking_hash.value
    assert isinstance(
        own_script_credential, ScriptCredential
    ), "Invalid script credential"

    own_output = tx_info.outputs[redeemer.own_output_index]
    own_output_state: StakeHolderState = resolve_datum_unsafe(own_output, tx_info)
    check_output_reasonably_sized(own_output, own_output_state, 2000)
    assert (
        own_output_state.params.owner == own_script_credential
    ), "Owner must be the current script"
    own_pool_state_datum: SomeOutputDatum = own_output_state.aux
    own_pool_state: PoolState = own_pool_state_datum.datum
    own_pool_state_params = own_pool_state.params
    own_policy_id = own_script_credential.credential_hash
    own_token_name = sha2_256(serialise_data(own_pool_state_params.initial_utxo))
    if isinstance(redeemer, RegisterPool):
        # need to check that we don't spend any funds
        assert (
            sum(
                [
                    amount_of_token_in_output(
                        own_pool_state_params.stake_auth_nft, i.resolved
                    )
                    for i in tx_info.inputs
                ]
            )
            == 0
        ), "Must not spend any stake holder states"
        # and that the initial utxo is spent
        assert (
            tx_info.inputs[redeemer.ref_input_index].out_ref
            == own_pool_state_params.initial_utxo
        ), "Must spend the initial utxo"
        # check that the initial liquidity is 1000 which can not be withdrawn because their are no corresponding LP tokens
        # I.e. all stakecoin locked at init can not be withdrawn -> don't lock any at init (or minimum amount possible)
        assert not own_policy_id in tx_info.mint.keys(), "Must not mint any tokens"
        assert own_pool_state.all_lp_tokens == 1000, "Initial liquidity must be 1000"
        return None

    assert not isinstance(redeemer, RegisterPool), "Invalid redeemer"
    own_input = tx_info.inputs[redeemer.own_input_index].resolved
    own_input_state: StakeHolderState = resolve_datum_unsafe(own_input, tx_info)
    assert (
        own_input_state.params == own_output_state.params
    ), "Stake holder params must be preserved"
    chain_input = tx_info.inputs[redeemer.chain_input_index].resolved
    chain_input_state: StakeChainState = resolve_datum_unsafe(chain_input, tx_info)
    chain_output = tx_info.outputs[redeemer.chain_output_index]
    # we just ensure that the chain logic is correct
    chain_auth_nft = own_pool_state_params.chain_auth_nft
    assert (
        amount_of_token_in_output(chain_auth_nft, chain_input) == 1
    ), "Chain input must have exactly one auth NFT"
    assert (
        amount_of_token_in_output(chain_auth_nft, chain_output) == 1
    ), "Chain output must have exactly one auth NFT"

    if isinstance(redeemer, InteractWithPool):
        # check that aux data (#lp-tokens & pool state) is preserved
        assert (
            own_input_state.aux == own_output_state.aux
        ), "Auxiliary data must be preserved"
        # and we check that the owner signed the tx
        admin = own_pool_state_params.admin
        check_owner_signed_tx(admin, tx_info)
        # we also check that no stakecoins go anywhere except to the pool or the chain
        stake_coin = chain_input_state.params.stake_coin
        coin_in_contract_before = amount_of_token_in_output(stake_coin, chain_input)
        coin_in_contract_after = amount_of_token_in_output(stake_coin, chain_output)
        coin_rewarded = coin_in_contract_before - coin_in_contract_after
        assert coin_rewarded >= 0, "Stake coin can not be moved back into chain"
        own_in_coin = amount_of_token_in_output(stake_coin, own_input)
        own_out_coin = amount_of_token_in_output(stake_coin, own_output)
        own_coin_increase = own_out_coin - own_in_coin
        assert own_coin_increase >= ceil_fraction(
            scale_fraction(
                coin_rewarded, own_pool_state_params.guaranteed_reward_fraction
            )
        ), "Admin must get no more than reward fraction"
    else:
        pool_input_state_datum: SomeOutputDatum = own_input_state.aux
        pool_input_state: PoolState = pool_input_state_datum.datum
        chain_output_state: StakeChainState = resolve_datum_unsafe(
            chain_output, tx_info
        )
        # no block mining
        assert (
            chain_output_state.chain_state == chain_input_state.chain_state
        ), "Chain state must be preserved"

        stakecoin = chain_input_state.params.stake_coin

        all_lp_tokens = pool_input_state.all_lp_tokens

        prev_value = amount_of_token_in_output(stakecoin, own_input)
        new_value = amount_of_token_in_output(stakecoin, own_output)
        delta_value = new_value - prev_value

        assert (
            own_pool_state_params == pool_input_state.params
        ), "Pool params must be preserved"
        new_all_lp_tokens = own_pool_state.all_lp_tokens

        if isinstance(redeemer, AddStake):
            # we check that the stake is added correctly
            assert delta_value > 0, "Stake must be added"
            # mint lp tokens x such that x/new_tokens = delta_value/new_value
            # i.e. x / (x + all_lp_tokens) = delta_value / new_value
            # i.e. x = all_lp_tokens * delta_value / (new_value - delta_value)
            minted_value = all_lp_tokens * delta_value // (new_value - delta_value)
            check_mint_exactly_n_with_name(
                tx_info.mint, minted_value, own_policy_id, own_token_name
            )
            assert (
                new_all_lp_tokens == all_lp_tokens + minted_value
            ), "Auxiliary data must be updated"
        elif isinstance(redeemer, RemoveStake):
            # we check that the stake is removed correctly
            assert delta_value < 0, "Stake must be removed"
            # must remove proportionally to the stake
            # i.e. must burn lp tokens x such that x/all_lp_tokens = delta_value/prev_value
            # i.e. x = all_lp_tokens * delta_value / prev_value
            burned_value = all_lp_tokens * delta_value // prev_value + 1
            check_mint_exactly_n_with_name(
                tx_info.mint, burned_value, own_policy_id, own_token_name
            )
            assert (
                new_all_lp_tokens == all_lp_tokens + burned_value
            ), "Auxiliary data must be updated"
        else:
            assert False, "Invalid redeemer"
