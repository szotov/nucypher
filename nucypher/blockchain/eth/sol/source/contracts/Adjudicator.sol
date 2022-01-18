// SPDX-License-Identifier: AGPL-3.0-or-later

pragma solidity ^0.8.0;

import "contracts/lib/ReEncryptionValidator.sol";
import "contracts/lib/SignatureVerifier.sol";
import "zeppelin/math/Math.sol";
import "zeppelin/math/SafeCast.sol";


/**
* @title Adjudicator
* @notice Supervises workers' behavior and punishes when something's wrong.
* @dev |v3.1.1|
*/
abstract contract Adjudicator {

    using UmbralDeserializer for bytes;
    using SafeCast for uint256;

    event CFragEvaluated(
        bytes32 indexed evaluationHash,
        address indexed investigator,
        bool correctness
    );
    event IncorrectCFragVerdict(
        bytes32 indexed evaluationHash,
        address indexed worker,
        address indexed operator
    );

    // used only for upgrading
    bytes32 constant RESERVED_CAPSULE_AND_CFRAG_BYTES = bytes32(0);
    address constant RESERVED_ADDRESS = address(0);

    SignatureVerifier.HashAlgorithm public immutable hashAlgorithm;
    uint256 public immutable basePenalty;
    uint256 public immutable penaltyHistoryCoefficient;
    uint256 public immutable percentagePenaltyCoefficient;

    mapping (address => uint256) public penaltyHistory;
    mapping (bytes32 => bool) public evaluatedCFrags;

    uint256[50] private reservedSlots;

    /**
    * @param _hashAlgorithm Hashing algorithm
    * @param _basePenalty Base for the penalty calculation
    * @param _penaltyHistoryCoefficient Coefficient for calculating the penalty depending on the history
    * @param _percentagePenaltyCoefficient Coefficient for calculating the percentage penalty
    */
    constructor(
        SignatureVerifier.HashAlgorithm _hashAlgorithm,
        uint256 _basePenalty,
        uint256 _penaltyHistoryCoefficient,
        uint256 _percentagePenaltyCoefficient
    ) {
        require(_percentagePenaltyCoefficient != 0, "Wrong input parameters");
        hashAlgorithm = _hashAlgorithm;
        basePenalty = _basePenalty;
        percentagePenaltyCoefficient = _percentagePenaltyCoefficient;
        penaltyHistoryCoefficient = _penaltyHistoryCoefficient;
    }

    /**
    * @notice Submit proof that a worker created wrong CFrag
    * @param _capsuleBytes Serialized capsule
    * @param _cFragBytes Serialized CFrag
    * @param _cFragSignature Signature of CFrag by worker
    * @param _taskSignature Signature of task specification by Bob
    * @param _requesterPublicKey Bob's signing public key, also known as "stamp"
    * @param _workerPublicKey Worker's signing public key, also known as "stamp"
    * @param _workerIdentityEvidence Signature of worker's public key by worker's eth-key
    * @param _preComputedData Additional pre-computed data for CFrag correctness verification
    */
    function evaluateCFrag(
        bytes memory _capsuleBytes,
        bytes memory _cFragBytes,
        bytes memory _cFragSignature,
        bytes memory _taskSignature,
        bytes memory _requesterPublicKey,
        bytes memory _workerPublicKey,
        bytes memory _workerIdentityEvidence,
        bytes memory _preComputedData
    )
        public
    {
        // 1. Check that CFrag is not evaluated yet
        bytes32 evaluationHash = SignatureVerifier.hash(
            abi.encodePacked(_capsuleBytes, _cFragBytes), hashAlgorithm);
        require(!evaluatedCFrags[evaluationHash], "This CFrag has already been evaluated.");
        evaluatedCFrags[evaluationHash] = true;

        // 2. Verify correctness of re-encryption
        bool cFragIsCorrect = ReEncryptionValidator.validateCFrag(_capsuleBytes, _cFragBytes, _preComputedData);
        emit CFragEvaluated(evaluationHash, msg.sender, cFragIsCorrect);

        // 3. Verify associated public keys and signatures
        require(ReEncryptionValidator.checkSerializedCoordinates(_workerPublicKey),
                "Staker's public key is invalid");
        require(ReEncryptionValidator.checkSerializedCoordinates(_requesterPublicKey),
                "Requester's public key is invalid");

        UmbralDeserializer.PreComputedData memory precomp = _preComputedData.toPreComputedData();

        // Verify worker's signature of CFrag
        require(SignatureVerifier.verify(
                _cFragBytes,
                abi.encodePacked(_cFragSignature, precomp.lostBytes[1]),
                _workerPublicKey,
                hashAlgorithm),
                "CFrag signature is invalid"
        );

        // Verify worker's signature of taskSignature and that it corresponds to cfrag.proof.metadata
        UmbralDeserializer.CapsuleFrag memory cFrag = _cFragBytes.toCapsuleFrag();
        require(SignatureVerifier.verify(
                _taskSignature,
                abi.encodePacked(cFrag.proof.metadata, precomp.lostBytes[2]),
                _workerPublicKey,
                hashAlgorithm),
                "Task signature is invalid"
        );

        // Verify that _taskSignature is bob's signature of the task specification.
        // A task specification is: capsule + ursula pubkey + alice address + blockhash
        bytes32 stampXCoord;
        assembly {
            stampXCoord := mload(add(_workerPublicKey, 32))
        }
        bytes memory stamp = abi.encodePacked(precomp.lostBytes[4], stampXCoord);

        require(SignatureVerifier.verify(
                abi.encodePacked(_capsuleBytes,
                                 stamp,
                                 _workerIdentityEvidence,
                                 precomp.alicesKeyAsAddress,
                                 bytes32(0)),
                abi.encodePacked(_taskSignature, precomp.lostBytes[3]),
                _requesterPublicKey,
                hashAlgorithm),
                "Specification signature is invalid"
        );

        // 4. Extract worker address from stamp signature.
        address worker = SignatureVerifier.recover(
            SignatureVerifier.hashEIP191(stamp, bytes1(0x45)), // Currently, we use version E (0x45) of EIP191 signatures
            _workerIdentityEvidence);
        address operator = operatorFromWorker(worker);
        require(operator != address(0), "Worker must be related to an operator");

        // 5. Check that operator can be slashed
        uint96 operatorValue = authorizedStake(operator);
        require(operatorValue > 0, "Operator has no tokens");

        // 6. If CFrag was incorrect, slash operator
        if (!cFragIsCorrect) {
            uint96 penalty = calculatePenalty(operator, operatorValue);
            slash(operator, penalty, msg.sender);
            emit IncorrectCFragVerdict(evaluationHash, worker, operator);
        }
    }

    /**
    * @notice Calculate penalty to the operator
    * @param _operator Operator's address
    * @param _operatorValue Amount of tokens that belong to the operator
    */
    function calculatePenalty(address _operator, uint96 _operatorValue)
        internal returns (uint96)
    {
        uint256 penalty = basePenalty + penaltyHistoryCoefficient * penaltyHistory[_operator];
        penalty = Math.min(penalty, _operatorValue / percentagePenaltyCoefficient);
        // TODO add maximum condition or other overflow protection or other penalty condition (#305?)
        penaltyHistory[_operator] = penaltyHistory[_operator] + 1;
        return penalty.toUint96();
    }

    /**
    * @notice Get all tokens delegated to the operator
    */
    function authorizedStake(address _operator) public view virtual returns (uint96);

    /**
    * @notice Get operator address bonded with specified worker address
    */
    function operatorFromWorker(address _worker) public view virtual returns (address);

    /**
    * @notice Slash the operator's stake and reward the investigator
    * @param _operator Operator's address
    * @param _penalty Penalty
    * @param _investigator Investigator
    */
    function slash(
        address _operator,
        uint96 _penalty,
        address _investigator
    ) internal virtual;

}
