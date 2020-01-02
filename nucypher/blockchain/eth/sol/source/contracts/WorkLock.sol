pragma solidity ^0.5.3;


import "zeppelin/math/SafeMath.sol";
import "zeppelin/token/ERC20/SafeERC20.sol";
import "zeppelin/utils/Address.sol";
import "contracts/NuCypherToken.sol";
import "contracts/StakingEscrow.sol";
import "contracts/staking_contracts/PreallocationEscrow.sol";
import "contracts/staking_contracts/AbstractStakingContract.sol";
import "contracts/lib/AdditionalMath.sol";


/**
* @notice The WorkLock distribution contract
*/
contract WorkLock {
    using SafeERC20 for NuCypherToken;
    using SafeMath for uint256;
    using AdditionalMath for uint256;
    using Address for address payable;
    using Address for address;

    event Deposited(address indexed sender, uint256 value);
    event Bid(address indexed sender, uint256 depositedETH);
    event Claimed(address indexed sender, address preallocationEscrow, uint256 claimedTokens);
    event Refund(address indexed sender, address preallocationEscrow, uint256 refundETH, uint256 completedWork);
    event Burnt(address indexed sender, uint256 value);
    event Canceled(address indexed sender, uint256 value);

    struct WorkInfo {
        uint256 depositedETH;
        uint256 completedWork;
        PreallocationEscrow preallocationEscrow;
    }

    NuCypherToken public token;
    StakingEscrow public escrow;
    StakingInterfaceRouter public router;

    uint256 public startBidDate;
    uint256 public endBidDate;

    /*
    * @dev WorkLock calculations:
    * depositRate = tokenSupply / ethSupply
    * claimedTokens = depositedETH * depositRate
    * refundRate = depositRate * SLOWING_REFUND / boostingRefund
    * refundETH = completedWork / refundRate
    */
    uint256 public boostingRefund;
    uint16 public constant SLOWING_REFUND = 100;
    uint256 private constant MAX_ETH_SUPPLY = 2e10 ether;

    uint256 public tokenSupply;
    uint256 public ethSupply;
    uint256 public unclaimedTokens;
    uint256 public lockingDuration;
    mapping(address => WorkInfo) public workInfo;
    mapping(address => address) public depositors;

    /**
    * @param _token Token contract
    * @param _escrow Escrow contract
    * @param _router Router contract
    * @param _startBidDate Timestamp when bidding starts
    * @param _endBidDate Timestamp when bidding will end
    * @param _boostingRefund Coefficient to boost refund ETH
    * @param _lockingDuration Duration of tokens locking
    */
    constructor(
        NuCypherToken _token,
        StakingEscrow _escrow,
        StakingInterfaceRouter _router,
        uint256 _startBidDate,
        uint256 _endBidDate,
        uint256 _boostingRefund,
        uint256 _lockingDuration
    )
        public
    {
        uint256 totalSupply = _token.totalSupply();
        require(totalSupply > 0 &&
            _escrow.secondsPerPeriod() > 0 &&
            _router.target().isContract() &&
            _endBidDate > _startBidDate &&
            _endBidDate > block.timestamp &&
            _boostingRefund > 0 &&
            _lockingDuration > 0);
        // worst case for `ethToWork()` and `workToETH()`,
        // when ethSupply == MAX_ETH_SUPPLY and tokenSupply == totalSupply
        require(MAX_ETH_SUPPLY * totalSupply * SLOWING_REFUND / MAX_ETH_SUPPLY / totalSupply == SLOWING_REFUND &&
            MAX_ETH_SUPPLY * totalSupply * _boostingRefund / MAX_ETH_SUPPLY / totalSupply == _boostingRefund);

        token = _token;
        escrow = _escrow;
        router = _router;
        startBidDate = _startBidDate;
        endBidDate = _endBidDate;
        boostingRefund = _boostingRefund;
        lockingDuration = _lockingDuration;
    }

    /**
    * @notice Deposit tokens to contract
    * @param _value Amount of tokens to transfer
    **/
    function tokenDeposit(uint256 _value) external {
        require(block.timestamp <= endBidDate, "Can't deposit more tokens after end of bidding");
        token.safeTransferFrom(msg.sender, address(this), _value);
        tokenSupply += _value;
        emit Deposited(msg.sender, _value);
    }

    /**
    * @notice Calculate amount of tokens that will be get for specified amount of ETH
    * @dev This value will be fixed only after end of bidding
    **/
    function ethToTokens(uint256 _ethAmount) public view returns (uint256) {
        return _ethAmount.mul(tokenSupply).div(ethSupply);
    }

    /**
    * @notice Calculate amount of work that need to be done to refund specified amount of ETH
    * @dev This value will be fixed only after end of bidding
    **/
    function ethToWork(uint256 _ethAmount) public view returns (uint256) {
        return _ethAmount.mul(tokenSupply).mul(SLOWING_REFUND).divCeil(ethSupply.mul(boostingRefund));
    }

    /**
    * @notice Calculate amount of ETH that will be refund for completing specified amount of work
    * @dev This value will be fixed only after end of bidding
    **/
    function workToETH(uint256 _completedWork) public view returns (uint256) {
        return _completedWork.mul(ethSupply).mul(boostingRefund).div(tokenSupply.mul(SLOWING_REFUND));
    }

    /**
    * @notice Get remaining work to full refund
    */
    function getRemainingWork(address _preallocationEscrow) public view returns (uint256) {
        address depositor = depositors[_preallocationEscrow];
        WorkInfo storage info = workInfo[depositor];
        uint256 completedWork = escrow.getCompletedWork(_preallocationEscrow).sub(info.completedWork);
        uint256 remainingWork = ethToWork(info.depositedETH);
        if (remainingWork <= completedWork) {
            return 0;
        }
        return remainingWork.sub(completedWork);
    }

    /**
    * @notice Bid for tokens by transferring ETH
    */
    function bid() external payable {
        require(block.timestamp >= startBidDate && block.timestamp <= endBidDate,
            "Bid is open during a certain period");
        WorkInfo storage info = workInfo[msg.sender];
        info.depositedETH = info.depositedETH.add(msg.value);
        ethSupply = ethSupply.add(msg.value);
        emit Bid(msg.sender, msg.value);
    }

    /**
    * @notice Cancel bid and refund deposited ETH
    */
    function cancelBid() external {
        // TODO check date? check minimum amount of tokens? (#1508)
        WorkInfo storage info = workInfo[msg.sender];
        require(info.depositedETH > 0, "No bid to cancel");
        require(address(info.preallocationEscrow) == address(0), "Tokens are already claimed");
        uint256 refundETH = info.depositedETH;
        info.depositedETH = 0;
        if (block.timestamp <= endBidDate) {
            ethSupply = ethSupply.sub(refundETH);
        } else {
            unclaimedTokens = unclaimedTokens.add(ethToTokens(refundETH));
        }
        msg.sender.sendValue(refundETH);
        emit Canceled(msg.sender, refundETH);
    }

    /**
    * @notice Claimed tokens will be deposited and locked as stake in the StakingEscrow contract.
    */
    function claim() external returns (PreallocationEscrow preallocationEscrow, uint256 claimedTokens) {
        require(block.timestamp >= endBidDate, "Claiming tokens allowed after bidding is over");
        WorkInfo storage info = workInfo[msg.sender];
        require(address(info.preallocationEscrow) == address(0), "Tokens are already claimed");
        claimedTokens = ethToTokens(info.depositedETH);
        require(claimedTokens > 0, "Nothing to claim");

        preallocationEscrow = new PreallocationEscrow(router, token, StakingEscrowInterface(address(escrow)));
        token.approve(address(preallocationEscrow), claimedTokens);
        preallocationEscrow.initialDeposit(claimedTokens, lockingDuration);
        preallocationEscrow.transferOwnership(msg.sender);
        depositors[address(preallocationEscrow)] = msg.sender;
        info.preallocationEscrow = preallocationEscrow;
        info.completedWork = escrow.setWorkMeasurement(address(preallocationEscrow), true);
        emit Claimed(msg.sender, address(preallocationEscrow), claimedTokens);
    }

    /**
    * @notice Refund ETH for the completed work
    */
    function refund(PreallocationEscrow _preallocationEscrow) public returns (uint256 refundETH) {
        address depositor = depositors[address(_preallocationEscrow)];
        require(depositor != address(0), "Untrusted contract");
        WorkInfo storage info = workInfo[depositor];
        require(info.depositedETH > 0, "Nothing deposited");
        require(_preallocationEscrow.owner() == msg.sender, "Only the owner of specified contract can request a refund");
        assert(_preallocationEscrow == info.preallocationEscrow);
        uint256 currentWork = escrow.getCompletedWork(address(_preallocationEscrow));

        uint256 completedWork = currentWork.sub(info.completedWork);
        require(completedWork > 0, "No work that has been completed.");
        refundETH = workToETH(completedWork);

        if (refundETH > info.depositedETH) {
            refundETH = info.depositedETH;
        }
        if (refundETH == info.depositedETH) {
            escrow.setWorkMeasurement(address(_preallocationEscrow), false);
        }
        info.depositedETH = info.depositedETH.sub(refundETH);
        completedWork = ethToWork(refundETH);

        info.completedWork = info.completedWork.add(completedWork);
        emit Refund(msg.sender, address(_preallocationEscrow), refundETH, completedWork);
        msg.sender.sendValue(refundETH);
    }

    /**
    * @notice Burn unclaimed tokens
    **/
    function burnUnclaimed() public {
        require(block.timestamp >= endBidDate, "Burning tokens allowed when bidding is over");
        require(unclaimedTokens > 0, "There are no tokens that can be burned");
        token.approve(address(escrow), unclaimedTokens);
        escrow.burn(unclaimedTokens);
        emit Burnt(msg.sender, unclaimedTokens);
        unclaimedTokens = 0;
    }

}
