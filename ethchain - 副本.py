import logging,pickle,sys,requests,random,time,json,traceback
import pandas as pd
from pathlib import Path

from okx.Funding import FundingAPI
from okx.Account import AccountAPI
from okx.PublicData import PublicAPI
from okx.Trade import TradeAPI


from decimal import Decimal
from web3 import Web3
from web3.types import TxParams
from web3.middleware import geth_poa_middleware
from web3.exceptions import ContractLogicError
from web3.contract import ContractFunction

from eth_typing import HexStr
from eth_account import Account
from eth_account.signers.local import LocalAccount

from zksync2.module.zksync_module import ZkSync
from zksync2.module.request_types import *
from zksync2.module.module_builder import ZkSyncBuilder
from zksync2.manage_contracts.l2_bridge import L2BridgeEncoder
from zksync2.core.types import Token, ZkBlockParams, BridgeAddresses, EthBlockParams
from zksync2.signer.eth_signer import PrivateKeyEthSigner
from zksync2.transaction.transaction712 import Transaction712

from zksync2.manage_contracts.contract_deployer import ContractDeployer
from zksync2.manage_contracts.nonce_holder import NonceHolder

from zksync2.manage_contracts.erc20_contract import ERC20FunctionEncoder
from zksync2.manage_contracts.gas_provider import StaticGasProvider
from zksync2.provider.eth_provider import EthereumProvider
from zksync2.transaction.transaction712 import TxFunctionCall
from zksync2.transaction.transaction712 import TxCreateContract
from zksync2.transaction.transaction712 import TxCreate2Contract

# https://v2-docs.zksync.io/api/api.html#zksync-specific-json-rpc-methods
# https://goerli.etherscan.io/address/0xd8792d39bddb4622cbadd62004a067e72206ca98#code
# https://goerli.etherscan.io/address/0x272acae075a120a219b343e9c8d148e1379bcdda#code
# https://github.com/matter-labs
# https://docs.zksync.io/api/web3-rpc/#note-on-input
# https://docs.zksync.io/apiv02-docs/#accounts-api-v0.2-accounts-{accountidoraddress}-transactions-pending-get
# https://explorer.zksync.io/tx/0xc59f1874524dc72a58ded1fb173c8a2dfe7612384d61736eb2e305c43556d430#overview
# 0xdf4bee40ff896a7dc365ffa377710482da37d1dd

def get_taskads(task_file, result_file, source_id, source_data, source_data2 = None):

    # 任务来源（用txt做列表）
    with open(task_file, "r", encoding='gb18030', errors='ignore') as file:
        taskfile = file.readlines()
        taskads = []
        for j in taskfile:
            taskads.append(j.strip("\n"))
        file.close()

    # 剔除result中的完成
    try:
        resultframe = pd.read_csv(result_file, encoding="gb18030")
        resultframe = pd.DataFrame(resultframe, columns=["ads", "address", "status", "remarks"])
        resultframe = resultframe.set_index(["ads"])
        resultads = resultframe[resultframe.remarks == "完成"].index.tolist()
        for i in resultads:
            if i in taskads:
                taskads.remove(i)
    # 假设result文件不存在创建
    except FileNotFoundError:
        result_data = [["test", "test", "test", "test"]]
        resultframe = pd.DataFrame(result_data, columns=["ads", "address", "status", "remarks"])
        resultframe = resultframe.set_index(["ads"])
        resultframe.to_csv(result_file, encoding="gb18030", errors='ignore')

    with open(source_id, "rb") as file:
        adsid = pickle.load(file)
        file.close()

    with open(source_data, "rb") as file:
        data_frame = pickle.load(file)
        file.close()

    data_frame2 = pd.read_csv(source_data2, encoding="gb18030")
    data_frame2 = pd.DataFrame(data_frame2, columns=["ads", "address", "dc", "mail", 'tw', 'sui-address', 'to'])
    data_frame2 = data_frame2.set_index(["ads"])

    return taskads, data_frame, adsid, data_frame2

def to_okcex_address(addressmark):
    okcextodict = {
        'r1-a9': '0x253e9a3de05f3526a4059b3098993fa98c4cf2a7',
        'a10-a3': '0xffb94f3c8df40abcfe88ae46dae44e74eb59f555',
        'a4-a17': '0xbd1fd6672c2e706a161a021b1a3669efd0043287',
        'a18-a26': '0x573d57266f08a3315f2c0d1361fb19a0db2b2af7',
        'a27-a35': '0x249e9d80c926266c6e354bc115b0716b94d79e20'
    }
    for i in okcextodict.keys():
        if addressmark == i:
            return okcextodict[i]

