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
    tx = pre_application.functions.bondWorker(operator1, operator1).transact({'from': operator1})
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


def test_update_reward(testerchain, token, threshold_staking, pre_application, token_economics):
    creator, distributor, operator1, operator2, *everyone_else = testerchain.client.accounts
    min_authorization = token_economics.minimum_allowed_locked
    reward_portion = min_authorization
    reward_duration = 60 * 60
    deauthorization_duration = 60 * 60
    min_worker_seconds = 24 * 60 * 60
    value = int(1.5 * min_authorization)

    reward_per_token = 0
    new_reward_per_token = 0
    operator1_reward = 0
    operator1_new_reward = 0
    operator2_reward = 0
    operator2_new_reward = 0

    def check_reward_no_confirmation():
        nonlocal reward_per_token, new_reward_per_token, operator1_reward, operator1_new_reward

        new_reward_per_token = pre_application.functions.rewardPerToken().call()
        assert new_reward_per_token > reward_per_token
        assert pre_application.functions.rewardPerTokenStored().call() == new_reward_per_token
        operator1_new_reward = pre_application.functions.earned(operator1).call()
        assert operator1_new_reward > operator1_reward
        assert pre_application.functions.operatorInfo(operator1).call()[REWARDS_SLOT] == 0
        assert pre_application.functions.operatorInfo(operator1).call()[REWARDS_PAID_SLOT] == 0
        assert pre_application.functions.earned(operator2).call() == 0
        assert pre_application.functions.operatorInfo(operator2).call()[REWARDS_SLOT] == 0
        assert pre_application.functions.operatorInfo(operator2).call()[REWARDS_PAID_SLOT] == new_reward_per_token
        reward_per_token = new_reward_per_token
        operator1_reward = operator1_new_reward

    def check_reward_with_confirmation():
        nonlocal reward_per_token, \
                 new_reward_per_token, \
                 operator1_reward, \
                 operator1_new_reward, \
                 operator2_reward, \
                 operator2_new_reward

        new_reward_per_token = pre_application.functions.rewardPerToken().call()
        assert new_reward_per_token > reward_per_token
        assert pre_application.functions.rewardPerTokenStored().call() == new_reward_per_token
        operator1_new_reward = pre_application.functions.earned(operator1).call()
        assert operator1_new_reward > operator1_reward
        assert pre_application.functions.operatorInfo(operator1).call()[REWARDS_SLOT] == 0
        assert pre_application.functions.operatorInfo(operator1).call()[REWARDS_PAID_SLOT] == 0
        operator2_new_reward = pre_application.functions.earned(operator2).call()
        assert operator2_new_reward > operator2_reward
        assert pre_application.functions.operatorInfo(operator2).call()[REWARDS_SLOT] == operator2_new_reward
        assert pre_application.functions.operatorInfo(operator2).call()[REWARDS_PAID_SLOT] == new_reward_per_token
        reward_per_token = new_reward_per_token
        operator1_reward = operator1_new_reward
        operator2_reward = operator2_new_reward

    # Prepare one operator and reward
    tx = threshold_staking.functions.authorizationIncreased(operator1, 0, value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.bondWorker(operator1, operator1).transact({'from': operator1})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.confirmWorkerAddress().transact({'from': operator1})
    testerchain.wait_for_receipt(tx)

    tx = pre_application.functions.setRewardDistributor(distributor).transact({'from': creator})
    testerchain.wait_for_receipt(tx)
    tx = token.functions.transfer(distributor, 100 * reward_portion).transact({'from': creator})
    testerchain.wait_for_receipt(tx)
    tx = token.functions.approve(pre_application.address, 100 * reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.pushReward(2 * reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.rewardPerTokenStored().call() == 0
    assert pre_application.functions.rewardPerToken().call() == 0
    assert pre_application.functions.earned(operator1).call() == 0

    testerchain.time_travel(seconds=reward_duration // 2)
    # Reward per token will be updated but nothing earned yet
    tx = threshold_staking.functions.authorizationIncreased(operator2, 0, 4 * value).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_no_confirmation()

    # Add reward, wait and bond worker
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    # Reward per token will be updated but nothing earned yet (need confirmation)
    tx = pre_application.functions.bondWorker(operator2, operator2).transact({'from': operator2})
    testerchain.wait_for_receipt(tx)
    check_reward_no_confirmation()

    # Involuntary decrease without confirmation
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = threshold_staking.functions.involuntaryAuthorizationDecrease(operator2, 4 * value, 3 * value).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_no_confirmation()

    # Request for decrease
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = threshold_staking.functions.authorizationDecreaseRequested(operator2, 3 * value, 2 * value).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.earned(operator2).call() == 0
    assert pre_application.functions.operatorInfo(operator2).call()[REWARDS_SLOT] == 0
    assert pre_application.functions.operatorInfo(operator2).call()[REWARDS_PAID_SLOT] == reward_per_token

    # Finish decrease without confirmation
    testerchain.time_travel(seconds=deauthorization_duration)
    tx = pre_application.functions.finishAuthorizationDecrease(operator2).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_no_confirmation()

    # Resync without confirmation
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = threshold_staking.functions.setAuthorized(operator2, value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.resynchronizeAuthorization(operator2).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_no_confirmation()

    # Wait and confirm worker
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    # Reward per token will be updated but nothing earned yet (just confirmed worker)
    tx = pre_application.functions.confirmWorkerAddress().transact({'from': operator2})
    testerchain.wait_for_receipt(tx)
    check_reward_no_confirmation()

    # Increase authorization with confirmation
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = threshold_staking.functions.authorizationIncreased(operator2, value, 4 * value).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_with_confirmation()

    # Involuntary decrease with confirmation
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = threshold_staking.functions.involuntaryAuthorizationDecrease(operator2, 4 * value, 3 * value).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_with_confirmation()

    # Request for decrease
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = threshold_staking.functions.authorizationDecreaseRequested(operator2, 3 * value, 2 * value).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.operatorInfo(operator2).call()[REWARDS_SLOT] == operator2_reward
    assert pre_application.functions.operatorInfo(operator2).call()[REWARDS_PAID_SLOT] == reward_per_token

    # Finish decrease with confirmation
    testerchain.time_travel(seconds=deauthorization_duration)
    tx = pre_application.functions.finishAuthorizationDecrease(operator2).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_with_confirmation()

    # Resync with confirmation
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = threshold_staking.functions.setAuthorized(operator2, value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.resynchronizeAuthorization(operator2).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_with_confirmation()

    # Bond worker with confirmation (confirmation will be dropped)
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=min_worker_seconds)
    # Reward per token will be updated but nothing earned yet (need confirmation)
    tx = pre_application.functions.bondWorker(operator2, everyone_else[0]).transact({'from': operator2})
    testerchain.wait_for_receipt(tx)
    check_reward_with_confirmation()

    # Push reward wait some time and check that no more reward
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration)
    assert pre_application.functions.earned(operator2).call() == operator2_reward
    assert pre_application.functions.operatorInfo(operator2).call()[REWARDS_SLOT] == operator2_reward
    assert pre_application.functions.operatorInfo(operator2).call()[REWARDS_PAID_SLOT] == reward_per_token
