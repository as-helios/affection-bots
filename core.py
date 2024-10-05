import json
import logging
import math
import os
import random
import sys
import time
import asyncio
from json import JSONDecodeError
from logging.handlers import TimedRotatingFileHandler
from statistics import median, mean, mode

import requests
from dotenv import load_dotenv
from requests import RequestException
from web3 import Web3
from web3.exceptions import BlockNotFound, Web3Exception, Web3ValidationError
from web3_multi_provider import MultiProvider

load_dotenv()
for package in ('web3', 'web3_multi_provider', 'urllib3',):
    logging.getLogger(package).setLevel(logging.ERROR)

web3 = Web3(MultiProvider(json.load(open('./data/rpc_servers.json'))))

gas_multiplier = float(os.getenv('GAS_MULTIPLIER'))
rapid_gas_fee_limit = int(os.getenv('GAS_FEE_RAPID_LIMIT'))
gas_cache_seconds = int(os.getenv('GAS_CACHE_SECONDS'))
wallet_a_address = os.getenv('WALLET_A_ADDRESS')
wallet_b_address = os.getenv('WALLET_B_ADDRESS')
wallet_c_address = os.getenv('WALLET_C_ADDRESS')

def apply_estimated_gas(tx, attempts=18):
    while attempts > 0:
        try:
            if 'gas' not in tx:
                tx['gas'] = web3.eth.estimate_gas(tx)
        except Exception as e:
            logging.debug(e)
            attempts -= 1
            time.sleep(1)
        else:
            return tx


def apply_gas_multiplier(tx, multiplier=None):
    if not multiplier:
        multiplier = os.getenv('GAS_MULTIPLIER')
    try:
        multiplier = float(multiplier)
    except ValueError:
        raise ValueError("Invalid float for GAS_MULTIPLIER")
    else:
        tx['gas'] = int(tx['gas'] * multiplier)
        if 'maxFeePerGas' in tx:
            tx['maxFeePerGas'] = int(tx['maxFeePerGas'] * multiplier)
        return tx


def apply_median_gas_strategy(tx, tx_amount=100):
    median_gas_price = get_average_gas_prices('median', tx_amount)['gas_price']
    tx['maxFeePerGas'] = int(web3.to_wei(median_gas_price, 'wei'))
    tx['maxPriorityFeePerGas'] = web3.to_wei(500, 'gwei')
    return tx


def approve_token_spending(account, token_address, spender_address, amount, attempts=18):
    token_contract = load_contract(token_address)
    token_info = get_token_info(token_address)
    token_amount = to_token_decimals(amount, token_info['decimals'])
    if token_contract.functions.allowance(account.address, spender_address).call() < token_amount:
        try:
            tx = token_contract.functions.approve(spender_address, token_amount).build_transaction({
                'nonce': get_nonce(account.address),
                'from': account.address
            })
            return broadcast_transaction(account, tx, True, attempts)
        except Exception as e:
            if error := interpret_exception_message(e):
                logging.error("{}. Failed to approve {} ({})".format(error, token_info['name'], token_info['symbol']))
            return False