class net(object):

    def __init__(self, network, wallet, private_key, apikey = None):
        # 设置w3
        ethmainnet_url = "xxxxxxxxxxxxxxxx"
        ethgortli_url = 'xxxxxxxxxxxxxxxx'
        ethop = 'xxxxxxxxxxxxxxxx'
        bnb = 'https://bsc-dataseed1.binance.org'
        arb = 'xxxxxxxxxxxxxxxx'
        if network == 'goerli':
            self.w3 = Web3(Web3.HTTPProvider(ethgortli_url))
            self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)  # 连接公共节点需要注入此中间件
        elif network == 'mainnet':
            self.w3 = Web3(Web3.HTTPProvider(ethmainnet_url))
        elif network == 'op':
            self.w3 = Web3(Web3.HTTPProvider(ethop))
            self.chainId = 10
        elif network == 'bsc':
            self.w3 = Web3(Web3.HTTPProvider(bnb))
            self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)  # 连接公共节点需要注入此中间件
        elif network == 'arb':
            self.w3 = Web3(Web3.HTTPProvider(arb))
        # 主钱包地址
        self.wallet = Web3.toChecksumAddress(wallet)
        # 钱包的私钥与API
        self.private_key = private_key
        self.api = apikey
        self.network = network
        # 代币简写
        self.token_name = 'USDT'
        # 登录成功提示
        print()
        print("——————————————————————————————")
        print(ads_zh, self.wallet, f"{network}：", self.w3.isConnected())

    def fetch_abi(self, module, action):
        if self.network == 'bsc':
            # 获取BNB链上的合约ABI
            url = "https://api.bscscan.com/api"
            params = {
                "module": module,
                "action": action,
                "address": self.contract_address,
                "apikey": self.api,
            }
            resp = requests.get(url, params=params).json()
            return resp["result"]
        elif self.network == 'op':
            opabi = '[{"inputs":[{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"amount","type":"uint256"}],"name":"transfer","outputs":[{"internalType":"bool","name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"account","type":"address"}],"name":"balanceOf","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]'
            return opabi
        elif self.network == 'goerli':
            goerliabiurl = 'https://api-goerli.etherscan.io/api?module=contract&action=getabi&address=0x768B3367320e4bFF330Cc01A2434E73B01b3F71f'
            resp = requests.get(goerliabiurl).json()
            return resp["result"]

    def create_contract(self, contract_address, abi = '', module = 'contract', action = 'getabi'):

        def get_abi_file(p: Path):
            with p.open(mode='r') as json_f:
                return json.load(json_f)

        def get_abi_url(url):
            resp = requests.get(url)
            a = resp.json()
            return a["result"]

        self.contract_address = Web3.toChecksumAddress(contract_address)
        if abi == 'bsc':
            self.abi = self.fetch_abi(module, action)
        elif abi == 'arb_claim':
            arb_claim_abi = '[{"inputs":[{"internalType":"contract IERC20VotesUpgradeable","name":"_token","type":"address"},{"internalType":"address payable","name":"_sweepReceiver","type":"address"},{"internalType":"address","name":"_owner","type":"address"},{"internalType":"uint256","name":"_claimPeriodStart","type":"uint256"},{"internalType":"uint256","name":"_claimPeriodEnd","type":"uint256"},{"internalType":"address","name":"delegateTo","type":"address"}],"stateMutability":"nonpayable","type":"constructor"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"recipient","type":"address"},{"indexed":false,"internalType":"uint256","name":"amount","type":"uint256"}],"name":"CanClaim","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"recipient","type":"address"},{"indexed":false,"internalType":"uint256","name":"amount","type":"uint256"}],"name":"HasClaimed","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"previousOwner","type":"address"},{"indexed":true,"internalType":"address","name":"newOwner","type":"address"}],"name":"OwnershipTransferred","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"newSweepReceiver","type":"address"}],"name":"SweepReceiverSet","type":"event"},{"anonymous":false,"inputs":[{"indexed":false,"internalType":"uint256","name":"amount","type":"uint256"}],"name":"Swept","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"recipient","type":"address"},{"indexed":false,"internalType":"uint256","name":"amount","type":"uint256"}],"name":"Withdrawal","type":"event"},{"inputs":[],"name":"claim","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"delegatee","type":"address"},{"internalType":"uint256","name":"expiry","type":"uint256"},{"internalType":"uint8","name":"v","type":"uint8"},{"internalType":"bytes32","name":"r","type":"bytes32"},{"internalType":"bytes32","name":"s","type":"bytes32"}],"name":"claimAndDelegate","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"claimPeriodEnd","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"claimPeriodStart","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"","type":"address"}],"name":"claimableTokens","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"owner","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"renounceOwnership","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address[]","name":"_recipients","type":"address[]"},{"internalType":"uint256[]","name":"_claimableAmount","type":"uint256[]"}],"name":"setRecipients","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address payable","name":"_sweepReceiver","type":"address"}],"name":"setSweepReciever","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"sweep","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"sweepReceiver","outputs":[{"internalType":"address payable","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"token","outputs":[{"internalType":"contract IERC20VotesUpgradeable","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"totalClaimable","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"newOwner","type":"address"}],"name":"transferOwnership","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"uint256","name":"amount","type":"uint256"}],"name":"withdraw","outputs":[],"stateMutability":"nonpayable","type":"function"}]'
            self.abi = arb_claim_abi
        elif abi == 'arb_coin':
            arb_coin_abi = '[{"inputs":[{"internalType":"address","name":"_logic","type":"address"},{"internalType":"address","name":"admin_","type":"address"},{"internalType":"bytes","name":"_data","type":"bytes"}],"stateMutability":"payable","type":"constructor"},{"anonymous":false,"inputs":[{"indexed":false,"internalType":"address","name":"previousAdmin","type":"address"},{"indexed":false,"internalType":"address","name":"newAdmin","type":"address"}],"name":"AdminChanged","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"beacon","type":"address"}],"name":"BeaconUpgraded","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"implementation","type":"address"}],"name":"Upgraded","type":"event"},{"stateMutability":"payable","type":"fallback"},{"inputs":[],"name":"admin","outputs":[{"internalType":"address","name":"admin_","type":"address"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"newAdmin","type":"address"}],"name":"changeAdmin","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"implementation","outputs":[{"internalType":"address","name":"implementation_","type":"address"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"newImplementation","type":"address"}],"name":"upgradeTo","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"newImplementation","type":"address"},{"internalType":"bytes","name":"data","type":"bytes"}],"name":"upgradeToAndCall","outputs":[],"stateMutability":"payable","type":"function"},{"stateMutability":"payable","type":"receive"}]'
            self.abi = arb_coin_abi
        elif abi == 'arb_contract':
            arb_contract_abi = '[{"inputs":[],"stateMutability":"nonpayable","type":"constructor"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"owner","type":"address"},{"indexed":true,"internalType":"address","name":"spender","type":"address"},{"indexed":false,"internalType":"uint256","name":"value","type":"uint256"}],"name":"Approval","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"delegator","type":"address"},{"indexed":true,"internalType":"address","name":"fromDelegate","type":"address"},{"indexed":true,"internalType":"address","name":"toDelegate","type":"address"}],"name":"DelegateChanged","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"delegate","type":"address"},{"indexed":false,"internalType":"uint256","name":"previousBalance","type":"uint256"},{"indexed":false,"internalType":"uint256","name":"newBalance","type":"uint256"}],"name":"DelegateVotesChanged","type":"event"},{"anonymous":false,"inputs":[{"indexed":false,"internalType":"uint8","name":"version","type":"uint8"}],"name":"Initialized","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"previousOwner","type":"address"},{"indexed":true,"internalType":"address","name":"newOwner","type":"address"}],"name":"OwnershipTransferred","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"from","type":"address"},{"indexed":true,"internalType":"address","name":"to","type":"address"},{"indexed":false,"internalType":"uint256","name":"value","type":"uint256"},{"indexed":false,"internalType":"bytes","name":"data","type":"bytes"}],"name":"Transfer","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"from","type":"address"},{"indexed":true,"internalType":"address","name":"to","type":"address"},{"indexed":false,"internalType":"uint256","name":"value","type":"uint256"}],"name":"Transfer","type":"event"},{"inputs":[],"name":"DOMAIN_SEPARATOR","outputs":[{"internalType":"bytes32","name":"","type":"bytes32"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"MINT_CAP_DENOMINATOR","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"MINT_CAP_NUMERATOR","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"MIN_MINT_INTERVAL","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"owner","type":"address"},{"internalType":"address","name":"spender","type":"address"}],"name":"allowance","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"spender","type":"address"},{"internalType":"uint256","name":"amount","type":"uint256"}],"name":"approve","outputs":[{"internalType":"bool","name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"account","type":"address"}],"name":"balanceOf","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"uint256","name":"amount","type":"uint256"}],"name":"burn","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"account","type":"address"},{"internalType":"uint256","name":"amount","type":"uint256"}],"name":"burnFrom","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"account","type":"address"},{"internalType":"uint32","name":"pos","type":"uint32"}],"name":"checkpoints","outputs":[{"components":[{"internalType":"uint32","name":"fromBlock","type":"uint32"},{"internalType":"uint224","name":"votes","type":"uint224"}],"internalType":"struct ERC20VotesUpgradeable.Checkpoint","name":"","type":"tuple"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"decimals","outputs":[{"internalType":"uint8","name":"","type":"uint8"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"spender","type":"address"},{"internalType":"uint256","name":"subtractedValue","type":"uint256"}],"name":"decreaseAllowance","outputs":[{"internalType":"bool","name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"delegatee","type":"address"}],"name":"delegate","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"delegatee","type":"address"},{"internalType":"uint256","name":"nonce","type":"uint256"},{"internalType":"uint256","name":"expiry","type":"uint256"},{"internalType":"uint8","name":"v","type":"uint8"},{"internalType":"bytes32","name":"r","type":"bytes32"},{"internalType":"bytes32","name":"s","type":"bytes32"}],"name":"delegateBySig","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"account","type":"address"}],"name":"delegates","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"uint256","name":"blockNumber","type":"uint256"}],"name":"getPastTotalSupply","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"account","type":"address"},{"internalType":"uint256","name":"blockNumber","type":"uint256"}],"name":"getPastVotes","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"account","type":"address"}],"name":"getVotes","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"spender","type":"address"},{"internalType":"uint256","name":"addedValue","type":"uint256"}],"name":"increaseAllowance","outputs":[{"internalType":"bool","name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"_l1TokenAddress","type":"address"},{"internalType":"uint256","name":"_initialSupply","type":"uint256"},{"internalType":"address","name":"_owner","type":"address"}],"name":"initialize","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"l1Address","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"recipient","type":"address"},{"internalType":"uint256","name":"amount","type":"uint256"}],"name":"mint","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"name","outputs":[{"internalType":"string","name":"","type":"string"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"nextMint","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"owner","type":"address"}],"name":"nonces","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"account","type":"address"}],"name":"numCheckpoints","outputs":[{"internalType":"uint32","name":"","type":"uint32"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"owner","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"owner","type":"address"},{"internalType":"address","name":"spender","type":"address"},{"internalType":"uint256","name":"value","type":"uint256"},{"internalType":"uint256","name":"deadline","type":"uint256"},{"internalType":"uint8","name":"v","type":"uint8"},{"internalType":"bytes32","name":"r","type":"bytes32"},{"internalType":"bytes32","name":"s","type":"bytes32"}],"name":"permit","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"renounceOwnership","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"symbol","outputs":[{"internalType":"string","name":"","type":"string"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"totalSupply","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"amount","type":"uint256"}],"name":"transfer","outputs":[{"internalType":"bool","name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"_to","type":"address"},{"internalType":"uint256","name":"_value","type":"uint256"},{"internalType":"bytes","name":"_data","type":"bytes"}],"name":"transferAndCall","outputs":[{"internalType":"bool","name":"success","type":"bool"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"from","type":"address"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"amount","type":"uint256"}],"name":"transferFrom","outputs":[{"internalType":"bool","name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"newOwner","type":"address"}],"name":"transferOwnership","outputs":[],"stateMutability":"nonpayable","type":"function"}]'
            self.abi = arb_contract_abi
        else:
            print('abi 为', abi)
            sys.exit('abi选择错误，请检查')
        self.contract = self.w3.eth.contract(address=self.contract_address, abi=self.abi)
        return self.contract

    def balance(self):
        return self.w3.eth.get_balance(self.wallet) / 1e18

    def balanceOf(self, contract_address, isnft, id = None):
        self.create_contract(contract_address, 'arb_contract') # 生成合约
        if isnft == True:
            return self.contract.functions.balanceOf(self.wallet, id).call()
        return self.contract.functions.balanceOf(self.wallet).call()

    def transfer(self, coin_address, contract_address, coin, to, value, reserve, gas):
        '''进行代币转账
        args：
            to str：接收代币的地址
            value str/int：代币数量，以ether为单位，可以是字符串和int类型
        returns：
            (str, str)：返回交易哈希，以及异常信息
        '''
        try:
            token_balance = self.balanceOf(coin_address, isnft=False) / 1e18
            print(f'{coin} balance =', token_balance)
            # 如果代币不足返回异常
            if (Decimal(token_balance) < Decimal(value)) or (token_balance < 0):
                return '不足'
            # 进行转账代币
            nonce = self.w3.eth.getTransactionCount(self.wallet)
            tx = {
                'from': self.wallet,
                'nonce': nonce,
                'gas': gas,
                'gasPrice': self.w3.eth.gas_price,
                'chainId': self.w3.eth.chain_id
            }
            to = Web3.toChecksumAddress(to)
            if value == 0: # value填0代表直接转账余额
                value = token_balance - reserve
            amount = self.w3.toWei(value, 'ether')
            # 签名交易
            contract = self.create_contract(coin_address, 'arb_contract')
            txn = contract.functions.transfer(to, amount).buildTransaction(tx)
            signed_txn = self.w3.eth.account.sign_transaction(txn, private_key=self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)
            print(f'{coin} 数量: {value} 转账到：{to}')
            return print(self.w3.toHex(tx_hash))
        except (Exception, ValueError) as e:
            if e == "{'code': -32000, 'message': 'invalid transaction: insufficient funds for gas * price + value'}":
                return print(f'手续费不足')
            logging.error(f'转账{coin}代币时发生异常：{e}')
            logging.exception(e)
            return None, str(e)

    def transfer_eth(self, coin, to, value, reserve, gas):
        '''进行eth转账
        args：
            to str：接收以太坊的地址
            value str/int：数量，以ether为单位，可以是字符串和int类型
        returns：
            str：返回交易哈希
        '''
        try:
            token_balance = self.balance()
            print(f'bnb balance =', '%.4f' % token_balance)
            # 如果代币不足返回异常
            if Decimal(token_balance) < Decimal(value):
                return '不足'
            # value填0代表直接转账余额，如果小于0跳过
            if value == 0:
                value = token_balance - reserve
                if value < 0:
                    return '不足'
            # 进行转账代币
            nonce = self.w3.eth.getTransactionCount(self.wallet)
            to = Web3.toChecksumAddress(to)
            tx = {
                'to': to,
                'nonce': nonce,
                'gas': gas,
                'gasPrice': self.w3.eth.gas_price,
                'chainId': self.w3.eth.chain_id,
                'value': self.w3.toWei(value, 'ether')
            }
            # 签名交易
            signed_txn = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)
            print(f'转账到 {to[0]}：{to}')
            return print(self.w3.toHex(tx_hash))
        except Exception as e:
            if e == "{'code': -32000, 'message': 'invalid transaction: insufficient funds for gas * price + value'}":
                return print(f'手续费不足')
            logging.error(f'转账{coin}时发生异常：{e}')
            logging.exception(e)
            return None, str(e)

    def transfer_bnb(self, binance_address, value, reserve, gasless, gasmax):
        """
            1、gaslimit参考：gasless：25000, gasmax：30000
            2、value 为 0 即是账户里的转账余额，不为 0 则转实际的value值
            3、reserve 为转账时预留多少float格式的余额：或用作gas费使用，或打满余额转账可能发生小数后位数太多出错。每个coin情况不同
            """
        to = ['币安', binance_address]
        gas = random.randint(gasless, gasmax)
        transfer = self.transfer_eth('bnb', to[1], value, reserve, gas)
        if transfer == '不足':
            print('bnb 不足')
            return '不足'
        time.sleep(6)
        print('bnb balance =', '%.4f' % self.balance())

    def transfer_op(self, to, value, reserve, gasless, gasmax):
        """
            1、gaslimit参考：gasless：95000, gasmax：100000
            2、value 为 0 即是账户里的转账余额，不为 0 则转实际的value值
            3、reserve 为转账时预留多少float格式的余额：或用作gas费使用，或打满余额转账可能发生小数后位数太多出错。每个coin情况不同
            """
        contract_address = '0x4200000000000000000000000000000000000042'
        gas = random.randint(gasless, gasmax)
        print('eth balance = ', '%.4f' % self.balance())
        transfer = self.transfer(contract_address, 'op', to, value, reserve, gas)
        if transfer == '不足':
            print('op 不足')
            return '不足'
        time.sleep(5)
        print('op balance =', '%.4f' % self.balanceOf(contract_address, isnft=False) / 1e18)

    def transfer_arb(self, to, value, reserve, gasless, gasmax):
        """
            1、gaslimit参考：gasless：95000, gasmax：100000
            2、value 为 0 即是账户里的转账余额，不为 0 则转实际的value值
            3、reserve 为转账时预留多少float格式的余额：或用作gas费使用，或打满余额转账可能发生小数后位数太多出错。每个coin情况不同
            """
        coin_address = '0x912CE59144191C1204E64559FE8253a0e49E6548'
        contract_address = '0xC4ed0A9Ea70d5bCC69f748547650d32cC219D882'
        gas = random.randint(gasless, gasmax)
        print('eth balance = ', '%.4f' % self.balance())
        transfer = self.transfer(coin_address, contract_address, 'arb', to, value, reserve, gas)
        if transfer == '不足':
            print('arb 不足')
            return '不足'
        # time.sleep(5)
        # print('arb balance =', '%.4f' % self.balanceOf(contract_address, isnft=False) / 1e18)

    def withdraw(self, coin, price, dexgas, cexgas):
        """
            1、price：商品价格，gas：该链所有行为完成后所需手续费，cexgas：交易所提币手续费
            """
        payable = price + dexgas + cexgas - self.balance()
        print(f'{coin} need to withdraw = ', '%.5f' % payable)

    def zks_bridge(self,value):
        try:
            contract_address = '0x1908e2BF4a88F91E4eF0DC72f02b8Ea36BEa2319'
            # 生成合约
            contract = self.create_contract(contract_address)

            print('ETH balance = ', '%.3f' % self.balance())

            # 获取 nonce，这个是交易计数
            nonce = self.w3.eth.getTransactionCount(self.wallet)
            value_uint256 = [int(value * 1_000_000_000_000_000_000)]
            _factoryDeps = bytes()

            # goerli链：无须设置 gas, gas price , chainId, 会自动计算并配置为 EIP 1559 类型
            tx_params = {
                'value': self.w3.toWei(value, 'ether'),
                "nonce": nonce,
                # 'gas': 150000,
                # 'gasPrice': w3.toWei(2, 'gwei'),
                # 'maxFeePerGas': w3.toWei(8, 'gwei'),
                # 'maxPriorityFeePerGas': w3.toWei(2, 'gwei'),
                # 'chainId': chainId,
            }
            # 合约交互
            txn = self.contract.functions.requestL2Transaction(self.wallet, value_uint256, 00000000000000000000000000000000000000000000000000000000000000e0, 10000000, 800, '', self.wallet) # deposit,0x0000000000000000000000000000000000000000
            txn1 = txn.buildTransaction(tx_params)
            # 签名交易
            signed_tx = self.w3.eth.account.sign_transaction(txn1, private_key=private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            return print(self.w3.toHex(tx_hash))
        except Exception as e:
            logging.error(f'跨链存入eth时发生异常：{e}')
            logging.exception(e)
            return None,str(e)

    def auto_zks_bridge(self):
        try:
            balance = self.balance()
            print('ETH balance = ','%.3f' % balance)

            # 获取 nonce，这个是交易计数
            nonce = self.w3.eth.getTransactionCount(self.wallet)

            if Decimal(balance) < 0.01:
                return print('gortli eth 不足 0.01')
            value = balance - 0.01
            value_uint256 = int(value * 1_000_000_000_000_000_000)

            # goerli链：无须设置 gas, gas price , chainId, 会自动计算并配置为 EIP 1559 类型
            tx_params = {
                'value': self.w3.toWei(value, 'ether'),
                "nonce": nonce,
                # 'gas': 150000,
                # 'gasPrice': w3.toWei(2, 'gwei'),
                # 'maxFeePerGas': w3.toWei(8, 'gwei'),
                # 'maxPriorityFeePerGas': w3.toWei(2, 'gwei'),
                # 'chainId': chainId,
            }
            # 合约交互
            txn = self.contract.functions.deposit(self.wallet, '0x0000000000000000000000000000000000000000', value_uint256)
            txn1 = txn.buildTransaction(tx_params)
            # 签名交易
            signed_tx = self.w3.eth.account.sign_transaction(txn1, private_key=private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            return print(self.w3.toHex(tx_hash))
        except Exception as e:
            logging.error(f'跨链存入eth时发生异常：{e}')
            logging.exception(e)
            return None,str(e)

    def op_delegate(self, value):
        try:
            print('opETH balance = ', '%.4f' % self.balance())

            # 获取 nonce，这个是交易计数
            nonce = self.w3.eth.getTransactionCount(self.wallet)
            value_uint256 = int(value * 1_000_000_000_000_000_000)

            tx_params = {
                'from': self.wallet,
                'value': self.w3.toWei(value_uint256, 'ether'),
                "nonce": self.w3.eth.chain_id,
                'gas': 50000,
                'gasPrice': self.w3.toWei(0.001, 'gwei'),
                'chainId': self.chainId,
                # op链这两条函数用不到
                # 'maxFeePerGas': self.w3.toWei(5, 'gwei'),
                # 'maxPriorityFeePerGas': self.w3.toWei(5, 'gwei'),
            }
            # 合约交互
            func = self.contract.functions.delegate(self.wallet)
            txn = func.buildTransaction(tx_params)
            # 签名交易
            signed_tx = self.w3.eth.account.sign_transaction(txn, private_key=private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            return print(self.w3.toHex(tx_hash))
        except Exception as e:
            logging.error(f'发生异常：{e}')
            logging.exception(e)
            return None,str(e)

    def mint_space_gificard(self, contract_address, value, gas): # bsc spaceid
        # 生成合约
        contract = self.create_contract(contract_address, 'contract', 'getabi')

        print('bnb balance = ', '%.4f' % self.balance())
        ids_uint256 = [self.w3.toInt(int(2))] # 数组
        amount_uint256 = [self.w3.toInt(int(1))]
        txn = contract.functions.batchRegister(ids_uint256, amount_uint256).buildTransaction({
            "chainId": self.w3.eth.chain_id,
            "from": wallet,
            'value': self.w3.toWei(value, 'ether'),
            'gas': gas,
            "nonce": self.w3.eth.getTransactionCount(self.wallet),
            "gasPrice": self.w3.eth.gas_price
        })
        signed_txn = self.w3.eth.account.sign_transaction(txn, self.private_key)
        txn_hash = self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        return print(self.w3.toHex(txn_hash))

    def Redeem_space_gificard(self, contract_address, gas): # bsc spaceid
        # 生成合约
        contract = self.create_contract(contract_address, 'contract', 'getabi')

        print('bnb balance = ', '%.4f' % self.balance())
        mpIndexes_uint256 = [self.w3.toInt(2)] # 数组
        amount_uint256 = [self.w3.toInt(1)]
        txn = contract.functions.redeem(mpIndexes_uint256, amount_uint256).buildTransaction({
            "chainId": self.w3.eth.chain_id,
            "from": wallet,
            #'value': self.w3.toWei(value, 'ether'),
            'gas': gas,
            "nonce": self.w3.eth.getTransactionCount(self.wallet),
            "gasPrice": self.w3.eth.gas_price
        })
        signed_txn = self.w3.eth.account.sign_transaction(txn, self.private_key)
        txn_hash = self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        return print(self.w3.toHex(txn_hash))

    def Spaceid_mintandredeem_gificard(self, price, needbalace, gasless, gasmax):
        """
            1、gaslimit参考：gasless：110000, gasmax：120000
            2、price为商品价格，needbalace为加上手续费所需的余额
            """
        try:
            # 当前钱包地址联网
            # if self.w3.isConnected() == False:
            #     print('出现网络错误，重试中')
            #     time.sleep(5)
            #     return
            gas = random.randint(gasless, gasmax)

            # 查询是否符合交互条件
            if self.balance() < needbalace:
                print('bnb balance = ', '%.4f' % self.balance())
                print('bnb不足')
                return

            # 交互且输出结果
            self.mint_space_gificard(contract_address='0xa27445b254b79ee2e89071f2c7d3cefbeb365dfd', value=price,
                                    gas=gas)
            time.sleep(5)

            # 查询是否符合交互条件
            nft_contract_address = '0xA919CbBd647f0348c12ef409e7F6D4AB8436cF77'  # spaceid gift_card nft
            nftnumber = self.balanceOf(nft_contract_address, isnft=True, id=2)
            print('nft number = ', nftnumber)
            if nftnumber == 0:
                print('Spaceid giftnft unmint')

            # 交互且输出结果
            self.Redeem_space_gificard(contract_address='0x7b13756870e4f29482c9519101d916150f5d2390',
                                      gas=gas)  # Spaceid register
            time.sleep(5)
            print('nft number = ', self.balanceOf(nft_contract_address, isnft=True, id=2))
        except requests.exceptions.SSLError:
            print(ads_zh, '出现网络错误，重试中')
            time.sleep(2)

    def commit(self, contract_address, gas): # bsc spaceid
        # 生成合约
        contract = self.create_contract(contract_address, 'contract', 'getabi')
        # secret = '0xDf4bEE40ff896a7dc365ffA377710482dA37d1DD'
        # secret = self.w3.keccak(text='0x7A18768EdB2619e73c4d5067B90Fd84a71993C1D')
        # print(secret)
        # print(self.w3.toHex(secret))

        txn = contract.functions.makeCommitmentWithConfig(
            'bfundac',
            #self.wallet,
            Web3.toChecksumAddress('xxxxxxxxxxxxxxxx'),
            0x732f01e7805329c3f5e9a8b4ee3b77197c7ff2ebef10eec3bfc31838d2265770,
            '0x7A18768EdB2619e73c4d5067B90Fd84a71993C1D',
            #self.wallet
            Web3.toChecksumAddress('xxxxxxxxxxxxxxxx')
        ).call()
        #     buildTransaction(
        #     {
        #     "chainId": self.w3.eth.chain_id,
        #     "from": wallet,
        #     #'value': self.w3.toWei(value, 'ether'),
        #     'gas': gas,
        #     "nonce": self.w3.eth.getTransactionCount(self.wallet),
        #     "gasPrice": self.w3.eth.gas_price
        # })
        signed_txn = self.w3.eth.account.sign_transaction(txn, self.private_key)
        txn_hash = self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        return print(self.w3.toHex(txn_hash))

    def arb_claimableTokens(self, contract_address):
        abi = '[{"inputs":[{"internalType":"contract IERC20VotesUpgradeable","name":"_token","type":"address"},{"internalType":"address payable","name":"_sweepReceiver","type":"address"},{"internalType":"address","name":"_owner","type":"address"},{"internalType":"uint256","name":"_claimPeriodStart","type":"uint256"},{"internalType":"uint256","name":"_claimPeriodEnd","type":"uint256"},{"internalType":"address","name":"delegateTo","type":"address"}],"stateMutability":"nonpayable","type":"constructor"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"recipient","type":"address"},{"indexed":false,"internalType":"uint256","name":"amount","type":"uint256"}],"name":"CanClaim","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"recipient","type":"address"},{"indexed":false,"internalType":"uint256","name":"amount","type":"uint256"}],"name":"HasClaimed","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"previousOwner","type":"address"},{"indexed":true,"internalType":"address","name":"newOwner","type":"address"}],"name":"OwnershipTransferred","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"newSweepReceiver","type":"address"}],"name":"SweepReceiverSet","type":"event"},{"anonymous":false,"inputs":[{"indexed":false,"internalType":"uint256","name":"amount","type":"uint256"}],"name":"Swept","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"recipient","type":"address"},{"indexed":false,"internalType":"uint256","name":"amount","type":"uint256"}],"name":"Withdrawal","type":"event"},{"inputs":[],"name":"claim","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"delegatee","type":"address"},{"internalType":"uint256","name":"expiry","type":"uint256"},{"internalType":"uint8","name":"v","type":"uint8"},{"internalType":"bytes32","name":"r","type":"bytes32"},{"internalType":"bytes32","name":"s","type":"bytes32"}],"name":"claimAndDelegate","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"claimPeriodEnd","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"claimPeriodStart","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"","type":"address"}],"name":"claimableTokens","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"owner","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"renounceOwnership","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address[]","name":"_recipients","type":"address[]"},{"internalType":"uint256[]","name":"_claimableAmount","type":"uint256[]"}],"name":"setRecipients","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address payable","name":"_sweepReceiver","type":"address"}],"name":"setSweepReciever","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"sweep","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"sweepReceiver","outputs":[{"internalType":"address payable","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"token","outputs":[{"internalType":"contract IERC20VotesUpgradeable","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"totalClaimable","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"newOwner","type":"address"}],"name":"transferOwnership","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"uint256","name":"amount","type":"uint256"}],"name":"withdraw","outputs":[],"stateMutability":"nonpayable","type":"function"}]'
        contract = self.create_contract(contract_address, abi)

        claimable_tokens_uint256 = contract.functions.claimableTokens(self.wallet).call()
        if claimable_tokens_uint256 == 0:
            return 0
        claimable_tokens = claimable_tokens_uint256 / 10**18
        print(claimable_tokens)
        arb_claim_tokens[ads_zh] = [claimable_tokens_uint256, claimable_tokens]
        return claimable_tokens

    def arb_claim(self, contract_address, gasless, gasmax):
        '''
        用来估算gas花费、或者用来试探合约该调用开始了没
        estimated_gas = contract.functions.claim().estimateGas(tx_params)
        print(estimated_gas)
        '''

        contract = self.create_contract(contract_address, 'arb_claim')

        print('eth balance = ', '%.4f' % self.balance())
        gas = random.randint(gasless, gasmax)
        tx_params = {
            'chainId': self.w3.eth.chain_id,
            "nonce": self.w3.eth.getTransactionCount(self.wallet),
            'gas': gas,
            'gasPrice': self.w3.eth.gas_price,
            'from': self.wallet,
            'value': self.w3.toWei(0, 'ether'),
        }
        # 建立交易与签名
        txn = contract.functions.claim().buildTransaction(tx_params)
        signed_txn = self.w3.eth.account.sign_transaction(txn, self.private_key)
        txn_hash = self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        return print(self.w3.toHex(txn_hash))

    def estimated_gas(self, contract_address, gasless, gasmax):
        contract = self.create_contract(contract_address, 'arb_claim')
        gas = random.randint(gasless, gasmax)
        tx_params = {
            'chainId': self.w3.eth.chain_id,
            "nonce": self.w3.eth.getTransactionCount(self.wallet),
            'gas': gas,
            'gasPrice': self.w3.eth.gas_price,
            'from': self.wallet,
            'value': self.w3.toWei(0, 'ether'),
        }
        estimated_gas = contract.functions.claim().estimateGas(tx_params)
        print(estimated_gas)


class zks2net(object):

    def __init__(self, contract_address, private_key, abi_path: Path):

        # 设置zks2.0
        ZKSYNC_NETWORK_URL: str = 'https://zkSync2-testnet.zkSync.dev'
        self.zks2_w3 = ZkSyncBuilder.build(ZKSYNC_NETWORK_URL)
        self.zks = ZkSync(self.zks2_w3)
        self.web3 = web3
        # token合约地址
        self.contract_address = Web3.toChecksumAddress(contract_address)
        # 主钱包地址
        self.account: LocalAccount = Account.from_key(private_key)
        self.wallet = self.account.address
        # 钱包的私钥
        self.wallet_key = private_key
        # 合约的abi    self.abi = json.loads(f.read())
        self.abi = '[{"inputs":[{"internalType":"address","name":"_l2Receiver","type":"address"},{"internalType":"address","name":"_l1Token","type":"address"},{"internalType":"uint256","name":"_amount","type":"uint256"}],"name":"deposit","outputs":[{"internalType":"bytes32","name":"txHash","type":"bytes32"}],"stateMutability":"payable","type":"function"}]'
        # '[{"inputs":[{"internalType":"uint256","name":"_amount","type":"uint256"},{"internalType":"address","name":"_zkSyncAddress","type":"address"},{"internalType":"enum Operations.QueueType","name":"_queueType","type":"uint8"},{"internalType":"enum Operations.OpTree","name":"_opTree","type":"uint8"}],"name":"depositETH","outputs":[],"stateMutability":"payable","type":"function"},{"inputs":[],"name":"emergencyFreezeDiamond","outputs":[],"stateMutability":"nonpayable","type":"function"}]'
        # Deposit ETH ABI
        # 生成合约
        self.counter_contract = self.web3.eth.contract(abi=get_abi(abi_path))
        self.contract = self.zks2_w3.eth.contract(address=self.contract_address, abi=self.abi)
        # 代币简写
        self.token_name = 'USDT'
        # 登录成功提示
        print()
        print("——————————————————————————————")
        print(ads_zh, self.wallet)

    def encode_method(self, fn_name, args: list) -> HexStr:
        return self.counter_contract.encodeABI(fn_name, args)

    def balance(self):
        return self.zks2_w3.eth.get_balance(self.wallet) / 1e18

    def withdraw(self, value):
        balance = self.balance()
        print('zks2.0 ETH = ', '%.3f' % balance)

        chain_id = self.zks.chain_id
        signer = PrivateKeyEthSigner(self.account, chain_id)
        ETH_TOKEN = Token.create_eth()

        nonce = self.zks.get_transaction_count(self.wallet, ZkBlockParams.COMMITTED.value)
        bridges: BridgeAddresses = self.zks.zks_get_bridge_contracts()

        l2_func_encoder = L2BridgeEncoder(self.zks2_w3)
        call_data = l2_func_encoder.encode_function(fn_name="withdraw", args=[
            self.wallet,
            ETH_TOKEN.l2_address,
            ETH_TOKEN.to_int(Decimal(f"{value}"))
        ])

        tx = create_function_call_transaction(from_=self.wallet,
                                              to=bridges.l2_eth_default_bridge,
                                              ergs_limit=0,
                                              ergs_price=0,
                                              data=HexStr(call_data))
        estimate_gas = self.zks.eth_estimate_gas(tx)
        gas_price = self.zks.gas_price

        tx_712 = Transaction712(chain_id=chain_id,
                                nonce=nonce,
                                gas_limit=int(estimate_gas),
                                to=tx["to"],
                                value=tx["value"],
                                data=tx["data"],
                                maxPriorityFeePerGas=100000000,
                                maxFeePerGas=gas_price,
                                from_=self.wallet,
                                meta=tx["eip712Meta"])

        singed_message = signer.sign_typed_data(tx_712.to_eip712_struct())
        msg = tx_712.encode(singed_message)
        tx_hash = self.zks.send_raw_transaction(msg)
        tx_receipt = self.zks.wait_for_transaction_receipt(tx_hash, timeout=240, poll_latency=0.5)
        print(f"tx status: {tx_receipt['status']},{tx_receipt}")

    def auto_withdraw(self):
        balance = self.balance()
        print('zks2.0 ETH = ', '%.3f' % balance)

        chain_id = self.zks.chain_id
        signer = PrivateKeyEthSigner(self.account, chain_id)
        ETH_TOKEN = Token.create_eth()

        if Decimal(balance) < 0.005:
            return print('zks2.0 eth 不足 0.005')
        value = balance - 0.002

        nonce = self.zks.get_transaction_count(self.wallet, ZkBlockParams.COMMITTED.value)
        bridges: BridgeAddresses = self.zks.zks_get_bridge_contracts()

        l2_func_encoder = L2BridgeEncoder(self.zks2_w3)
        call_data = l2_func_encoder.encode_function(fn_name="withdraw", args=[
            self.wallet,
            ETH_TOKEN.l2_address,
            ETH_TOKEN.to_int(Decimal(f"{value}"))
        ])

        tx = create_function_call_transaction(from_=self.wallet,
                                              to=bridges.l2_eth_default_bridge,
                                              ergs_limit=0,
                                              ergs_price=0,
                                              data=HexStr(call_data))
        estimate_gas = self.zks.eth_estimate_gas(tx)
        gas_price = self.zks.gas_price

        tx_712 = Transaction712(chain_id=chain_id,
                                nonce=nonce,
                                gas_limit=int(estimate_gas),
                                to=tx["to"],
                                value=tx["value"],
                                data=tx["data"],
                                maxPriorityFeePerGas=100000000,
                                maxFeePerGas=gas_price,
                                from_=self.wallet,
                                meta=tx["eip712Meta"])

        singed_message = signer.sign_typed_data(tx_712.to_eip712_struct())
        msg = tx_712.encode(singed_message)
        tx_hash = self.zks.send_raw_transaction(msg)
        tx_receipt = self.zks.wait_for_transaction_receipt(tx_hash, timeout=240, poll_latency=0.5)
        print(f"tx status: {tx_receipt['status']},{tx_receipt}")



if __name__ == "__main__":

    task_file = "xxxxxxxxxxxxxxxx"
    result_file = "xxxxxxxxxxxxxxxx"
    source_id = 'xxxxxxxxxxxxxxxx'
    source_data = "xxxxxxxxxxxxxxxx"
    source_data2 = "xxxxxxxxxxxxxxxx"
    initial = get_taskads(task_file,result_file, source_id, source_data, source_data2)
    taskads = initial[0]
    data = initial[1]
    adsid = initial[2]
    data_frame2 = initial[3]
    bnbapikey = 'xxxxxxxxxxxxxxxx'

    count = 0
    arb_claim_tokens = {}
    gasless = 3000000
    gasmax = 4000000
    reserve = random.randint(2, 8)

    to1 = ['DA1','DA2','R1','R2','BU','RUAN']
    to2 = ['A9','A10','A11','A12','R9','R10']
    to_dd = 'xxxxxxxxxxxxxxxx'
    to_A8 = 'xxxxxxxxxxxxxxxx'


    for ads_zh in taskads:
        current_task = data.loc[ads_zh]
        wallet = current_task["address"]
        private_key = current_task["pri"]

        arb = net('arb', wallet, private_key)
        # chaxun_tokens = arb.arb_claimableTokens('0x67a24CE4321aB3aF51c2D0a4801c3E111D88C9d9', gasless, gasmax)
        arb.arb_claim('0x67a24CE4321aB3aF51c2D0a4801c3E111D88C9d9', gasless, gasmax)

    print('———————————————————— 转账 ——————————————————')
    time.sleep(5)

    for ads_zh in taskads:
        current_task = data.loc[ads_zh]
        wallet = current_task["address"]
        private_key = current_task["pri"]

        arb = net('arb', wallet, private_key)
        if ads_zh in to1:
            arb.transfer_arb(to_dd, 0, reserve, gasless, gasmax)
        if ads_zh in to2:
            arb.transfer_arb(to_A8, 0, reserve, gasless, gasmax)

    print('———————————————————— 转账结束后查询 ——————————————————')
    time.sleep(5)

    for ads_zh in taskads:
        current_task = data.loc[ads_zh]
        wallet = current_task["address"]
        private_key = current_task["pri"]

        arb = net('arb', wallet, private_key)
        arb_balance = arb.balanceOf(contract_address='0x912CE59144191C1204E64559FE8253a0e49E6548',isnft=False)
        print('arb balance = ', arb_balance / 1e18)



'''
——

op = net('op', wallet, private_key)
arb = net('arb', wallet, private_key)
bnb = net('bsc', wallet, private_key, bnbapikey)
goerli = net('goerli', wallet, private_key)
balance = op.balance()

balance = bnb.balance()
time.sleep(5)
print('bnb balance = ', '%.4f' % balance)

——

estimated_gas = self.w3.eth.estimateGas(tx_params) # 估算gas使用量
print('预计gas使用量: {}'.format(estimated_gas))

gas_cost_wei = estimated_gas * tx_params['gasPrice'] # 计算所需的gas费用

gas_cost_eth = Decimal(gas_cost_wei) / Decimal('1000000000000000000')
print('预计手续费 eth: {:.6f}'.format(gas_cost_eth))
gas_cost_usdt = gas_cost_eth * 1740
print('预计手续费 usdt: {:.6f}'.format(gas_cost_usdt))

——

'''

# "0xc24215226336d22238a20a72f8e489c005b44c4a" # zks2.0 跨链桥合约
# ethop = net('op', contract_address,wallet,private_key)
# ethop.op_delegate(0)

# zks2 = zks2net(contract_address,private_key)
# zks2.withdraw('0.01')
# zks2.auto_withdraw()

# eth = net('mainnet', contract_address,wallet,private_key)
# balance_e = eth.balance()
# balance_e_u = balance_e * 1320
# if balance_e_u > 2:
#     ethlist.append(ads_zh)
#     print('ETH = ', '%.5f' % balance_e, 'ETH_U = ', balance_e_u)

# bridgezks.auto_zks_bridge()

'''
Web3.sha3(text)：将字符串转换为 uint256 类型的哈希值。
Web3.soliditySha3(*args)：将传入的参数转换为 uint256 类型的哈希值，参数可以是整数、字符串或列表。
Web3.eth.getBlock(block_identifier)：返回一个区块对象，其中包含多个 uint256 类型的属性，如 block number、gas limit、timestamp 等。
'''


