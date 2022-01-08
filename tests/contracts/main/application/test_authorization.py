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


def test_authorization_increase(testerchain, threshold_staking, pre_application, token_economics):
    """
    Tests for authorization method: authorizationIncreased
    """

    creator, operator1 = testerchain.client.accounts[0:2]
    increase_log = pre_application.events.AuthorizationIncreased.createFilter(fromBlock='latest')

    minimum_authorization = token_economics.minimum_allowed_locked  # TODO
    value = minimum_authorization

    # Can't call `authorizationIncreased` directly
    with pytest.raises((TransactionFailed, ValueError)):
        tx = pre_application.functions.authorizationIncreased(
            operator1, 0, value
        ).transact({'from': creator})
        testerchain.wait_for_receipt(tx)

    # Operator and toAmount must be specified
    with pytest.raises((TransactionFailed, ValueError)):
        tx = threshold_staking.functions.authorizationIncreased(
            NULL_ADDRESS, 0, value
        ).transact({'from': creator})
        testerchain.wait_for_receipt(tx)
    with pytest.raises((TransactionFailed, ValueError)):
        tx = threshold_staking.functions.authorizationIncreased(
            operator1, 0, 0
        ).transact({'from': creator})
        testerchain.wait_for_receipt(tx)

    # Authorization must be greater than minimum
    with pytest.raises((TransactionFailed, ValueError)):
        tx = threshold_staking.functions.authorizationIncreased(
            operator1, 0, value - 1
        ).transact({'from': creator})
        testerchain.wait_for_receipt(tx)

    # First authorization
    tx = threshold_staking.functions.authorizationIncreased(
        operator1, 0, value
    ).transact({'from': creator})
    testerchain.wait_for_receipt(tx)
    assert pre_application.functions.operatorInfo(operator1).call()[AUTHORIZATION_SLOT] == value
    assert pre_application.functions.authorizedOverall().call() == 0

    # Check that all events are emitted
    events = increase_log.get_all_entries()
    assert len(events) == 1
    event_args = events[-1]['args']
    assert event_args['operator'] == operator1
    assert event_args['fromAmount'] == 0
    assert event_args['toAmount'] == value
