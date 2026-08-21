import random
from datetime import datetime
from functools import reduce
from itertools import combinations


class BankError(Exception):
  """Base for every error this bank can raise."""


class InvalidAmountError(BankError):
  def __init__(self, raw):
    super().__init__(f"\"{raw}\" isn't a valid amount — enter a number greater than 0.")


class InsufficientFundsError(BankError):
  def __init__(self, number, shortfall):
    super().__init__(f"Account {number} would go {money(shortfall)} past its overdraft limit.")


def random_reference_digits():
  return str(random.randint(1000, 9999))


def timestamp_now():
  return datetime.now().strftime("%d/%m/%Y, %H:%M:%S")


def money(amount):
  if amount < 0:
    return f"-${abs(amount):.2f}"
  return f"${amount:.2f}"


def money_signed(amount):
  if amount > 0:
    return f"+${amount:.2f}"
  if amount < 0:
    return f"-${abs(amount):.2f}"
  return "—"

_next_ledger_id = 1


class Account:
  BASE_INTEREST_RATE = 0.0

  def __init__(self, account_number, opening_balance):
    self.account_number = account_number
    self.__balance = opening_balance
    self.ledger = []

  @property
  def balance(self):
    return self.__balance

  @balance.setter
  def balance(self, value):
    limit = self.overdraft_limit()
    if value < limit:
      raise InsufficientFundsError(self.account_number, limit - value)
    self.__balance = value

  def overdraft_limit(self):
    return 0

  def deposit(self, amount):
    self.balance = self.balance + amount
    self.post_transaction("DEPOSIT", amount, "deposit")
    self.apply_instant_interest(amount)

  def withdraw(self, amount):
    self.balance = self.balance - amount
    self.post_transaction("WITHDRAW", -amount, "withdrawn")

  def transfer_to(self, other, amount):
    self.balance = self.balance - amount
    self.post_transaction("TRANSFER", -amount, f"transferred to account {other.account_number}")
    other.balance = other.balance + amount
    other.post_transaction("TRANSFER", amount, f"transferred from account {self.account_number}")
    other.apply_instant_interest(amount)

  def apply_instant_interest(self, amount):
    rate = getattr(type(self), "INTEREST_RATE", Account.BASE_INTEREST_RATE)
    if rate <= 0:
      return
    calculate_interest = make_interest_calculator(rate)
    interest = calculate_interest(amount)
    self.balance = self.balance + interest
    self.post_transaction("INTEREST", interest, "interest")

  def post_transaction(self, entry_type, amount, note):
    global _next_ledger_id
    self.ledger.append({
      "id": _next_ledger_id,
      "type": entry_type,
      "amount": amount,
      "note": note,
      "when": timestamp_now(),
      "balance_after": self.__balance,
    })
    _next_ledger_id += 1

  def transactions(self):
    for entry in self.ledger:
      yield entry

  @classmethod
  def account_type(cls):
    return "Account"

  @classmethod
  def from_application(cls, application):
    number = f"{application['branch']}-{random_reference_digits()}"
    return cls(number, application["opening_balance"])


class SavingsAccount(Account):
  INTEREST_RATE = 0.02

  @classmethod
  def account_type(cls):
    return "Savings"


class CheckingAccount(Account):
  TRANSACTION_FEE = 1.50

  @classmethod
  def account_type(cls):
    return "Checking"

  def withdraw(self, amount):
    fee = apply_rate(amount, FEE_RULES["Checking"])
    limit = self.overdraft_limit()
    attempted_balance = self.balance - amount - fee
    if attempted_balance < limit:
      raise InsufficientFundsError(self.account_number, limit - attempted_balance)
    super().withdraw(amount)
    self.balance = self.balance - fee
    self.post_transaction("FEE", -fee, "withdrawal fee")


class CreditAccount(Account):
  @classmethod
  def account_type(cls):
    return "Credit"

  def __init__(self, account_number, opening_balance, credit_limit):
    super().__init__(account_number, opening_balance)
    self.credit_limit = credit_limit

  def overdraft_limit(self):
    return -self.credit_limit


class OverdraftMixin:
  def overdraft_limit(self):
    return -100


class FlexAccount(OverdraftMixin, SavingsAccount):
  INTEREST_RATE = 0.015

  @classmethod
  def account_type(cls):
    return "Flex"

