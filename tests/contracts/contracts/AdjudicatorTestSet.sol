// SPDX-License-Identifier: AGPL-3.0-or-later

pragma solidity ^0.8.0;


import "contracts/Adjudicator.sol";
import "contracts/lib/SignatureVerifier.sol";
//import "contracts/proxy/Upgradeable.sol";


/**
* @notice Contract for testing the Adjudicator contract
*/
contract ExtendedAdjudicator is Adjudicator {

    uint32 public immutable secondsPerPeriod = 1;
    mapping (address => uint96) public operatorInfo;
    mapping (address => uint256) public rewardInfo;
    mapping (address => address) _operatorFromWorker;

    constructor(
        SignatureVerifier.HashAlgorithm _hashAlgorithm,
        uint256 _basePenalty,
        uint256 _penaltyHistoryCoefficient,
        uint256 _percentagePenaltyCoefficient
    )
        Adjudicator(_hashAlgorithm, _basePenalty, _penaltyHistoryCoefficient, _percentagePenaltyCoefficient)
    {
    }

    function operatorFromWorker(address _worker) public view override returns (address) {
        return _operatorFromWorker[_worker];
    }

    function setOperatorInfo(address _operator, uint96 _amount, address _worker) public {
        operatorInfo[_operator] = _amount;
        if (_worker == address(0)) {
            _worker = _operator;
        }
        _operatorFromWorker[_worker] = _operator;
    }

    function authorizedStake(address _operator) public view override returns (uint96) {
        return operatorInfo[_operator];
    }

    function slash(
        address _operator,
        uint96 _penalty,
        address _investigator
    )
        internal override
    {
        operatorInfo[_operator] -= _penalty;
        rewardInfo[_investigator] += 1;
    }

}


///**
//* @notice Upgrade to this contract must lead to fail
//*/
//contract AdjudicatorBad is Upgradeable {
//
//    mapping (bytes32 => bool) public evaluatedCFrags;
//    mapping (address => uint256) public penaltyHistory;
//
//}
//
//
///**
//* @notice Contract for testing upgrading the Adjudicator contract
//*/
//contract AdjudicatorV2Mock is Adjudicator {
//
//    uint256 public valueToCheck;
//
//    constructor(
//        SignatureVerifier.HashAlgorithm _hashAlgorithm,
//        uint256 _basePenalty,
//        uint256 _percentagePenalty,
//        uint256 _penaltyHistoryCoefficient
//    )
//        Adjudicator(
//            _hashAlgorithm,
//            _basePenalty,
//            _percentagePenalty,
//            _penaltyHistoryCoefficient
//        )
//    {
//    }
//
//    function setValueToCheck(uint256 _valueToCheck) public {
//        valueToCheck = _valueToCheck;
//    }
//
//    function verifyState(address _testTarget) override public {
//        super.verifyState(_testTarget);
//        require(uint256(delegateGet(_testTarget, this.valueToCheck.selector)) == valueToCheck);
//    }
//}