def broadcast_transaction(account, tx, auto_gas=True, attempts=18):
    tx_hash = None
    tx['chainId'] = 369
    if not auto_gas:
        tx = apply_estimated_gas(tx)
        tx = apply_median_gas_strategy(tx)
        tx = apply_gas_multiplier(tx)
    logging.debug("Broadcasting TX: {}".format(tx))
    _attempts = attempts
    while _attempts > 0:
        try:
            signed_tx = web3.eth.account.sign_transaction(tx, private_key=account.key)
            tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        except Exception as e:
            logging.debug(e)
            if "insufficient funds" in str(e):
                logging.error("Not enough gas for this TX: {}".format(tx))
                return False
            elif "nonce too low" in str(e):
                tx['nonce'] = get_nonce(account.address)
                continue
            elif "could not replace existing tx" in str(e):
                tx['gas'] = int(tx['gas'] * 1.0369)
                if 'maxFeePerGas' in tx:
                    tx['maxFeePerGas'] = int(tx['maxFeePerGas'] * 1.0369)
                if 'maxPriorityFeePerGas' in tx:
                    tx['maxPriorityFeePerGas'] = int(tx['maxPriorityFeePerGas'] * 1.0369)
                continue
            elif "already known" in str(e):
                pass
            else:
                _attempts -= 1
                time.sleep(1)
        if not tx_hash:
            _attempts -= 1
            time.sleep(1)
            if _attempts != 0:
                logging.debug("Rebroadcasting TX ... {}".format(attempts - _attempts))
            continue
        else:
            try:
                tx_receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=10)
            except Exception as e:
                logging.debug(e)
                _attempts -= 1
                time.sleep(1)
                if _attempts != 0:
                    logging.debug("Rebroadcasting TX ... {}".format(attempts - _attempts))
            else:
                logging.debug("Confirmed TX: {}".format(tx_receipt))
                return tx_receipt
    return False


def convert_tokens(account, token0_address, token1_address, output_amount, attempts=18):
    # check if conversion route exists
    routes_functions = json.load(open('./data/routes.json'))
    if token0_address not in routes_functions[token1_address]['functions'].keys():
        raise Exception("Route not available for {} to {}".format(token0_address, token1_address))

    # get the cost required to convert tokens
    cost = routes_functions[token1_address]['costs'][token0_address]
    tokens_required = cost * output_amount
    if (tokens_balance := get_token_balance(token0_address, account.address)) < tokens_required:
        logging.error("Need {} more tokens".format(tokens_required - tokens_balance))
        return False

    # call the buy function with amount or default to no args
    call_function = routes_functions[token1_address]['functions'][token0_address]
    approve_token_spending(account, token0_address, token1_address, get_token_supply(token0_address, True))
    token1_contract = load_contract(token1_address, load_contract_abi(token1_address))
    amount = to_token_decimals(output_amount, token1_contract.functions.decimals().call())
    try:
        tx = getattr(token1_contract.functions, call_function)(int(amount)).build_transaction({
            "from": account.address,
            "nonce": get_nonce(account.address)
        })
    except Web3ValidationError as e:
        if 'positional arguments with type(s) `int`' in str(e):
            for i in range(0, amount):
                # cancel the rest of this loop if the gas price is too damn high
                if get_mempool_gas_prices('rapid', gas_cache_seconds) > rapid_gas_fee_limit:
                    logging.warning("Gas fees are too high")
                    return None
                try:
                    tx = getattr(token1_contract.functions, call_function)().build_transaction({
                        "from": account.address,
                        "nonce": get_nonce(account.address)
                    })
                    success = broadcast_transaction(account, tx, True, attempts)
                except Exception as e:
                    if error := interpret_exception_message(e):
                        logging.error(
                            "{}. Failed to convert using {}".format(error, routes_functions[token1_address]['label']))
                else:
                    if success:
                        logging.info("Called {}({}) from {}".format(
                            call_function,
                            amount,
                            routes_functions[token1_address]['label']
                        ))
                    else:
                        logging.warning("Failed to call {}({}) from {}".format(
                            call_function,
                            amount,
                            routes_functions[token1_address]['label']
                        ))
                        return False
        else:
            raise Web3ValidationError(e)
        return True
    else:
        try:
            success = broadcast_transaction(account, tx, True, attempts)
        except Exception as e:
            if error := interpret_exception_message(e):
                logging.error("{}. Failed to convert using {}".format(error, routes_functions[token1_address]['label']))
            return False
        else:
            if success:
                logging.info("Called {}({}) from {}".format(
                    call_function,
                    amount,
                    routes_functions[token1_address]['label']
                ))
                return True
            else:
                logging.warning("Failed to call {}({}) from {}".format(
                    call_function,
                    amount,
                    routes_functions[token1_address]['label']
                ))
                return False