FEE_RULES = {
  "Savings": lambda amount: 0,
  "Checking": lambda amount: CheckingAccount.TRANSACTION_FEE,
  "Credit": lambda amount: 0,
  "Flex": lambda amount: 0,
}


def apply_rate(amount, rate_fn):
  return rate_fn(amount)


def make_interest_calculator(rate):
  def interest_calculator(amount):
    return round(amount * rate, 2)

  return interest_calculator


class AccountIterator:
  def __init__(self, accounts_list):
    self.accounts_list = accounts_list
    self.index = 0

  def __iter__(self):
    return self

  def __next__(self):
    if self.index >= len(self.accounts_list):
      raise StopIteration
    acc = self.accounts_list[self.index]
    self.index += 1
    return acc


def total_interest_earned(accounts_list):
  return sum(
    entry["amount"]
    for acc in accounts_list
    for entry in acc.transactions()
    if entry["type"] == "INTEREST"
  )


def all_transfer_pairings(accounts_list):
  pairings = []
  for a, b in combinations(accounts_list, 2):
    icon_a = ACCOUNT_TYPE_ICONS.get(type(a).account_type(), "")
    icon_b = ACCOUNT_TYPE_ICONS.get(type(b).account_type(), "")
    pairings.append(f"{icon_a} {a.account_number} <-> {icon_b} {b.account_number}")
  return pairings

accounts = []


def validate_amount(raw_text):
  try:
    amount = float(raw_text)
  except (TypeError, ValueError) as err:
    raise InvalidAmountError(raw_text) from err
  if amount <= 0:
    raise InvalidAmountError(raw_text)
  return amount


def perform_transaction(account, operation, raw_amount, target=None):
  succeeded = False
  breakdown = None
  target_breakdown = None
  error_message = None
  error = None

  try:
    amount = validate_amount(raw_amount)
    before = account.balance
    entries_before = len(account.ledger)

    if operation == "deposit":
      account.deposit(amount)
    elif operation == "withdraw":
      account.withdraw(amount)
    elif operation == "transfer":
      target_before = target.balance
      target_entries_before = len(target.ledger)
      account.transfer_to(target, amount)
      target_breakdown = {
        "before": target_before,
        "after": target.balance,
        "entries": target.ledger[target_entries_before:],
      }

    breakdown = {
      "before": before,
      "after": account.balance,
      "entries": account.ledger[entries_before:],
    }
  except InvalidAmountError as err:
    error_message = str(err)
    error = err
  except InsufficientFundsError as err:
    error_message = str(err)
    error = err
  except BankError as err:
    error_message = str(err)
    error = err
  except Exception as err:
    wrapped = BankError(f"Something went wrong processing this transaction ({err}).")
    error_message = str(wrapped)
    error = wrapped
  else:
    succeeded = True

  return {
    "succeeded": succeeded,
    "breakdown": breakdown,
    "target_breakdown": target_breakdown,
    "error_message": error_message,
    "error": error,
  }


def open_initial_accounts():
  savings_application = {
    "branch": "SV",
    "opening_balance": 1200.00,
  }
  accounts.append(SavingsAccount.from_application(savings_application))
  accounts.append(CheckingAccount("CK-1029", 640.50))
  accounts.append(CreditAccount("CR-8834", -120.00, 500))
  accounts.append(FlexAccount("FX-2048", 305.75))


def show(text):
  print()
  print(text)


def ask(prompt):
  print()
  return input(prompt)

ACCOUNT_TYPE_ICONS = {
  "Savings": "🟢",
  "Checking": "🔵",
  "Credit": "🔴",
  "Flex": "🟣",
}


def render_accounts_summary(accounts_list):
  lines = []
  for acc in AccountIterator(accounts_list):
    type_name = type(acc).account_type()
    icon = ACCOUNT_TYPE_ICONS.get(type_name, "")
    lines.append(f"{icon} {type_name} Account {acc.account_number} = {money(acc.balance)}")
  return "\n".join(lines)


def show_totals():
  total_balance = reduce(lambda running, acc: running + acc.balance, accounts, 0.0)
  total_interest = total_interest_earned(accounts)
  show(f"Total interest earned so far: {money(total_interest)}    Total balance: {money(total_balance)}")


