// SPDX-License-Identifier: AGPL-3.0-or-later

pragma solidity ^0.8.0;


import "aragon/interfaces/IERC900History.sol";
import "contracts/NuCypherToken.sol";
import "contracts/lib/Bits.sol";
import "contracts/lib/Snapshot.sol";
import "contracts/proxy/Upgradeable.sol";
import "zeppelin/math/Math.sol";
import "zeppelin/token/ERC20/SafeERC20.sol";
import "contracts/threshold/ITokenStaking.sol";


/**
* @notice Adjudicator interface
*/
interface AdjudicatorInterface {
    function rewardCoefficient() external view returns (uint32);
}


/**
* @notice WorkLock interface
*/
interface WorkLockInterface {
    function token() external view returns (NuCypherToken);
}


/**
* @title StakingEscrowStub
* @notice Stub is used to deploy main StakingEscrow after all other contract and make some variables immutable
* @dev |v1.1.0|
*/
contract StakingEscrowStub is Upgradeable {
    NuCypherToken public immutable token;

    /**
    * @notice Predefines some variables for use when deploying other contracts
    * @param _token Token contract
    */
    constructor(NuCypherToken _token) {
        require(_token.totalSupply() > 0);

        token = _token;
    }

    /// @dev the `onlyWhileUpgrading` modifier works through a call to the parent `verifyState`
    function verifyState(address _testTarget) public override virtual {
        super.verifyState(_testTarget);

        // we have to use real values even though this is a stub
        require(address(uint160(delegateGet(_testTarget, this.token.selector))) == address(token));
    }
}


