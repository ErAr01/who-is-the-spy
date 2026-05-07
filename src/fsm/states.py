from aiogram.fsm.state import State, StatesGroup


class CustomSetup(StatesGroup):
    waiting_civilian_payload = State()
    waiting_civilian_wiki_url = State()
    waiting_spy_payload = State()
    waiting_spy_wiki_url = State()


class TestRoundSetup(StatesGroup):
    selecting_categories = State()