def show_welcome_facts():
  pairings = all_transfer_pairings(accounts)
  show(f"Ways to transfer between your own accounts: {', '.join(pairings)}")


def prompt_choice(prompt_text, valid_choices):
  while True:
    raw = ask(prompt_text).strip()
    if raw.isdigit() and int(raw) in valid_choices:
      return int(raw)
    show(f"Please enter one of: {', '.join(str(c) for c in valid_choices)}")


def prompt_amount():
  while True:
    raw = ask("Enter amount: $").strip()
    try:
      return validate_amount(raw)
    except InvalidAmountError as err:
      show(str(err))

PLAIN_STAR_BORDER = ("* " * 32).rstrip()
CLOSING_STAR_BORDER = ("* " * 38).rstrip()


def build_ticket_top_border(acc):
  type_name = type(acc).account_type().upper()
  return ("* " * 10 + f'🪙 YOUR "{type_name}" ACCOUNT UPDATE 🪙 ' + "* " * 10).rstrip()


def build_ticket_text(breakdown):
  lines = [f"Balance before:    {money(breakdown['before'])}"]
  for entry in breakdown["entries"]:
    lines.append(f"      • {entry['note'].upper()} ({entry['when']}):    {money_signed(entry['amount'])}")
  lines.append(f"Balance after:    {money(breakdown['after'])}")
  return "\n".join(lines)


def show_account_ticket(acc, breakdown):
  show(build_ticket_top_border(acc))
  show(build_ticket_text(breakdown))
  show(CLOSING_STAR_BORDER)


def run_transaction_flow():
  account_lines = ["Select an account:"]
  for i, acc in enumerate(accounts, start=1):
    account_lines.append(f"{i}. {type(acc).account_type()} ({acc.account_number})")
  show("\n".join(account_lines))
  acc_choice = prompt_choice("Enter 1, 2, 3 or 4: ", list(range(1, len(accounts) + 1)))
  selected = accounts[acc_choice - 1]

  show(
    "What would you like to do?\n"
    "1. Withdraw\n"
    "2. Deposit\n"
    "3. Transfer to some account"
  )
  op_choice = prompt_choice("Enter 1, 2 or 3: ", [1, 2, 3])

  target_account = None
  if op_choice == 3:
    others = [a for a in accounts if a.account_number != selected.account_number]
    transfer_lines = ["Transfer to which account?"]
    for i, acc in enumerate(others, start=1):
      transfer_lines.append(f"{i}. {type(acc).account_type()} ({acc.account_number})")
    show("\n".join(transfer_lines))
    target_choice = prompt_choice("Select an option: ", list(range(1, len(others) + 1)))
    target_account = others[target_choice - 1]

  amount = prompt_amount()
  operation = {
    1: "withdraw",
    2: "deposit",
    3: "transfer",
  }[op_choice]

  result = perform_transaction(selected, operation, str(amount), target_account)

  if not result["succeeded"]:
    reason = ""
    if isinstance(result["error"], InsufficientFundsError):
      if type(selected).account_type() in ("Savings", "Checking"):
        reason = " due to insufficient funds"
      else:
        reason = " due to insufficient withdrawal limit"
    show(PLAIN_STAR_BORDER)
    show(f"❌ Transaction failed{reason}: {result['error_message']}")
    show(PLAIN_STAR_BORDER)
    return

  if operation == "withdraw":
    success_message = f"✅ {money(amount)} successfully withdrawn from {selected.account_number}."
  elif operation == "deposit":
    success_message = f"✅ {money(amount)} successfully deposited to {selected.account_number}."
  else:
    success_message = (
      f"✅ {money(amount)} successfully transferred from {selected.account_number} "
      f"to {target_account.account_number}."
    )

  show(PLAIN_STAR_BORDER)
  show(success_message)
  show_account_ticket(selected, result["breakdown"])
  if operation == "transfer":
    show_account_ticket(target_account, result["target_breakdown"])

  show(render_accounts_summary(accounts))
  show_totals()


def main():
  open_initial_accounts()

  show(
    "===================================\n"
    "           WORLD BANK\n"
    "==================================="
  )
  show_welcome_facts()
  show(render_accounts_summary(accounts))
  show_totals()

  while True:
    run_transaction_flow()

if __name__ == "__main__":
  main()
