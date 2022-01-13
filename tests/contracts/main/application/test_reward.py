"""
This file is part of nucypher.

nucypher is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

nucypher is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with nucypher.  If not, see <https://www.gnu.org/licenses/>.
"""

import pytest
from eth_tester.exceptions import TransactionFailed

from nucypher.blockchain.eth.constants import NULL_ADDRESS
from eth_utils import to_checksum_address


REWARDS_SLOT = 4
REWARDS_PAID_SLOT = 5
ERROR = 1e5


def test_push_reward(testerchain, token, threshold_staking, pre_application, token_economics):
    creator, distributor, operator1, operator2, *everyone_else = testerchain.client.accounts
    min_authorization = token_economics.minimum_allowed_locked
    reward_portion = min_authorization
    reward_duration = 60 * 60
    value = int(1.5 * min_authorization)

    rewards_log = pre_application.events.RewardAdded.createFilter(fromBlock='latest')
    distributors_log = pre_application.events.RewardDistributorSet.createFilter(fromBlock='latest')

    # Can't push reward without distributor
    tx = token.functions.approve(pre_application.address, reward_portion).transact({'from': creator})
    testerchain.wait_for_receipt(tx)
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.pushReward(reward_portion).transact({'from': creator})
        testerchain.wait_for_receipt(tx)

    # Only owner can set distributor
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.setRewardDistributor(distributor).transact({'from': distributor})
        testerchain.wait_for_receipt(tx)

    tx = pre_application.functions.setRewardDistributor(distributor).transact({'from': creator})
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.rewardDistributor().call() == distributor

    events = distributors_log.get_all_entries()
    assert len(events) == 1
    event_args = events[0]['args']
    assert event_args['distributor'] == distributor

    # Can't distribute zero rewards
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.pushReward(0).transact({'from': distributor})
        testerchain.wait_for_receipt(tx)

    # Push reward without operators
    tx = token.functions.transfer(distributor, 10 * reward_portion).transact({'from': creator})
    testerchain.wait_for_receipt(tx)
    tx = token.functions.approve(pre_application.address, 10 * reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    timestamp = testerchain.w3.eth.getBlock('latest').timestamp
    assert pre_application.functions.rewardRate().call() == reward_portion // reward_duration
    assert pre_application.functions.lastUpdateTime().call() == timestamp
    assert pre_application.functions.periodFinish().call() == timestamp + reward_duration
    assert token.functions.balanceOf(pre_application.address).call() == reward_portion
    assert token.functions.balanceOf(distributor).call() == 9 * reward_portion
    assert pre_application.functions.lastTimeRewardApplicable().call() == timestamp
    assert pre_application.functions.rewardPerTokenStored().call() == 0
    assert pre_application.functions.rewardPerToken().call() == 0
    assert pre_application.functions.earned(operator1).call() == 0

    events = rewards_log.get_all_entries()
    assert len(events) == 1
    event_args = events[-1]['args']
    assert event_args['reward'] == reward_portion

    # Wait some time and push reward again (without operators)
    testerchain.time_travel(seconds=reward_duration // 2 - 1)
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    timestamp = testerchain.w3.eth.getBlock('latest').timestamp
    expected_reward_rate = (reward_portion + reward_portion // 2) // reward_duration
    # Could be some error during calculations
    assert abs(pre_application.functions.rewardRate().call() - expected_reward_rate) <= ERROR
    assert pre_application.functions.lastUpdateTime().call() == timestamp
    assert pre_application.functions.periodFinish().call() == timestamp + reward_duration
    assert token.functions.balanceOf(pre_application.address).call() == 2 * reward_portion
    assert token.functions.balanceOf(distributor).call() == 8 * reward_portion
    assert pre_application.functions.lastTimeRewardApplicable().call() == timestamp
    assert pre_application.functions.rewardPerTokenStored().call() == 0
    assert pre_application.functions.rewardPerToken().call() == 0
    assert pre_application.functions.earned(operator1).call() == 0

    events = rewards_log.get_all_entries()
    assert len(events) == 2
    event_args = events[-1]['args']
    assert event_args['reward'] == reward_portion

    # Wait, add one operator and push reward again
    testerchain.time_travel(seconds=reward_duration)
    tx = threshold_staking.functions.authorizationIncreased(operator1, 0, value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.bondWorker(operator1).transact({'from': operator1})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.confirmWorkerAddress().transact({'from': operator1})
    testerchain.wait_for_receipt(tx)

    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    timestamp = testerchain.w3.eth.getBlock('latest').timestamp
    assert pre_application.functions.rewardRate().call() == reward_portion // reward_duration
    assert pre_application.functions.lastUpdateTime().call() == timestamp
    assert pre_application.functions.periodFinish().call() == timestamp + reward_duration
    assert token.functions.balanceOf(pre_application.address).call() == 3 * reward_portion
    assert token.functions.balanceOf(distributor).call() == 7 * reward_portion
    assert pre_application.functions.lastTimeRewardApplicable().call() == timestamp
    assert pre_application.functions.rewardPerTokenStored().call() == 0
    assert pre_application.functions.rewardPerToken().call() == 0
    assert pre_application.functions.earned(operator1).call() == 0

    events = rewards_log.get_all_entries()
    assert len(events) == 3
    event_args = events[-1]['args']
    assert event_args['reward'] == reward_portion

    # Wait some time and check reward for operator
    testerchain.time_travel(seconds=reward_duration // 2)
    assert pre_application.functions.rewardPerTokenStored().call() == 0
    expected_reward_per_token = int(reward_portion * 1e18) // value // 2
    assert abs(pre_application.functions.rewardPerToken().call() - expected_reward_per_token) < ERROR
    expected_reward = reward_portion // 2
    assert abs(pre_application.functions.earned(operator1).call() - expected_reward) < ERROR

    testerchain.time_travel(seconds=reward_duration // 2)
    assert pre_application.functions.rewardPerTokenStored().call() == 0
    expected_reward_per_token = int(reward_portion * 1e18) // value
    reward_per_token = pre_application.functions.rewardPerToken().call()
    assert abs(reward_per_token - expected_reward_per_token) <= 100
    expected_reward = reward_portion
    reward = pre_application.functions.earned(operator1).call()
    assert abs(reward - expected_reward) <= 1e5

    # Add another operator without confirmation and push reward again
    tx = threshold_staking.functions.authorizationIncreased(operator2, 0, value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    timestamp = testerchain.w3.eth.getBlock('latest').timestamp
    assert pre_application.functions.rewardRate().call() == reward_portion // reward_duration
    assert pre_application.functions.lastUpdateTime().call() == timestamp
    assert pre_application.functions.periodFinish().call() == timestamp + reward_duration
    assert token.functions.balanceOf(pre_application.address).call() == 4 * reward_portion
    assert token.functions.balanceOf(distributor).call() == 6 * reward_portion
    assert pre_application.functions.lastTimeRewardApplicable().call() == timestamp
    assert pre_application.functions.rewardPerTokenStored().call() == reward_per_token
    assert pre_application.functions.rewardPerToken().call() == reward_per_token
    assert pre_application.functions.earned(operator1).call() == reward
    assert pre_application.functions.earned(operator2).call() == 0

    events = rewards_log.get_all_entries()
    assert len(events) == 4
    event_args = events[-1]['args']
    assert event_args['reward'] == reward_portion

    testerchain.time_travel(seconds=reward_duration)
    assert abs(pre_application.functions.earned(operator1).call() - (reward + reward_portion)) < ERROR
    assert pre_application.functions.earned(operator2).call() == 0