def convert_tokens_multi(account, multi_address, token0_address, token1_address, iterations, attempts=18):
    # check if conversion route exists or is disabled
    routes_functions = json.load(open('./data/routes.json'))
    if token0_address not in routes_functions[multi_address]['functions'].keys():
        raise Exception("Route not available for {} to {} in {}".format(token0_address, token1_address, multi_address))
    elif routes_functions[multi_address]['functions'][token0_address][0] == '#':
        raise Exception("Route is disabled for {} to {} in {}".format(token0_address, token1_address, multi_address))

    # get the cost required to convert tokens
    cost = routes_functions[multi_address]['costs'][token0_address]
    mints = routes_functions[multi_address]['mints'] or 1
    tokens_cost = cost * iterations * mints
    tokens_required = round(tokens_cost, 15)

    # check if the wallet has enough tokens to convert
    if tokens_required > (tokens_balance := get_token_balance(token0_address, account.address)):
        logging.error("Need {} more tokens".format(tokens_required - tokens_balance))
        return False
    # approve the tokens required to convert and determine how many loops
    approve_token_spending(account, token0_address, multi_address, get_token_supply(token0_address, True))
    loops = math.floor(iterations / routes_functions[multi_address]['max_iterations'])
    if iterations % routes_functions[multi_address]['max_iterations'] != 0:
        loops += 1
    # start calling multi mints
    for i in list(range(0, loops)):
        # cancel the rest of this loop if the gas price is too damn high
        if get_mempool_gas_prices('rapid', gas_cache_seconds) > rapid_gas_fee_limit:
            logging.warning("Gas fees are too high")
            return None
        if i + 1 < loops or iterations % routes_functions[multi_address]['max_iterations'] == 0:
            # do max iterations during loop
            call_iterations = routes_functions[multi_address]['max_iterations']
        else:
            # on final loop run the remaining iterations
            call_iterations = iterations % routes_functions[multi_address]['max_iterations']
        # call the multi mint function with iterations based on tokens minted
        call_function = routes_functions[multi_address]['functions'][token0_address]
        multi_contract = load_contract(multi_address, load_contract_abi(multi_address))
        try:
            tx = getattr(multi_contract.functions, call_function)(call_iterations).build_transaction({
                "from": account.address,
                "nonce": get_nonce(account.address)
            })
            success = broadcast_transaction(account, tx, True, attempts)
        except Exception as e:
            if error := interpret_exception_message(e):
                logging.error("{}. Failed to convert using {}".format(error, routes_functions[multi_address]['label']))
        else:
            if success:
                logging.info("Called {}({}) from {}".format(
                    call_function,
                    call_iterations,
                    routes_functions[multi_address]['label']
                ))
            else:
                logging.warning("Failed to call {}({}) from {}".format(
                    call_function,
                    call_iterations,
                    routes_functions[multi_address]['label']
                ))
                return False
    return True


def estimate_swap_result(router_name, token0_address, token1_address, token0_amount, attempts=18):
    routers = json.load(open('./data/routers.json'))
    router_contract = load_contract(routers[router_name][0], routers[router_name][1])
    token0_info = get_token_info(token0_address)
    while attempts > 0:
        try:
            expected_output_amounts = router_contract.functions.getAmountsOut(
                int(token0_amount * 10 ** token0_info['decimals']),
                [token0_address, token1_address]
            ).call()
        except Exception as e:
            logging.debug(e)
            attempts -= 1
            time.sleep(1)
        else:
            return expected_output_amounts
    return []


def from_token_decimals(amount, decimals):
    return amount / 10 ** decimals


def generate_wallet(amount):
    addresses = []
    for i in list(range(0, amount)):
        account = Web3().eth.account.create()
        keystore = Web3().eth.account.encrypt(account.key.hex(), os.getenv('SECRET'))
        folder = "./data/wallets/{}".format(account.address)
        os.makedirs("data/wallets", exist_ok=True)
        os.makedirs(folder, exist_ok=True)
        open("{}/keystore".format(folder), 'w').write(json.dumps(keystore, indent=4))
        addresses.append(account)
    return addresses


