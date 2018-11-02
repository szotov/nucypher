pragma solidity ^0.4.25;


import "./lib/UmbralDeserializer.sol";
import "./lib/SignatureVerifier.sol";
import "./lib/Numerology.sol";
import "./MinersEscrow.sol";


/**
* @notice Challenges for NuCypher net characters
* @dev TODO move or integrate with MinersEscrow
**/
contract ChallengeOverseer {
    using UmbralDeserializer for bytes;

    // TODO events
    uint256 constant PENALTY = 100; // TODO

    MinersEscrow public escrow;
    SignatureVerifier.HashAlgorithm public hashAlgorithm;
    mapping (bytes32 => bool) public challengedCFrags;

    /**
    * @param _escrow Escrow contract
    * @param _hashAlgorithm Hashing algorithm
    **/
    constructor(
        MinersEscrow _escrow,
        SignatureVerifier.HashAlgorithm _hashAlgorithm
    ) public {
        require(address(_escrow) != 0x0);
        escrow = _escrow;
        hashAlgorithm = _hashAlgorithm;
    }

    /**
    * @notice Submit proof that miner created wrong CFrag
    * @param _capsuleBytes Serialized capsule
    * @param _capsuleSignatureByRequester Signature of Capsule by requester
    * @param _capsuleSignatureByRequesterAndMiner Signature of Capsule by requester and miner
    * @param _cFragBytes Serialized CFrag
    * @param _cFragSignatureByMiner Signature of CFrag by miner
    * @param _requesterPublicKey Requester's public key that was used to sign Capsule
    * @param _minerPublicKey Miner's public key that was used to sign Capsule and CFrag
    * @param _minerPublicKeySignature Signature of public key by miner's eth-key
    * @param _preComputedData Pre computed data for CFrag correctness verification
    **/
    function challengeCFrag(
        bytes _capsuleBytes,
        bytes _capsuleSignatureByRequester,
        bytes _capsuleSignatureByRequesterAndMiner,
        bytes _cFragBytes,
        bytes _cFragSignatureByMiner,
        bytes _requesterPublicKey,
        bytes _minerPublicKey,
        bytes _minerPublicKeySignature,
        // TODO rename
        bytes _preComputedData
    ) public {
        require(_minerPublicKey.length == 65 && _requesterPublicKey.length == 65);

        // Check that CFrag is not challenged yet
        bytes32 challengeHash = SignatureVerifier.hash(
            abi.encodePacked(_capsuleBytes, _cFragBytes), hashAlgorithm);
        require(!challengedCFrags[challengeHash]);

        // Verify requester's signature of Capsule
        bytes memory preparedPublicKey = new bytes(64);
        preparePublicKey(preparedPublicKey, _requesterPublicKey);
        require(SignatureVerifier.verify(
                _capsuleBytes, _capsuleSignatureByRequester, preparedPublicKey, hashAlgorithm));

        // Verify miner's signatures of capsule and CFrag
        preparePublicKey(preparedPublicKey, _minerPublicKey);
        require(SignatureVerifier.verify(
                _capsuleSignatureByRequester, _capsuleSignatureByRequesterAndMiner, preparedPublicKey, hashAlgorithm));
        require(SignatureVerifier.verify(
                _cFragBytes, _cFragSignatureByMiner, preparedPublicKey, hashAlgorithm));

        // Extract miner's address and check that is real miner
        address miner = SignatureVerifier.recover(
            SignatureVerifier.hash(_minerPublicKey, hashAlgorithm), _minerPublicKeySignature);
        require(escrow.getLockedTokens(miner) > 0); // TODO check that miner can be slashed

        // Verify correctness of re-encryption
        UmbralDeserializer.Capsule memory capsule = _capsuleBytes.toCapsule();
        UmbralDeserializer.CapsuleFrag memory cFrag = _cFragBytes.toCapsuleFrag();
        // TODO rename
        UmbralDeserializer.PreComputedData memory data = _preComputedData.toPreComputedData();
        if (!isCapsuleFragCorrect(capsule, cFrag, data)) {
            escrow.slashMiner(miner, PENALTY);
        }
        challengedCFrags[challengeHash] = true;
    }

    /**
    * @notice Prepare public key before verification (cut the first byte)
    **/
    function preparePublicKey(bytes memory _preparedPublicKey, bytes memory _publicKey) public pure {
        assembly {
            let destination := add(_preparedPublicKey, 32) // skip array length
            let source := add(_publicKey, 33) // skip array length and first byte in the array
            mstore(destination, mload(source))
            mstore(add(destination, 32), mload(add(source, 32)))
        }
    }

    /**
    * @notice Check correctness of re-encryption
    * @param _capsule Capsule
    * @param _cFrag Capsule frag
    * @param _precomputed Additional precomputed data
    **/
    function isCapsuleFragCorrect(
        UmbralDeserializer.Capsule memory _capsule,
        UmbralDeserializer.CapsuleFrag memory _cFrag,
        UmbralDeserializer.PreComputedData memory _precomputed
    // TODO make public when possible
    ) internal pure returns (bool) {

        // Compute h = hash_to_bignum(e, e1, e2, v, v1, v2, u, u1, u2)
        bytes memory hashInput = abi.encodePacked(
            // Point E
            _capsule.pointE.sign,
            _capsule.pointE.xCoord,
            // Point E1
            _cFrag.pointE1.sign,
            _cFrag.pointE1.xCoord,
            // Point E2
            _cFrag.proof.pointE2.sign,
            _cFrag.proof.pointE2.xCoord
        );

        hashInput = abi.encodePacked(
            hashInput,
            // Point V
            _capsule.pointV.sign,
            _capsule.pointV.xCoord,
            // Point V1
            _cFrag.pointV1.sign,
            _cFrag.pointV1.xCoord,
            // Point V2
            _cFrag.proof.pointV2.sign,
            _cFrag.proof.pointV2.xCoord
        );

        hashInput = abi.encodePacked(
            hashInput,
            // Point U
            bytes1(0x02),
            bytes32(0xef62d276f6f311573b29790b970f2c4b4e44637c0c45f0838ffdc9167a05b999),
            // Point U1
            _cFrag.proof.pointKFragCommitment.sign,
            _cFrag.proof.pointKFragCommitment.xCoord,
            // Point U2
            _cFrag.proof.pointKFragPok.sign,
            _cFrag.proof.pointKFragPok.xCoord
        );

        uint256 h = SignatureVerifier.extendedKeccakToBN(hashInput);

        //////
        // Verifying equation: z*E + h*E_1 = E_2
        //////

        // Input validation: E
        require(Numerology.check_compressed_point(
            _capsule.pointE.sign,
            _capsule.pointE.xCoord,
            _precomputed.pointEyCoord
        ));

        bool ez_is_correct = Numerology.ecmulVerify(
            _capsule.pointE.xCoord,     // E_x
            _precomputed.pointEyCoord,  // E_y
            _cFrag.proof.bnSig,         // z
            _precomputed.pointEZxCoord, // zE_x
            _precomputed.pointEZyCoord  // zE_y
        );

        require(Numerology.check_compressed_point(
            _cFrag.pointE1.sign,         // E_sign
            _cFrag.pointE1.xCoord,      // E1_x
            _precomputed.pointE1yCoord  // E1_y
        ));

        bool e1h_is_correct = Numerology.ecmulVerify(
            _cFrag.pointE1.xCoord,          // E1_x
            _precomputed.pointE1yCoord,     // E1_y
            h,
            _precomputed.pointE1HxCoord,    // hE1_x
            _precomputed.pointE1HyCoord     // hE1_y
        );

        require(Numerology.check_compressed_point(
            _cFrag.proof.pointE2.sign,        // E2_sign
            _cFrag.proof.pointE2.xCoord,      // E2_x
            _precomputed.pointE2yCoord        // E2_y
        ));

        bool sum_is_correct = Numerology.eqAffineJacobian(
            [_cFrag.proof.pointE2.xCoord, _precomputed.pointE2yCoord],
            Numerology.addAffineJacobian(
                [_precomputed.pointEZxCoord,  _precomputed.pointEZyCoord],
                [_precomputed.pointE1HxCoord, _precomputed.pointE1HyCoord]
            )
        );

        // TODO: Repeat with v and u
        return ez_is_correct && e1h_is_correct && sum_is_correct;
    }

}