/**
* @title StakingEscrow
* @notice Contract holds and locks stakers tokens.
* Each staker that locks their tokens will receive some compensation
* @dev |v6.1.1|
*/
contract StakingEscrow is Upgradeable, IERC900History {

    using Bits for uint256;
    using Snapshot for uint128[];
    using SafeERC20 for NuCypherToken;

    /**
    * @notice Signals that tokens were deposited
    * @param staker Staker address
    * @param value Amount deposited (in NuNits)
    */
    event Deposited(address indexed staker, uint256 value);

    /**
    * @notice Signals that NU tokens were withdrawn to the staker
    * @param staker Staker address
    * @param value Amount withdraws (in NuNits)
    */
    event Withdrawn(address indexed staker, uint256 value);

    /**
    * @notice Signals that the staker was slashed
    * @param staker Staker address
    * @param penalty Slashing penalty
    * @param investigator Investigator address
    * @param reward Value of reward provided to investigator (in NuNits)
    */
    event Slashed(address indexed staker, uint256 penalty, address indexed investigator, uint256 reward);

    /**
    * @notice Signals that the snapshot parameter was activated/deactivated
    * @param staker Staker address
    * @param snapshotsEnabled Updated parameter value
    */
    event SnapshotSet(address indexed staker, bool snapshotsEnabled);

    /// internal event
    event WorkMeasurementSet(address indexed staker, bool measureWork);

    struct StakerInfo {
        uint256 value;
        uint16 stub1; // former slot for currentCommittedPeriod // TODO combine 4 slots?
        uint16 stub2; // former slot for nextCommittedPeriod
        uint16 stub3; // former slot for lastCommittedPeriod
        uint16 stub4; // former slot for lockReStakeUntilPeriod
        uint256 stub5; // former slot for completedWork
        uint16 stub6; // former slot for workerStartPeriod
        address stub7; // former slot for worker
        uint256 flags; // uint256 to acquire whole slot and minimize operations on it

        uint256 vestingReleaseTimestamp;
        uint256 vestingReleaseRate;

        uint256 reservedSlot3;
        uint256 reservedSlot4;
        uint256 reservedSlot5;

        uint256[] stub8; // former slot for pastDowntime
        uint256[] stub9; // former slot for subStakes
        uint128[] history; // TODO ???

    }

    // indices for flags (0, 1, 2, and 4 were in use, skip it in future)
    uint8 internal constant SNAPSHOTS_DISABLED_INDEX = 3;
    uint8 internal constant MERGED_INDEX = 5;

    NuCypherToken public immutable token;
    AdjudicatorInterface public immutable adjudicator;
    WorkLockInterface public immutable workLock;
    ITokenStaking public immutable tokenStaking;

    uint128 stub1; // former slot for previousPeriodSupply
    uint128 stub2; // former slot for currentPeriodSupply
    uint16 stub3; // former slot for currentMintingPeriod

    mapping (address => StakerInfo) public stakerInfo;
    address[] public stakers;
    mapping (address => address) stub4; // former slot for stakerFromWorker

    mapping (uint16 => uint256) stub5; // former slot for lockedPerPeriod
    uint128[] public balanceHistory;

    address stub6; // former slot for PolicyManager
    address stub7; // former slot for Adjudicator
    address stub8; // former slot for WorkLock

    mapping (uint16 => uint256) stub9; // last former slot for lockedPerPeriod

    /**
    * @notice Constructor sets address of token contract and parameters for staking
    * @param _token NuCypher token contract
    * @param _adjudicator Adjudicator contract
    * @param _workLock WorkLock contract. Zero address if there is no WorkLock
    * @param _tokenStaking T token staking contract
    */
    constructor(
        NuCypherToken _token,
        AdjudicatorInterface _adjudicator,
        WorkLockInterface _workLock,
        ITokenStaking _tokenStaking
    ) {
        require(_token.totalSupply() > 0 &&
            _adjudicator.rewardCoefficient() != 0 &&
            (address(_workLock) == address(0) || _workLock.token() == _token));

        token = _token;
        adjudicator = _adjudicator;
        workLock = _workLock;
        tokenStaking = _tokenStaking;
    }

    /**
    * @dev Checks the existence of a staker in the contract
    */
    modifier onlyStaker()
    {
        require(stakerInfo[msg.sender].value > 0);
        _;
    }

    //------------------------Main getters------------------------
    /**
    * @notice Get all tokens belonging to the staker
    */
    function getAllTokens(address _staker) external view returns (uint256) {
        return stakerInfo[_staker].value;
    }

    /**
    * @notice Get all flags for the staker
    */
    function getFlags(address _staker)
        external view returns (
            bool snapshots,
            bool merged
        )
    {
        StakerInfo storage info = stakerInfo[_staker];
        snapshots = !info.flags.bitSet(SNAPSHOTS_DISABLED_INDEX);
        merged = info.flags.bitSet(MERGED_INDEX);
    }

    /**
    * @notice Get work that completed by the staker
    */
    function getCompletedWork(address _staker) external view returns (uint256) {
        return token.totalSupply();
    }


    //------------------------Main methods------------------------
    /**
    * @notice Stub for WorkLock
    * @param _staker Staker
    * @param _measureWork Value for `measureWork` parameter
    * @return Work that was previously done
    */
    function setWorkMeasurement(address _staker, bool _measureWork) external returns (uint256) {
        require(msg.sender == address(workLock));
        return 0;
    }

    /**
    * @notice Deposit tokens from WorkLock contract
    * @param _staker Staker address
    * @param _value Amount of tokens to deposit
    * @param _unlockingDuration Amount of periods during which tokens will be unlocked when wind down is enabled
    */
    function depositFromWorkLock(
        address _staker,
        uint256 _value,
        uint16 _unlockingDuration
    )
        external
    {
        require(msg.sender == address(workLock));
        require(_value != 0);
        StakerInfo storage info = stakerInfo[_staker];
        // initial stake of the staker
        stakers.push(_staker);
        token.safeTransferFrom(msg.sender, address(this), _value);
        info.value += _value;

        addSnapshot(info, int256(_value));
        emit Deposited(_staker, _value);
    }

    /**
    * @notice Activate/deactivate taking snapshots of balances
    * @param _enableSnapshots True to activate snapshots, False to deactivate
    */
    function setSnapshots(bool _enableSnapshots) external {
        StakerInfo storage info = stakerInfo[msg.sender];
        if (info.flags.bitSet(SNAPSHOTS_DISABLED_INDEX) == !_enableSnapshots) {
            return;
        }

        uint256 lastGlobalBalance = uint256(balanceHistory.lastValue());
        if(_enableSnapshots){
            info.history.addSnapshot(info.value);
            balanceHistory.addSnapshot(lastGlobalBalance + info.value);
        } else {
            info.history.addSnapshot(0);
            balanceHistory.addSnapshot(lastGlobalBalance - info.value);
        }
        info.flags = info.flags.toggleBit(SNAPSHOTS_DISABLED_INDEX);

        emit SnapshotSet(msg.sender, _enableSnapshots);
    }

    /**
    * @notice Adds a new snapshot to both the staker and global balance histories,
    * assuming the staker's balance was already changed
    * @param _info Reference to affected staker's struct
    * @param _addition Variance in balance. It can be positive or negative.
    */
    function addSnapshot(StakerInfo storage _info, int256 _addition) internal {
        if(!_info.flags.bitSet(SNAPSHOTS_DISABLED_INDEX)){
            _info.history.addSnapshot(_info.value);
            uint256 lastGlobalBalance = uint256(balanceHistory.lastValue());
            balanceHistory.addSnapshot(lastGlobalBalance + (_addition >= 0 ? uint256(_addition) : uint256(-_addition)));
        }
    }

    /**
    * @notice Withdraw available amount of NU tokens to staker
    * @param _value Amount of tokens to withdraw
    */
    function withdraw(uint256 _value) external onlyStaker {
        StakerInfo storage info = stakerInfo[msg.sender];
        require(info.flags.bitSet(MERGED_INDEX) &&
            _value + getVestedTokens(msg.sender) <= info.value &&
            _value <= tokenStaking.getAvailableToWithdraw(msg.sender, ITokenStaking.StakingProvider.NU));
        info.value -= _value;

        addSnapshot(info, - int256(_value)); // TODO
        token.safeTransfer(msg.sender, _value);
        emit Withdrawn(msg.sender, _value);
    }

    /**
    * @notice Returns amount of not released yet tokens for staker
    */
    function getVestedTokens(address _staker) public view returns (uint256) {
        StakerInfo storage info = stakerInfo[_staker];
        if (info.vestingReleaseTimestamp <= block.timestamp) {
            return 0;
        }
        return (block.timestamp - info.vestingReleaseTimestamp) * info.vestingReleaseRate;
    }

    /**
    * @notice Setup vesting parameters
    */
    function setupVesting(
        address[] calldata _stakers,
        uint256[] calldata _releaseTimestamp,
        uint256[] calldata _releaseRate
    ) external onlyOwner {
        require(_stakers.length == _releaseTimestamp.length &&
            _releaseTimestamp.length == _releaseRate.length);
        for (uint256 i = 0; i < _stakers.length; i++) {
            address staker = _stakers[i];
            StakerInfo storage info = stakerInfo[staker];
            require(info.vestingReleaseTimestamp == 0); // set only once
            info.vestingReleaseTimestamp = _releaseTimestamp[i];
            info.vestingReleaseRate = _releaseRate[i];
            require(getVestedTokens(staker) <= info.value);
            // TODO emit event
        }
    }

    /**
    * @notice Confirm migration to threshold network
    */
    function confirmMerge() external onlyStaker {
        uint256 unallocated = tokenStaking.getAvailableToWithdraw(msg.sender, ITokenStaking.StakingProvider.NU);
        StakerInfo storage info = stakerInfo[msg.sender];
        require(!info.flags.bitSet(MERGED_INDEX) &&
            unallocated <= 1e5); // TODO ???
        info.flags = info.flags.toggleBit(MERGED_INDEX);
        // TODO emit event
    }

    //-------------------------Slashing-------------------------
    /**
    * @notice Slash the staker's stake and reward the investigator
    * @param _staker Staker's address
    * @param _penalty Penalty
    * @param _investigator Investigator
    * @param _reward Reward for the investigator
    */
    function slashStaker(
        address _staker,
        uint256 _penalty,
        address _investigator,
        uint256 _reward
    )
        external
    {
        require(msg.sender == address(adjudicator)); // TODO allow KEaNU token staking too
        require(_penalty > 0);
        StakerInfo storage info = stakerInfo[_staker];
        if (info.value <= _penalty) {
            _penalty = info.value;
        }
        info.value -= _penalty;
        if (_reward > _penalty) {
            _reward = _penalty;
        }

        emit Slashed(_staker, _penalty, _investigator, _reward);
        if (_reward > 0) {
            token.safeTransfer(_investigator, _reward);
        }

        addSnapshot(info, - int256(_penalty));
    }

    //-------------Additional getters for stakers info-------------
    /**
    * @notice Return the length of the array of stakers
    */
    function getStakersLength() external view returns (uint256) {
        return stakers.length;
    }

    //------------------ ERC900 connectors ----------------------

    function totalStakedForAt(address _owner, uint256 _blockNumber) public view override returns (uint256){
        return stakerInfo[_owner].history.getValueAt(_blockNumber);
    }

    function totalStakedAt(uint256 _blockNumber) public view override returns (uint256){
        return balanceHistory.getValueAt(_blockNumber);
    }

    function supportsHistory() external pure override returns (bool){
        return true;
    }

    //------------------------Upgradeable------------------------
    /**
    * @dev Get StakerInfo structure by delegatecall
    */
    function delegateGetStakerInfo(address _target, bytes32 _staker)
        internal returns (StakerInfo memory result)
    {
        bytes32 memoryAddress = delegateGetData(_target, this.stakerInfo.selector, 1, _staker, 0);
        assembly {
            result := memoryAddress
        }
    }

    /// @dev the `onlyWhileUpgrading` modifier works through a call to the parent `verifyState`
    function verifyState(address _testTarget) public override virtual {
        super.verifyState(_testTarget);
//        require(address(uint160(delegateGet(_testTarget, this.stakerFromWorker.selector, bytes32(0)))) ==
//            stakerFromWorker[address(0)]);

        require(delegateGet(_testTarget, this.getStakersLength.selector) == stakers.length);
        if (stakers.length == 0) {
            return;
        }
        address stakerAddress = stakers[0];
        require(address(uint160(delegateGet(_testTarget, this.stakers.selector, 0))) == stakerAddress);
        StakerInfo storage info = stakerInfo[stakerAddress];
        bytes32 staker = bytes32(uint256(uint160(stakerAddress)));
        StakerInfo memory infoToCheck = delegateGetStakerInfo(_testTarget, staker);
        require(infoToCheck.value == info.value &&
//            infoToCheck.workerStartTimestamp == info.workerStartTimestamp &&
            infoToCheck.vestingReleaseTimestamp == info.vestingReleaseTimestamp &&
            infoToCheck.vestingReleaseRate == info.vestingReleaseRate);

        // it's not perfect because checks not only slot value but also decoding
        // at least without additional functions
        require(delegateGet(_testTarget, this.totalStakedForAt.selector, staker, bytes32(block.number)) ==
            totalStakedForAt(stakerAddress, block.number));
        require(delegateGet(_testTarget, this.totalStakedAt.selector, bytes32(block.number)) ==
            totalStakedAt(block.number));

//        if (info.worker != address(0)) {
//            require(address(uint160(delegateGet(_testTarget, this.stakerFromWorker.selector, bytes32(uint256(uint160(info.worker)))))) ==
//                stakerFromWorker[info.worker]);
//        }
    }

    /// @dev the `onlyWhileUpgrading` modifier works through a call to the parent `finishUpgrade`
    function finishUpgrade(address _target) public override virtual {
        super.finishUpgrade(_target);
    }
}