def get_abi_from_blockscout(address, attempts=18):
    while attempts > 0:
        try:
            r = requests.get("https://api.scan.pulsechain.com/api/v2/smart-contracts/{}".format(address))
            r.raise_for_status()
        except RequestException:
            attempts -= 1
            if attempts > 0:
                time.sleep(1)
                continue
            else:
                raise RequestException
        else:
            resp = r.json()
            if 'abi' in resp.keys():
                return resp['abi']
            else:
                return []


def get_average_gas_prices(average='median', tx_amount=100, attempts=18):
    if not (latest_block := get_block('latest', False, attempts)):
        return {}
    else:
        latest_block = latest_block['number']
    gas_limit = []
    gas_prices = []
    for block_number in range(latest_block, latest_block - tx_amount, -1):
        if not (block := get_block(block_number, True)):
            return {}
        for _tx in block['transactions']:
            gas_limit.append(_tx['gas'])
            gas_prices.append(_tx['gasPrice'])
        if len(gas_prices) >= tx_amount:
            break
    match average:
        case 'mean':
            average_gas_limit = mean(gas_limit[:tx_amount])
            average_gas_price = mean(gas_prices[:tx_amount])
        case 'median':
            average_gas_limit = median(gas_limit[:tx_amount])
            average_gas_price = median(gas_prices[:tx_amount])
        case 'mode':
            average_gas_limit = mode(gas_limit[:tx_amount])
            average_gas_price = mode(gas_prices[:tx_amount])
        case _:
            raise Exception('Invalid average type')
    return {
        "gas_limit": average_gas_limit,
        "gas_price": average_gas_price
    }



async def estimate_mempool_gas_prices():
    pending = web3.eth.get_block('pending', full_transactions=True)
    gas_prices = []
    for tx in pending['transactions']:
        if 'maxFeePerGas' in tx:
            gas_prices.append(web3.from_wei(tx['maxFeePerGas'], 'gwei'))
        elif 'gasPrice' in tx:
            gas_prices.append(web3.from_wei(tx['gasPrice'], 'gwei'))
    if not gas_prices:
        return None
    gas_prices.sort()
    very_slow = gas_prices[int(len(gas_prices) * 0.1)]  # 10th percentile
    slow = gas_prices[int(len(gas_prices) * 0.25)]  # 25th percentile
    standard = gas_prices[int(len(gas_prices) * 0.5)]  # 50th percentile (median)
    fast = gas_prices[int(len(gas_prices) * 0.70)]  # 70th percentile
    rapid = gas_prices[int(len(gas_prices) * 0.80)]  # 80th percentile
    instant = gas_prices[int(len(gas_prices) * 0.90)]  # 90th percentile
    return {
        'very_slow': float(round(very_slow, 2)),
        'slow': float(round(slow, 2)),
        'standard': float(round(standard, 2)),
        'fast': float(round(fast, 2)),
        'rapid': float(round(rapid, 2)),
        'instant': float(round(instant, 2)),
        'avg': float(round(mean(gas_prices), 2)),
        'median': float(round(median(gas_prices), 2)),
        'lowest': float(round(min(gas_prices), 2)),
        'highest': float(round(max(gas_prices), 2)),
        'tx_count': len(gas_prices),
        'timestamp': time.time()
    }

