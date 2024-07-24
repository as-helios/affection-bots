from core import *

# set config variables
sell_percent_diff_pdai = 15
sell_percent_diff_pusdc = 25
sell_with_amount_affection = 500
slippage_percent = 5
wallet_min_pls = 20000
loop_delay = 3
loop_sell_delay = 10
rapid_gas_fee_limit = 650000

# load wallet C and set address for logging
set_logging(wallet_c_address, 'INFO')
account = load_wallet(wallet_c_address, os.getenv('SECRET'))

# load affection contract/info
affection_address = '0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D'
affection_info = get_token_info(affection_address)
affection_contract = load_contract(affection_address)
affection_sample_result_last = None

# load wpls contract/info
wpls_address = '0xA1077a294dDE1B09bB078844df40758a5D0f9a27'
wpls_info = get_token_info(wpls_address)
wpls_contract = load_contract(wpls_address)

# load contract addresses
pdai_address = '0x6B175474E89094C44Da98b954EedeAC495271d0F'
pusdc_address = '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'

while True:
    # log the wallet's pls balance
    logging.info("PLS Balance: {:.15f}".format(get_pls_balance(account.address)))

    # take samples of 1 pdai/pusdc/affection to wpls price
    pdai_sample_result = sample_exchange_rate('PulseX_v2', pdai_address, wpls_address)
    pusdc_sample_result = sample_exchange_rate('PulseX_v2', pusdc_address, wpls_address)
    affection_sample_result = sample_exchange_rate('PulseX_v2', affection_address, wpls_address)
    if not pdai_sample_result or not pusdc_sample_result or not affection_sample_result:
        logging.warning("Failed to sample prices")
        log_end_loop(loop_delay)
        continue

    # log the current rates
    logging.info("pDAI Rate: 1 = {} PLS".format(pdai_sample_result / 10 ** 18))
    logging.info("pUSDC Rate: 1 = {} PLS".format(pusdc_sample_result / 10 ** 18))
    logging.info("AFFECTION™ Rate: 1 = {} PLS".format(affection_sample_result / 10 ** 18))

    # log the balance
    affection_balance = get_token_balance(affection_address, wallet_c_address)
    logging.info("AFFECTION™ Balance: {:.15f}".format(affection_balance))

    # check if wallet c has at least 1 token
    if affection_balance > 1:
        # get amounts of affection to sell
        sells = math.floor(affection_balance / sell_with_amount_affection)
        selling_amounts = [sell_with_amount_affection] * sells
        selling_amounts.append(math.floor(affection_balance - sum(selling_amounts)))
        # start selling affection in different amounts
        logging.info("Selling {} AFFECTION™...".format(sum(selling_amounts)))
        i = 0
        while i < len(selling_amounts):
            # check the current gas price
            if get_beacon_gas_prices('rapid', beacon_gasnow_cache_seconds) > rapid_gas_fee_limit:
                logging.warning("Gas fees are too high")
                log_end_loop(loop_delay)
                break
            amount = selling_amounts[i]
            # check if the pdai/pusdc price is cheaper than affection price
            if (pdai_sample_result < affection_sample_result
                    or pusdc_sample_result < affection_sample_result):
                pdai_percent_diff = ((pdai_sample_result - affection_sample_result) / affection_sample_result) * 100
                pusdc_percent_diff = ((pusdc_sample_result - affection_sample_result) / affection_sample_result) * 100
                # pdai/pusdc price must be cheaper and over the diff threshold
                if (pdai_percent_diff < 0 and abs(pdai_percent_diff) >= sell_percent_diff_pdai) \
                        or (pusdc_percent_diff < 0 and abs(pusdc_percent_diff) >= sell_percent_diff_pusdc):
                    estimated_swap_result = estimate_swap_result(
                        'PulseX_v2',
                        affection_address,
                        wpls_address,
                        amount
                    )
                    if estimated_swap_result:
                        if swap_tokens(
                                account,
                                'PulseX_v2',
                                [affection_address, wpls_address],
                                estimated_swap_result,
                                slippage_percent,
                                wallet_a_address
                        ):
                            logging.info("Swapped {} AFFECTION™ to PLS".format(amount))
                            i += 1
                    else:
                        logging.warning("No estimated swap result from RPC")
                        break
                    # delay if amounts remain in the list
                    if i < len(selling_amounts):
                        logging.info("Waiting for {} seconds...".format(loop_sell_delay))
                        time.sleep(loop_sell_delay)
                        # resample the prices
                        pdai_sample_result = sample_exchange_rate('PulseX_v2', pdai_address, wpls_address)
                        pusdc_sample_result = sample_exchange_rate('PulseX_v2', pusdc_address, wpls_address)
                        affection_sample_result = sample_exchange_rate('PulseX_v2', affection_address, wpls_address)
                        if not pdai_sample_result or not pusdc_sample_result or not affection_sample_result:
                            logging.warning("Failed to sample prices")
                            break
                else:
                    logging.info("AFFECTION™ price is not within targeted range for selling")
                    break
            else:
                logging.info("AFFECTION™ price is too low")
                break

    # wait before next loop
    log_end_loop(loop_delay)

