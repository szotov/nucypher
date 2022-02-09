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
from nucypher.blockchain.eth.token import NU


AUTHORIZATION_SLOT = 3
DEAUTHORIZING_SLOT = 6
END_DEAUTHORIZATION_SLOT = 7


def test_authorization_increase(testerchain, threshold_staking, pre_application, application_economics):
    """
    Tests for authorization method: authorizationIncreased
    """

    creator, staking_provider = testerchain.client.accounts[0:2]
    increase_log = pre_application.events.AuthorizationIncreased.createFilter(fromBlock='latest')

    minimum_authorization = application_economics.min_authorization
    value = minimum_authorization

    # Can't call `authorizationIncreased` directly
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.authorizationIncreased(staking_provider, 0, value).transact()
        testerchain.wait_for_receipt(tx)

    # Staking provider and toAmount must be specified
    with pytest.raises((TransactionFailed, ValueError)):
        tx = threshold_staking.functions.authorizationIncreased( NULL_ADDRESS, 0, value).transact()
        testerchain.wait_for_receipt(tx)
    with pytest.raises((TransactionFailed, ValueError)):
        tx = threshold_staking.functions.authorizationIncreased(staking_provider, 0, 0).transact()
        testerchain.wait_for_receipt(tx)

    # Authorization must be greater than minimum
    with pytest.raises((TransactionFailed, ValueError)):
        tx = threshold_staking.functions.authorizationIncreased(staking_provider, 0, value - 1).transact()
        testerchain.wait_for_receipt(tx)

    # First authorization
    tx = threshold_staking.functions.authorizationIncreased(staking_provider, 0, value).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == value
    assert pre_application.functions.authorizedOverall().call() == 0
    assert pre_application.functions.authorizedStake(staking_provider).call() == value
    assert pre_application.functions.isAuthorized(staking_provider).call()

    # Check that all events are emitted
    events = increase_log.get_all_entries()
    assert len(events) == 1
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == 0
    assert event_args['toAmount'] == value

    # Decrease and try to increase again
    tx = threshold_staking.functions.involuntaryAuthorizationDecrease(staking_provider, value, value // 2).transact()
    testerchain.wait_for_receipt(tx)

    # Resulting authorization must be greater than minimum
    with pytest.raises((TransactionFailed, ValueError)):
        tx = threshold_staking.functions.authorizationIncreased(staking_provider, value // 2, value - 1).transact()
        testerchain.wait_for_receipt(tx)

    tx = threshold_staking.functions.authorizationIncreased(staking_provider, value // 2, value).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == value
    assert pre_application.functions.authorizedOverall().call() == 0
    assert pre_application.functions.authorizedStake(staking_provider).call() == value
    assert pre_application.functions.isAuthorized(staking_provider).call()

    events = increase_log.get_all_entries()
    assert len(events) == 2
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value // 2
    assert event_args['toAmount'] == value

    # Confirm operator address and try to increase authorization again
    tx = pre_application.functions.bondOperator(staking_provider, staking_provider).transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.confirmOperatorAddress().transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)

    authorization = 2 * value + 1
    tx = threshold_staking.functions.authorizationIncreased(staking_provider, value, authorization).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == authorization
    assert pre_application.functions.authorizedOverall().call() == authorization
    assert pre_application.functions.authorizedStake(staking_provider).call() == authorization
    assert pre_application.functions.isAuthorized(staking_provider).call()

    events = increase_log.get_all_entries()
    assert len(events) == 3
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value
    assert event_args['toAmount'] == authorization

    # Emulate slash and desync by sending smaller fromAmount
    tx = threshold_staking.functions.authorizationIncreased(staking_provider, value // 2, value).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == value
    assert pre_application.functions.authorizedOverall().call() == value
    assert pre_application.functions.authorizedStake(staking_provider).call() == value
    assert pre_application.functions.isAuthorized(staking_provider).call()

    events = increase_log.get_all_entries()
    assert len(events) == 4
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value // 2
    assert event_args['toAmount'] == value


def test_involuntary_authorization_decrease(testerchain, threshold_staking, pre_application, application_economics):
    """
    Tests for authorization method: involuntaryAuthorizationDecrease
    """

    creator, staking_provider = testerchain.client.accounts[0:2]
    involuntary_decrease_log = pre_application.events.AuthorizationInvoluntaryDecreased.createFilter(fromBlock='latest')

    minimum_authorization = application_economics.min_authorization
    value = minimum_authorization

    # Prepare staking providers
    tx = threshold_staking.functions.authorizationIncreased(staking_provider, 0, value).transact()
    testerchain.wait_for_receipt(tx)

    # Can't call `involuntaryAuthorizationDecrease` directly
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.involuntaryAuthorizationDecrease(
            staking_provider, value, 0).transact({'from': creator})
        testerchain.wait_for_receipt(tx)

    authorization = value // 2
    tx = threshold_staking.functions.involuntaryAuthorizationDecrease(staking_provider, value, value // 2).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == authorization
    assert pre_application.functions.authorizedOverall().call() == 0
    assert pre_application.functions.authorizedStake(staking_provider).call() == authorization
    assert pre_application.functions.isAuthorized(staking_provider).call()
    assert not pre_application.functions.isOperatorConfirmed(staking_provider).call()

    events = involuntary_decrease_log.get_all_entries()
    assert len(events) == 1
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value
    assert event_args['toAmount'] == authorization

    # Prepare request to decrease before involuntary decrease
    tx = threshold_staking.functions.authorizationDecreaseRequested(staking_provider,  value // 2, 0).transact()
    testerchain.wait_for_receipt(tx)
    authorization = value // 4
    tx = threshold_staking.functions.involuntaryAuthorizationDecrease(staking_provider, value // 2, authorization).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == authorization
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[DEAUTHORIZING_SLOT] == authorization
    assert pre_application.functions.authorizedOverall().call() == 0
    assert pre_application.functions.authorizedStake(staking_provider).call() == authorization
    assert pre_application.functions.isAuthorized(staking_provider).call()
    assert not pre_application.functions.isOperatorConfirmed(staking_provider).call()

    events = involuntary_decrease_log.get_all_entries()
    assert len(events) == 2
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value // 2
    assert event_args['toAmount'] == authorization

    # Confirm operator address and decrease again
    tx = pre_application.functions.bondOperator(staking_provider, staking_provider).transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.confirmOperatorAddress().transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)

    authorization = value // 8
    tx = threshold_staking.functions.involuntaryAuthorizationDecrease(staking_provider, value // 4, authorization).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == authorization
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[DEAUTHORIZING_SLOT] == authorization
    assert pre_application.functions.authorizedOverall().call() == authorization
    assert pre_application.functions.authorizedStake(staking_provider).call() == authorization
    assert pre_application.functions.isAuthorized(staking_provider).call()
    assert pre_application.functions.isOperatorConfirmed(staking_provider).call()
    assert pre_application.functions.getOperatorFromStakingProvider(staking_provider).call() == staking_provider
    assert pre_application.functions.stakingProviderFromOperator(staking_provider).call() == staking_provider

    events = involuntary_decrease_log.get_all_entries()
    assert len(events) == 3
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value // 4
    assert event_args['toAmount'] == authorization

    # Decrease everything
    tx = threshold_staking.functions.involuntaryAuthorizationDecrease(staking_provider, authorization, 0).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == 0
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[DEAUTHORIZING_SLOT] == 0
    assert pre_application.functions.authorizedOverall().call() == 0
    assert pre_application.functions.authorizedStake(staking_provider).call() == 0
    assert not pre_application.functions.isAuthorized(staking_provider).call()
    assert not pre_application.functions.isOperatorConfirmed(staking_provider).call()
    assert pre_application.functions.getOperatorFromStakingProvider(staking_provider).call() == NULL_ADDRESS
    assert pre_application.functions.stakingProviderFromOperator(staking_provider).call() == NULL_ADDRESS

    events = involuntary_decrease_log.get_all_entries()
    assert len(events) == 4
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == authorization
    assert event_args['toAmount'] == 0

    # Emulate slash and desync by sending smaller fromAmount
    tx = threshold_staking.functions.authorizationIncreased(staking_provider, 0, 2 * value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.bondOperator(staking_provider, staking_provider).transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.confirmOperatorAddress().transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)
    authorization = value // 2
    tx = threshold_staking.functions.involuntaryAuthorizationDecrease(staking_provider, value, value // 2).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == authorization
    assert pre_application.functions.authorizedOverall().call() == authorization
    assert pre_application.functions.authorizedStake(staking_provider).call() == authorization

    events = involuntary_decrease_log.get_all_entries()
    assert len(events) == 5
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value
    assert event_args['toAmount'] == authorization


def test_authorization_decrease_request(testerchain, threshold_staking, pre_application, application_economics):
    """
    Tests for authorization method: authorizationDecreaseRequested
    """

    creator, staking_provider = testerchain.client.accounts[0:2]
    decrease_request_log = pre_application.events.AuthorizationDecreaseRequested.createFilter(fromBlock='latest')

    deauthorization_duration = application_economics.deauthorization_duration
    minimum_authorization = application_economics.min_authorization
    value = 2 * minimum_authorization + 1

    # Prepare staking providers
    tx = threshold_staking.functions.authorizationIncreased(staking_provider, 0, value).transact()
    testerchain.wait_for_receipt(tx)

    # Can't call `involuntaryAuthorizationDecrease` directly
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.authorizationDecreaseRequested(
            staking_provider, value, 0).transact({'from': creator})
        testerchain.wait_for_receipt(tx)

    # Can't increase amount using request
    with pytest.raises((TransactionFailed, ValueError)):
        tx = threshold_staking.functions.authorizationDecreaseRequested(staking_provider, value, value + 1).transact()
        testerchain.wait_for_receipt(tx)

    # Resulting amount must be greater than minimum or 0
    with pytest.raises((TransactionFailed, ValueError)):
        tx = threshold_staking.functions.authorizationDecreaseRequested(staking_provider, value, 1).transact()
        testerchain.wait_for_receipt(tx)

    # Request of partial decrease
    tx = threshold_staking.functions.authorizationDecreaseRequested(staking_provider, value, minimum_authorization).transact()
    testerchain.wait_for_receipt(tx)
    timestamp = testerchain.w3.eth.getBlock('latest').timestamp
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == value
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[DEAUTHORIZING_SLOT] == minimum_authorization + 1
    end_deauthorization = timestamp + deauthorization_duration
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[END_DEAUTHORIZATION_SLOT] == end_deauthorization
    assert pre_application.functions.authorizedOverall().call() == 0
    assert pre_application.functions.authorizedStake(staking_provider).call() == value
    assert pre_application.functions.isAuthorized(staking_provider).call()

    events = decrease_request_log.get_all_entries()
    assert len(events) == 1
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value
    assert event_args['toAmount'] == minimum_authorization

    # Confirm operator address and request full decrease
    tx = pre_application.functions.bondOperator(staking_provider, staking_provider).transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.confirmOperatorAddress().transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)

    tx = threshold_staking.functions.authorizationDecreaseRequested(staking_provider, value, 0).transact()
    testerchain.wait_for_receipt(tx)
    timestamp = testerchain.w3.eth.getBlock('latest').timestamp
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == value
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[DEAUTHORIZING_SLOT] == value
    end_deauthorization = timestamp + deauthorization_duration
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[END_DEAUTHORIZATION_SLOT] == end_deauthorization
    assert pre_application.functions.authorizedOverall().call() == value
    assert pre_application.functions.authorizedStake(staking_provider).call() == value
    assert pre_application.functions.isAuthorized(staking_provider).call()

    events = decrease_request_log.get_all_entries()
    assert len(events) == 2
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value
    assert event_args['toAmount'] == 0

    # Emulate slash and desync by sending smaller fromAmount
    tx = threshold_staking.functions.authorizationDecreaseRequested(staking_provider, value // 2, 0).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == value // 2
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[DEAUTHORIZING_SLOT] == value // 2
    assert pre_application.functions.authorizedOverall().call() == value // 2
    assert pre_application.functions.authorizedStake(staking_provider).call() == value // 2

    events = decrease_request_log.get_all_entries()
    assert len(events) == 3
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value // 2
    assert event_args['toAmount'] == 0


def test_finish_authorization_decrease(testerchain, threshold_staking, pre_application, application_economics):
    """
    Tests for authorization method: finishAuthorizationDecrease
    """

    creator, staking_provider = testerchain.client.accounts[0:2]
    decrease_log = pre_application.events.AuthorizationDecreaseApproved.createFilter(fromBlock='latest')

    deauthorization_duration = application_economics.deauthorization_duration
    minimum_authorization = application_economics.min_authorization
    value = 3 * minimum_authorization

    # Prepare staking providers
    tx = threshold_staking.functions.authorizationIncreased(staking_provider, 0, value).transact()
    testerchain.wait_for_receipt(tx)

    # Can't approve decrease without request
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.finishAuthorizationDecrease(staking_provider).transact()
        testerchain.wait_for_receipt(tx)

    new_value = 2 * minimum_authorization
    tx = threshold_staking.functions.authorizationDecreaseRequested(staking_provider, value, new_value).transact()
    testerchain.wait_for_receipt(tx)

    # Can't approve decrease before end timestamp
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.finishAuthorizationDecrease(staking_provider).transact()
        testerchain.wait_for_receipt(tx)

    # Wait some time
    testerchain.time_travel(seconds=deauthorization_duration)
    tx = pre_application.functions.finishAuthorizationDecrease(staking_provider).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == new_value
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[DEAUTHORIZING_SLOT] == 0
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[END_DEAUTHORIZATION_SLOT] == 0
    assert pre_application.functions.authorizedOverall().call() == 0
    assert pre_application.functions.authorizedStake(staking_provider).call() == new_value
    assert pre_application.functions.isAuthorized(staking_provider).call()
    assert threshold_staking.functions.authorizedStake(staking_provider, pre_application.address).call() == new_value

    events = decrease_log.get_all_entries()
    assert len(events) == 1
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value
    assert event_args['toAmount'] == new_value

    # Confirm operator, request again then desync values and finish decrease
    value = new_value
    tx = pre_application.functions.bondOperator(staking_provider, staking_provider).transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.confirmOperatorAddress().transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)
    tx = threshold_staking.functions.authorizationDecreaseRequested(staking_provider, value, minimum_authorization).transact()
    testerchain.wait_for_receipt(tx)

    new_value = minimum_authorization // 2
    tx = threshold_staking.functions.setDecreaseRequest(staking_provider, new_value).transact()
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=deauthorization_duration)
    tx = pre_application.functions.finishAuthorizationDecrease(staking_provider).transact()
    testerchain.wait_for_receipt(tx)

    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == new_value
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[DEAUTHORIZING_SLOT] == 0
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[END_DEAUTHORIZATION_SLOT] == 0
    assert pre_application.functions.getOperatorFromStakingProvider(staking_provider).call() == staking_provider
    assert pre_application.functions.stakingProviderFromOperator(staking_provider).call() == staking_provider
    assert pre_application.functions.authorizedOverall().call() == new_value
    assert pre_application.functions.authorizedStake(staking_provider).call() == new_value
    assert pre_application.functions.isAuthorized(staking_provider).call()
    assert pre_application.functions.isOperatorConfirmed(staking_provider).call()
    assert threshold_staking.functions.authorizedStake(staking_provider, pre_application.address).call() == new_value

    events = decrease_log.get_all_entries()
    assert len(events) == 2
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value
    assert event_args['toAmount'] == new_value

    # Decrease everything
    value = new_value
    tx = threshold_staking.functions.authorizationDecreaseRequested(staking_provider, value, 0).transact()
    testerchain.wait_for_receipt(tx)
    testerchain.time_travel(seconds=deauthorization_duration)
    tx = pre_application.functions.finishAuthorizationDecrease(staking_provider).transact()
    testerchain.wait_for_receipt(tx)

    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == 0
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[DEAUTHORIZING_SLOT] == 0
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[END_DEAUTHORIZATION_SLOT] == 0
    assert pre_application.functions.getOperatorFromStakingProvider(staking_provider).call() == NULL_ADDRESS
    assert pre_application.functions.stakingProviderFromOperator(staking_provider).call() == NULL_ADDRESS
    assert pre_application.functions.authorizedOverall().call() == 0
    assert pre_application.functions.authorizedStake(staking_provider).call() == 0
    assert not pre_application.functions.isAuthorized(staking_provider).call()
    assert not pre_application.functions.isOperatorConfirmed(staking_provider).call()
    assert threshold_staking.functions.authorizedStake(staking_provider, pre_application.address).call() == 0

    events = decrease_log.get_all_entries()
    assert len(events) == 3
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value
    assert event_args['toAmount'] == 0


def test_resync(testerchain, threshold_staking, pre_application, application_economics):
    """
    Tests for authorization method: resynchronizeAuthorization
    """

    creator, staking_provider = testerchain.client.accounts[0:2]
    resync_log = pre_application.events.AuthorizationReSynchronized.createFilter(fromBlock='latest')

    minimum_authorization = application_economics.min_authorization
    value = 3 * minimum_authorization

    # Nothing sync for not staking provider
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.resynchronizeAuthorization(staking_provider).transact()
        testerchain.wait_for_receipt(tx)

    # Prepare staking providers
    tx = threshold_staking.functions.authorizationIncreased(staking_provider, 0, value).transact()
    testerchain.wait_for_receipt(tx)

    # Nothing to resync
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.resynchronizeAuthorization(staking_provider).transact()
        testerchain.wait_for_receipt(tx)

    # Change authorized amount and resync
    new_value = 2 * minimum_authorization
    tx = threshold_staking.functions.setAuthorized(staking_provider, new_value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.resynchronizeAuthorization(staking_provider).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == new_value
    assert pre_application.functions.authorizedOverall().call() == 0
    assert pre_application.functions.authorizedStake(staking_provider).call() == new_value
    assert pre_application.functions.isAuthorized(staking_provider).call()

    events = resync_log.get_all_entries()
    assert len(events) == 1
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value
    assert event_args['toAmount'] == new_value

    # Confirm operator and change authorized amount again
    value = new_value
    tx = pre_application.functions.bondOperator(staking_provider, staking_provider).transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.confirmOperatorAddress().transact({'from': staking_provider})
    testerchain.wait_for_receipt(tx)

    new_value = minimum_authorization
    tx = threshold_staking.functions.setAuthorized(staking_provider, new_value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.resynchronizeAuthorization(staking_provider).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == new_value
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[DEAUTHORIZING_SLOT] == 0
    assert pre_application.functions.authorizedOverall().call() == new_value
    assert pre_application.functions.getOperatorFromStakingProvider(staking_provider).call() == staking_provider
    assert pre_application.functions.stakingProviderFromOperator(staking_provider).call() == staking_provider
    assert pre_application.functions.authorizedOverall().call() == new_value
    assert pre_application.functions.authorizedStake(staking_provider).call() == new_value
    assert pre_application.functions.isAuthorized(staking_provider).call()
    assert pre_application.functions.isOperatorConfirmed(staking_provider).call()

    events = resync_log.get_all_entries()
    assert len(events) == 2
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value
    assert event_args['toAmount'] == new_value

    # Request decrease and change authorized amount again
    value = new_value
    tx = threshold_staking.functions.authorizationDecreaseRequested(staking_provider, value, 0).transact()
    testerchain.wait_for_receipt(tx)
    new_value = minimum_authorization // 2

    tx = threshold_staking.functions.setAuthorized(staking_provider, new_value).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.resynchronizeAuthorization(staking_provider).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == new_value
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[DEAUTHORIZING_SLOT] == new_value
    assert pre_application.functions.authorizedOverall().call() == new_value
    assert pre_application.functions.getOperatorFromStakingProvider(staking_provider).call() == staking_provider
    assert pre_application.functions.stakingProviderFromOperator(staking_provider).call() == staking_provider
    assert pre_application.functions.authorizedOverall().call() == new_value
    assert pre_application.functions.authorizedStake(staking_provider).call() == new_value
    assert pre_application.functions.isAuthorized(staking_provider).call()
    assert pre_application.functions.isOperatorConfirmed(staking_provider).call()

    events = resync_log.get_all_entries()
    assert len(events) == 3
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value
    assert event_args['toAmount'] == new_value

    # Set authorized amount to zero and resync again
    value = new_value
    tx = threshold_staking.functions.setAuthorized(staking_provider, 0).transact()
    testerchain.wait_for_receipt(tx)
    tx = pre_application.functions.resynchronizeAuthorization(staking_provider).transact()
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[AUTHORIZATION_SLOT] == 0
    assert pre_application.functions.stakingProviderInfo(staking_provider).call()[DEAUTHORIZING_SLOT] == 0
    assert pre_application.functions.authorizedOverall().call() == 0
    assert pre_application.functions.getOperatorFromStakingProvider(staking_provider).call() == NULL_ADDRESS
    assert pre_application.functions.stakingProviderFromOperator(staking_provider).call() == NULL_ADDRESS
    assert pre_application.functions.authorizedOverall().call() == 0
    assert pre_application.functions.authorizedStake(staking_provider).call() == 0
    assert not pre_application.functions.isAuthorized(staking_provider).call()
    assert not pre_application.functions.isOperatorConfirmed(staking_provider).call()

    events = resync_log.get_all_entries()
    assert len(events) == 4
    event_args = events[-1]['args']
    assert event_args['stakingProvider'] == staking_provider
    assert event_args['fromAmount'] == value
    assert event_args['toAmount'] == 0