def get_mempool_gas_prices(speed=None, cache_interval_seconds=10):
    speeds = ('rapid', 'fast', 'standard', 'slow',)
    os.makedirs(cache_folder := './data/cache/', exist_ok=True)
    gas = {}
    gas_file = "{}/mempool_gas.json".format(cache_folder)

    try:
        gas = json.load(open(gas_file))
    except (JSONDecodeError, FileNotFoundError):
        pass
    if not gas or not gas['timestamp'] or (gas['timestamp'] + cache_interval_seconds < time.time()):
        try:
            _gas = asyncio.run(estimate_mempool_gas_prices())
        except Exception as e:
            if not gas:
                logging.debug(e)
                return 5555 * 10 ** 369
        else:
            if not _gas and not gas:
                logging.debug("No gas data")
                return 5555 * 10 ** 369
            elif _gas:
                gas = _gas
                open(gas_file, 'w').write(json.dumps(gas, indent=4))
    if type(speed) is str:
        try:
            return float(gas[speed])
        except KeyError:
            raise KeyError("No such speed as '{}' in gas price data {}".format(speed, list(speeds)))
    return {speed: float(price) for speed, price in gas.items() if speed in speeds}


def get_block(number, full_transactions=False, attempts=18):
    if type(number) is str and number not in ('latest',) and type(number) is not int:
        raise ValueError("Invalid block number")
    while attempts > 0:
        try:
            return web3.eth.get_block(number, full_transactions=full_transactions)
        except Exception as e:
            logging.debug(e)
            time.sleep(1)
            attempts -= 1
    return None


def get_last_block_base_fee(attempts=18):
    if latest_block := get_block('latest', False, attempts):
        base_fee = latest_block['baseFeePerGas']
        return float(round(web3.from_wei(base_fee, 'gwei'), 2))
    else:
        return -1


def get_nonce(address, attempts=18):
    while attempts > 0:
        try:
            return web3.eth.get_transaction_count(web3.to_checksum_address(address))
        except Exception as e:
            logging.debug(e)
            time.sleep(1)
            attempts -= 1
    return -1


def get_pls_balance(address, decimals=False, attempts=18):
    while attempts > 0:
        try:
            balance = web3.eth.get_balance(address)
        except Exception as e:
            logging.debug(e)
            time.sleep(1)
            attempts -= 1
        else:
            if decimals:
                return balance
            else:
                return from_token_decimals(balance, 18)
    return -1


def get_token_balance(token_address, wallet_address, decimals=False):
    token_contract = load_contract(token_address)
    token_info = get_token_info(token_address)
    token_balance = token_contract.functions.balanceOf(wallet_address).call()
    if decimals:
        return token_balance
    else:
        return float(round(from_token_decimals(token_balance, token_info['decimals']), 15))


def get_token_info(token_address, attempts=18):
    os.makedirs(token_folder := "./data/tokens".format(token_address), exist_ok=True)
    token_info_file = "{}/{}.json".format(token_folder, token_address)
    if os.path.isfile(token_info_file):
        token_info = json.load(open(token_info_file))
        if token_info['decimals'] is not None:
            return token_info
    token_name, token_symbol, token_decimals = None, None, None
    token_contract = load_contract(token_address)
    _attempts = attempts
    while _attempts > 0:
        try:
            token_name = token_contract.functions.name().call()
        except Web3Exception:
            _attempts -= 1
            continue
        else:
            break
    _attempts = attempts
    while _attempts > 0:
        try:
            token_symbol = token_contract.functions.symbol().call()
        except Web3Exception:
            _attempts -= 1
            continue
        else:
            break
    _attempts = attempts
    while _attempts > 0:
        try:
            token_decimals = token_contract.functions.decimals().call()
        except Web3Exception:
            _attempts -= 1
            continue
        else:
            break
    token_info = {"name": token_name, "symbol": token_symbol, "decimals": token_decimals}
    open(token_info_file, 'w').write(json.dumps(token_info, indent=4))
    return token_info


def get_token_supply(token_address, decimals=False):
    token_contract = load_contract(token_address)
    token_info = get_token_info(token_address)
    token_supply = token_contract.functions.totalSupply().call()
    if decimals:
        return token_supply
    else:
        return float(round(from_token_decimals(token_supply, token_info['decimals']), 15))


def interpret_exception_message(e):
    logging.debug(e)
    if 'insufficient funds for gas * price + value' in str(e):
        return 'Not enough PLS'
    elif 'transfer amount exceeds balance' in str(e):
        return 'Not enough tokens'
    return e


