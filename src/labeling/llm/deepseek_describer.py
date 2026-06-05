import json
import logging
import re
import time

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from src.labeling.llm.base import CharacterDescriber, DescriptionResult
from src.labeling.llm.retry import _call_with_rate_limit_retry

logger = logging.getLogger(__name__)

_MIN_NAME_TOKEN_LENGTH = 3


class CharacterProfile(BaseModel):
    description: str = Field(min_length=1)
    facts: list[str] = Field(default_factory=list)


def _name_token_pattern(token: str) -> str:
    # Токен должен начинаться на границе слова: иначе «Рон» вырезал бы «Электрон»,
    # а «Кот» — «которой». Для длинных токенов (>= 5) разрешаем короткий суффикс,
    # чтобы ловить склонения («Поттера», «Поттеру»); для коротких — только целое слово.
    escaped = re.escape(token)
    if len(token) >= 5:
        return rf"(?<!\w){escaped}\w{{0,3}}(?!\w)"
    return rf"(?<!\w){escaped}(?!\w)"


def filter_name_leaks(facts: list[str], name: str) -> list[str]:
    """Отбрасывает факты, в которых встречается имя персонажа.

    Игрок зачитывает факт вслух — упоминание имени мгновенно раскрывает карточку.
    Проверяем каждый токен имени длиной >= 3 символов без учёта регистра,
    по границам слов (см. _name_token_pattern).
    """
    tokens = [
        token
        for token in re.split(r"[^\w]+", name)
        if len(token) >= _MIN_NAME_TOKEN_LENGTH
    ]
    if not tokens:
        return list(facts)
    pattern = re.compile(
        "|".join(_name_token_pattern(token) for token in tokens),
        flags=re.IGNORECASE,
    )
    return [fact for fact in facts if not pattern.search(fact)]


class DeepSeekDescriber(CharacterDescriber):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        facts_count: int = 10,
    ) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.facts_count = facts_count

    def describe(self, name: str, categories: list[str]) -> DescriptionResult:
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        profile: CharacterProfile | None = None
        facts: list[str] = []
        retry_note: str | None = None
        # Один основной запрос + один ретрай, если ответ невалиден или факты
        # отфильтрованы из-за утечки имени.
        for attempt in range(2):
            completion = self._complete(name, categories, retry_note=retry_note)
            self._accumulate_usage(usage_total, completion)
            content = completion.choices[0].message.content or "{}"
            try:
                candidate = CharacterProfile.model_validate(json.loads(content))
            except (json.JSONDecodeError, ValidationError) as exc:
                logger.warning(
                    "DeepSeek description response invalid: name=%s attempt=%s error_type=%s",
                    name,
                    attempt + 1,
                    type(exc).__name__,
                )
                retry_note = "Предыдущий ответ был невалидным JSON. Верни строго JSON по описанной схеме."
                continue
            clean_facts = filter_name_leaks(candidate.facts, name)
            if profile is None or len(clean_facts) > len(facts):
                profile = candidate
                facts = clean_facts
            if len(clean_facts) >= self.facts_count:
                break
            leaked = [fact for fact in candidate.facts if fact not in clean_facts]
            retry_note = (
                "В этих фактах упоминалось имя персонажа, что запрещено: "
                + " | ".join(leaked[:5])
                + ". Перепиши все факты без имени и названия франшизы."
            )

        if profile is None:
            raise ValueError(f"DeepSeek did not return a valid character profile for '{name}'")
        if len(facts) < self.facts_count:
            logger.warning(
                "DeepSeek facts below target after filtering: name=%s facts=%s target=%s",
                name,
                len(facts),
                self.facts_count,
            )
        # Approximation for deepseek-chat ($0.27 / 1M input, $1.10 / 1M output).
        estimated_cost = (
            usage_total["prompt_tokens"] * 0.27 + usage_total["completion_tokens"] * 1.10
        ) / 1_000_000
        logger.info(
            "Character description completed: model=%s name=%s facts=%s prompt=%s completion=%s estimated_cost=%.6f",
            self.model,
            name,
            len(facts),
            usage_total["prompt_tokens"],
            usage_total["completion_tokens"],
            estimated_cost,
        )
        return DescriptionResult(
            description=profile.description.strip(),
            facts=facts[: self.facts_count],
            usage=usage_total,
            estimated_cost_usd=estimated_cost,
        )

    def _complete(self, name: str, categories: list[str], retry_note: str | None = None):
        run_id = f"describe-{int(time.time() * 1000)}"
        user_text = f"Персонаж: {name}. Категория: {', '.join(categories) or 'не указана'}."
        if retry_note:
            user_text += f"\n{retry_note}"
        return _call_with_rate_limit_retry(
            run_id=run_id,
            hypothesis_id="H7",
            location="src/labeling/llm/deepseek_describer.py:describe:retry",
            call=lambda: self._client.chat.completions.create(
                model=self.model,
                temperature=0.3,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": self._system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": user_text,
                    },
                ],
            ),
        )

    def _system_prompt(self) -> str:
        return (
            "Ты составляешь игровые материалы для игры «Кто шпион». "
            "Тебе дают имя персонажа или актёра и категорию, из которой он взят. "
            "Верни строго JSON с ключами description и facts без лишнего текста. "
            "description — краткое описание персонажа на русском языке (2-4 предложения): "
            "кто это, откуда, чем известен. "
            f"facts — ровно {self.facts_count} коротких фактов о персонаже на русском языке "
            "от третьего лица. "
            "В фактах ЗАПРЕЩЕНО упоминать имя персонажа, его прозвища и название "
            "франшизы/произведения: игрок зачитывает факт вслух и не должен раскрыть свою карточку. "
            "Факты должны быть конкретными и проверяемыми (род занятий, черты характера, внешность, "
            "известные поступки, окружение), без выдумок. "
            "Если персонаж малоизвестен — пиши только то, что знаешь достоверно."
        )

    @staticmethod
    def _accumulate_usage(usage_total: dict[str, int], completion) -> None:
        if completion.usage is None:
            return
        usage_total["prompt_tokens"] += completion.usage.prompt_tokens
        usage_total["completion_tokens"] += completion.usage.completion_tokens
        usage_total["total_tokens"] += completion.usage.total_tokens
