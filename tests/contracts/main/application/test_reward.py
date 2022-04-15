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


REWARDS_SLOT = 6
REWARDS_PAID_SLOT = 7
ERROR = 1e6


def test_push_reward(testerchain, token, threshold_staking, pre_application, application_economics):
    creator, distributor, staking_provider_1, staking_provider_2, *everyone_else = testerchain.client.accounts
    min_authorization = application_economics.min_authorization
    reward_portion = min_authorization
    reward_duration = application_economics.reward_duration
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

    # Push reward without staking providers
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
    assert pre_application.functions.earned(staking_provider_1).call() == 0

    events = rewards_log.get_all_entries()
    assert len(events) == 1
    event_args = events[-1]['args']
    assert event_args['reward'] == reward_portion

    # Wait some time and push reward again (without staking providers)
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
    assert pre_application.functions.earned(staking_provider_1).call() == 0

    events = rewards_log.get_all_entries()
    assert len(events) == 2
    event_args = events[-1]['args']
    assert event_args['reward'] == reward_portion

    # Wait, add one staking provider and push reward again
    testerchain.time_travel(seconds=reward_duration)
    tx = threshold_staking.functions.authorizationIncreased(staking_provider_1, 0, value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.bondOperator(staking_provider_1, staking_provider_1).transact({'from': staking_provider_1})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.confirmOperatorAddress().transact({'from': staking_provider_1})
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
    assert pre_application.functions.earned(staking_provider_1).call() == 0

    events = rewards_log.get_all_entries()
    assert len(events) == 3
    event_args = events[-1]['args']
    assert event_args['reward'] == reward_portion

    # Wait some time and check reward for staking provider
    testerchain.time_travel(seconds=reward_duration // 2)
    assert pre_application.functions.rewardPerTokenStored().call() == 0
    expected_reward_per_token = int(reward_portion * 1e18) // value // 2
    assert abs(pre_application.functions.rewardPerToken().call() - expected_reward_per_token) < ERROR
    expected_reward = reward_portion // 2
    assert abs(pre_application.functions.earned(staking_provider_1).call() - expected_reward) < ERROR

    testerchain.time_travel(seconds=reward_duration // 2)
    assert pre_application.functions.rewardPerTokenStored().call() == 0
    expected_reward_per_token = int(reward_portion * 1e18) // value
    reward_per_token = pre_application.functions.rewardPerToken().call()
    assert abs(reward_per_token - expected_reward_per_token) <= 100
    expected_reward = reward_portion
    reward = pre_application.functions.earned(staking_provider_1).call()
    assert abs(reward - expected_reward) <= ERROR

    # Add another staking provider without confirmation and push reward again
    tx = threshold_staking.functions.authorizationIncreased(staking_provider_2, 0, value).transact()
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
    assert pre_application.functions.earned(staking_provider_1).call() == reward
    assert pre_application.functions.earned(staking_provider_2).call() == 0

    events = rewards_log.get_all_entries()
    assert len(events) == 4
    event_args = events[-1]['args']
    assert event_args['reward'] == reward_portion

    testerchain.time_travel(seconds=reward_duration)
    assert abs(pre_application.functions.earned(staking_provider_1).call() - (reward + reward_portion)) < ERROR
    assert pre_application.functions.earned(staking_provider_2).call() == 0


def test_update_reward(testerchain, token, threshold_staking, pre_application, application_economics):
    creator, distributor, staking_provider_1, staking_provider_2, *everyone_else = testerchain.client.accounts
    min_authorization = application_economics.min_authorization
    reward_portion = min_authorization
    reward_duration = application_economics.reward_duration
    deauthorization_duration = application_economics.deauthorization_duration
    min_operator_seconds = application_economics.min_operator_seconds
    value = int(1.5 * min_authorization)

    reward_per_token = 0
    new_reward_per_token = 0
    staking_provider_1_reward = 0
    staking_provider_1_new_reward = 0
    staking_provider_2_reward = 0
    staking_provider_2_new_reward = 0

    def check_reward_no_confirmation():
        nonlocal reward_per_token, new_reward_per_token, staking_provider_1_reward, staking_provider_1_new_reward

        new_reward_per_token = pre_application.functions.rewardPerToken().call()
        assert new_reward_per_token > reward_per_token
        assert pre_application.functions.rewardPerTokenStored().call() == new_reward_per_token
        staking_provider_1_new_reward = pre_application.functions.earned(staking_provider_1).call()
        assert staking_provider_1_new_reward > staking_provider_1_reward
        assert pre_application.functions.stakingProviderInfo(staking_provider_1).call()[REWARDS_SLOT] == 0
        assert pre_application.functions.stakingProviderInfo(staking_provider_1).call()[REWARDS_PAID_SLOT] == 0
        assert pre_application.functions.earned(staking_provider_2).call() == 0
        assert pre_application.functions.stakingProviderInfo(staking_provider_2).call()[REWARDS_SLOT] == 0
        assert pre_application.functions.stakingProviderInfo(staking_provider_2).call()[REWARDS_PAID_SLOT] == new_reward_per_token
        reward_per_token = new_reward_per_token
        staking_provider_1_reward = staking_provider_1_new_reward

    def check_reward_with_confirmation():
        nonlocal reward_per_token, \
                 new_reward_per_token, \
                 staking_provider_1_reward, \
                 staking_provider_1_new_reward, \
                 staking_provider_2_reward, \
                 staking_provider_2_new_reward

        new_reward_per_token = pre_application.functions.rewardPerToken().call()
        assert new_reward_per_token > reward_per_token
        assert pre_application.functions.rewardPerTokenStored().call() == new_reward_per_token
        staking_provider_1_new_reward = pre_application.functions.earned(staking_provider_1).call()
        assert staking_provider_1_new_reward > staking_provider_1_reward
        assert pre_application.functions.stakingProviderInfo(staking_provider_1).call()[REWARDS_SLOT] == 0
        assert pre_application.functions.stakingProviderInfo(staking_provider_1).call()[REWARDS_PAID_SLOT] == 0
        staking_provider_2_new_reward = pre_application.functions.earned(staking_provider_2).call()
        assert staking_provider_2_new_reward > staking_provider_2_reward
        assert pre_application.functions.stakingProviderInfo(staking_provider_2).call()[REWARDS_SLOT] == staking_provider_2_new_reward
        assert pre_application.functions.stakingProviderInfo(staking_provider_2).call()[REWARDS_PAID_SLOT] == new_reward_per_token
        reward_per_token = new_reward_per_token
        staking_provider_1_reward = staking_provider_1_new_reward
        staking_provider_2_reward = staking_provider_2_new_reward

    # Prepare one staking provider and reward
    tx = threshold_staking.functions.authorizationIncreased(staking_provider_1, 0, value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.bondOperator(staking_provider_1, staking_provider_1).transact({'from': staking_provider_1})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.confirmOperatorAddress().transact({'from': staking_provider_1})
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
    assert pre_application.functions.earned(staking_provider_1).call() == 0

    testerchain.time_travel(seconds=reward_duration // 2)
    # Reward per token will be updated but nothing earned yet
    tx = threshold_staking.functions.authorizationIncreased(staking_provider_2, 0, 4 * value).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_no_confirmation()

    # Add reward, wait and bond operator
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    # Reward per token will be updated but nothing earned yet (need confirmation)
    tx = pre_application.functions.bondOperator(staking_provider_2, staking_provider_2).transact({'from': staking_provider_2})
    testerchain.wait_for_receipt(tx)
    check_reward_no_confirmation()

    # Involuntary decrease without confirmation
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = threshold_staking.functions.involuntaryAuthorizationDecrease(staking_provider_2, 4 * value, 3 * value).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_no_confirmation()

    # Request for decrease
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = threshold_staking.functions.authorizationDecreaseRequested(staking_provider_2, 3 * value, 2 * value).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.earned(staking_provider_2).call() == 0
    assert pre_application.functions.stakingProviderInfo(staking_provider_2).call()[REWARDS_SLOT] == 0
    assert pre_application.functions.stakingProviderInfo(staking_provider_2).call()[REWARDS_PAID_SLOT] == reward_per_token

    # Finish decrease without confirmation
    testerchain.time_travel(seconds=deauthorization_duration)
    tx = pre_application.functions.finishAuthorizationDecrease(staking_provider_2).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_no_confirmation()

    # Resync without confirmation
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = threshold_staking.functions.setAuthorized(staking_provider_2, value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.resynchronizeAuthorization(staking_provider_2).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_no_confirmation()

    # Wait and confirm operator
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    # Reward per token will be updated but nothing earned yet (just confirmed operator)
    tx = pre_application.functions.confirmOperatorAddress().transact({'from': staking_provider_2})
    testerchain.wait_for_receipt(tx)
    check_reward_no_confirmation()

    # Increase authorization with confirmation
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = threshold_staking.functions.authorizationIncreased(staking_provider_2, value, 4 * value).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_with_confirmation()

    # Involuntary decrease with confirmation
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = threshold_staking.functions.involuntaryAuthorizationDecrease(staking_provider_2, 4 * value, 3 * value).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_with_confirmation()

    # Request for decrease
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = threshold_staking.functions.authorizationDecreaseRequested(staking_provider_2, 3 * value, 2 * value).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider_2).call()[REWARDS_SLOT] == staking_provider_2_reward
    assert pre_application.functions.stakingProviderInfo(staking_provider_2).call()[REWARDS_PAID_SLOT] == reward_per_token

    # Finish decrease with confirmation
    testerchain.time_travel(seconds=deauthorization_duration)
    tx = pre_application.functions.finishAuthorizationDecrease(staking_provider_2).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_with_confirmation()

    # Resync with confirmation
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = threshold_staking.functions.setAuthorized(staking_provider_2, value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.resynchronizeAuthorization(staking_provider_2).transact()
    testerchain.wait_for_receipt(tx)
    check_reward_with_confirmation()

    # Bond operator with confirmation (confirmation will be dropped)
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=min_operator_seconds)
    # Reward per token will be updated but nothing earned yet (need confirmation)
    tx = pre_application.functions.bondOperator(staking_provider_2, everyone_else[0]).transact({'from': staking_provider_2})
    testerchain.wait_for_receipt(tx)
    check_reward_with_confirmation()

    # Push reward wait some time and check that no more reward
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration)
    assert pre_application.functions.earned(staking_provider_2).call() == staking_provider_2_reward
    assert pre_application.functions.stakingProviderInfo(staking_provider_2).call()[REWARDS_SLOT] == staking_provider_2_reward
    assert pre_application.functions.stakingProviderInfo(staking_provider_2).call()[REWARDS_PAID_SLOT] == reward_per_token


def test_withdraw(testerchain, token, threshold_staking, pre_application, application_economics):
    creator, distributor, staking_provider, owner, beneficiary, authorizer, staking_provider_2, \
        *everyone_else = testerchain.client.accounts
    min_authorization = application_economics.min_authorization
    reward_portion = min_authorization
    reward_duration = application_economics.reward_duration
    min_operator_seconds = application_economics.min_operator_seconds
    value = int(1.5 * min_authorization)

    withdrawals_log = pre_application.events.RewardPaid.createFilter(fromBlock='latest')

    # No rewards, no staking providers
    tx = threshold_staking.functions.setRoles(staking_provider, owner, beneficiary, authorizer).transact()
    testerchain.wait_for_receipt(tx)
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.withdraw(staking_provider).transact({'from': beneficiary})
        testerchain.wait_for_receipt(tx)

    # Prepare one staking provider and reward
    tx = threshold_staking.functions.authorizationIncreased(staking_provider, 0, value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.bondOperator(staking_provider, staking_provider).transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.confirmOperatorAddress().transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)

    # Nothing earned yet
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.withdraw(staking_provider).transact({'from': beneficiary})
        testerchain.wait_for_receipt(tx)

    tx = pre_application.functions.setRewardDistributor(distributor).transact({'from': creator})
    testerchain.wait_for_receipt(tx)
    tx = token.functions.transfer(distributor, 100 * reward_portion).transact({'from': creator})
    testerchain.wait_for_receipt(tx)
    tx = token.functions.approve(pre_application.address, 100 * reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.rewardPerTokenStored().call() == 0
    assert pre_application.functions.rewardPerToken().call() == 0
    assert pre_application.functions.earned(staking_provider).call() == 0

    testerchain.time_travel(seconds=reward_duration)
    # Only beneficiary can withdraw reward
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.withdraw(staking_provider).transact({'from': owner})
        testerchain.wait_for_receipt(tx)
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.withdraw(staking_provider).transact({'from': authorizer})
        testerchain.wait_for_receipt(tx)

    reward_per_token = pre_application.functions.rewardPerToken().call()
    assert reward_per_token > 0
    earned = pre_application.functions.earned(staking_provider).call()
    assert earned > 0

    tx = pre_application.functions.withdraw(staking_provider).transact({'from': beneficiary})
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.rewardPerTokenStored().call() == reward_per_token
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[REWARDS_SLOT] == 0
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[REWARDS_PAID_SLOT] == reward_per_token
    assert token.functions.balanceOf(beneficiary).call() == earned
    assert token.functions.balanceOf(pre_application.address).call() == reward_portion - earned

    events = withdrawals_log.get_all_entries()
    assert len(events) == 1
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['beneficiary'] == beneficiary
    assert event_args['reward'] == earned

    # Add one more staking provider, push reward again and drop operator
    testerchain.time_travel(seconds=min_operator_seconds)
    tx = threshold_staking.functions.setRoles(staking_provider_2).transact()
    testerchain.wait_for_receipt(tx)
    tx = threshold_staking.functions.authorizationIncreased(staking_provider_2, 0, value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.bondOperator(staking_provider_2, staking_provider_2).transact({'from': staking_provider_2})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.confirmOperatorAddress().transact({'from': staking_provider_2})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.pushReward(reward_portion).transact({'from': distributor})
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=reward_duration // 2)
    tx = pre_application.functions.bondOperator(staking_provider, NULL_ADDRESS).transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)

    new_earned = pre_application.functions.earned(staking_provider).call()
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[REWARDS_SLOT] == new_earned

    # Withdraw
    testerchain.time_travel(seconds=reward_duration // 2)
    assert pre_application.functions.earned(staking_provider).call() == new_earned
    tx = pre_application.functions.withdraw(staking_provider).transact({'from': beneficiary})
    testerchain.wait_for_receipt(tx)
    new_reward_per_token = pre_application.functions.rewardPerToken().call()
    assert pre_application.functions.rewardPerTokenStored().call() == new_reward_per_token
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[REWARDS_SLOT] == 0
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[REWARDS_PAID_SLOT] == new_reward_per_token
    assert token.functions.balanceOf(beneficiary).call() == earned + new_earned
    assert token.functions.balanceOf(pre_application.address).call() == 2 * reward_portion - earned - new_earned

    events = withdrawals_log.get_all_entries()
    assert len(events) == 2
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['beneficiary'] == beneficiary
    assert event_args['reward'] == new_earned
