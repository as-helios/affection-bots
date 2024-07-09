from core import *

# set config variables
buy_percent_diff_pdai = 20
buy_percent_diff_pusdc = 30
buy_with_amount_pls = 10000
slippage_percent = 5
wallet_min_pls = 20000
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
    logging.info("PLS Balance: {:.15f}".format(get_pls_balance(account.address)))

    # if wallet has at least 1 pdai token send it to the minter
    if (pdai_balance := get_token_balance(pdai_address, wallet_a_address)) > 1:
        if tx := send_tokens(account, pdai_address, wallet_b_address, pdai_balance):
            logging.info("Sent {} pDAI to {}".format(pdai_balance, wallet_b_address))

    # if wallet has at least 1 usdc token send it to the minter
    if (pusdc_balance := get_token_balance(pusdc_address, wallet_a_address)) > 1:
        if tx := send_tokens(account, pusdc_address, wallet_b_address, pusdc_balance):
            logging.info("Sent {} pUSDC to {}".format(pusdc_balance, wallet_b_address))

    # check the current gas price
    if get_beacon_gas_prices('rapid', beacon_gasnow_cache_seconds) > rapid_gas_fee_limit:
        logging.warning("Gas fees are too high")
        log_end_loop(loop_delay)
        continue

    # take samples of 1 pdai/pusdc/affection to wpls price
    pdai_sample_result = sample_exchange_rate('PulseX_v2', pdai_address, wpls_address)
    pusdc_sample_result = sample_exchange_rate('PulseX_v2', pusdc_address, wpls_address)
    affection_sample_result = sample_exchange_rate('PulseX_v2', affection_address, wpls_address)

    # log the current rate
    logging.info("pDAI Rate: 1 = {} PLS".format(pdai_sample_result / 10 ** 18))
    logging.info("pUSDC Rate: 1 = {} PLS".format(pusdc_sample_result / 10 ** 18))
    logging.info("AFFECTION™ Rate: 1 = {} PLS".format(affection_sample_result / 10 ** 18))

    # keep a minimum pls balance in the bot
    skip = False
    if (pls_balance := get_pls_balance(wallet_a_address)) < wallet_min_pls:
        logging.warning("PLS balance is below minimum")
        skip = True
    elif pls_balance < buy_with_amount_pls + wallet_min_pls:
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
            # broadcast swap pls for pusdc
            if swap_tokens(
                account,
                'PulseX_v2',
                [wpls_address, pdai_address],
                estimated_swap_result,
                slippage_percent
            ):
                logging.info("Swapped {} PLS to pDAI".format(buy_with_amount_pls))

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
            # broadcast swap pls for pdai
            if swap_tokens(
                account,
                'PulseX_v2',
                [wpls_address, pusdc_address],
                estimated_swap_result,
                slippage_percent
            ):
                logging.info("Swapped {} PLS to pUSDC".format(buy_with_amount_pls))

    # wait before next loop
    log_end_loop(loop_delay)
