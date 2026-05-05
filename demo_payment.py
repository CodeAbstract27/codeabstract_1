class PaymentProcessor:
    RATE = 0.029

    def __init__(self):
        self.transactions = []

    def calculate(self, amount):
        return round(amount * self.RATE, 2)

    def process(self, user, amount):
        fee = self.calculate(amount)
        total = amount + fee

        transaction = {
            "user": user,
            "amount": amount,
            "total": total
        }

        self.transactions.append(transaction)

        return transaction_id