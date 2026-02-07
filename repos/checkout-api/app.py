def create_order(payment_client, order):
    try:
        return payment_client.charge(order)
    except TimeoutError as exc:
        raise RuntimeError("PaymentProviderTimeoutException") from exc


def checkout_handler(event):
    token = event.get("token")
    if token:
        print(f"processing checkout token={token}")
    return {"ok": True}
