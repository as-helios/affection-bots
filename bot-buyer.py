from core import *

# set config variables
buy_percent_diff_pdai = 20
buy_percent_diff_pusdc = 30
buy_with_amount_pls = 30000
slippage_percent = 5
wallet_a_min_pls = 20000
wallet_b_min_pls = 100000
wallet_c_min_pls = 20000
loop_delay = 3
rapid_gas_fee_limit = 650000

# load wallet A and set address for logging
set_logging(wallet_a_address, 'INFO')
account = load_wallet(wallet_a_address, os.getenv('SECRET'))

# load contract addresses
pdai_address = '0x6B175474E89094C44Da98b954EedeAC495271d0F'
pusdc_address = '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'
affection_address = '0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D'
wpls_address = '0xA1077a294dDE1B09bB078844df40758a5D0f9a27'

while True:
    # log the wallet's pls balance
    pls_balance_a = get_pls_balance(account.address)
    logging.info("PLS Balance: {:.15f}".format(pls_balance_a))

    # check if wallet b has a minimum amount of pls and send some back for minting
    pls_balance_b = get_pls_balance(wallet_b_address)
    if pls_balance_b - wallet_b_min_pls < 0:
        send_to_wallet_b = math.ceil(wallet_b_min_pls - pls_balance_b)
        logging.info("Minter needs {} PLS".format(send_to_wallet_b))
        # check if sending pls to wallet b leaves wallet a with enough left over
        if send_to_wallet_b < (pls_balance_a - wallet_a_min_pls):
            if send_pls(account, wallet_b_address, send_to_wallet_b):
                logging.info("Sent {} PLS to {}".format(send_to_wallet_b, wallet_b_address))
            else:
                logging.warning("Failed to send {} PLS to {}".format(send_to_wallet_b, wallet_b_address))
        else:
            logging.info("Not enough PLS to send right now")

    # check if wallet c has a minimum amount of pls and send some back for selling
    pls_balance_c = get_pls_balance(wallet_c_address)
    if pls_balance_c - wallet_c_min_pls < 0:
        send_to_wallet_c = math.ceil(wallet_c_min_pls - pls_balance_c)
        logging.info("Seller needs {} PLS".format(send_to_wallet_c))
        # check if sending pls to wallet c leaves wallet a with enough left over
        if send_to_wallet_c < (pls_balance_a - wallet_a_min_pls):
            if send_pls(account, wallet_c_address, send_to_wallet_c):
                logging.info("Sent {} PLS to {}".format(send_to_wallet_c, wallet_c_address))
            else:
                logging.warning("Failed to send {} PLS to {}".format(send_to_wallet_c, wallet_c_address))
        else:
            logging.info("Not enough PLS to send right now")

    # check the current gas price
    if get_mempool_gas_prices('rapid', gas_cache_seconds) > rapid_gas_fee_limit:
        logging.warning("Gas fees are too high")
        log_end_loop(loop_delay)
        continue

    # take samples of 1 pdai/pusdc/affection to wpls price
    pdai_sample_result = sample_exchange_rate('PulseX_v2', pdai_address, wpls_address)
    pusdc_sample_result = sample_exchange_rate('PulseX_v2', pusdc_address, wpls_address)
    affection_sample_result = sample_exchange_rate('PulseX_v2', affection_address, wpls_address)
    if not pdai_sample_result or not pusdc_sample_result or not affection_sample_result:
        logging.warning("Failed to sample prices")
        log_end_loop(loop_delay)
        continue

    # log the current rate
    logging.info("pDAI Rate: 1 = {} PLS".format(pdai_sample_result / 10 ** 18))
    logging.info("pUSDC Rate: 1 = {} PLS".format(pusdc_sample_result / 10 ** 18))
    logging.info("AFFECTION™ Rate: 1 = {} PLS".format(affection_sample_result / 10 ** 18))

    # keep a minimum pls balance in the bot
    skip = False
    if (pls_balance := get_pls_balance(wallet_a_address)) < wallet_a_min_pls:
        logging.warning("PLS balance is below minimum")
        skip = True
    elif pls_balance < buy_with_amount_pls + wallet_a_min_pls:
        logging.warning("Buying would put the PLS balance below minimum")
        skip = True
    if skip:
        log_end_loop(loop_delay)
        continue

    # check if the pdai price is cheaper than affection price
    if pdai_sample_result < affection_sample_result:
        percent_diff = ((pdai_sample_result - affection_sample_result) / affection_sample_result) * 100
        # pdai price must be cheaper and over the diff threshold
        if percent_diff < 0 and abs(percent_diff) >= buy_percent_diff_pdai:
            logging.info("Buying pDAI...")
            # get the estimated amounts returned for the swap
            estimated_swap_result = estimate_swap_result(
                'PulseX_v2',
                wpls_address,
                pdai_address,
                buy_with_amount_pls
            )
            if estimated_swap_result:
                # broadcast swap pls for pdai
                if swap_tokens(
                    account,
                    'PulseX_v2',
                    [wpls_address, pdai_address],
                    estimated_swap_result,
                    slippage_percent,
                    wallet_b_address
                ):
                    logging.info("Swapped {} PLS to pDAI".format(buy_with_amount_pls))
            else:
                logging.warning("No estimated swap result data")
        else:
            logging.info("pDAI is not within range to buy yet ({}%)".format(buy_percent_diff_pdai))
    else:
        logging.info("pDAI is not cheaper than AFFECTION™ yet")

    # check if the pusdc price is cheaper than affection price
    if pusdc_sample_result < affection_sample_result:
        # check the percent difference
        percent_diff = ((pusdc_sample_result - affection_sample_result) / affection_sample_result) * 100
        # pusdc price must be cheaper and over the diff threshold
        if percent_diff < 0 and abs(percent_diff) >= buy_percent_diff_pusdc:
            logging.info("Buying pUSDC...")
            # get the estimated amounts returned for the swap
            estimated_swap_result = estimate_swap_result(
                'PulseX_v2',
                wpls_address,
                pusdc_address,
                buy_with_amount_pls
            )
            if estimated_swap_result:
                # broadcast swap pls for pusdc
                if swap_tokens(
                    account,
                    'PulseX_v2',
                    [wpls_address, pusdc_address],
                    estimated_swap_result,
                    slippage_percent,
                    wallet_b_address
                ):
                    logging.info("Swapped {} PLS to pUSDC".format(buy_with_amount_pls))
            else:
                logging.warning("No estimated swap result data")
        else:
            logging.info("pUSDC is not within range to buy yet ({}%)".format(buy_percent_diff_pusdc))
    else:
        logging.info("pUSDC is not cheaper than AFFECTION™ yet")

    # wait before next loop
    log_end_loop(loop_delay)

