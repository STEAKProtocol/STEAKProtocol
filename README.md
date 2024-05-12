<div align="center">
  <a href="https://github.com/STEAKProtocol/STEAKProtocol">
    <img src="https://steakprotocol.com/logo.png" width="200" />
  </a>
  <h1> STEAK Protocol </h1>
</div>  

> Cardano style Proof Of Stake as a Randomness Oracle Smart Contract

The STEAK protocol is a decentralized protocol similar to [ForTuna](https://github.com/cardano-miners/fortuna) that 
distributes rewards to users based on their stake in the protocol.
The protocol is implemented as a smart contract on the Cardano blockchain.
It consecutively attaches a new block to the blockchain every 60 seconds (slots).
These blocks can be used as a source of randomness for other protocols as the exact
block hash is practically unpredictable for a given slot.

## Architecture

The STEAK protocol consists of the following components:
- **Block Chain**: A chain of consecutive blocks that refer to the previous block by its hash.
- **Stake Holder**: A position of tokens that participates in the protocol.
- **Stake Pool**: A withdrawal contract that ensures fair pooling of funds in a stake holder across different users.

Every 60 seconds, a slot leader is elected by the protocol to attach a new block to the blockchain.
The slot leader is chosen pseudorandomly based on the block hash and weighs participations based on the stake of the contributing pool.

More details can be found in the [whitepaper](https://steakprotocol.com/whitepaper.pdf).

The chain can be observed on preview testnet on any Chain Explorer like CexPlorer at this address: [addr_test1wqtr9jvc6tnavc3s86ws76sfpdau3g3gnezpnz5xhhusnrcd3lmvq](https://preview.cexplorer.io/address/addr_test1wqtr9jvc6tnavc3s86ws76sfpdau3g3gnezpnz5xhhusnrcd3lmvq/tx#data).

The $STK token on preview testnet has this token name and policy id: [`126a82c32b90b321eec79a79eaacd07abcc902d18cfcf62652708e6d.0014df107374616b65636f696e`](https://preview.cexplorer.io/asset/asset17xpvsxzxvdw4rraeyj4jk3p0gcm9vdetdrh0fa)

The $STK token can be obtained by trading on [preview SundaeSwap v2](https://v2.preview.sundaeswap.finance/).
You can obtain tADA at the [Cardano testnet faucet](https://docs.cardano.org/cardano-testnets/tools/faucet/) - make sure to select "Preview" testnet!

## Mining Blocks

The protocol uses a Proof of Stake (PoS) consensus mechanism to elect slot leaders.
The PoS mechanism is implemented as a smart contract that selects the slot leader based on the stake of the contributing pool.
The stake of a pool is determined by the number of tokens it holds.
The protocol uses a random seed generated from the previous block hash to select the slot leader.
The slot leader is responsible for attaching a new block to the blockchain every 60 seconds.

To become a participant in the protocol, a user must:
- Register a stake holder or stake pool with the protocol.
- Deposit $STK tokens into the stake holder position or stake pool.

To mine a block, the slot leader must:
- Generate a random seed from the previous block hash.
- Prove that the slot leader has the right to mine the block by providing a proof of stake.
- Attach the new block to the blockchain.
- Distribute rewards to the stake pool based on the stake of the pool.

Code for each of these activities is provided in the `steak_protocol/offchain` directory.
An example is shown below.

```bash
# Obtain a blockfrost key for the correct network from https://blockfrost.io/
export BLOCKFROST_PROJECT_ID=<your-blockfrost-key>
# Alternatively, set up ogmios to point to localhost:1337

# Install all dependencies
poetry install
# Activate the poetry shell
poetry shell
# Create a key pair
python3 steak_protocol/create_key_pair.py alice
# Deposit $STK tokens and at least 10 Ada at the created address
# Using a wallet or something similar

# Option A)
# Then, register as a stake holder
python3 -m steak_protocol.offchain.stakeholder.init alice --stake_amount 1000 --stakeholder_id alice
# Finally, try mining a block
python3 -m steak_protocol.offchain.stakechain.mine alice --pool_id alice

# Option B)
# For stake pools, the process is a bit more involved
# First, register a stake pool
python3 -m steak_protocol.offchain.stakepool.init alice --stakepool_id apool
# The, place a request to join the pool
python3 -m steak_protocol.offchain.stakepool.place_request alice --stakepool_id apool --stakecoin_amount 10_000_000
# The request can be batched by anyone, but you may want to batch it yourself
python3 -m steak_protocol.offchain.stakepool.fill_request alice --no_stake_key
# Finally, try mining a block
python3 -m steak_protocol.offchain.stakechain.mine alice --stakepool_id apool


# To batch requests from a specific user placed through the frontend, put their staking key
python3 -m steak_protocol.offchain.stakepool.fill_request alice --stake_key stake_...
```

Note that stake pools can allow further users to join the pool by placing a request to join the pool.
Singleton stake holder can not be pooled, but can still mine blocks.
All corresponding scripts and documentation can be found in the `steak_protocol/offchain/stakepool` directory.
Any script provides a `--help` flag to show the available options.


## Building the contracts

To reproduce the contract addresses, you can build the contracts using the following steps:

1. Install [poetry](https://python-poetry.org/docs/#installation) and [aiken v1.0.26-alpha+075668b
](https://aiken-lang.org/installation-instructions).
2. Run `make` in the root of the directory