def load_contract(address, abi=None):
    if not abi:
        abi = load_contract_abi(address)
    if not abi:
        abi = json.load(open('./data/abi/ERC20.json'))
    return web3.eth.contract(address=address, abi=abi)


def load_contract_abi(address):
    try:
        abi = json.load(open("./data/abi/{}.json".format(address)))
    except FileNotFoundError:
        try:
            abi = get_abi_from_blockscout(address)
        except Exception as e:
            logging.debug(e)
            raise FileNotFoundError("Download a copy of the abi from Blockscout to this folder")
        else:
            if abi:
                open("./data/abi/{}.json".format(address), 'w').write(json.dumps(abi, indent=4))
            else:
                raise FileNotFoundError("No abi found for this contract")
    return abi


def load_wallet(address, secret):
    file_path = "./data/wallets/{}/keystore".format(address)
    if not os.path.exists(file_path):
        raise FileNotFoundError("Can't find your wallet keystore for address: {}".format(address))
    keystore = "\n".join([line.strip() for line in open(file_path, 'r+')])
    private_key = web3.eth.account.decrypt(keystore, secret)
    return web3.eth.account.from_key(private_key)


def log_end_loop(delay):
    if delay:
        logging.info("Waiting for {} seconds...".format(delay))
        time.sleep(delay)
    logging.info("-" * 50)


def mint_tokens(account, token_address, amount, attempts=18):
    rng_functions = json.load(open('./data/rng.json'))
    if token_address not in rng_functions:
        raise Exception("Mint/RNG function not available for {}".format(token_address))
    call_function = random.choice(list(rng_functions[token_address]['functions']))
    token_contract = load_contract(token_address, load_contract_abi(token_address))
    token_info = get_token_info(token_address)
    loops = math.ceil(amount / rng_functions[token_address]['mints'])
    for i in list(range(0, loops)):
        tx = getattr(token_contract.functions, call_function)().build_transaction({
            "from": account.address,
            "nonce": get_nonce(account.address)
        })
        try:
            success = broadcast_transaction(account, tx, False, attempts)
        except Exception as e:
            if error := interpret_exception_message(e):
                logging.error("{} to mint {}".format(error, rng_functions[token_address]['label']))
            return False
        else:
            if success:
                logging.info("Called mint function for {} ({})".format(token_info['name'], token_info['symbol']))
            else:
                logging.warning(
                    "Failed to call mint function for {} ({})".format(token_info['name'], token_info['symbol']))
                return False
    return True


def sample_exchange_rate(router_name, token_address, quote_address, attempts=18):
    while attempts > 0:
        token_result = estimate_swap_result(router_name, token_address, quote_address, 1)
        if len(token_result) == 0:
            attempts -= 1
            time.sleep(1)
            continue
        else:
            return token_result[1]
    return None


def send_pls(account, to_address, amount, attempts=18):
    tx = {
        'nonce': get_nonce(account.address),
        'from': account.address,
        'to': to_address,
        'value': to_token_decimals(amount, 18),
    }
    try:
        return broadcast_transaction(account, tx, False, attempts)
    except Exception as e:
        if error := interpret_exception_message(e):
            logging.error("{}. Could not send to {}".format(error, to_address))
        return False


def send_tokens(account, token_address, to_address, amount, attempts=18):
    token_contract = load_contract(token_address)
    token_info = get_token_info(token_address)
    try:
        tx = token_contract.functions.transfer(
            to_address,
            to_token_decimals(amount, token_info['decimals'])
        ).build_transaction({
            'nonce': get_nonce(account.address),
            'from': account.address
        })
        return broadcast_transaction(account, tx, False, attempts)
    except Exception as e:
        if error := interpret_exception_message(e):
            logging.error("{}. Could not send {} ({}) to {}".format(
                error,
                token_info['name'],
                token_info['symbol'],
                to_address
            ))
        return False


