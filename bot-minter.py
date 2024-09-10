from core import *

# set config variables
wallet_min_pls = 20000
loop_delay = 3
rapid_gas_fee_limit = 450000

# load wallet B and set address for logging
set_logging(wallet_b_address, 'INFO')
account = load_wallet(wallet_b_address, os.getenv('SECRET'))

# load affection contract/info
affection_address = '0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D'
affection_info = get_token_info(affection_address)
affection_contract = load_contract(affection_address)

# load pdai contract/info
pdai_address = '0x6B175474E89094C44Da98b954EedeAC495271d0F'
pdai_info = get_token_info(pdai_address)
pdai_contract = load_contract(pdai_address)

# load pusdc contract/info
pusdc_address = '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'
pusdc_info = get_token_info(pusdc_address)
pusdc_contract = load_contract(pusdc_address)

# load pi contract/info
pi_address = '0xA2262D7728C689526693aE893D0fD8a352C7073C'
pi_info = get_token_info(pi_address)
pi_contract = load_contract(pi_address)

# load g5 contract/info
g5_address = '0x2fc636E7fDF9f3E8d61033103052079781a6e7D2'
g5_info = get_token_info(g5_address)
g5_contract = load_contract(g5_address)

# load math 1.1 contract/info
math11_address = '0xB680F0cc810317933F234f67EB6A9E923407f05D'
math11_info = get_token_info(math11_address)
math11_contract = load_contract(math11_address)

# load multi contract addresses
multi_affection_address = '0x81fcd03D2100A0fE9767C0CfC68050bdc6a2969d'
multi_math_1_1_address = '0x1322Dab9eE385Bb3D81f75EBb8356015B0872e53'
multi_g5_address = '0xa4c61D20945c11855E7A390153fd29ceC9C7349b'
multi_pi_address = '0xcCDaCEF154704c604365dB9E3b1DF356B9c4B6E2'

while True:
    # log the wallet's pls balance
    logging.info("PLS Balance: {:.15f}".format(pls_balance := get_pls_balance(account.address)))

    # transfer affection
    logging.info("AFFECTION™ Balance: {:.15f}".format(affection_balance := math.floor(get_token_balance(affection_address, wallet_b_address))))
    if affection_balance > 1:
        # send affection tokens to wallet C for selling
        if send_tokens(account, affection_address, wallet_c_address, affection_balance):
            logging.info("Sent {} AFFECTION™ to {}".format(affection_balance, wallet_c_address))

    # check the current gas price
    if get_beacon_gas_prices('rapid', beacon_gasnow_cache_seconds) > rapid_gas_fee_limit:
        logging.warning("Gas fees are too high")
        log_end_loop(loop_delay)
        continue

    # keep a minimum pls balance in the bot
    if pls_balance < wallet_min_pls:
        logging.info("PLS balance is below minimum threshold")
        log_end_loop(loop_delay)
        continue

    # convert pi to affection
    logging.info("PI Balance: {:.15f}".format(pi_balance := get_token_balance(pi_address, wallet_b_address)))
    if (loops := math.floor(pi_balance / 0.01)) != 0:
        logging.info("Converting {} PI to AFFECTION™...".format(loops * 0.01))
        convert_tokens_multi(account, multi_affection_address, pi_address, affection_address, loops)

    # convert g5 to affection
    logging.info("G5 Balance: {:.15f}".format(g5_balance := get_token_balance(g5_address, wallet_b_address)))
    if (loops := math.floor(g5_balance / 0.6)) != 0:
        logging.info("Converting {} G5 to AFFECTION™...".format(loops * 0.6))
        convert_tokens_multi(account, multi_affection_address, g5_address, affection_address, loops)

    # convert math 1.1 to affection
    logging.info("MATH 1.1 Balance: {:.15f}".format(math11_balance := get_token_balance(math11_address, wallet_b_address)))
    if (loops := math.floor(math11_balance / 3)) != 0:
        logging.info("Converting {} MATH v1.1 to AFFECTION™...".format(loops * 3))
        convert_tokens_multi(account, multi_affection_address, math11_address, affection_address, loops)

    # transfer affection
    logging.info("AFFECTION™ Balance: {:.15f}".format(affection_balance := math.floor(get_token_balance(affection_address, wallet_b_address))))
    if affection_balance > 1:
        # send affection tokens to wallet C for selling
        if send_tokens(account, affection_address, wallet_c_address, affection_balance):
            logging.info("Sent {} AFFECTION™ to {}".format(affection_balance, wallet_c_address))

    # convert pdai to pi
    logging.info("pDAI Balance: {:.15f}".format(pdai_balance := get_token_balance(pdai_address, wallet_b_address)))
    if (loops := math.floor(pdai_balance / 300)) != 0:
        logging.info("Converting {} pDAI to PI...".format(loops * 300))
        convert_tokens_multi(account, multi_pi_address, pdai_address, pi_address, loops)

    # convert pdai to g5
    pdai_balance = get_token_balance(pdai_address, wallet_b_address)
    if (loops := math.floor(pdai_balance / 5)) != 0:
        logging.info("Converting {} pDAI to G5...".format(loops * 5))
        convert_tokens_multi(account, multi_g5_address, pdai_address, g5_address, loops)

    # convert pdai to math1.1
    pdai_balance = get_token_balance(pdai_address, wallet_b_address)
    if (loops := math.floor(pdai_balance)) != 0:
        logging.info("Converting {} pDAI to MATH v1.1 ...".format(loops))
        convert_tokens_multi(account, multi_math_1_1_address, pdai_address, math11_address, loops)

    # convert pusdc to math1.1
    logging.info("pUSDC Balance: {:.15f}".format(pusdc_balance := get_token_balance(pusdc_address, wallet_b_address)))
    if (loops := math.floor(pusdc_balance)) != 0:
        logging.info("Converting {} pUSDC to MATH v1.1 ...".format(loops))
        convert_tokens_multi(account, multi_math_1_1_address, pusdc_address, math11_address, loops)

    # wait before next loop
    log_end_loop(loop_delay)
