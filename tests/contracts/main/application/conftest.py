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

from nucypher.blockchain.eth.token import TToken
from tests.constants import (
    TEST_ETH_PROVIDER_URI,
)
from tests.utils.ursula import MOCK_URSULA_STARTING_PORT
from tests.utils.config import make_ursula_test_configuration
from nucypher.blockchain.eth.registry import InMemoryContractRegistry


TOTAL_SUPPLY = TToken(10_000_000_000, 'T').to_units()


@pytest.fixture()
def token(deploy_contract):
    # Create an ERC20 token
    token, _ = deploy_contract('TToken', _totalSupplyOfTokens=TOTAL_SUPPLY)
    return token


@pytest.fixture()
def threshold_staking(deploy_contract):
    threshold_staking, _ = deploy_contract('ThresholdStakingForPREApplicationMock')
    return threshold_staking


@pytest.fixture()
def pre_application(testerchain, token, threshold_staking, deploy_contract, application_economics):
    # Creator deploys the PRE application
    contract, _ = deploy_contract(
        'ExtendedPREApplication',
        token.address,
        threshold_staking.address,
        *application_economics.pre_application_deployment_parameters
    )

    tx = contract.functions.initialize().transact()
    testerchain.wait_for_receipt(tx)
    tx = threshold_staking.functions.setApplication(contract.address).transact()
    testerchain.wait_for_receipt(tx)

    return contract
