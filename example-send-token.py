from core import *

tokenA_address = ''
tokenA_info = get_token_info(tokenA_address)
tokenA_amount = 1

wallet_address = ''
destination_address = ''
set_logging(wallet_address, 'INFO')
account = load_wallet(wallet_address, os.getenv('SECRET'))

if send_tokens(
        account,
        tokenA_address,
        destination_address,
        tokenA_amount
):
    logging.info("Sent {} {} to {}".format(tokenA_amount, tokenA_info['symbol'], destination_address))
else:
    logging.info("Failed to send {} {} to {}".format(tokenA_amount, tokenA_info['symbol'], destination_address))
