from opshin.prelude import *
from opshin.std.fractions import *

Owner = Union[PubKeyCredential, ScriptCredential]


@dataclass
class StakeChainParams(PlutusData):
    CONSTR_ID = 0
    # The address of the stake holder (NOTE: the position of this should not change in upgrades)
    stakeholder_address: Address
    # The unique nft identifying valid stake holders
    stakeholder_auth_nft: Token
    # slot length in milliseconds
    slot_length: POSIXTime
    # The token to be distributed as reward
    stake_coin: Token
    # fraction of remaining tokens to distribute each block (recommended: Fraction(5, 10000000))
    fraction_per_block: Fraction
    # The unique NFT identifying the correct stake chain thread
    auth_nft: Token
    # Genesis time
    genesis_time: POSIXTime
    # Fee for registering a stake holder in stake coin
    register_fee: int
    # Upgrade approval contract
    upgrade_approval: Owner
    # number of slot leaders per slot
    num_slot_leaders: int
    # max number of holders (for which MineBlock still goes through)
    max_holders: int


@dataclass
class StakeHolderRegistrations(PlutusData):
    CONSTR_ID = 0
    # weights of registered holders
    stake_holder_weights: List[int]
    # holder ids of registered holders
    stake_holder_ids: List[bytes]


@dataclass
class CoreChainState(PlutusData):
    """
    The core of the chain state
    which should not be changed when adjusting holders.
    """

    CONSTR_ID = 0
    # The current block number
    block_number: int
    # The current hash of the chain
    block_hash: bytes
    # the slot number
    slot_number: int


@dataclass
class ProducerState(PlutusData):
    """
    The message of the producer to validate this block
    """

    CONSTR_ID = 0

    # the signature of the slot leader that produced the block
    producer_signature: bytes
    # creator chosen message, should not be tampered with during holder adjustments
    auxiliary: OutputDatum
    # hash of the previous producer state
    prev_producer_state_hash: bytes


@dataclass
class ReducedChainState(PlutusData):
    """
    A Stake Chain state that is reduced in size and detail in comparison to the full state.
    It allows verifying the chain state without having to store the full state
    and without having to restore updates to stake holder lists.
    """

    CONSTR_ID = 0
    params_hash: bytes
    holder_state_hash: bytes
    chain_state_hash: bytes
    producer_state_hash: bytes
    # holders registered during the last block, to be skipped in the next block
    # just an int since new holders always jump to the start of the list
    skip_holders: int
    # reference to previous output
    spent_for: Union[Nothing, TxOutRef]


# NOTE: a full stake chain state without any registered pool is around 330 bytes
@dataclass
class StakeChainState(PlutusData):
    CONSTR_ID = 0
    params: StakeChainParams
    holder_state: StakeHolderRegistrations
    chain_state: CoreChainState
    producer_state: ProducerState
    # holders registered during the last block, to be skipped in the next block
    # just an int since new holders always jump to the start of the list
    skip_holders: int
    # reference to previous output
    spent_for: Union[Nothing, TxOutRef]


@dataclass
class StakePoolParams(PlutusData):
    CONSTR_ID = 0
    # Who controls the stake holder
    owner: Owner
    # The id of the stake holder in the stake chain stake holder list
    # can have any value, as long as it is unique (shorter is better)
    stakechain_id: bytes
    # The authenticating token of the stake chain
    chain_auth_nft: Token
    # The authenticating token of stake holders
    stakeholder_auth_nft: Token


@dataclass
class StakeHolderState(PlutusData):
    CONSTR_ID = 0
    params: StakePoolParams
    committed_hashes: List[bytes]
    aux: OutputDatum
