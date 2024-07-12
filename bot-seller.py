from core import *

# set config variables
sell_percent_diff_affection = 0
sell_with_amount_affection = 500
slippage_percent = 5
wallet_min_pls = 20000
loop_delay = 3
loop_sell_delay = 10
rapid_gas_fee_limit = 777777

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

while True:
    # log the wallet's pls balance
    logging.info("PLS Balance: {:.15f}".format(get_pls_balance(account.address)))

    # send pls back to wallet a for buying
    pls_balance = get_pls_balance(account.address, False)
    pls_balance -= wallet_min_pls
    # send the minter 1/4
    send_to_wallet_b = float(round(pls_balance / 4, 2))
    # send the rest to buyer
    send_to_wallet_a = float(round(pls_balance - send_to_wallet_b, 2))
    if pls_balance > wallet_min_pls:
        # send pls to wallet a
        if send_pls(account, wallet_a_address, send_to_wallet_a):
            logging.info("Sent {} PLS to {}".format(send_to_wallet_a, wallet_a_address))
        else:
            logging.warning("Failed to send {} PLS to {}".format(send_to_wallet_a, wallet_a_address))
        # send pls to wallet b
        if send_pls(account, wallet_b_address, send_to_wallet_b):
            logging.info("Sent {} PLS to {}".format(send_to_wallet_b, wallet_b_address))
        else:
            logging.warning("Failed to send {} PLS to {}".format(send_to_wallet_b, wallet_b_address))

    # check the current gas price
    if get_beacon_gas_prices('rapid', beacon_gasnow_cache_seconds) > rapid_gas_fee_limit:
        logging.warning("Gas fees are too high")
        log_end_loop(loop_delay)
        continue

    # take a sample of the 1 affection to wpls price
    affection_sample_result = sample_exchange_rate('PulseX_v2', affection_address, wpls_address)
    if not affection_sample_result_last:
        affection_sample_result_last = affection_sample_result

    # log the current rate
    logging.info("AFFECTION™ Rate: 1 = {} PLS".format(affection_sample_result / 10 ** 18))
    logging.info("AFFECTION™ Balance: {:.15f}".format(affection_balance := get_token_balance(affection_address, wallet_c_address), 2))
    # check if wallet c has at least 1 token to sell
    if affection_balance > 1:
        # check if the affection price spiked since last time
        if not sell_percent_diff_affection or affection_sample_result > affection_sample_result_last:
            # check the percent difference
            percent_diff = ((affection_sample_result_last - affection_sample_result) / affection_sample_result) * 100
            # sell if percent is met
            if not sell_percent_diff_affection or (percent_diff < 0 and abs(percent_diff) >= sell_percent_diff_affection):
                # get amounts of affection to sell
                sells = math.floor(affection_balance / sell_with_amount_affection)
                selling_amounts = [sell_with_amount_affection] * sells
                selling_amounts.append(math.floor(affection_balance - sum(selling_amounts)))
                # start selling affection in different amounts
                logging.info("Selling {} AFFECTION™...".format(sum(selling_amounts)))
                for i, amount in enumerate(selling_amounts):
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
                            slippage_percent
                        ):
                            logging.info("Swapped {} AFFECTION™ to PLS".format(amount))
                    else:
                        logging.warning("No estimated swap result from RPC")
                        break
                    # delay if amounts remain in the list
                    if i + 1 != len(selling_amounts):
                        logging.info("Waiting for {} seconds...".format(loop_sell_delay))
                        time.sleep(loop_sell_delay)
            else:
                logging.info("AFFECTION™ is not within range to sell yet ({}%)".format(sell_percent_diff_affection))
        else:
            logging.info("AFFECTION™ price hasn't increased yet")

    # save the last sample price
    affection_sample_result_last = affection_sample_result

    # wait before next loop
    log_end_loop(loop_delay)