def set_logging(filename='app', level='INFO', backup_count=7):
    if hasattr(logging, level.upper()):
        os.makedirs('./data/logs/', exist_ok=True)
        logging.basicConfig(
            format='%(asctime)s %(name)s %(levelname)s %(message)s',
            datefmt='%H:%M:%S',
            level=getattr(logging, level.upper()),
            handlers=[
                TimedRotatingFileHandler(
                    "./data/logs/{}.log".format(filename),
                    when="midnight",
                    interval=1,
                    backupCount=backup_count
                ),
                logging.StreamHandler(sys.stdout)
            ]
        )
        return True
    raise Exception("Invalid logging level")


def swap_tokens(account, router_name, token_route, estimated_swap_result, slippage_percent, to_address=None, taxed=False, attempts=18):
    routers = json.load(open('./data/routers.json'))
    router_contract = load_contract(routers[router_name][0], routers[router_name][1])
    approve_token_spending(account, token_route[0], routers[router_name][0], estimated_swap_result[0])
    if token_route[-1] == "0xA1077a294dDE1B09bB078844df40758a5D0f9a27":
        tx = router_contract.functions.swapExactTokensForETH(
            estimated_swap_result[0],
            estimated_swap_result[1] - round(estimated_swap_result[1] * (slippage_percent / 100)),
            token_route,
            to_address or account.address,
            int(time.time()) + (60 * 3)
        )
        tx_params = {
            "from": account.address,
            "nonce": get_nonce(account.address)
        }
    elif token_route[0] == "0xA1077a294dDE1B09bB078844df40758a5D0f9a27":
        if taxed:
            swap_function = router_contract.functions.swapExactETHForTokensSupportingFeeOnTransferTokens
        else:
            swap_function = router_contract.functions.swapExactETHForTokens
        tx = swap_function(
            0,
            token_route,
            to_address or account.address,
            int(time.time()) + (60 * 3)
        )
        tx_params = {
            "from": account.address,
            "nonce": get_nonce(account.address),
            "value": estimated_swap_result[0]
        }
    else:
        if taxed:
            swap_function = router_contract.functions.swapExactTokensForETHSupportingFeeOnTransferTokens
        else:
            swap_function = router_contract.functions.swapExactTokensForETH
        tx = swap_function(
            estimated_swap_result[0],
            estimated_swap_result[1] - (estimated_swap_result[1] * slippage_percent),
            token_route,
            to_address or account.address,
            int(time.time()) + (60 * 3)
        )
        tx_params = {
            "from": account.address,
            "nonce": get_nonce(account.address)
        }
    try:
        tx = tx.build_transaction(tx_params)
        return broadcast_transaction(account, tx, True, attempts)
    except Exception as e:
        if error := interpret_exception_message(e):
            logging.error("{}. Failed to swap".format(error))
        return False


def to_token_decimals(amount, decimals):
    amount = str(amount)
    if '.' in amount:
        decimals -= len(str(amount).split('.')[1])
    return int(str(amount).replace('.', '') + '0' * decimals)


def unwrap_pls(account, amount, attempts=18):
    wpls_contract = load_contract("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
    try:
        tx = wpls_contract.functions.withdraw(to_token_decimals(amount, 18)).build_transaction({
            "from": account.address,
            "nonce": get_nonce(account.address)
        })
        return broadcast_transaction(account, tx, True, attempts)
    except Exception as e:
        if error := interpret_exception_message(e):
            logging.error("{} to unwrap PLS".format(error))
        return False


def wrap_pls(account, amount, attempts=18):
    wpls_contract = load_contract("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
    try:
        tx = wpls_contract.functions.deposit().build_transaction({
            "from": account.address,
            "nonce": get_nonce(account.address),
            "value": to_token_decimals(amount, 18)
        })
        return broadcast_transaction(account, tx, True, attempts)
    except Exception as e:
        if error := interpret_exception_message(e):
            logging.error("{} to wrap PLS".format(error))
        return False
